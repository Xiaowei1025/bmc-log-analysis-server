import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import database, main
from app.bmc_skill_adapter import run_bmc_skill


def demo_adapter(*, files: dict[str, str], archive_path: Path) -> dict:
    return {
        "skill_name": "test-company-skill",
        "skill_version": "2026.07-test",
        "findings": [
            {
                "rule_id": "fan.failure",
                "title": "风扇故障",
                "severity": "high",
                "summary": "测试用确定性结论",
                "diagnosis": "风扇告警已出现",
                "solution": "更换风扇",
                "evidence": [{"file": "source.log", "line": 1, "excerpt": files["source.log"]}],
                "metadata": {"adapter": "test"},
            }
        ],
    }


class BmcSkillAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_db_path = database.DB_PATH
        database.DB_PATH = Path(self.temp_dir.name) / "bmc_hub.db"
        database.init_db()
        self.db = database.connection()
        self.user_id = self.db.execute(
            "INSERT INTO users (username,password_hash) VALUES (?,?)", ("skill-tester", "not-used-in-test")
        ).lastrowid

    def tearDown(self):
        self.db.close()
        database.DB_PATH = self.previous_db_path
        self.temp_dir.cleanup()

    def test_adapter_normalizes_and_persists_findings_with_analysis(self):
        source = Path(self.temp_dir.name) / "source.log"
        source.write_text("Fan 3 failed\n", encoding="utf-8")
        with patch.dict(os.environ, {"BMC_SKILL_ADAPTER": "tests.test_bmc_skill_adapter:demo_adapter"}):
            report = main.create_analysis(self.db, self.user_id, source, source.name)
        self.db.commit()

        finding = self.db.execute("SELECT * FROM analysis_skill_findings WHERE analysis_id=?", (report["id"],)).fetchone()
        _, _, _, findings = main.report_context(self.db, report["id"])

        self.assertEqual("test-company-skill", finding["skill_name"])
        self.assertEqual("fan.failure", finding["rule_id"])
        self.assertEqual("high", finding["severity"])
        self.assertEqual("source.log", findings[0]["evidence_items"][0]["file"])

    def test_misconfigured_adapter_does_not_block_analysis(self):
        with patch.dict(os.environ, {"BMC_SKILL_ADAPTER": "invalid-adapter"}):
            result = run_bmc_skill({"source.log": "Fan 3 failed"}, Path("source.log"))
        self.assertEqual([], result["findings"])
        self.assertIn("格式无效", result["warning"])

    def test_html_report_template_renders_skill_and_feature_sections(self):
        rendered = main.templates.get_template("report_export.html").render(
            report={"id": 1, "original_name": "source.log", "created_at": "2026-07-23", "username": "tester", "status": "completed", "file_count": 1, "match_count": 1},
            summary={"skill_name": "test", "skill_version": "v1"},
            features=[],
            skill_findings=[],
            severity_label=main.severity_label,
        )
        self.assertIn("BMC 日志问题分析报告", rendered)
        self.assertIn("公司 BMC Skill 结构化结论", rendered)
        self.assertIn("问题特征库比对", rendered)


if __name__ == "__main__":
    unittest.main()
