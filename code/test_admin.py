"""Tests for the admin sign-in on the web dashboard.

    uv run test_admin.py

It starts its own cluster in test_run/admin/ and uses its own password file, so
your stored files, results/ and admin.json are not touched. It takes a few
seconds. Like run_tests.py it needs ports 5000-5003, so stop any running cluster
or dashboard first.

The check that matters most is the same as test T3: with a storage node stopped,
a download through the dashboard must still match the original checksum, for
visitors too. Only the buttons are locked, never access to the data.
"""
import hashlib
import io
import json
import os
import shutil
import sys
from pathlib import Path

import admin
from client import Client
from cluster import Cluster

HERE = Path(__file__).resolve().parent
WORK = HERE / "test_run" / "admin"
PASSWORD = "first-Password-1"
NEW_PASSWORD = "second-Password-2"
NAME = "report.bin"
VICTIM = 5002

failures = []


def check(what, passed, detail=""):
    print(f"  {'PASS' if passed else 'FAIL'}  {what}" + (f"  ({detail})" if detail else ""))
    if not passed:
        failures.append(what)


def upload(browser, data, name=NAME):
    return browser.post("/api/upload", data={"file": (io.BytesIO(data), name)},
                        content_type="multipart/form-data")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def test_first_run(dashboard, visitor, owner):
    state = visitor.get("/api/state").get_json()["admin"]
    check("no password is set on the first run", state == {"configured": False, "signed_in": False})
    check("cannot sign in before a password exists",
          visitor.post("/api/admin/login", json={"password": "x"}).status_code == 409)
    check("a weak password is refused",
          owner.post("/api/admin/setup", json={"password": "short1"}).status_code == 400)
    check("letters only is refused",
          owner.post("/api/admin/setup", json={"password": "onlyletters"}).status_code == 400)
    r = owner.post("/api/admin/setup", json={"password": PASSWORD})
    check("the first person sets the password and is signed in", r.get_json()["signed_in"] is True)
    check("the password can only be set once",
          visitor.post("/api/admin/setup", json={"password": "attacker-1"}).status_code == 409)
    stored = admin.ACCOUNT_FILE.read_text()
    check("admin.json holds a hash, not the password", PASSWORD not in stored
          and json.loads(stored)["password_hash"].startswith("pbkdf2:sha256"))
    check("a visitor is still not signed in",
          visitor.get("/api/state").get_json()["admin"]["signed_in"] is False)


def test_visitor_is_blocked(visitor, data):
    r = upload(visitor, data)
    check("a visitor can upload a new file", r.status_code == 200, r.get_data(as_text=True)[:80])
    blocked = [("DELETE", f"/api/files/{NAME}"), ("POST", f"/api/nodes/{VICTIM}/crash"),
               ("POST", f"/api/nodes/{VICTIM}/start"), ("POST", "/api/reset"),
               ("POST", "/api/admin/verify"), ("GET", "/api/admin/activity"),
               ("POST", "/api/admin/password")]
    for method, path in blocked:
        code = visitor.open(path, method=method).status_code
        check(f"a visitor gets 401 from {method} {path}", code == 401, str(code))
    check("the blocked delete did nothing", Client().info(NAME)["size"] == len(data))
    r = upload(visitor, b"overwrite attempt")
    check("a visitor cannot replace a file", r.status_code == 409)
    check("the file is unchanged after that", Client().info(NAME)["sha256"] == sha(data))


def test_sign_in(app):
    browser = app.test_client()
    check("a wrong password is refused",
          browser.post("/api/admin/login", json={"password": "wrong"}).status_code == 403)
    r = browser.post("/api/admin/login", json={"password": PASSWORD})
    check("the right password signs in", r.get_json()["signed_in"] is True)
    browser.post("/api/admin/logout")
    check("signing out locks the admin tools again",
          browser.get("/api/admin/activity").status_code == 401)
    check("a forged cookie is refused", forged(app).get("/api/admin/activity").status_code == 401)


def forged(app):
    """A browser presenting a session cookie that was not signed with our secret."""
    browser = app.test_client()
    browser.set_cookie("session", "eyJhZG1pbiI6InRydWUifQ.ZZZZZZ.not-a-real-signature")
    return browser


def test_t3_through_the_dashboard(owner, visitor, storage, data):
    check("a visitor cannot crash a node",
          visitor.post(f"/api/nodes/{VICTIM}/crash").status_code == 401)
    check("the admin crashes a node", owner.post(f"/api/nodes/{VICTIM}/crash").status_code == 200)

    r = visitor.post(f"/api/files/{NAME}/download")
    body = r.get_json()
    check("T3: a visitor downloads the file with a node down", r.status_code == 200, body.get("path"))
    saved = Path(body["path"]).read_bytes() if r.status_code == 200 else b""
    check("T3: the checksum matches the original", sha(saved) == sha(data))
    check("T3: a backup copy was really used",
          any(c["skipped"] for c in body.get("chunks", [])))

    report = owner.post("/api/admin/verify").get_json()
    file = report["files"][0]
    check("the integrity check reports the unreachable copies but the file readable",
          report["readable"] == 1 and file["status"] == "at risk"
          and {p["problem"] for p in file["problems"]} == {"unreachable"}
          and {p["node"] for p in file["problems"]} == {VICTIM})

    check("the admin restarts the node", owner.post(f"/api/nodes/{VICTIM}/start").status_code == 200)
    report = owner.post("/api/admin/verify").get_json()
    check("every copy is good again",
          report["good_copies"] == report["expected_copies"] == 10, str(report["good_copies"]))

    # Damage one copy on disk. The master cannot see this; only the check can.
    damaged = next(storage.glob(f"node_*/{NAME}_0"))
    damaged.write_bytes(b"damaged " * 100)
    r = visitor.post(f"/api/files/{NAME}/download")
    check("a damaged copy does not reach the reader", r.status_code == 200
          and sha(Path(r.get_json()["path"]).read_bytes()) == sha(data))
    report = owner.post("/api/admin/verify").get_json()
    problems = report["files"][0]["problems"]
    check("the integrity check finds the damaged copy",
          len(problems) == 1 and problems[0]["problem"] == "bad checksum"
          and problems[0]["chunk"] == f"{NAME}_0", str(problems))


def test_admin_file_control(owner, data):
    r = upload(owner, data[:2 * 2**20])
    check("the admin can replace a file", r.status_code == 200 and len(r.get_json()["chunks"]) == 2)
    check("the admin can delete a file", owner.delete(f"/api/files/{NAME}").status_code == 200)
    check("the file is gone", Client().files() == [])


def test_client_needs_no_password(data):
    path = WORK / "cli.bin"
    path.write_bytes(data)
    client = Client()
    client.upload(path, "cli.bin")
    saved = WORK / "cli_copy.bin"
    client.download("cli.bin", saved)
    check("client.py still uploads and downloads with no sign-in",
          sha(saved.read_bytes()) == sha(data))
    client.delete("cli.bin")
    check("client.py still deletes with no sign-in", client.files() == [])


def test_password_change(app, owner):
    other = app.test_client()
    other.post("/api/admin/login", json={"password": PASSWORD})
    r = owner.post("/api/admin/password", json={"current": "wrong", "new": NEW_PASSWORD})
    check("changing the password needs the current one", r.status_code == 403)
    r = owner.post("/api/admin/password", json={"current": PASSWORD, "new": "weak"})
    check("the new password must follow the rules", r.status_code == 400)
    r = owner.post("/api/admin/password", json={"current": PASSWORD, "new": NEW_PASSWORD})
    check("the admin changes the password", r.status_code == 200)
    check("the browser that changed it stays signed in",
          owner.get("/api/admin/activity").status_code == 200)
    check("every other browser is signed out",
          other.get("/api/admin/activity").status_code == 401)
    check("the old password no longer works",
          other.post("/api/admin/login", json={"password": PASSWORD}).status_code == 403)
    check("the new password works",
          other.post("/api/admin/login", json={"password": NEW_PASSWORD}).status_code == 200)


def test_activity_and_reset(owner, visitor, data):
    upload(visitor, data[:2**20], "kept-until-reset.bin")
    log = owner.get("/api/admin/activity").get_json()["activity"]
    actions = {e["action"] for e in log}
    check("the activity log records admin actions",
          {"crashed a node", "restarted a node", "deleted a file",
           "ran the integrity check", "changed the admin password"} <= actions)
    check("the activity log records failed sign-ins", "failed sign-in" in actions)
    check("the activity log tells visitors from the admin",
          log[0]["who"] == "visitor" and log[0]["action"] == "uploaded a file", str(log[0]))

    check("the admin resets the cluster", owner.post("/api/reset").status_code == 200)
    check("the reset deleted the files", Client().files() == [])
    log = owner.get("/api/admin/activity").get_json()["activity"]
    check("the activity log survives the reset", log[0]["action"] == "reset the cluster"
          and any(e["action"] == "crashed a node" for e in log))


def main():
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    admin.ACCOUNT_FILE = WORK / "admin.json"             # keep away from the real files
    admin.ACTIVITY_FILE = WORK / "activity.jsonl"

    import dashboard                                     # loads the test password file
    dashboard.STORAGE = WORK / "storage"
    dashboard.METADATA = WORK / "metadata.json"
    dashboard.DOWNLOADS = WORK / "downloads"
    dashboard.cluster = Cluster(data_dir=dashboard.STORAGE, metadata=dashboard.METADATA,
                                log_dir=WORK / "logs")
    dashboard.MODE["managed"] = True

    app = dashboard.app
    visitor, owner = app.test_client(), app.test_client()
    data = os.urandom(5 * 2**20)
    try:
        dashboard.cluster.start_all()
        for section in (lambda: test_first_run(dashboard, visitor, owner),
                        lambda: test_visitor_is_blocked(visitor, data),
                        lambda: test_sign_in(app),
                        lambda: test_t3_through_the_dashboard(owner, visitor, dashboard.STORAGE, data),
                        lambda: test_admin_file_control(owner, data),
                        lambda: test_client_needs_no_password(data),
                        lambda: test_password_change(app, owner),
                        lambda: test_activity_and_reset(owner, visitor, data)):
            section()
    finally:
        dashboard.cluster.stop_all()

    if failures:
        print(f"\n{len(failures)} check(s) FAILED:")
        for failure in failures:
            print(f"  - {failure}")
        print(f"\nCluster logs kept in {WORK / 'logs'}")
        sys.exit(1)
    shutil.rmtree(WORK, ignore_errors=True)
    print("\nAll admin checks passed.")


if __name__ == "__main__":
    main()
