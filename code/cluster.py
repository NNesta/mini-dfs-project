"""Start the whole cluster (master + 3 storage nodes) from one terminal.

    python cluster.py             start everything, then type:
        stop 5002                 crash a storage node (fault-tolerance demo)
        start 5002                bring it back
        status                    show which processes are running
        quit                      stop everything

    python cluster.py --fresh     wipe stored chunks and metadata first

Each component can also run in its own terminal instead:
    python master.py
    python storage_node.py --port 5001   (and 5002, 5003)
"""
import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

import requests

import config

HERE = Path(__file__).resolve().parent


def responds(url):
    try:
        return requests.get(url, timeout=1).ok
    except requests.RequestException:
        return False


def wait_until(check, what, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if check():
            return
        time.sleep(0.2)
    raise RuntimeError(f"{what} did not start within {timeout} s")


class Cluster:
    """Starts and stops the master and storage nodes as separate processes."""

    def __init__(self, data_dir="storage", metadata="metadata.json", log_dir=None):
        self.data_dir, self.metadata, self.log_dir = str(data_dir), str(metadata), log_dir
        self.procs, self.logs = {}, {}

    def _spawn(self, key, args):
        out = None
        if self.log_dir:
            Path(self.log_dir).mkdir(parents=True, exist_ok=True)
            out = self.logs[key] = open(Path(self.log_dir) / f"{key}.log", "a")
        self.procs[key] = subprocess.Popen([sys.executable, "-u", *args], cwd=HERE,
                                           stdout=out, stderr=subprocess.STDOUT if out else None)

    def start_master(self):
        self._spawn("master", ["master.py", "--metadata", self.metadata])
        wait_until(lambda: responds(config.MASTER_URL + "/"), "master")

    def start_node(self, port):
        self._spawn(port, ["storage_node.py", "--port", str(port), "--data-dir", self.data_dir])
        wait_until(lambda: responds(config.node_url(port) + "/health"), f"node {port}")

    def stop_node(self, port):
        """Kill the process without warning, as a real crash would."""
        proc = self.procs.pop(port, None)
        if proc:
            proc.kill()
            proc.wait()

    def start_all(self):
        self.start_master()
        for port in config.NODE_PORTS:
            self.start_node(port)
        # each node sends its first heartbeat as soon as it starts
        wait_until(lambda: len(requests.get(config.MASTER_URL + "/").json()["nodes_alive"])
                   == len(config.NODE_PORTS), "heartbeats from all nodes")

    def stop_all(self):
        for key in list(self.procs):
            proc = self.procs.pop(key)
            proc.kill()
            proc.wait()
        for handle in self.logs.values():
            handle.close()
        self.logs.clear()

    def running(self):
        return [key for key, proc in self.procs.items() if proc.poll() is None]


def main():
    parser = argparse.ArgumentParser(description="Run the master and 3 storage nodes.")
    parser.add_argument("--fresh", action="store_true", help="delete stored data first")
    args = parser.parse_args()
    if args.fresh:
        shutil.rmtree(HERE / "storage", ignore_errors=True)
        (HERE / "metadata.json").unlink(missing_ok=True)

    cluster = Cluster()
    cluster.start_all()
    time.sleep(0.3)
    print("\nCluster running: master on 5000, storage nodes on "
          f"{', '.join(map(str, config.NODE_PORTS))}.")
    print("Commands: stop <port> | start <port> | status | quit\n")
    try:
        while True:
            words = input().strip().split()
            if not words:
                continue
            cmd, port = words[0].lower(), (int(words[1]) if len(words) > 1 and
                                           words[1].isdigit() else None)
            if cmd in ("quit", "exit", "q"):
                break
            elif cmd == "stop" and port in config.NODE_PORTS:
                cluster.stop_node(port)
                print(f"[cluster] node {port} stopped (crashed)")
            elif cmd == "start" and port in config.NODE_PORTS:
                if port in cluster.running():
                    print(f"[cluster] node {port} is already running")
                else:
                    cluster.start_node(port)
            elif cmd == "status":
                print("[cluster] running: " + ", ".join(str(k) for k in cluster.running()))
            else:
                print("Commands: stop <port> | start <port> | status | quit")
    except (KeyboardInterrupt, EOFError):
        pass
    finally:
        cluster.stop_all()
        print("\n[cluster] all processes stopped")


if __name__ == "__main__":
    main()
