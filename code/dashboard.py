"""Web dashboard for the Mini Distributed File Storage system.

    uv run dashboard.py             start the master, 3 storage nodes and the dashboard
    uv run dashboard.py --fresh     same, but wipe stored chunks and metadata first
    uv run dashboard.py --open      also open the dashboard in your browser

Then open http://127.0.0.1:8080.

The dashboard is just another client: uploads and downloads go through the same
Client class as client.py, so chunk data still travels straight between the
client and the storage nodes. On top of that it can crash and restart storage
nodes (it runs them as child processes, like cluster.py does) and it shows the
master's chunk map, node heartbeats and cluster events live in the browser.

If a master is already running (for example from cluster.py), the dashboard
attaches to it instead of starting a second cluster. In that mode the crash
button only works for nodes the dashboard itself restarted.
"""
import argparse
import logging
import os
import shutil
import signal
import sys
import tempfile
import threading
import time
import webbrowser
from pathlib import Path
from urllib.parse import quote

import flask.cli
import requests
from flask import Flask, abort, jsonify, request, send_from_directory
from werkzeug.exceptions import HTTPException

import config
from client import Client, DFSError, safe_name
from cluster import HERE, Cluster, responds

WEB = HERE / "web"
RESULTS = HERE / "results"
SAMPLE = HERE / "samples" / "reviews.csv"
DOWNLOADS = HERE / "downloads"
STORAGE = HERE / "storage"
METADATA = HERE / "metadata.json"

SETTINGS = {
    "master_port": config.MASTER_PORT,
    "node_ports": config.NODE_PORTS,
    "chunk_size": config.CHUNK_SIZE,
    "replication_factor": config.REPLICATION_FACTOR,
    "heartbeat_interval": config.HEARTBEAT_INTERVAL,
    "dead_after": config.DEAD_AFTER,
    "monitor_interval": config.MONITOR_INTERVAL,
}

app = Flask(__name__, static_folder=None)
app.config["MAX_CONTENT_LENGTH"] = 512 * 2**20       # browser uploads up to 512 MB
client = Client()
cluster = Cluster(data_dir=STORAGE, metadata=METADATA)
control = threading.Lock()                            # one start / crash / reset at a time
MODE = {"managed": False}                             # True when we started the cluster


@app.errorhandler(HTTPException)
def http_error(error):
    return jsonify(error=error.description), error.code


@app.errorhandler(DFSError)
def dfs_error(error):
    return jsonify(error=str(error)), 400


def fetch(url, timeout=1.0):
    """GET a JSON document, or None if the server is down or answers with an error."""
    try:
        r = requests.get(url, timeout=timeout)
        return r.json() if r.ok else None
    except (requests.RequestException, ValueError):
        return None


def check_name(name):
    if not config.is_safe_name(name):
        abort(400, description="invalid file name")


def check_port(port):
    if port not in config.NODE_PORTS:
        abort(404, description=f"no storage node on port {port}")


def wipe():
    shutil.rmtree(STORAGE, ignore_errors=True)
    METADATA.unlink(missing_ok=True)


# ------------------------------------------------------------------ web pages

@app.get("/")
def index():
    return send_from_directory(WEB, "index.html", max_age=0)


@app.get("/assets/<path:name>")
def assets(name):
    return send_from_directory(WEB, name, max_age=0)


@app.get("/results/<path:name>")
def result_file(name):
    return send_from_directory(RESULTS, name, max_age=0)


# --------------------------------------------------------------- live state

@app.get("/api/state")
def state():
    """Everything the dashboard draws, gathered from the master and the nodes."""
    since = request.args.get("since", 0, type=float)
    master = config.MASTER_URL
    overview = fetch(master + "/")
    up = bool(overview) and overview.get("service") == "Mini DFS master"

    known, files, events = {}, [], []
    if up:
        known = {n["port"]: n for n in (fetch(master + "/nodes") or {}).get("nodes", [])}
        for item in (fetch(master + "/files") or {}).get("files", []):
            info = fetch(f"{master}/files/{quote(item['name'])}")
            if info:
                files.append(info)
        events = (fetch(f"{master}/events?since={since}") or {}).get("events", [])

    running = cluster.running()
    nodes = []
    for port in config.NODE_PORTS:
        held = fetch(f"{config.node_url(port)}/chunks", timeout=0.5)   # what is on disk
        view = known.get(port)                                         # what the master thinks
        nodes.append({"port": port, "reachable": held is not None,
                      "held": held["chunks"] if held else None,
                      "managed": port in running, "known": view is not None,
                      "alive": bool(view and view["alive"]),
                      "last_seen_ago": view["last_seen_ago"] if view else None,
                      "bytes": view["bytes"] if view else 0})

    return jsonify(time=time.time(), managed=MODE["managed"],
                   master={"up": up, "url": master, "managed": "master" in running},
                   nodes=nodes, files=files, events=events, config=SETTINGS)


@app.get("/api/results")
def results():
    path = RESULTS / "results.json"
    if not path.exists():
        abort(404, description="no test results yet; run: uv run run_tests.py")
    return app.response_class(path.read_text(), mimetype="application/json")


# ------------------------------------------------------------ file actions

@app.post("/api/upload")
def upload():
    item = request.files.get("file")
    if item is None or not item.filename:
        abort(400, description="choose a file to upload")
    name = safe_name(Path(item.filename).name)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / name
        item.save(path)
        return jsonify(client.upload(path, name))


@app.post("/api/upload/sample")
def upload_sample():
    return jsonify(client.upload(SAMPLE))


@app.post("/api/upload/random")
def upload_random():
    body = request.get_json(silent=True) or {}
    size_mb = max(0.1, min(float(body.get("size_mb", 5)), 100))
    name = f"random_{size_mb:g}mb_{os.urandom(2).hex()}.bin"
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / name
        path.write_bytes(os.urandom(int(size_mb * 2**20)))
        return jsonify(client.upload(path, name))


@app.post("/api/files/<name>/download")
def download(name):
    """Rebuild the file from the nodes (checking every checksum) into downloads/."""
    check_name(name)
    result = client.download(name, DOWNLOADS / name)
    result["url"] = f"/api/downloads/{quote(name)}"
    return jsonify(result)


@app.get("/api/downloads/<name>")
def saved_download(name):
    check_name(name)
    return send_from_directory(DOWNLOADS, name, as_attachment=True, max_age=0)


@app.delete("/api/files/<name>")
def delete(name):
    check_name(name)
    return jsonify(client.delete(name))


# ------------------------------------------------------------ node control

@app.post("/api/nodes/<int:port>/crash")
def crash_node(port):
    """Kill a storage node without warning, as a power cut would."""
    check_port(port)
    with control:
        if port not in cluster.running():
            abort(409, description=f"node {port} was not started by the dashboard; "
                                   f"stop it in its own terminal with Ctrl+C")
        cluster.stop_node(port)
    print(f"[dashboard] node {port} crashed (process killed)", flush=True)
    return jsonify(crashed=port)


@app.post("/api/nodes/<int:port>/start")
def start_node(port):
    check_port(port)
    with control:
        if responds(config.node_url(port) + "/health"):
            abort(409, description=f"node {port} is already running")
        try:
            cluster.start_node(port)
        except RuntimeError as exc:
            abort(500, description=str(exc))
    print(f"[dashboard] node {port} started", flush=True)
    return jsonify(started=port)


@app.post("/api/reset")
def reset():
    """Stop everything, delete all chunks and metadata, start a fresh cluster."""
    if not MODE["managed"]:
        abort(409, description="the dashboard is attached to a cluster it did not start; "
                               "stop that cluster and run: uv run dashboard.py --fresh")
    with control:
        cluster.stop_all()
        wipe()
        shutil.rmtree(DOWNLOADS, ignore_errors=True)
        cluster.start_all()
    print("[dashboard] cluster reset: all data deleted, fresh master and nodes", flush=True)
    return jsonify(reset=True)


# --------------------------------------------------------------------- main

def main():
    parser = argparse.ArgumentParser(description="Run the Mini DFS web dashboard.")
    parser.add_argument("--port", type=int, default=config.DASHBOARD_PORT,
                        help=f"dashboard port (default {config.DASHBOARD_PORT})")
    parser.add_argument("--fresh", action="store_true",
                        help="delete stored chunks and metadata before starting")
    parser.add_argument("--open", action="store_true", help="open the dashboard in a browser")
    args = parser.parse_args()

    # A `kill` (SIGTERM) should stop the child processes too, like Ctrl+C does.
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))

    if responds(config.MASTER_URL + "/"):
        print("[dashboard] a master is already running; attaching to it "
              "(crash/restart buttons work for nodes the dashboard starts)")
        if args.fresh:
            print("[dashboard] --fresh ignored: the running cluster's data is left alone")
    else:
        busy = [p for p in config.NODE_PORTS if responds(config.node_url(p) + "/health")]
        if busy:
            sys.exit(f"[dashboard] storage node port(s) {busy} are already in use. "
                     f"Stop the old cluster first.")
        if args.fresh:
            wipe()
        print("[dashboard] starting the master and 3 storage nodes...")
        cluster.start_all()
        MODE["managed"] = True

    url = f"http://{config.HOST}:{args.port}"
    logging.getLogger("werkzeug").setLevel(logging.WARNING)
    flask.cli.show_server_banner = lambda *a: None
    print(f"\n  Mini DFS dashboard:  {url}\n  Master API:          {config.MASTER_URL}\n"
          f"  Press Ctrl+C to stop everything.\n", flush=True)
    if args.open:
        threading.Timer(1.0, webbrowser.open, [url]).start()
    try:
        app.run(host=config.HOST, port=args.port, threaded=True)
    finally:
        cluster.stop_all()
        print("[dashboard] all processes stopped", flush=True)


if __name__ == "__main__":
    main()
