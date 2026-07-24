import asyncio
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException
from starlette.requests import Request

from app import database, main


def make_request(user_id=None, csrf_token="test-csrf", method="GET", body=b""):
    sent = False

    async def receive():
        nonlocal sent
        if sent:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}

    headers = []
    if body:
        headers.append((b"content-type", b"application/x-www-form-urlencoded"))
    session = {"csrf_token": csrf_token}
    if user_id is not None:
        session["user_id"] = user_id
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": "/test",
            "raw_path": b"/test",
            "query_string": b"",
            "headers": headers,
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "root_path": "",
            "session": session,
        },
        receive,
    )


class AccessControlTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_db_path = database.DB_PATH
        database.DB_PATH = Path(self.temp_dir.name) / "bmc_hub.db"
        database.init_db()
        self.db = database.connection()
        self.owner_id = self.create_user("owner", "contributor")
        self.other_id = self.create_user("other", "contributor")
        self.reviewer_id = self.create_user("reviewer", "reviewer")
        self.admin_id = self.create_user("admin", "admin")

        self.log_path = Path(self.temp_dir.name) / "source.log"
        self.log_path.write_text("Fan 3 failed\n", encoding="utf-8")
        self.report_id = self.db.execute(
            """INSERT INTO analyses (original_name,storage_path,summary,status,created_by)
            VALUES (?,?,?,?,?)""",
            ("source.log", str(self.log_path), "{}", "completed", self.owner_id),
        ).lastrowid
        self.case_id = self.db.execute(
            "INSERT INTO knowledge_cases (title,body,created_by) VALUES (?,?,?)",
            ("案例", "正文", self.owner_id),
        ).lastrowid
        self.document_path = Path(self.temp_dir.name) / "source.docx"
        self.document_path.write_bytes(b"case source")
        self.import_id = self.db.execute(
            """INSERT INTO case_imports
            (knowledge_case_id,original_name,storage_path,source_format,imported_by)
            VALUES (?,?,?,?,?)""",
            (self.case_id, "source.docx", str(self.document_path), "docx", self.owner_id),
        ).lastrowid
        self.feature_id, _ = main.save_feature(
            self.db,
            None,
            "风扇异常",
            "风扇告警",
            "风扇需要检查",
            "检查风扇模块",
            "fan",
            "散热",
            "high",
            "all",
            [("*", "Fan 3 failed", False)],
            self.owner_id,
            [],
        )
        self.db.execute(
            "INSERT INTO feature_log_reviews (case_id,analysis_id,status,requested_by) VALUES (?,?,?,?)",
            (self.feature_id, self.report_id, "pending", self.owner_id),
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        database.DB_PATH = self.previous_db_path
        self.temp_dir.cleanup()

    def create_user(self, username, role):
        return self.db.execute(
            "INSERT INTO users (username,password_hash,role) VALUES (?,?,?)",
            (username, "not-used-in-test", role),
        ).lastrowid

    def test_anonymous_dashboard_is_rejected(self):
        with self.assertRaises(HTTPException) as context:
            main.dashboard(make_request())
        self.assertEqual(401, context.exception.status_code)

    def test_production_secret_rejects_examples_and_short_values(self):
        self.assertFalse(main.production_secret_is_safe("replace-with-a-long-random-secret"))
        self.assertFalse(main.production_secret_is_safe("too-short"))
        self.assertTrue(main.production_secret_is_safe("a" * 48))

    def test_original_log_is_limited_to_owner_reviewer_and_admin(self):
        owner_response = main.download_original_log(make_request(self.owner_id), self.report_id)
        reviewer_response = main.download_original_log(make_request(self.reviewer_id), self.report_id)
        admin_response = main.download_original_log(make_request(self.admin_id), self.report_id)
        self.assertEqual(self.log_path, owner_response.path)
        self.assertEqual(self.log_path, reviewer_response.path)
        self.assertEqual(self.log_path, admin_response.path)
        with self.assertRaises(HTTPException) as context:
            main.download_original_log(make_request(self.other_id), self.report_id)
        self.assertEqual(403, context.exception.status_code)

    def test_case_source_is_limited_to_owner_reviewer_and_admin(self):
        owner_response = main.download_case_import(make_request(self.owner_id), self.import_id)
        reviewer_response = main.download_case_import(make_request(self.reviewer_id), self.import_id)
        admin_response = main.download_case_import(make_request(self.admin_id), self.import_id)
        self.assertEqual(self.document_path, owner_response.path)
        self.assertEqual(self.document_path, reviewer_response.path)
        self.assertEqual(self.document_path, admin_response.path)
        with self.assertRaises(HTTPException) as context:
            main.download_case_import(make_request(self.other_id), self.import_id)
        self.assertEqual(403, context.exception.status_code)

    def test_feature_review_requires_owner_reviewer_or_admin(self):
        with self.assertRaises(HTTPException) as context:
            main.update_feature_review(
                make_request(self.other_id), self.feature_id, self.report_id, decision="confirmed"
            )
        self.assertEqual(403, context.exception.status_code)

        response = main.update_feature_review(
            make_request(self.reviewer_id), self.feature_id, self.report_id, decision="confirmed", note="证据充分"
        )
        self.assertEqual(303, response.status_code)
        review = self.db.execute(
            "SELECT status,reviewed_by,note FROM feature_log_reviews WHERE case_id=? AND analysis_id=?",
            (self.feature_id, self.report_id),
        ).fetchone()
        self.assertEqual("confirmed", review["status"])
        self.assertEqual(self.reviewer_id, review["reviewed_by"])
        self.assertEqual("证据充分", review["note"])

    def test_csrf_middleware_rejects_missing_or_invalid_token(self):
        async def invoke(body):
            pending = [{"type": "http.request", "body": body, "more_body": False}]
            sent, received = [], []

            async def receive():
                return pending.pop(0) if pending else {"type": "http.disconnect"}

            async def send(message):
                sent.append(message)

            async def downstream(scope, receive, send):
                received.append(await receive())
                await send({"type": "http.response.start", "status": 200, "headers": []})
                await send({"type": "http.response.body", "body": b"ok"})

            scope = {
                "type": "http", "http_version": "1.1", "method": "POST", "path": "/test",
                "raw_path": b"/test", "query_string": b"", "scheme": "http", "root_path": "",
                "headers": [(b"content-type", b"application/x-www-form-urlencoded")],
                "session": {"csrf_token": "test-csrf"},
            }
            await main.CSRFSecurityMiddleware(downstream)(scope, receive, send)
            return sent, received

        valid_sent, valid_received = asyncio.run(invoke(b"csrf_token=test-csrf&title=ok"))
        self.assertEqual(200, valid_sent[0]["status"])
        self.assertEqual(b"csrf_token=test-csrf&title=ok", valid_received[0]["body"])

        multipart = (
            b"------test\r\nContent-Disposition: form-data; name=\"csrf_token\"\r\n\r\n"
            b"test-csrf\r\n------test--\r\n"
        )
        self.assertEqual(
            "test-csrf",
            main.csrf_token_from_body(b"multipart/form-data; boundary=----test", multipart),
        )

        invalid_sent, invalid_received = asyncio.run(invoke(b"csrf_token=wrong"))
        self.assertEqual(403, invalid_sent[0]["status"])
        self.assertEqual([], invalid_received)


if __name__ == "__main__":
    unittest.main()
