"""Command-line client for the Mini Distributed File Storage system.

    python client.py upload   samples/reviews.csv
    python client.py list
    python client.py map      reviews.csv
    python client.py download reviews.csv
    python client.py nodes
    python client.py delete   reviews.csv
    python client.py events

The client does the heavy lifting: it splits files into 1 MB chunks, asks the
master where each chunk goes, sends chunks straight to the storage nodes, and
on download fetches each chunk from any live copy and checks the SHA-256.
"""
import argparse
import hashlib
import math
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

import config


class DFSError(Exception):
    """A problem worth showing to the user as a one-line error."""


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def mb(num_bytes):
    return f"{num_bytes / 2**20:.2f} MB"


def safe_name(name):
    """Turn any file name into one the cluster accepts."""
    cleaned = re.sub(r"[^A-Za-z0-9._()\- ]", "_", name).strip()
    if not cleaned or not cleaned[0].isalnum():
        cleaned = "file_" + cleaned
    return cleaned[:150]


class Client:
    def __init__(self, master=config.MASTER_URL):
        self.master = master.rstrip("/")

    # ------------------------------------------------------------ master calls
    def _call(self, method, path, **kwargs):
        try:
            r = requests.request(method, self.master + path,
                                 timeout=config.REQUEST_TIMEOUT, **kwargs)
        except requests.RequestException:
            raise DFSError(f"cannot reach the master at {self.master} (is master.py running?)")
        if r.status_code >= 400:
            try:
                message = r.json().get("error", r.text)
            except ValueError:
                message = r.text
            raise DFSError(message)
        return r.json()

    def files(self):
        return self._call("GET", "/files")["files"]

    def info(self, name):
        return self._call("GET", f"/files/{name}")

    def nodes(self):
        return self._call("GET", "/nodes")["nodes"]

    def delete(self, name):
        return self._call("DELETE", f"/files/{name}")

    def events(self, since=0):
        return self._call("GET", f"/events?since={since}")["events"]

    # ------------------------------------------------------------ node calls
    @staticmethod
    def _put_chunk(port, chunk_id, data, digest):
        try:
            r = requests.put(f"{config.node_url(port)}/chunks/{chunk_id}", data=data,
                             headers={"X-Chunk-SHA256": digest},
                             timeout=config.REQUEST_TIMEOUT)
            return r.status_code == 201
        except requests.RequestException:
            return False

    @staticmethod
    def _get_chunk(port, chunk_id):
        """Returns (data, None) on success or (None, reason) on failure."""
        try:
            r = requests.get(f"{config.node_url(port)}/chunks/{chunk_id}",
                             timeout=config.REQUEST_TIMEOUT)
        except requests.RequestException:
            return None, "unreachable"
        if r.status_code != 200:
            return None, "missing"
        return r.content, None

    # ---------------------------------------------------------------- upload
    def upload(self, path, name=None):
        path = Path(path)
        if not path.is_file():
            raise DFSError(f"no such file: {path}")
        name = name or safe_name(path.name)
        size = path.stat().st_size
        count = math.ceil(size / config.CHUNK_SIZE)
        start = time.perf_counter()

        plan = self._call("POST", "/allocate", json={"name": name, "chunks": count})
        file_hash, stored, warnings = hashlib.sha256(), [], []
        with path.open("rb") as f:
            for entry in plan["chunks"]:
                data = f.read(config.CHUNK_SIZE)
                digest = sha256(data)
                file_hash.update(data)
                ok = [p for p in entry["nodes"] if self._put_chunk(p, entry["id"], data, digest)]
                if not ok:                       # every planned node failed: try the others
                    spare = [n["port"] for n in self.nodes()
                             if n["alive"] and n["port"] not in entry["nodes"]]
                    ok = [p for p in spare[:1] if self._put_chunk(p, entry["id"], data, digest)]
                if not ok:
                    raise DFSError(f"could not store {entry['id']} on any storage node")
                stored.append({"id": entry["id"], "nodes": ok, "size": len(data),
                               "sha256": digest})

        single = sum(len(c["nodes"]) < config.REPLICATION_FACTOR for c in stored)
        if single:
            warnings.append(f"{single} chunk(s) have 1 copy for now; the master adds "
                            f"the second copy as soon as another node is alive")
        digest = file_hash.hexdigest()
        self._call("POST", "/commit", json={"name": name, "size": size, "sha256": digest,
                                            "chunks": stored})
        return {"name": name, "size": size, "sha256": digest, "chunks": stored,
                "warnings": warnings, "seconds": time.perf_counter() - start}

    # -------------------------------------------------------------- download
    def download(self, name, out=None):
        start = time.perf_counter()
        info = self.info(name)
        out = Path(out) if out else Path("downloads") / name
        out.parent.mkdir(parents=True, exist_ok=True)
        part = out.with_name(out.name + ".part")

        file_hash, served = hashlib.sha256(), []
        with part.open("wb") as f:
            for chunk in info["chunks"]:
                # live copies first, then any other copy the master knows about
                order = chunk["live_nodes"] + [p for p in chunk["nodes"]
                                               if p not in chunk["live_nodes"]]
                data, used, skipped = None, None, []
                for port in order:
                    data, problem = self._get_chunk(port, chunk["id"])
                    if data is not None and sha256(data) != chunk["sha256"]:
                        data, problem = None, "bad checksum"
                    if data is not None:
                        used = port
                        break
                    skipped.append((port, problem))
                if data is None:
                    f.close()
                    part.unlink(missing_ok=True)
                    raise DFSError(f"{chunk['id']} is not available on any node "
                                   f"(tried {', '.join(str(p) for p in order)})")
                f.write(data)
                file_hash.update(data)
                served.append({"id": chunk["id"], "node": used, "skipped": skipped})

        digest = file_hash.hexdigest()
        if digest != info["sha256"]:
            part.unlink(missing_ok=True)
            raise DFSError("file checksum does not match the original; download discarded")
        os.replace(part, out)
        return {"name": name, "path": str(out), "size": info["size"], "sha256": digest,
                "verified": True, "chunks": served, "seconds": time.perf_counter() - start}


# ------------------------------------------------------------------ CLI output

def table(headers, rows):
    rows = [[str(c) for c in row] for row in rows]
    widths = [max(len(x) for x in col) for col in zip(headers, *rows)]
    line = lambda cells: "  " + "  ".join(c.ljust(w) for c, w in zip(cells, widths)).rstrip()
    print(line(headers))
    print(line(["-" * w for w in widths]))
    for row in rows:
        print(line(row))


def cmd_upload(client, args):
    path = Path(args.path)
    result = client.upload(path, args.name)
    print(f"Uploaded {result['name']}  ({mb(result['size'])}, {len(result['chunks'])} chunks)")
    table(["chunk", "size", "stored on nodes"],
          [[c["id"], f"{c['size'] / 1024:.0f} KB", ", ".join(map(str, c["nodes"]))]
           for c in result["chunks"]])
    for warning in result["warnings"]:
        print(f"  note: {warning}")
    speed = result["size"] / 2**20 / max(result["seconds"], 1e-6)
    print(f"Done in {result['seconds']:.2f} s ({speed:.1f} MB/s)   sha256 {result['sha256'][:16]}...")


def cmd_download(client, args):
    result = client.download(args.name, args.out)
    print(f"Downloaded {result['name']}  ({mb(result['size'])}, {len(result['chunks'])} chunks)")
    rows = []
    for c in result["chunks"]:
        note = "; ".join(f"node {p} {why}" for p, why in c["skipped"])
        rows.append([c["id"], c["node"], f"used backup copy ({note})" if note else ""])
    table(["chunk", "from node", "note"], rows)
    print(f"Checksum OK  sha256 {result['sha256'][:16]}... matches the original")
    print(f"Saved to {result['path']} in {result['seconds']:.2f} s")


def cmd_list(client, args):
    files = client.files()
    if not files:
        print("No files stored yet.")
        return
    table(["file", "size", "chunks", "status", "uploaded"],
          [[f["name"], mb(f["size"]), f["chunks"], f["status"], f["uploaded"]] for f in files])


def cmd_map(client, args):
    """Chunk map: which node holds each chunk of a file (or of every file)."""
    names = [args.name] if args.name else [f["name"] for f in client.files()]
    if not names:
        print("No files stored yet.")
        return
    nodes = client.nodes()
    ports = [n["port"] for n in nodes]
    alive = {n["port"]: n["alive"] for n in nodes}
    headers = ["chunk"] + [f"{p}" + ("" if alive[p] else " DOWN") for p in ports] + ["live copies"]
    for name in names:
        info = client.info(name)
        print(f"\n{name}  {mb(info['size'])}  status: {info['status'].upper()}"
              f"  sha256 {info['sha256'][:16]}...")
        table(headers, [[c["id"]] + [("X" if p in c["nodes"] else ".") for p in ports]
                        + [f"{len(c['live_nodes'])}/{config.REPLICATION_FACTOR}"]
                        for c in info["chunks"]])


def cmd_nodes(client, args):
    table(["node", "status", "last heartbeat", "chunks", "disk"],
          [[n["port"], "UP" if n["alive"] else "DOWN", f"{n['last_seen_ago']} s ago",
            n["chunks"], mb(n["bytes"])] for n in client.nodes()])


def cmd_delete(client, args):
    client.delete(args.name)
    print(f"Deleted {args.name} and its chunks.")


def cmd_events(client, args):
    for e in client.events()[-args.last:]:
        print(f"  {datetime.fromtimestamp(e['time']):%H:%M:%S}  {e['message']}")


def main():
    parser = argparse.ArgumentParser(description="Mini Distributed File Storage client")
    parser.add_argument("--master", default=config.MASTER_URL, help="master node URL")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("upload", help="split a file into chunks and store it")
    p.add_argument("path")
    p.add_argument("--name", help="name to store it under (default: the file name)")
    p.set_defaults(run=cmd_upload)

    p = sub.add_parser("download", help="rebuild a stored file and verify its checksum")
    p.add_argument("name")
    p.add_argument("--out", help="where to save it (default: downloads/<name>)")
    p.set_defaults(run=cmd_download)

    sub.add_parser("list", help="list stored files").set_defaults(run=cmd_list)

    p = sub.add_parser("map", help="show which nodes hold each chunk")
    p.add_argument("name", nargs="?", help="one file (default: all files)")
    p.set_defaults(run=cmd_map)

    sub.add_parser("nodes", help="show storage node health").set_defaults(run=cmd_nodes)

    p = sub.add_parser("delete", help="delete a file and its chunks")
    p.add_argument("name")
    p.set_defaults(run=cmd_delete)

    p = sub.add_parser("events", help="show recent cluster events from the master")
    p.add_argument("--last", type=int, default=20)
    p.set_defaults(run=cmd_events)

    args = parser.parse_args()
    try:
        args.run(Client(args.master), args)
    except DFSError as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
