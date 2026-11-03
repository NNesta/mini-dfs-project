"""Shared settings for the Mini Distributed File Storage system.

Every component (master, storage nodes, client, tests) imports these values,
so the whole cluster agrees on ports, chunk size and timing.
"""
import re

HOST = "127.0.0.1"

MASTER_PORT = 5000
MASTER_URL = f"http://{HOST}:{MASTER_PORT}"
NODE_PORTS = [5001, 5002, 5003]
DASHBOARD_PORT = 8080           # web dashboard (dashboard.py)

CHUNK_SIZE = 1024 * 1024        # 1 MB per chunk
REPLICATION_FACTOR = 2          # every chunk is stored on 2 different nodes

HEARTBEAT_INTERVAL = 3          # a node reports to the master every 3 s
DEAD_AFTER = 10                 # silent for 10 s -> the master marks it dead
MONITOR_INTERVAL = 1            # how often the master checks nodes and repairs

REQUEST_TIMEOUT = 5             # seconds before an HTTP call gives up

# File names become part of chunk ids and chunk file names on disk, so they are
# limited to characters that are safe on Windows, macOS and Linux.
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._()\- ]{0,150}$")


def node_url(port):
    """Base URL of the storage node listening on `port`."""
    return f"http://{HOST}:{port}"


def is_safe_name(name):
    return bool(SAFE_NAME.match(name or ""))
