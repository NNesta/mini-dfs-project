# Mini Distributed File Storage

A small file storage system modelled on HDFS. It splits files into 1 MB chunks,
stores two copies of every chunk on different storage nodes, and still returns
the complete, unchanged file when a storage node fails. When a node stays down,
the master copies its chunks to a healthy node so every chunk has two copies again.

One master, three storage nodes and a client, all on one laptop:

```
                 client.py  (splits, uploads, downloads, checks SHA-256)
                  |      \
   1. where do    |       \  2. chunks go straight
      chunks go?  |        \    to the storage nodes
                  v         v
          master.py :5000   storage_node.py :5001  :5002  :5003
          (chunk map,  <----  heartbeat every 3 s
           health, healing)
```

## Requirements

- [uv](https://docs.astral.sh/uv/) (`curl -LsSf https://astral.sh/uv/install.sh | sh` or `brew install uv`)
- Run `uv sync` once in this folder. It downloads Python 3.13 if needed and creates
  `.venv/` with Flask, requests and matplotlib, pinned in `uv.lock`.
- Without uv: Python 3.10 or newer and `pip install -r requirements.txt`, then use
  `python` wherever this guide says `uv run`.

`uv run <script>` runs a script inside `.venv/`. You can also activate the
environment once with `source .venv/bin/activate` and then type `python <script>`.

> **macOS note:** AirPlay Receiver also listens on port 5000. The master still
> works because it binds `127.0.0.1:5000` directly. If the master is **not**
> running, the client may print an empty error (AirPlay answers with HTTP 403).
> To avoid confusion, turn off *System Settings → General → AirDrop & Handoff →
> AirPlay Receiver*.

## Quick start

**Web dashboard (best for presenting)**

```bash
uv run dashboard.py --fresh      # starts the master, 3 storage nodes and the dashboard
```

Open <http://127.0.0.1:8080>. Everything runs from this one command, and Ctrl+C
stops it all. See [Web dashboard](#web-dashboard) below.

**Option A - one terminal for the whole cluster**

```bash
uv run cluster.py --fresh        # starts the master and 3 storage nodes
```

Then, in a second terminal:

```bash
uv run client.py upload samples/reviews.csv
uv run client.py map reviews.csv
uv run client.py download reviews.csv
```

In the cluster terminal you can type `stop 5002`, `start 5002`, `status` or `quit`.

**Option B - one terminal per component** (best for the live demo, since you can
see each node's log and stop one with Ctrl+C)

```bash
uv run master.py
uv run storage_node.py --port 5001
uv run storage_node.py --port 5002
uv run storage_node.py --port 5003
```

## Client commands

| Command | What it does |
|---|---|
| `uv run client.py upload <path> [--name N]` | Split a file into 1 MB chunks and store 2 copies of each |
| `uv run client.py download <name> [--out P]` | Rebuild the file from any live copies and verify its SHA-256 |
| `uv run client.py list` | List stored files with their health (healthy / degraded / unavailable) |
| `uv run client.py map [name]` | Chunk map: which node holds each chunk, and how many live copies |
| `uv run client.py nodes` | Storage node status, last heartbeat, chunks and disk use |
| `uv run client.py delete <name>` | Delete a file and all its chunks |
| `uv run client.py events` | Recent cluster events (joins, failures, re-replication) |

## Web dashboard

```bash
uv run dashboard.py            # start the cluster and the dashboard
uv run dashboard.py --fresh    # same, but delete stored chunks and metadata first
uv run dashboard.py --open     # also open the browser
```

Then open <http://127.0.0.1:8080>. The dashboard is just another client: it
uploads and downloads through the same `Client` class as `client.py`, so chunk
data still goes straight between the client and the nodes. It also runs the
master and the nodes as child processes (like `cluster.py`), so it can crash and
restart nodes from the browser.

| Page | What it shows |
|---|---|
| **Live cluster** | Health summary; the **guided fault-tolerance demo** (upload, crash a node, read during the failure, watch the master detect it and re-replicate, restart the node); a live topology with animated heartbeats and chunk transfers; each node's heartbeat timer against the 10 s limit and the chunks on its disk; file upload (drag and drop, sample CSV, random file), download with checksum report; the chunk map; the master's event log |
| **Test results** | `results/results.json` from `run_tests.py`: the T1-T6 + E1 table, key timings, the three charts and a transfer-time comparison |
| **How it works** | The three roles, the five flows (upload, download, failure detection, self-healing, rejoin), both HTTP APIs and the known limitations |
| **Admin** | After sign-in: cluster control, file management, the chunks on each node, the integrity check, the activity log, password change and cluster reset. See [Admin sign-in](#admin-sign-in) |

Add `?theme=light` or `?theme=dark` to the URL to force a theme, for example on
a projector. If a master is already running (say from `cluster.py`), the dashboard
attaches to it instead of starting a second cluster. In that case **Crash node**
only works for nodes the dashboard itself restarted. Stop the dashboard before
running `run_tests.py`, because both use ports 5000-5003.

Dashboard API (used by the page, handy for scripting):

| Method | Path | Purpose | Needs admin |
|---|---|---|---|
| GET | `/api/state?since=<t>` | Master view, node health, chunks on each node's disk, files with chunk maps, new events, sign-in state | No |
| POST | `/api/upload` | Upload a file (multipart field `file`) | To replace a file |
| POST | `/api/upload/sample`, `/api/upload/random` | Upload `samples/reviews.csv`, or a random file of `{"size_mb": n}` | No |
| POST | `/api/files/<name>/download` | Rebuild and verify a file into `downloads/`, return the per-chunk report | No |
| DELETE | `/api/files/<name>` | Delete a file and its chunks | Yes |
| POST | `/api/nodes/<port>/crash`, `/api/nodes/<port>/start` | Kill or restart a storage node | Yes |
| POST | `/api/reset` | Stop everything, delete all data, start a fresh cluster | Yes |
| GET | `/api/results` | Saved test results | No |
| POST | `/api/admin/setup`, `/api/admin/login`, `/api/admin/logout` | Set the first password (`{"password": ...}`), sign in, sign out | No |
| POST | `/api/admin/password` | Change the password (`{"current": ..., "new": ...}`) | Yes |
| POST | `/api/admin/verify` | Integrity check: read every copy of every chunk | Yes |
| GET | `/api/admin/activity` | The latest 200 activity log entries | Yes |

## Admin sign-in

The dashboard has one admin and one password. User accounts are out of scope for
this project, so nobody registers and files have no owners. The first time you
open the dashboard, click **Admin sign-in** and choose the password. Whoever does
this first becomes the admin.

| Action | Anyone | Admin |
|---|---|---|
| Watch the cluster, read test results | Yes | Yes |
| Upload a new file, download any file | Yes | Yes |
| Replace or delete a file | No | Yes |
| Crash or restart a storage node | No | Yes |
| Inspect chunks, run the integrity check, read the activity log | No | Yes |
| Reset the cluster | No | Yes |

Downloads stay open on purpose, so a visitor can still prove test T3 while a node
is down. The **Admin** tab adds:

- **Cluster control:** every process with its status, last heartbeat and disk use,
  and the crash and restart buttons.
- **Files:** every stored file, with download and delete.
- **Chunks on a node:** what each node holds, including stale copies. It is
  read-only on purpose. The master tracks which nodes are alive, not which copies
  each node holds, so deleting a copy by hand would leave a chunk short of copies
  without anyone noticing.
- **Integrity check:** reads every copy of every chunk and compares it with the
  SHA-256 the master recorded, like `hdfs fsck`. A normal download stops at the
  first good copy, so only this finds a damaged second copy. It reports problems
  but does not repair them.
- **Activity log:** who did what on the dashboard, including failed sign-ins. It
  survives restarts, `--fresh` and a cluster reset.

The password is stored only as a PBKDF2-SHA256 hash in `admin.json`, and activity
goes to `admin_activity.jsonl`. Git ignores both. To reset a forgotten password,
stop the dashboard and delete `admin.json`. Run the admin checks with:

```bash
uv run test_admin.py     # a few seconds, uses its own cluster and password file
```

Like `run_tests.py` it needs ports 5000-5003, so stop any running cluster first.
It does not touch `results/`.

## Tests and charts

```bash
uv run run_tests.py
```

Starts its own cluster in `test_run/` (your normal data is untouched), runs the
roadmap tests T1-T6 plus one extra rejoin check, times uploads and downloads,
and writes `results/results.md`, `results/results.json` and three charts. It takes
about 40 seconds, mostly waiting for the 10-second failure detection.

| # | Test | Expected result |
|---|---|---|
| T1 | Upload a 5 MB file | 5 chunks, each stored on 2 different nodes |
| T2 | Download with all nodes running | SHA-256 checksum matches the original |
| T3 | Stop one storage node, then download | File downloads complete; checksum matches |
| T4 | Keep the node stopped for 10+ seconds | Master marks it dead and copies its chunks to a healthy node |
| T5 | Stop a second node after re-replication | File still downloads correctly |
| T6 | Upload 10 files of different sizes | Chunks spread roughly evenly across the 3 nodes |
| E1 | Restart both stopped nodes (extra) | Nodes rejoin, 2 live copies again, stale copies removed |

## Live demo script (about 3 minutes)

**With the dashboard:** run `uv run dashboard.py --fresh`, open
<http://127.0.0.1:8080>, and either press **Auto-play** in the guided demo or click
through its five steps while explaining each one. The steps match the script below.
Crashing and restarting a node need the admin password, so sign in before you start.

**From the terminal:**

1. Start the cluster: `uv run cluster.py --fresh` (or four terminals, Option B).
2. `uv run client.py upload samples/reviews.csv` - 3 chunks, 2 nodes each.
3. `uv run client.py map reviews.csv` - show the chunk map.
4. Stop a node: type `stop 5002` (or Ctrl+C in its terminal).
5. `uv run client.py download reviews.csv` - complete file, "Checksum OK", the
   note column shows which chunks came from a backup copy.
6. Wait about 10 seconds; the master prints `node 5002 is DEAD` and
   `re-replicated ...`. Run `uv run client.py map reviews.csv` - every chunk is back
   to 2/2 live copies, none on 5002.
7. Bring it back: `start 5002`; the master removes its stale copies.

## How it works

- **Upload:** the client asks the master (`POST /allocate`) which 2 nodes get each
  chunk; the master picks the least-loaded live nodes. The client sends each chunk
  straight to those nodes (`PUT /chunks/<id>`), then reports the result
  (`POST /commit`) with the file's and each chunk's SHA-256.
- **Download:** the client gets the chunk map (`GET /files/<name>`), reads each
  chunk from the first live copy, checks the chunk checksum, falls back to the
  other copy if a node is down or a chunk is damaged, then checks the whole file's
  SHA-256 before saving it.
- **Failure detection:** each node sends a heartbeat every 3 s. A node that has
  been silent for 10 s is marked dead.
- **Self-healing:** for each chunk left with one live copy, the master tells a
  surviving node to copy it to a healthy node (`POST /replicate`), so chunk data
  moves node to node, never through the master.
- **Rejoin:** a node that comes back is asked for its chunk list; copies that
  were re-created elsewhere while it was away are deleted.

## Project files

| File | Role |
|---|---|
| `config.py` | Ports, chunk size, replication factor, heartbeat timings |
| `storage_node.py` | Flask storage node: save, return, list, delete and copy chunks; heartbeats |
| `master.py` | Flask master: metadata, chunk placement, failure detection, re-replication |
| `client.py` | Command-line client: upload, download, map, nodes, list, delete, events |
| `cluster.py` | Starts the master and 3 nodes from one terminal; stop/start nodes for demos |
| `dashboard.py` | Web dashboard server: starts the cluster, serves `web/`, exposes `/api/*` |
| `admin.py` | Dashboard admin sign-in, activity log and integrity check |
| `web/` | Dashboard front end (`index.html`, `style.css`, `app.js`); plain HTML/CSS/JS, no build step |
| `run_tests.py` | Automated tests T1-T6 + E1 and timing measurements |
| `test_admin.py` | Automated checks for the admin sign-in and what it protects |
| `charts.py` | Draws the result charts with matplotlib |
| `samples/reviews.csv` | 3 MB sample file for the demo |

## Known limitations

- The master is a single point of failure; real HDFS adds a standby master.
- All nodes run on one laptop, so real network delays are not tested.
- Files cannot be edited after upload, only replaced (as in HDFS).
- The admin sign-in guards the dashboard only. The master and node APIs stay open,
  so `client.py` needs no password and anyone on this laptop can still call them.
