# Test results

Run on 2026-10-28 11:34 (Python 3.13.18 on Linux).

| # | Test | Expected | Observed | Result |
|---|---|---|---|---|
| T1 | Upload a 5 MB file | 5 chunks, each stored on 2 different nodes | 5 chunks, 10 copies on 2 different nodes each; copies per node 5001: 4, 5002: 3, 5003: 3; upload took 0.10 s | PASS |
| T2 | Download with all nodes running | SHA-256 checksum matches the original | SHA-256 matches the original (9fb8166b41a9...); download took 0.04 s | PASS |
| T3 | Stop one storage node, then download | File downloads complete; checksum matches | node 5002 stopped; file complete in 0.05 s, 1 of 5 chunks read from their second copy; checksum matches | PASS |
| T4 | Keep the node stopped for 10+ seconds | Master marks it dead and copies its chunks to a healthy node | marked dead after 10.4 s without a heartbeat (10.0 s after it stopped); 3 lost copies re-created on healthy nodes 0.04 s later; every chunk back to 2 live copies | PASS |
| T5 | Stop a second node after re-replication | File still downloads correctly | nodes 5002 and 5003 both down; all 5 chunks read from node 5001; checksum matches | PASS |
| E1 | Restart both stopped nodes (extra) | Nodes rejoin, 2 live copies again, stale copies removed | both nodes rejoined; every chunk has 2 live copies; 3 stale copies deleted from node 5002; checksum still matches | PASS |
| T6 | Upload 10 files of different sizes | Chunks spread roughly evenly across the 3 nodes | 10 files (0.3-10 MB), 45 chunks, 90 copies: node 5001: 30, node 5002: 30, node 5003: 30; all 10 files download with matching checksums | PASS |

## Upload and download time (median of 5 runs)

| File size | Upload | Download |
|---|---|---|
| 1 MB | 0.014 s | 0.008 s |
| 5 MB | 0.068 s | 0.046 s |
| 10 MB | 0.135 s | 0.077 s |
| 25 MB | 0.321 s | 0.374 s |
| 50 MB | 0.570 s | 0.622 s |
