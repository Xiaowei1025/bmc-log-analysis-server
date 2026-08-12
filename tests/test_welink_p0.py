import asyncio
import json
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from fastapi import HTTPException
from app import database, main
from app.welink_scheduler import claim_due_schedules
from tests.test_access_control import make_request
from starlette.requests import Request


def endpoint(path, method):
    return next(route.endpoint for route in main.app.routes if route.path == path and method in route.methods)


def api_request(token=None, body=None):
    raw = json.dumps(body or {}).encode("utf-8")
    headers = [(b"content-type", b"application/json")]
    if token:
        headers.append((b"authorization", f"Bearer {token}".encode()))
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": raw, "more_body": False}

    return Request({"type": "http", "http_version": "1.1", "method": "POST", "scheme": "http", "path": "/api", "raw_path": b"/api", "query_string": b"", "headers": headers, "client": ("127.0.0.1", 1), "server": ("test", 80), "root_path": "", "session": {}}, receive)


class WeLinkP0Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old = database.DB_PATH
        database.DB_PATH = Path(self.temp.name) / "hub.db"
        database.init_db()
        self.db = database.connection()
        self.owner = self.db.execute("INSERT INTO users(username,password_hash,role) VALUES('owner','x','contributor')").lastrowid
        self.other = self.db.execute("INSERT INTO users(username,password_hash,role) VALUES('other','x','contributor')").lastrowid
        self.db.commit()

    def tearDown(self):
        self.db.close(); database.DB_PATH = self.old; self.temp.cleanup()

    def test_group_write_is_bound_and_other_user_cannot_update_issue(self):
        source_response = endpoint("/welink/sources", "POST")(
            make_request(self.owner), source_type="notice_group", display_name="私有群", conversation_key="private", note="", lookback_days=3, group_id=0
        )
        self.assertEqual(303, source_response.status_code)
        source = self.db.execute("SELECT group_id FROM welink_sources WHERE conversation_key='private'").fetchone()
        self.assertIsNotNone(source["group_id"])
        issue_id = self.db.execute("INSERT INTO welink_issues(title,group_id,created_by) VALUES('私有问题',?,?)", (source["group_id"], self.owner)).lastrowid
        self.db.commit()
        with self.assertRaises(Exception) as error:
            endpoint("/welink/issues/{issue_id}/status", "POST")(make_request(self.other), issue_id=issue_id, status="已闭环")
        self.assertEqual(404, error.exception.status_code)

    def test_invalid_group_read_does_not_leave_sqlite_locked(self):
        with self.assertRaises(HTTPException) as missing:
            endpoint("/welink", "GET")(make_request(self.owner), group_id=999999)
        self.assertEqual(404, missing.exception.status_code)
        # The next normal request must still be able to read/write the same
        # database connection after the rejected group id.
        page = endpoint("/welink", "GET")(make_request(self.owner))
        self.assertEqual(200, page.status_code)

    def test_connector_pair_lease_and_result_round_trip(self):
        pair = endpoint("/welink/connectors/pair", "POST")(make_request(self.owner), device_name="Windows 连接器")
        payload = json.loads(pair.body.decode())
        token = payload["token"]
        group_id = self.db.execute("SELECT id FROM welink_groups WHERE owner_id=? AND is_personal=1", (self.owner,)).fetchone()["id"]
        run_id = self.db.execute("INSERT INTO welink_runs(status,summary,run_mode,requested_by,group_id) VALUES('queued','等待','production',?,?)", (self.owner, group_id)).lastrowid
        self.db.execute("INSERT INTO welink_jobs(group_id,requested_by,run_id,payload,idempotency_key) VALUES(?,?,?,?,?)", (group_id, self.owner, run_id, '{"sources":[]}', "test-job")); self.db.commit()
        heartbeat = asyncio.run(endpoint("/api/welink/connectors/heartbeat", "POST")(api_request(token, {"capabilities": ["welink-cli"]})))
        self.assertEqual(200, heartbeat.status_code)
        leased = endpoint("/api/welink/connectors/jobs", "GET")(api_request(token))
        job = json.loads(leased.body.decode())["job"]
        self.assertIsNotNone(job)
        result = asyncio.run(endpoint("/api/welink/connectors/jobs/{job_id}/result", "POST")(api_request(token, {"lease_token": job["lease_token"], "ok": True, "summary": "已读取并完成投递", "issues": [{"title": "风扇异常", "severity": "P1", "background": "温度上升", "evidence": [{"excerpt": "fan alarm", "source_name": "测试群"}], "actions": [{"title": "更换风扇"}]}], "report": "## 测试报告"}), job_id=job["id"]))
        self.assertEqual(200, result.status_code)
        self.assertEqual("completed", self.db.execute("SELECT status FROM welink_jobs WHERE id=?", (job["id"],)).fetchone()["status"])
        self.assertEqual("completed", self.db.execute("SELECT status FROM welink_runs WHERE id=?", (run_id,)).fetchone()["status"])
        self.assertEqual(1, self.db.execute("SELECT COUNT(*) FROM welink_issues WHERE run_id=?", (run_id,)).fetchone()[0])
        self.assertEqual(1, self.db.execute("SELECT COUNT(*) FROM welink_reports WHERE run_id=?", (run_id,)).fetchone()[0])

    def test_scheduler_is_group_scoped_and_idempotent_per_minute(self):
        endpoint("/welink", "GET")(make_request(self.owner))
        group_id = self.db.execute(
            "SELECT id FROM welink_groups WHERE owner_id=? AND is_personal=1", (self.owner,)
        ).fetchone()["id"]
        self.db.execute(
            "INSERT INTO app_settings (key,value,updated_by) VALUES ('welink_run_mode','production',?)",
            (self.owner,),
        )
        self.db.execute(
            "INSERT INTO welink_schedules (group_id,enabled,schedule_time,updated_by) VALUES (?,?,?,?)",
            (group_id, 1, "08:00", self.owner),
        )
        self.db.execute(
            "INSERT INTO welink_sources (source_type,display_name,conversation_key,created_by,group_id) VALUES ('notice_group','定时群','scheduled',?,?)",
            (self.owner, group_id),
        )
        self.db.commit()
        first = claim_due_schedules(datetime(2026, 8, 6, 8, 0))
        second = claim_due_schedules(datetime(2026, 8, 6, 8, 0))
        self.assertEqual(1, len(first))
        self.assertEqual([], second)
        self.assertEqual(1, self.db.execute("SELECT COUNT(*) AS count FROM welink_jobs").fetchone()["count"])
        run = self.db.execute("SELECT group_id,status FROM welink_runs WHERE id=?", (first[0],)).fetchone()
        self.assertEqual(group_id, run["group_id"])
        self.assertEqual("queued", run["status"])


if __name__ == "__main__":
    unittest.main()
