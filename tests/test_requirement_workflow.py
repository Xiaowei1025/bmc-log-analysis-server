import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException
from starlette.requests import Request

from app import database, main


def make_request(user_id: int) -> Request:
    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "POST",
            "scheme": "http",
            "path": "/requests",
            "raw_path": b"/requests",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "root_path": "",
            "session": {"user_id": user_id, "csrf_token": "test-csrf"},
        },
        receive,
    )


class RequirementWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_db_path = database.DB_PATH
        database.DB_PATH = Path(self.temp_dir.name) / "bmc_hub.db"
        database.init_db()
        db = database.connection()
        self.owner_id = db.execute(
            "INSERT INTO users (username,password_hash,role) VALUES (?,?,?)",
            ("requester", "not-used", "contributor"),
        ).lastrowid
        self.reviewer_id = db.execute(
            "INSERT INTO users (username,password_hash,role) VALUES (?,?,?)",
            ("demo-maintainer", "not-used", "reviewer"),
        ).lastrowid
        self.other_id = db.execute(
            "INSERT INTO users (username,password_hash,role) VALUES (?,?,?)",
            ("other", "not-used", "contributor"),
        ).lastrowid
        db.commit()
        db.close()

    def tearDown(self):
        database.DB_PATH = self.previous_db_path
        self.temp_dir.cleanup()

    def create_requirement(self):
        response = main.create_requirement_request(
            make_request(self.owner_id),
            title="每天分析 AFR",
            category="feature",
            description="每天需要重复分析 AFR 工具结果。",
            expected_value="减少人工重复操作。",
        )
        self.assertEqual(303, response.status_code)
        requirement_id = int(response.headers["location"].rsplit("/", 1)[-1])
        return requirement_id

    def test_create_review_edit_and_re_review_preserve_history(self):
        requirement_id = self.create_requirement()
        db = database.connection()
        first_revision = db.execute(
            "SELECT * FROM requirement_revisions WHERE requirement_id=?", (requirement_id,)
        ).fetchone()
        self.assertEqual(1, first_revision["revision_number"])
        db.close()

        response = main.review_requirement_request(
            make_request(self.reviewer_id), requirement_id, status="accepted", note="纳入自动化分析。"
        )
        self.assertEqual(303, response.status_code)

        response = main.edit_requirement_request(
            make_request(self.owner_id), requirement_id,
            title="AFR 自动分析",
            category="workflow",
            description="每天自动拉取并分析 AFR 结果。",
            expected_value="减少重复分析并保留追踪记录。",
        )
        self.assertEqual(303, response.status_code)

        db = database.connection()
        requirement = db.execute("SELECT * FROM requirement_requests WHERE id=?", (requirement_id,)).fetchone()
        revisions = db.execute(
            "SELECT * FROM requirement_revisions WHERE requirement_id=? ORDER BY revision_number",
            (requirement_id,),
        ).fetchall()
        events = db.execute(
            "SELECT * FROM requirement_review_events WHERE requirement_id=? ORDER BY id",
            (requirement_id,),
        ).fetchall()
        db.close()
        self.assertEqual("pending", requirement["status"])
        self.assertEqual("AFR 自动分析", requirement["title"])
        self.assertEqual(2, len(revisions))
        self.assertEqual("每天分析 AFR", revisions[0]["title"])
        self.assertEqual("accepted", revisions[1]["status_at_submission"])
        self.assertEqual(1, len(events))
        self.assertEqual(first_revision["id"], events[0]["revision_id"])

        response = main.review_requirement_request(
            make_request(self.reviewer_id), requirement_id, status="planned", note="进入排期。"
        )
        self.assertEqual(303, response.status_code)
        db = database.connection()
        latest_event = db.execute("SELECT * FROM requirement_review_events ORDER BY id DESC LIMIT 1").fetchone()
        latest_revision = db.execute("SELECT * FROM requirement_revisions ORDER BY id DESC LIMIT 1").fetchone()
        db.close()
        self.assertEqual(latest_revision["id"], latest_event["revision_id"])

    def test_only_submitter_can_edit_and_detail_exposes_history(self):
        requirement_id = self.create_requirement()
        with self.assertRaises(HTTPException) as context:
            main.edit_requirement_request_form(make_request(self.other_id), requirement_id)
        self.assertEqual(403, context.exception.status_code)
        with self.assertRaises(HTTPException) as context:
            main.edit_requirement_request(make_request(self.other_id), requirement_id, title="越权", description="越权")
        self.assertEqual(403, context.exception.status_code)

        response = main.requirement_request_detail(make_request(self.owner_id), requirement_id)
        body = response.body.decode("utf-8")
        self.assertIn("修改需求", body)
        self.assertIn("版本 1", body)
        self.assertIn("提交历史", body)


if __name__ == "__main__":
    unittest.main()
