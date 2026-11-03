"""Storage node: stores chunks in its own folder and reports to the master.

Each node is a small Flask server. It does not know which file a chunk belongs
to; it only saves, returns, lists and deletes chunks, and copies a chunk to
another node when the master asks it to (re-replication).

Run one node per terminal:
    python storage_node.py --port 5001
    python storage_node.py --port 5002
    python storage_node.py --port 5003
"""
import argparse
import hashlib
import logging
import os
import threading
import time
from pathlib import Path

import flask.cli
import requests
from flask import Flask, abort, jsonify, request, send_file
from werkzeug.exceptions import HTTPException

import config

app = Flask(__name__)
STATE = {"port": None, "folder": None, "master": config.MASTER_URL, "started": time.time()}


@app.errorhandler(HTTPException)
def json_error(error):
    return jsonify(error=error.description), error.code


def log(message):
    print(f"[node {STATE['port']}] {message}", flush=True)


def chunk_path(chunk_id):
    """Path of a chunk on disk; rejects ids that could escape the folder."""
    if not config.is_safe_name(chunk_id):
        abort(400, description="invalid chunk id")
    return STATE["folder"] / chunk_id


def stored_chunks():
    return sorted(p.name for p in STATE["folder"].iterdir()
                  if p.is_file() and not p.name.endswith(".tmp"))


def disk_usage():
    return sum(p.stat().st_size for p in STATE["folder"].iterdir() if p.is_file())


# --------------------------------------------------------------------------- API

@app.put("/chunks/<chunk_id>")
def put_chunk(chunk_id):
    """Save a chunk. The body is the raw chunk bytes."""
    path = chunk_path(chunk_id)
    data = request.get_data()
    expected = request.headers.get("X-Chunk-SHA256")
    if expected and hashlib.sha256(data).hexdigest() != expected:
        abort(400, description="checksum mismatch, chunk rejected")

    tmp = path.with_name(path.name + ".tmp")      # write, then rename:
    tmp.write_bytes(data)                         # a half-written chunk
    os.replace(tmp, path)                         # is never visible
    log(f"stored   {chunk_id} ({len(data) / 1024:.0f} KB)")
    return jsonify(stored=chunk_id, size=len(data)), 201


@app.get("/chunks/<chunk_id>")
def get_chunk(chunk_id):
    path = chunk_path(chunk_id)
    if not path.exists():
        abort(404, description="chunk not found")
    return send_file(path, mimetype="application/octet-stream")


@app.delete("/chunks/<chunk_id>")
def delete_chunk(chunk_id):
    path = chunk_path(chunk_id)
    existed = path.exists()
    path.unlink(missing_ok=True)
    if existed:
        log(f"deleted  {chunk_id}")
    return jsonify(deleted=chunk_id, existed=existed)


@app.get("/chunks")
def list_chunks():
    return jsonify(port=STATE["port"], chunks=stored_chunks())


@app.post("/replicate")
def replicate():
    """Copy one of this node's chunks straight to another node.

    The master calls this during self-healing, so chunk data moves node to node
    and never passes through the master.
    """
    body = request.get_json(force=True)
    chunk_id, target = body["chunk_id"], int(body["target"])
    path = chunk_path(chunk_id)
    if not path.exists():
        abort(404, description="chunk not found")
    data = path.read_bytes()
    try:
        r = requests.put(f"{config.node_url(target)}/chunks/{chunk_id}", data=data,
                         headers={"X-Chunk-SHA256": hashlib.sha256(data).hexdigest()},
                         timeout=config.REQUEST_TIMEOUT)
        r.raise_for_status()
    except requests.RequestException as exc:
        abort(502, description=f"copy to node {target} failed: {exc}")
    log(f"copied   {chunk_id} -> node {target}")
    return jsonify(copied=chunk_id, target=target)


@app.get("/health")
def health():
    return jsonify(status="ok", port=STATE["port"], chunks=len(stored_chunks()),
                   bytes=disk_usage(), uptime=round(time.time() - STATE["started"], 1))


# --------------------------------------------------------------------- heartbeat

def heartbeat_loop():
    """Tell the master every few seconds that this node is alive."""
    connected = None
    while True:
        try:
            requests.post(f"{STATE['master']}/heartbeat", timeout=config.REQUEST_TIMEOUT,
                          json={"port": STATE["port"], "chunks": len(stored_chunks()),
                                "bytes": disk_usage()})
            if connected is not True:
                log("connected to master")
            connected = True
        except requests.RequestException:
            if connected is not False:
                log("master not reachable, retrying...")
            connected = False
        time.sleep(config.HEARTBEAT_INTERVAL)


def main():
    parser = argparse.ArgumentParser(description="Start a storage node.")
    parser.add_argument("--port", type=int, required=True, help="port to listen on, e.g. 5001")
    parser.add_argument("--data-dir", default="storage", help="parent folder for chunk folders")
    parser.add_argument("--master", default=config.MASTER_URL, help="master node URL")
    args = parser.parse_args()

    STATE["port"] = args.port
    STATE["master"] = args.master
    STATE["folder"] = Path(args.data_dir) / f"node_{args.port}"
    STATE["folder"].mkdir(parents=True, exist_ok=True)

    logging.getLogger("werkzeug").setLevel(logging.WARNING)   # hide per-request lines
    flask.cli.show_server_banner = lambda *args: None           # hide Flask's banner
    threading.Thread(target=heartbeat_loop, daemon=True).start()
    log(f"listening on {config.node_url(args.port)}, chunks in {STATE['folder']}/ "
        f"({len(stored_chunks())} already stored)")
    app.run(host=config.HOST, port=args.port, threaded=True)


if __name__ == "__main__":
    main()
