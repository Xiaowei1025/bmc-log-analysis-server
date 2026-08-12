import io
import inspect
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException
from starlette.datastructures import UploadFile
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
            "path": "/tools",
            "raw_path": b"/tools",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "root_path": "",
            "session": {"user_id": user_id, "csrf_token": "test-csrf"},
        },
        receive,
    )


class ToolPublishTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_db_path = database.DB_PATH
        self.previous_upload_dir = main.UPLOAD_DIR
        database.DB_PATH = Path(self.temp_dir.name) / "bmc_hub.db"
        main.UPLOAD_DIR = Path(self.temp_dir.name) / "uploads"
        for folder in ("tools", "logos"):
            (main.UPLOAD_DIR / folder).mkdir(parents=True)
        database.init_db()
        db = database.connection()
        self.user_id = db.execute(
            "INSERT INTO users (username,password_hash,role) VALUES (?,?,?)",
            ("publisher", "not-used-in-test", "contributor"),
        ).lastrowid
        self.admin_id = db.execute(
            "INSERT INTO users (username,password_hash,role) VALUES (?,?,?)",
            ("tool-admin", "not-used-in-test", "admin"),
        ).lastrowid
        db.commit()
        db.close()

    def tearDown(self):
        main.UPLOAD_DIR = self.previous_upload_dir
        database.DB_PATH = self.previous_db_path
        self.temp_dir.cleanup()

    def test_release_notes_is_optional_and_publishes_with_redirect(self):
        release_notes_default = inspect.signature(main.create_tool).parameters["release_notes"].default
        self.assertEqual("", release_notes_default.default)
        package = UploadFile(file=io.BytesIO(b"tool contents"), filename="maintenance-tool.zip")
        response = main.create_tool(
            make_request(self.user_id),
            name="维护工具",
            short_description="服务器维护工具",
            details="运行说明",
            version="1.0.0",
            release_notes="",
            package=package,
            logo=None,
        )

        self.assertEqual(303, response.status_code)
        self.assertRegex(response.headers["location"], r"^/tools/\d+$")
        db = database.connection()
        tool = db.execute("SELECT * FROM tools").fetchone()
        version = db.execute("SELECT * FROM tool_versions").fetchone()
        db.close()
        self.assertEqual("维护工具", tool["name"])
        self.assertEqual("", version["release_notes"])
        self.assertTrue(Path(version["file_path"]).is_file())

    def test_only_admin_can_delete_tool_and_attachments(self):
        package = UploadFile(file=io.BytesIO(b"delete me"), filename="remove-me.zip")
        logo = UploadFile(file=io.BytesIO(b"logo"), filename="remove-me.png")
        response = main.create_tool(
            make_request(self.user_id), name="待删除工具", short_description="测试", details="说明",
            version="1.0.0", release_notes="", package=package, logo=logo,
        )
        tool_id = int(response.headers["location"].rsplit("/", 1)[-1])
        db = database.connection()
        tool = db.execute("SELECT * FROM tools WHERE id=?", (tool_id,)).fetchone()
        version = db.execute("SELECT * FROM tool_versions WHERE tool_id=?", (tool_id,)).fetchone()
        db.execute("INSERT INTO feedback (tool_id,body,created_by) VALUES (?,?,?)", (tool_id, "反馈", self.user_id))
        db.execute("INSERT INTO downloads (tool_version_id,user_id) VALUES (?,?)", (version["id"], self.user_id))
        db.commit(); db.close()
        package_path, logo_path = Path(version["file_path"]), Path(tool["logo_path"])

        with self.assertRaises(HTTPException) as context:
            main.delete_tool(make_request(self.user_id), tool_id)
        self.assertEqual(403, context.exception.status_code)

        response = main.delete_tool(make_request(self.admin_id), tool_id)
        self.assertEqual(303, response.status_code)
        self.assertEqual("/tools", response.headers["location"])
        db = database.connection()
        self.assertIsNone(db.execute("SELECT id FROM tools WHERE id=?", (tool_id,)).fetchone())
        self.assertIsNone(db.execute("SELECT id FROM tool_versions WHERE tool_id=?", (tool_id,)).fetchone())
        self.assertIsNone(db.execute("SELECT id FROM feedback WHERE tool_id=?", (tool_id,)).fetchone())
        self.assertIsNone(db.execute("SELECT id FROM downloads WHERE tool_version_id=?", (version["id"],)).fetchone())
        db.close()
        self.assertFalse(package_path.exists())
        self.assertFalse(logo_path.exists())


if __name__ == "__main__":
    unittest.main()
