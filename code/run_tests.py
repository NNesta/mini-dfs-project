"""Automated tests T1-T6 from the project roadmap, plus timing measurements.

    python run_tests.py

It starts its own cluster in test_run/ (your normal data is not touched), runs
every test, then writes:
    results/results.json   all measured numbers
    results/results.md     the results table used in the report
    results/*.png          charts (made by charts.py)

It takes about 1.5 minutes; most of that is waiting for failure detection.
"""
import hashlib
import json
import platform
import random
import shutil
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

import config
from client import Client
from cluster import Cluster

HERE = Path(__file__).resolve().parent
WORK = HERE / "test_run"
RESULTS = HERE / "results"
MB = 2**20

client = Client()
report = {"generated": datetime.now().strftime("%Y-%m-%d %H:%M"),
          "environment": f"Python {platform.python_version()} on {platform.system()}",
          "tests": [], "performance": [], "timeline": {}, "distribution": {}}


# ------------------------------------------------------------------- helpers

def make_file(name, size, seed):
    path = WORK / "input" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(random.Random(seed).randbytes(size))
    return path


def file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def chunks_on(port):
    """What a storage node physically holds (asks the node, not the master)."""
    return set(requests.get(f"{config.node_url(port)}/chunks", timeout=5).json()["chunks"])


def wait_for_event(kind, since, timeout=30, **match):
    deadline = time.time() + timeout
    while time.time() < deadline:
        for e in client.events(since):
            if e["kind"] == kind and all(e.get(k) == v for k, v in match.items()):
                return e
        time.sleep(0.2)
    raise AssertionError(f"no '{kind}' event within {timeout} s")


def record(test_id, name, expected, passed, observed, **data):
    report["tests"].append({"id": test_id, "name": name, "expected": expected,
                            "observed": observed, "passed": bool(passed), **data})
    print(f"  {test_id:<3} {'PASS' if passed else 'FAIL'}  {name}\n       {observed}")


def run(test_id, name, expected, fn):
    """Run one test; an exception counts as a failure with its message."""
    try:
        fn()
    except Exception as exc:                           # noqa: BLE001 - report every failure
        record(test_id, name, expected, False, f"error: {exc}")


def fresh_cluster(cluster):
    cluster.stop_all()
    shutil.rmtree(WORK / "storage", ignore_errors=True)
    (WORK / "metadata.json").unlink(missing_ok=True)
    cluster.start_all()


# --------------------------------------------------------------------- tests

STATE = {}


def t1():
    path = make_file("test_5mb.bin", 5 * MB, seed=1)
    STATE.update(path=path, sha=file_sha(path))
    up = client.upload(path)
    info = client.info(path.name)
    distinct = all(len(set(c["nodes"])) == 2 for c in info["chunks"])
    on_disk = all(c["id"] in chunks_on(p) for c in info["chunks"] for p in c["nodes"])
    per_node = {p: sum(p in c["nodes"] for c in info["chunks"]) for p in config.NODE_PORTS}
    passed = len(info["chunks"]) == 5 and distinct and on_disk
    record("T1", "Upload a 5 MB file", "5 chunks, each stored on 2 different nodes", passed,
           f"{len(info['chunks'])} chunks, {2 * len(info['chunks'])} copies on 2 different "
           f"nodes each; copies per node "
           + ", ".join(f"{p}: {n}" for p, n in per_node.items())
           + f"; upload took {up['seconds']:.2f} s",
           seconds=up["seconds"], placement={c["id"]: c["nodes"] for c in info["chunks"]})


def t2():
    out = WORK / "output" / "t2.bin"
    down = client.download(STATE["path"].name, out)
    passed = file_sha(out) == STATE["sha"]
    record("T2", "Download with all nodes running", "SHA-256 checksum matches the original",
           passed, f"SHA-256 matches the original ({STATE['sha'][:12]}...); "
           f"download took {down['seconds']:.2f} s", seconds=down["seconds"])


def t3(cluster):
    STATE["t0"] = time.time()
    cluster.stop_node(5002)
    out = WORK / "output" / "t3.bin"
    down = client.download(STATE["path"].name, out)
    STATE["t3_done"] = time.time()
    backups = [c["id"] for c in down["chunks"] if c["skipped"]]
    passed = file_sha(out) == STATE["sha"]
    record("T3", "Stop one storage node, then download",
           "File downloads complete; checksum matches", passed,
           f"node 5002 stopped; file complete in {down['seconds']:.2f} s, {len(backups)} of "
           f"{len(down['chunks'])} chunks read from their second copy; checksum matches",
           seconds=down["seconds"], backup_chunks=backups)


def t4():
    t0 = STATE["t0"]
    dead = wait_for_event("node_dead", t0, port=5002)
    healthy = wait_for_event("healthy", dead["time"] - 0.001)
    copies = [e for e in client.events(t0) if e["kind"] == "repaired"]
    info = client.info(STATE["path"].name)
    off_dead = all(5002 not in c["nodes"] and len(c["live_nodes"]) == 2 for c in info["chunks"])
    on_disk = all(c["id"] in chunks_on(p) for c in info["chunks"] for p in c["nodes"])
    detect, repair = dead["time"] - t0, healthy["time"] - t0
    last_beat = detect - dead["silent"]
    report["timeline"] = {"last_heartbeat": round(last_beat, 2), "node_stopped": 0.0,
                          "download_ok": round(STATE["t3_done"] - t0, 2),
                          "marked_dead": round(detect, 2), "re_replicated": round(repair, 2),
                          "copies_made": len(copies)}
    record("T4", "Keep the node stopped for 10+ seconds",
           "Master marks it dead and copies its chunks to a healthy node",
           off_dead and on_disk and len(copies) == dead["chunks"],
           f"marked dead after {dead['silent']:.1f} s without a heartbeat ({detect:.1f} s after "
           f"it stopped); {len(copies)} lost copies re-created on healthy nodes "
           f"{repair - detect:.2f} s later; every chunk back to 2 live copies",
           detect_seconds=detect, repair_seconds=repair, silent_seconds=dead["silent"])


def t5(cluster):
    STATE["t5"] = time.time()
    cluster.stop_node(5003)
    out = WORK / "output" / "t5.bin"
    down = client.download(STATE["path"].name, out)
    served = sorted({c["node"] for c in down["chunks"]})
    passed = file_sha(out) == STATE["sha"]
    record("T5", "Stop a second node after re-replication", "File still downloads correctly",
           passed, f"nodes 5002 and 5003 both down; all {len(down['chunks'])} chunks read "
           f"from node {', '.join(map(str, served))}; checksum matches",
           seconds=down["seconds"])


def e1(cluster):
    """Extra check: stopped nodes rejoin and the cluster heals itself."""
    wait_for_event("node_dead", STATE["t5"], port=5003)
    since = time.time()
    cluster.start_node(5002)
    cluster.start_node(5003)
    wait_for_event("healthy", since)
    cleanup = wait_for_event("cleanup", since, port=5002)
    info = client.info(STATE["path"].name)
    healthy = all(len(c["live_nodes"]) == 2 for c in info["chunks"])
    no_stale = not any(c["id"] in chunks_on(5002) for c in info["chunks"]
                       if 5002 not in c["nodes"])
    out = WORK / "output" / "e1.bin"
    client.download(STATE["path"].name, out)
    passed = healthy and no_stale and file_sha(out) == STATE["sha"]
    record("E1", "Restart both stopped nodes (extra)",
           "Nodes rejoin, 2 live copies again, stale copies removed", passed,
           f"both nodes rejoined; every chunk has 2 live copies; {cleanup['chunks']} stale "
           f"copies deleted from node 5002; checksum still matches")


def performance():
    """Median upload and download time over 5 runs for several file sizes."""
    for size_mb in (1, 5, 10, 25, 50):
        path = make_file(f"perf_{size_mb}mb.bin", size_mb * MB, seed=size_mb)
        ups, downs = [], []
        for _ in range(5):
            ups.append(client.upload(path)["seconds"])
            downs.append(client.download(path.name, WORK / "output" / path.name)["seconds"])
            client.delete(path.name)
        row = {"size_mb": size_mb, "upload_s": round(statistics.median(ups), 3),
               "download_s": round(statistics.median(downs), 3)}
        report["performance"].append(row)
        print(f"       {size_mb:>3} MB  upload {row['upload_s']:.3f} s   "
              f"download {row['download_s']:.3f} s")


def t6():
    sizes_mb = [0.3, 0.8, 1.5, 2.2, 3.0, 4.5, 5.0, 6.7, 8.0, 10.0]
    paths = [make_file(f"dataset_{i + 1:02d}.bin", int(s * MB), seed=100 + i)
             for i, s in enumerate(sizes_mb)]
    for path in paths:
        client.upload(path)
    per_node_meta = {p: 0 for p in config.NODE_PORTS}
    total_chunks = 0
    for path in paths:
        for c in client.info(path.name)["chunks"]:
            total_chunks += 1
            for p in c["nodes"]:
                per_node_meta[p] += 1
    per_node_disk = {p: len(chunks_on(p)) for p in config.NODE_PORTS}
    verified = all(file_sha(client.download(p.name, WORK / "output" / p.name)["path"])
                   == file_sha(p) for p in paths)
    spread = max(per_node_disk.values()) - min(per_node_disk.values())
    report["distribution"] = {"files": len(paths), "chunks": total_chunks,
                              "per_node": {str(p): n for p, n in per_node_disk.items()},
                              "file_sizes_mb": sizes_mb}
    record("T6", "Upload 10 files of different sizes",
           "Chunks spread roughly evenly across the 3 nodes",
           per_node_meta == per_node_disk and spread <= 2 and verified,
           f"{len(paths)} files (0.3-10 MB), {total_chunks} chunks, {2 * total_chunks} copies: "
           + ", ".join(f"node {p}: {n}" for p, n in per_node_disk.items())
           + "; all 10 files download with matching checksums")


# ---------------------------------------------------------------------- main

def write_results():
    RESULTS.mkdir(exist_ok=True)
    (RESULTS / "results.json").write_text(json.dumps(report, indent=2))
    lines = ["# Test results", "", f"Run on {report['generated']} ({report['environment']}).", "",
             "| # | Test | Expected | Observed | Result |", "|---|---|---|---|---|"]
    lines += [f"| {t['id']} | {t['name']} | {t['expected']} | {t['observed']} | "
              f"{'PASS' if t['passed'] else 'FAIL'} |" for t in report["tests"]]
    lines += ["", "## Upload and download time (median of 5 runs)", "",
              "| File size | Upload | Download |", "|---|---|---|"]
    lines += [f"| {r['size_mb']} MB | {r['upload_s']:.3f} s | {r['download_s']:.3f} s |"
              for r in report["performance"]]
    (RESULTS / "results.md").write_text("\n".join(lines) + "\n")


def main():
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir()
    cluster = Cluster(data_dir=WORK / "storage", metadata=WORK / "metadata.json",
                      log_dir=WORK / "logs")
    print("Starting a test cluster (master + 3 storage nodes)...\n")
    try:
        cluster.start_all()
        run("T1", "Upload a 5 MB file", "5 chunks, each stored on 2 different nodes", t1)
        run("T2", "Download with all nodes running", "SHA-256 checksum matches the original", t2)
        run("T3", "Stop one storage node, then download",
            "File downloads complete; checksum matches", lambda: t3(cluster))
        print("       waiting for the master to notice the failure...")
        run("T4", "Keep the node stopped for 10+ seconds",
            "Master marks it dead and copies its chunks to a healthy node", t4)
        run("T5", "Stop a second node after re-replication", "File still downloads correctly",
            lambda: t5(cluster))
        print("       restarting the stopped nodes...")
        run("E1", "Restart both stopped nodes (extra)",
            "Nodes rejoin, 2 live copies again, stale copies removed", lambda: e1(cluster))

        print("\nFresh cluster for timing and distribution tests...")
        fresh_cluster(cluster)
        performance()
        run("T6", "Upload 10 files of different sizes",
            "Chunks spread roughly evenly across the 3 nodes", t6)
    finally:
        cluster.stop_all()

    write_results()
    passed = sum(t["passed"] for t in report["tests"])
    print(f"\n{passed}/{len(report['tests'])} tests passed. Results in {RESULTS}/")
    try:
        import charts
        charts.main()
    except ImportError as exc:
        print(f"(charts skipped: {exc})")
    sys.exit(0 if passed == len(report["tests"]) else 1)


if __name__ == "__main__":
    main()
