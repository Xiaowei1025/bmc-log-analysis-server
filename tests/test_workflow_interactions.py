import tempfile
import unittest
from pathlib import Path

from starlette.requests import Request

from app import database, main


def make_request(user_id):
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": "/",
            "raw_path": b"/",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 12345),
            "server": ("testserver", 80),
            "root_path": "",
            "session": {"user_id": user_id, "csrf_token": "test-csrf"},
        }
    )


class WorkflowInteractionTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_db_path = database.DB_PATH
        database.DB_PATH = Path(self.temp_dir.name) / "workflow.db"
        database.init_db()
        db = database.connection()
        self.user_id = db.execute(
            "INSERT INTO users (username,password_hash,role) VALUES (?,?,?)",
            ("workflow-owner", "not-used", "contributor"),
        ).lastrowid
        self.report_id = db.execute(
            """INSERT INTO analyses
               (original_name,storage_path,summary,status,file_count,match_count,created_by)
               VALUES (?,?,?,?,?,?,?)""",
            ("fan-alert.log", str(Path(self.temp_dir.name) / "fan-alert.log"), "{}", "completed", 2, 1, self.user_id),
        ).lastrowid
        db.execute(
            """INSERT INTO analyses
               (original_name,storage_path,summary,status,file_count,match_count,created_by)
               VALUES (?,?,?,?,?,?,?)""",
            ("normal.log", str(Path(self.temp_dir.name) / "normal.log"), "{}", "completed", 1, 0, self.user_id),
        )
        db.commit()
        db.close()

    def tearDown(self):
        database.DB_PATH = self.previous_db_path
        self.temp_dir.cleanup()

    def test_report_filter_and_pagination_context(self):
        response = main.reports(
            make_request(self.user_id),
            q="fan",
            status="completed",
            hit="matched",
            page_no=1,
        )
        self.assertEqual(1, response.context["total_count"])
        self.assertEqual("fan-alert.log", response.context["reports"][0]["original_name"])
        self.assertEqual("matched", response.context["hit"])
        self.assertIsNone(response.context["previous_url"])

    def test_report_can_seed_feature_and_case_without_copying_log(self):
        feature_response = main.create_feature(
            make_request(self.user_id),
            title="风扇告警",
            description="风扇异常",
            diagnosis="需要检查风扇",
            solution="检查连接器",
            keywords="fan",
            tags="散热",
            severity="high",
            match_mode="all",
            file_patterns=["*"],
            expressions=["Fan"],
            regex_flags=[],
            knowledge_case_ids=[],
            report_id=self.report_id,
            source_bundles=[],
        )
        self.assertEqual(303, feature_response.status_code)
        case_response = main.create_knowledge_case(
            make_request(self.user_id),
            title="风扇告警排查案例",
            summary="来自现有报告",
            body="检查风扇连接器并复测。",
            import_id=None,
            report_id=self.report_id,
            bundles=[],
        )
        self.assertEqual(303, case_response.status_code)
        db = database.connection()
        self.assertEqual(
            1,
            db.execute("SELECT COUNT(*) FROM feature_log_links WHERE analysis_id=?", (self.report_id,)).fetchone()[0],
        )
        self.assertEqual(
            1,
            db.execute("SELECT COUNT(*) FROM case_log_links WHERE analysis_id=?", (self.report_id,)).fetchone()[0],
        )
        db.close()

    def test_templates_expose_natural_workflow_controls(self):
        base = (self.root / "app/templates/base.html").read_text(encoding="utf-8")
        logs = (self.root / "app/templates/logs.html").read_text(encoding="utf-8")
        report = (self.root / "app/templates/report_detail.html").read_text(encoding="utf-8")
        interactions = (self.root / "app/static/app_interactions.js").read_text(encoding="utf-8")
        upload = (self.root / "app/static/upload_runtime.js").read_text(encoding="utf-8")
        workflow = (self.root / "app/static/workflow.css").read_text(encoding="utf-8")

        self.assertIn("confirm-dialog", base)
        self.assertIn("nav-scrim", base)
        self.assertIn("workflow.css?v=0.9.0", base)
        self.assertIn("data-upload-form", logs)
        self.assertIn("upload-file-list", logs)
        self.assertIn("upload-submit", logs)
        self.assertIn("/features/new?report_id={{ report.id }}", report)
        self.assertIn("/cases/new?report_id={{ report.id }}", report)
        self.assertIn("/ask?report_id={{ report.id }}", report)
        self.assertIn("form[method=\"post\"]:not([data-no-pending])", interactions)
        self.assertIn("bmc-form-draft:", interactions)
        self.assertIn("requestSubmit", interactions)
        self.assertIn("DataTransfer", upload)
        self.assertIn(".report-filter", workflow)
        self.assertIn(".empty-state", workflow)


if __name__ == "__main__":
    unittest.main()
