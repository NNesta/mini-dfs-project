"""Master node: keeps the chunk map, watches node health and heals the cluster.

The master never stores file data. It keeps two things:
  * files - for every file: size, SHA-256, and which nodes hold each chunk
            (saved to metadata.json, so it survives a master restart)
  * nodes - which storage nodes are alive, learned from their heartbeats

A background monitor marks a node dead after 10 s without a heartbeat, then asks
a surviving node to copy every lost chunk to a healthy node (re-replication).

Run:  python master.py
"""
import argparse
import json
import logging
import os
import threading
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import flask.cli
import requests
from flask import Flask, abort, jsonify, request
from werkzeug.exceptions import HTTPException

import config

R = config.REPLICATION_FACTOR

app = Flask(__name__)
lock = threading.RLock()

files = {}                    # name -> {"size", "sha256", "uploaded", "chunks": [...]}
nodes = {}                    # port -> {"last_seen", "alive", "heard", "chunks", "bytes"}
events = deque(maxlen=500)    # recent cluster events, served at /events
pending_cleanup = set()       # nodes that came back and may hold stale copies
SETTINGS = {"metadata": Path("metadata.json"), "under_replicated": 0}


@app.errorhandler(HTTPException)
def json_error(error):
    return jsonify(error=error.description), error.code


def log(message, kind="info", **data):
    events.append({"time": time.time(), "kind": kind, "message": message, **data})
    print(f"[master] {datetime.now():%H:%M:%S}  {message}", flush=True)


# ----------------------------------------------------------------- metadata file

def save_metadata():
    path = SETTINGS["metadata"]
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(files, indent=2))
    os.replace(tmp, path)                        # atomic: never a half-written file


def load_metadata():
    path = SETTINGS["metadata"]
    if path.exists():
        files.update(json.loads(path.read_text()))


# ---------------------------------------------------------------------- helpers

def is_alive(port):
    node = nodes.get(port)
    return bool(node and node["alive"])


def alive_ports():
    return sorted(p for p, n in nodes.items() if n["alive"])


def chunk_load():
    """Number of chunk copies the metadata places on each node."""
    load = {p: 0 for p in nodes}
    for record in files.values():
        for chunk in record["chunks"]:
            for p in chunk["nodes"]:
                load[p] = load.get(p, 0) + 1
    return load


def pick_nodes(load, count, exclude=()):
    """Choose the `count` least-loaded live nodes (ties go to the lower port)."""
    candidates = [p for p in alive_ports() if p not in exclude]
    chosen = sorted(candidates, key=lambda p: (load.get(p, 0), p))[:count]
    for p in chosen:
        load[p] = load.get(p, 0) + 1
    return chosen


def live_copies(chunk):
    return [p for p in chunk["nodes"] if is_alive(p)]


def file_status(record):
    copies = [len(live_copies(c)) for c in record["chunks"]]
    if any(n == 0 for n in copies):
        return "unavailable"
    if any(n < R for n in copies):
        return "degraded"
    return "healthy"


def find_chunk(name, chunk_id):
    for chunk in files.get(name, {}).get("chunks", []):
        if chunk["id"] == chunk_id:
            return chunk
    return None


def delete_copies(pairs):
    """Best-effort delete of (chunk_id, port) copies on storage nodes."""
    for chunk_id, port in pairs:
        try:
            requests.delete(f"{config.node_url(port)}/chunks/{chunk_id}",
                            timeout=config.REQUEST_TIMEOUT)
        except requests.RequestException:
            pass                                  # node is down; cleaned when it returns


def copies_of(record):
    return {(c["id"], p) for c in record["chunks"] for p in c["nodes"]} if record else set()


# --------------------------------------------------------------------- node API

@app.post("/heartbeat")
def heartbeat():
    body = request.get_json(force=True)
    port = int(body["port"])
    with lock:
        node = nodes.get(port)
        if node is None or not node["heard"]:
            log(f"node {port} joined the cluster", "node_joined", port=port)
        elif not node["alive"]:
            log(f"node {port} is back online", "node_back", port=port)
        if node is not None and not node["alive"]:
            pending_cleanup.add(port)             # may hold copies made elsewhere since
        nodes[port] = {"last_seen": time.time(), "alive": True, "heard": True,
                       "chunks": body.get("chunks", 0), "bytes": body.get("bytes", 0)}
    return jsonify(ok=True)


@app.get("/nodes")
def list_nodes():
    now = time.time()
    with lock:
        load = chunk_load()
        result = [{"port": p, "url": config.node_url(p), "alive": n["alive"],
                   "last_seen_ago": round(now - n["last_seen"], 1),
                   "chunks": load.get(p, 0), "bytes": n["bytes"]}
                  for p, n in sorted(nodes.items())]
    return jsonify(nodes=result)


# --------------------------------------------------------------------- file API

@app.post("/allocate")
def allocate():
    """Step 1 of an upload: decide which 2 nodes receive each chunk."""
    body = request.get_json(force=True)
    name, count = body.get("name", ""), int(body.get("chunks", 0))
    if not config.is_safe_name(name):
        abort(400, description="file name may only use letters, digits, spaces and . _ - ( )")
    with lock:
        live = alive_ports()
        if not live:
            abort(503, description="no storage nodes are alive")
        load = chunk_load()
        replicas = min(R, len(live))
        plan = [{"id": f"{name}_{i}", "nodes": pick_nodes(load, replicas)} for i in range(count)]
    return jsonify(chunks=plan, replicas=replicas)


@app.post("/commit")
def commit():
    """Step 2 of an upload: record the file once its chunks are on the nodes."""
    body = request.get_json(force=True)
    name = body.get("name", "")
    if not config.is_safe_name(name):
        abort(400, description="invalid file name")
    chunks = [{"id": c["id"], "nodes": [int(p) for p in c["nodes"]],
               "size": c["size"], "sha256": c["sha256"]} for c in body["chunks"]]
    if any(not c["nodes"] for c in chunks):
        abort(400, description="every chunk needs at least one stored copy")
    record = {"size": body["size"], "sha256": body["sha256"],
              "uploaded": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "chunks": chunks}
    with lock:
        old = files.get(name)
        files[name] = record
        save_metadata()
    delete_copies(copies_of(old) - copies_of(record))     # a replaced file's leftovers
    verb = "replaced" if old else "stored"
    log(f"{verb} {name}: {record['size'] / 2**20:.2f} MB in {len(chunks)} chunks", "upload",
        file=name)
    return jsonify(ok=True, status=file_status(record))


@app.get("/files")
def list_files():
    with lock:
        result = [{"name": name, "size": r["size"], "chunks": len(r["chunks"]),
                   "uploaded": r["uploaded"], "status": file_status(r)}
                  for name, r in sorted(files.items())]
    return jsonify(files=result)


@app.get("/files/<name>")
def file_info(name):
    with lock:
        record = files.get(name)
        if record is None:
            abort(404, description=f"no file named {name}")
        chunks = [{**c, "live_nodes": live_copies(c)} for c in record["chunks"]]
        return jsonify(name=name, size=record["size"], sha256=record["sha256"],
                       uploaded=record["uploaded"], status=file_status(record), chunks=chunks)


@app.delete("/files/<name>")
def delete_file(name):
    with lock:
        record = files.pop(name, None)
        if record is None:
            abort(404, description=f"no file named {name}")
        save_metadata()
    delete_copies(copies_of(record))
    log(f"deleted {name}", "delete", file=name)
    return jsonify(deleted=name)


@app.get("/events")
def list_events():
    since = float(request.args.get("since", 0))
    return jsonify(events=[e for e in list(events) if e["time"] > since])


@app.get("/")
def overview():
    with lock:
        return jsonify(service="Mini DFS master", nodes_alive=alive_ports(),
                       nodes_known=sorted(nodes), files=len(files),
                       chunk_size=config.CHUNK_SIZE, replication_factor=R,
                       endpoints=["/nodes", "/files", "/files/<name>", "/events",
                                  "/allocate", "/commit", "/heartbeat"])


# ------------------------------------------------- failure detection and healing

def detect_dead_nodes():
    now = time.time()
    with lock:
        for port, node in nodes.items():
            silent = now - node["last_seen"]
            if node["alive"] and silent > config.DEAD_AFTER:
                node["alive"] = False
                lost = sum(port in c["nodes"] for r in files.values() for c in r["chunks"])
                log(f"node {port} is DEAD (no heartbeat for {silent:.0f} s), "
                    f"{lost} chunk copies affected", "node_dead", port=port, chunks=lost,
                    silent=round(silent, 2))


def clean_stale_copies(port):
    """A returning node may hold chunks that were copied elsewhere while it was
    away. Metadata no longer lists it for those chunks, so delete them."""
    try:
        held = requests.get(f"{config.node_url(port)}/chunks",
                            timeout=config.REQUEST_TIMEOUT).json()["chunks"]
    except requests.RequestException:
        return
    with lock:
        owners = {c["id"]: c["nodes"] for r in files.values() for c in r["chunks"]}
    stale = [cid for cid in held if cid in owners and port not in owners[cid]]
    delete_copies((cid, port) for cid in stale)
    if stale:
        log(f"removed {len(stale)} stale chunk copies from node {port}", "cleanup",
            port=port, chunks=len(stale))


def repair_under_replicated():
    """Bring every chunk back to 2 live copies when enough nodes are alive."""
    with lock:
        load = chunk_load()
        tasks = []
        for name, record in files.items():
            for chunk in record["chunks"]:
                holders = live_copies(chunk)
                missing = R - len(holders)
                if holders and missing > 0:
                    for target in pick_nodes(load, missing, exclude=chunk["nodes"]):
                        tasks.append((name, chunk["id"], holders[0], target))

    repaired = 0
    for name, chunk_id, source, target in tasks:
        try:
            r = requests.post(f"{config.node_url(source)}/replicate",
                              json={"chunk_id": chunk_id, "target": target},
                              timeout=config.REQUEST_TIMEOUT * 2)
            r.raise_for_status()
        except requests.RequestException as exc:
            log(f"copy of {chunk_id} from node {source} to node {target} failed: {exc}",
                "repair_failed")
            continue
        with lock:
            chunk = find_chunk(name, chunk_id)
            if chunk is None:
                continue                               # file was deleted meanwhile
            kept = [p for p in chunk["nodes"] if is_alive(p) and p != target]
            chunk["nodes"] = kept + [target]
            repaired += 1
        log(f"re-replicated {chunk_id}: node {source} -> node {target}", "repaired",
            chunk=chunk_id, source=source, target=target)

    with lock:
        if repaired:
            save_metadata()
        short = sum(len(live_copies(c)) < R for r in files.values() for c in r["chunks"])
        changed = short != SETTINGS["under_replicated"]
        SETTINGS["under_replicated"] = short
        if short == 0 and (changed or repaired):
            log(f"cluster healthy: every chunk has {R} live copies", "healthy")
        elif short and changed:
            log(f"{short} chunks have fewer than {R} live copies "
                f"(waiting for a healthy node)", "degraded", chunks=short)


def monitor_loop():
    while True:
        time.sleep(config.MONITOR_INTERVAL)
        try:
            detect_dead_nodes()
            with lock:
                returning = list(pending_cleanup)
                pending_cleanup.clear()
            for port in returning:
                clean_stale_copies(port)
            repair_under_replicated()
        except Exception as exc:                       # the monitor must never stop
            log(f"monitor error: {exc}", "error")


def main():
    parser = argparse.ArgumentParser(description="Start the master node.")
    parser.add_argument("--port", type=int, default=config.MASTER_PORT)
    parser.add_argument("--metadata", default="metadata.json", help="metadata file path")
    args = parser.parse_args()

    SETTINGS["metadata"] = Path(args.metadata)
    SETTINGS["metadata"].parent.mkdir(parents=True, exist_ok=True)
    load_metadata()
    # Nodes named in saved metadata get the usual 10 s to send a heartbeat.
    for port in {p for r in files.values() for c in r["chunks"] for p in c["nodes"]}:
        nodes[port] = {"last_seen": time.time(), "alive": True, "heard": False,
                       "chunks": 0, "bytes": 0}

    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    flask.cli.show_server_banner = lambda *a: None
    threading.Thread(target=monitor_loop, daemon=True).start()
    log(f"listening on http://{config.HOST}:{args.port}, {len(files)} files in {args.metadata}")
    app.run(host=config.HOST, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
