import unittest
from pathlib import Path
from types import SimpleNamespace

from app import main


class ToolDetailUiTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(__file__).resolve().parents[1]

    def test_tool_detail_keeps_history_actions_and_renders_overview(self):
        rendered = main.templates.get_template("tool_detail.html").render(
            request=SimpleNamespace(url=SimpleNamespace(path="/tools/2"), session={}),
            user=SimpleNamespace(id=7, username="maintainer", role="contributor"),
            tool=SimpleNamespace(
                id=2,
                name="服务器知识",
                short_description="内部维护工具",
                details="直接双击使用。",
                username="maintainer",
                created_by=7,
                created_at="2026-07-23 13:04:10",
                logo_path="",
            ),
            versions=[
                SimpleNamespace(id=11, version="1.2.0", release_notes="增强兼容性", created_at="2026-07-30", username="maintainer", downloads=5),
                SimpleNamespace(id=10, version="1.0.0", release_notes="", created_at="2026-07-23", username="maintainer", downloads=2),
            ],
            feedback=[],
            error=None,
            notice=None,
            help_title="工具详情帮助",
            help_text="测试",
            role_label=main.role_label,
            csrf_token="test-token",
            registration_enabled=False,
        )

        self.assertIn("最新版本", rendered)
        self.assertIn("v1.2.0", rendered)
        self.assertIn("累计下载", rendered)
        self.assertIn(">7<", rendered)
        self.assertIn('href="/download/11"', rendered)
        self.assertIn("下载此版本", rendered)
        self.assertIn('action="/tools/2/versions"', rendered)
        self.assertIn('action="/tools/2/feedback"', rendered)
        self.assertIn("修改介绍", rendered)
        self.assertNotIn('<main class="tool-detail-main">', rendered)

    def test_tool_detail_uses_layered_glass_and_strong_button_feedback(self):
        css = (self.root / "app/static/tool-detail.css").read_text(encoding="utf-8")
        base = (self.root / "app/templates/base.html").read_text(encoding="utf-8")

        self.assertIn("/static/tool-detail.css?v=0.8.5", base)
        self.assertIn(".tool-detail-hero", css)
        self.assertIn("backdrop-filter:blur(34px) saturate(165%)", css)
        self.assertIn(".tool-surface", css)
        self.assertIn("0 24px 62px rgba(39,67,108,.16)", css)
        self.assertIn(".tool-download-button", css)
        self.assertIn("0 13px 28px rgba(42,101,205,.34)", css)
        self.assertIn(".tool-download-button:hover", css)
        self.assertIn(".tool-download-button:active", css)
        self.assertIn("html[data-theme=dark] .tool-detail-hero", css)
        self.assertIn("@media(max-width:960px)", css)
        self.assertIn("@media(max-width:700px)", css)


if __name__ == "__main__":
    unittest.main()
