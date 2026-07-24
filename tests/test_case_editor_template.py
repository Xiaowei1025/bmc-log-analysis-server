import unittest
from pathlib import Path
from types import SimpleNamespace

from app import main


class CaseEditorTemplateTests(unittest.TestCase):
    def test_publish_case_template_supports_rich_text_and_markdown(self):
        template = main.templates.get_template("knowledge_case_form.html")
        source = Path(template.filename).read_text(encoding="utf-8")

        self.assertIn('data-editor-mode="rich"', source)
        self.assertIn('data-editor-mode="markdown"', source)
        self.assertIn('id="case-rich-editor"', source)
        self.assertIn('id="case-markdown-input"', source)
        self.assertIn('id="markdown-syntax-dialog"', source)
        self.assertIn('id="case-preview-button"', source)
        self.assertIn('richToMarkdown', source)
        self.assertIn('String.fromCharCode(10)', source)
        self.assertIn('name="import_id"', source)
        self.assertIn('data-editor-command="bold"', source)
        self.assertIn("event.metaKey || event.ctrlKey", source)
        self.assertIn("applyMarkdownCommand('bold')", source)
        self.assertIn('restoreRichSelection', source)
        self.assertIn('cacheRichSelection', source)
        self.assertIn('toolbar.hidden = false', source)

    def test_publish_case_template_renders_with_editor_assets(self):
        rendered = main.templates.get_template("knowledge_case_form.html").render(
            request=SimpleNamespace(url=SimpleNamespace(path="/cases/new")),
            user=SimpleNamespace(username="tester"),
            error=None,
            notice=None,
            help_title="发布案例帮助",
            help_text="测试帮助",
        )

        self.assertIn('/static/case-editor.css', rendered)
        self.assertIn('/static/case-import.css', rendered)
        self.assertIn('Markdown 快速说明', rendered)
        self.assertIn('富文本', rendered)


if __name__ == "__main__":
    unittest.main()
