"""Admin sign-in for the web dashboard, and the tools only the admin can use.

User accounts are out of scope for Mini DFS, so there is one admin and one
password. Anyone who opens the dashboard can watch the cluster, upload files and
download them. Signing in unlocks the actions that can lose or hide data:
crashing and restarting nodes, deleting or replacing files, resetting the cluster.

Two files live next to this one (neither goes into git):
    admin.json             password hash and session secret, never the password
    admin_activity.jsonl   one line per action: who did what, and when

The first person to open the dashboard chooses the password. To reset a forgotten
password, stop the dashboard and delete admin.json.

This guards the dashboard only. The master and the storage nodes keep their open
HTTP APIs, so client.py, the tests and failure recovery work exactly as before.
"""
import json
import os
import secrets
import threading
import time
from functools import wraps
from pathlib import Path

from flask import Blueprint, abort, jsonify, request, session
from werkzeug.security import check_password_hash, generate_password_hash

import config
from client import Client, DFSError, sha256

HERE = Path(__file__).resolve().parent
ACCOUNT_FILE = HERE / "admin.json"
ACTIVITY_FILE = HERE / "admin_activity.jsonl"
MIN_PASSWORD = 8

bp = Blueprint("admin", __name__, url_prefix="/api/admin")
client = Client()
lock = threading.Lock()
account = {}                  # "secret_key", "password_hash", "session_id"


def init_app(app):
    """Load admin.json (creating it on the first run) and add the admin routes."""
    if ACCOUNT_FILE.exists():
        account.update(json.loads(ACCOUNT_FILE.read_text()))
    else:
        account.update(secret_key=secrets.token_hex(32), password_hash=None, session_id=None)
        save_account()
    app.secret_key = account["secret_key"]
    # Strict: the browser never sends this cookie on a request started by another
    # site, so a web page you happen to visit cannot press admin buttons for you.
    app.config.update(SESSION_COOKIE_SAMESITE="Strict", SESSION_COOKIE_HTTPONLY=True)
    app.register_blueprint(bp)


def save_account():
    tmp = ACCOUNT_FILE.with_name(ACCOUNT_FILE.name + ".tmp")
    tmp.write_text(json.dumps(account, indent=2))
    tmp.chmod(0o600)                             # readable by this user only
    os.replace(tmp, ACCOUNT_FILE)


# ------------------------------------------------------------------ who is signed in

def signed_in():
    return bool(account["session_id"]) and session.get("admin") == account["session_id"]


def status():
    return {"configured": bool(account["password_hash"]), "signed_in": signed_in()}


def admin_required(view):
    """Put this on a route to answer 401 unless the admin is signed in."""
    @wraps(view)
    def wrapper(*args, **kwargs):
        if not signed_in():
            abort(401, description="sign in as admin to do this")
        return view(*args, **kwargs)
    return wrapper


# ---------------------------------------------------------------------- activity log

def record(action, detail=""):
    entry = {"time": time.time(), "who": "admin" if signed_in() else "visitor",
             "action": action, "detail": detail}
    with lock, ACTIVITY_FILE.open("a") as log:
        log.write(json.dumps(entry) + "\n")


def recent_activity(limit=200):
    with lock:
        lines = ACTIVITY_FILE.read_text().splitlines() if ACTIVITY_FILE.exists() else []
    return [json.loads(line) for line in reversed(lines[-limit:])]


# -------------------------------------------------------------------------- password

def posted(field):
    return str((request.get_json(silent=True) or {}).get(field, ""))


def check_rules(password):
    if len(password) < MIN_PASSWORD or password.isdigit() or password.isalpha():
        abort(400, description=f"use at least {MIN_PASSWORD} characters, "
                               f"with both letters and numbers")


def set_password(password):
    account["password_hash"] = generate_password_hash(password, method="pbkdf2:sha256")
    account["session_id"] = secrets.token_hex(16)     # signs out every other browser
    save_account()
    session["admin"] = account["session_id"]


@bp.post("/setup")
def setup():
    """First run: whoever gets here first chooses the admin password."""
    if account["password_hash"]:
        abort(409, description="the admin password is already set")
    password = posted("password")
    check_rules(password)
    set_password(password)
    record("set the admin password")
    return jsonify(status())


@bp.post("/login")
def login():
    if not account["password_hash"]:
        abort(409, description="choose the admin password first")
    if not check_password_hash(account["password_hash"], posted("password")):
        record("failed sign-in")
        abort(403, description="wrong password")
    session["admin"] = account["session_id"]
    record("signed in")
    return jsonify(status())


@bp.post("/logout")
def logout():
    if signed_in():
        record("signed out")
    session.clear()
    return jsonify(status())


@bp.post("/password")
@admin_required
def change_password():
    if not check_password_hash(account["password_hash"], posted("current")):
        abort(403, description="the current password is not correct")
    password = posted("new")
    check_rules(password)
    set_password(password)
    record("changed the admin password")
    return jsonify(status())


# --------------------------------------------------------------------- admin tools

@bp.get("/activity")
@admin_required
def activity():
    return jsonify(activity=recent_activity())


def check_file(info):
    """Read every copy of one file's chunks and compare each with the master's SHA-256."""
    problems, good, short, lost = [], 0, 0, 0
    for chunk in info["chunks"]:
        copies = 0
        for port in chunk["nodes"]:
            data, problem = client._get_chunk(port, chunk["id"])
            if data is not None and sha256(data) != chunk["sha256"]:
                problem = "bad checksum"
            if problem:
                problems.append({"chunk": chunk["id"], "node": port, "problem": problem})
            else:
                copies += 1
        good += copies
        short += copies < config.REPLICATION_FACTOR
        lost += copies == 0
    return {"name": info["name"], "status": "unreadable" if lost else "at risk" if short else "ok",
            "chunks": len(info["chunks"]), "good_copies": good,
            "expected_copies": len(info["chunks"]) * config.REPLICATION_FACTOR,
            "problems": problems}


@bp.post("/verify")
@admin_required
def verify():
    """Integrity check, like `hdfs fsck`: look at every copy, not just the first good one.

    A download stops at the first good copy, so it never notices a damaged second
    copy, and neither does the master, which only tracks which nodes are alive. The
    dashboard reads the chunks as a client, so data still never passes through the master.
    """
    start = time.perf_counter()
    report = []
    for item in client.files():
        try:
            report.append(check_file(client.info(item["name"])))
        except DFSError:
            pass                                       # deleted while we were checking
    readable = sum(f["status"] != "unreadable" for f in report)
    good = sum(f["good_copies"] for f in report)
    expected = sum(f["expected_copies"] for f in report)
    record("ran the integrity check", f"files readable: {readable} of {len(report)}, "
                                      f"copies good: {good} of {expected}")
    return jsonify(files=report, readable=readable, good_copies=good, expected_copies=expected,
                   seconds=time.perf_counter() - start)
