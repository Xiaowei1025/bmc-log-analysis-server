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
        self.assertIn('data-draft-save', source)
        self.assertIn('data-draft-cancel', source)
        self.assertIn('保存草稿', source)
        self.assertIn('取消发布', source)
        self.assertIn('richToMarkdown', source)
        self.assertIn('String.fromCharCode(10)', source)
        self.assertIn('name="import_id"', source)
        self.assertIn('data-editor-command="bold"', source)
        for marker in ('data-editor-command="image"', 'data-editor-command="table"', 'data-editor-command="link"', 'data-editor-command="hr"', 'case-image-input', 'data-editor-image-size', 'BmcEditorMedia', 'handlePaste', 'insertRichTable'):
            self.assertIn(marker, source)
        self.assertIn("event.metaKey || event.ctrlKey", source)
        self.assertIn("applyMarkdownCommand('bold')", source)
        self.assertIn('restoreRichSelection', source)
        self.assertIn('cacheRichSelection', source)
        self.assertIn('toolbar.hidden = false', source)
        self.assertIn("editorBlock.dataset.editorMode = mode", source)
        self.assertIn("markdown.addEventListener('input', refreshPreview)", source)
        self.assertIn("previewStatus.textContent = '实时同步 · 安全渲染'", source)
        self.assertIn("previewButton.hidden = true", source)
        self.assertIn("Markdown 专业使用指南", source)
        self.assertIn("CommonMark 0.31.2", source)
        self.assertIn("GitHub Flavored Markdown", source)
        self.assertIn("data-markdown-source", source)
        self.assertIn("data-markdown-result", source)
        self.assertIn("window.BmcMarkdown.renderTo(result", source)
        self.assertIn("完整服务器维护案例模板", source)
        self.assertIn("本工具兼容边界", source)

    def test_publish_case_template_renders_with_editor_assets(self):
        rendered = main.templates.get_template("knowledge_case_form.html").render(
            request=SimpleNamespace(url=SimpleNamespace(path="/cases/new"), session={}),
            user=SimpleNamespace(username="tester"),
            error=None,
            notice=None,
            help_title="发布案例帮助",
            help_text="测试帮助",
        )

        self.assertIn('/static/case-editor.css?v=0.8.6', rendered)
        self.assertIn('/static/editor-media.js?v=0.2.0', rendered)
        self.assertIn('/static/case-live-preview.css?v=0.8.3', rendered)
        self.assertIn('/static/case-import.css', rendered)
        self.assertIn('Markdown 专业使用指南', rendered)
        self.assertIn('富文本', rendered)

    def test_markdown_live_preview_uses_two_column_responsive_layout(self):
        root = Path(__file__).resolve().parents[1]
        css = (root / "app/static/case-live-preview.css").read_text(encoding="utf-8")

        self.assertIn('.case-editor-block[data-editor-mode="markdown"]', css)
        self.assertIn("grid-template-columns:minmax(0,1fr) minmax(0,1fr)", css)
        self.assertIn(".case-preview", css)
        self.assertIn("position:sticky", css)
        self.assertIn("@media(max-width:860px)", css)
        self.assertIn("grid-template-columns:minmax(0,1.08fr) minmax(230px,.92fr)", css)
        self.assertNotIn("grid-template-columns:minmax(0,1fr);", css)

    def test_markdown_guide_shows_source_and_rendered_examples_responsively(self):
        root = Path(__file__).resolve().parents[1]
        css = (root / "app/static/case-editor.css").read_text(encoding="utf-8")
        template = (root / "app/templates/knowledge_case_form.html").read_text(encoding="utf-8")

        self.assertGreaterEqual(template.count("data-markdown-source"), 8)
        self.assertGreaterEqual(template.count("data-markdown-result"), 8)
        self.assertIn("| 节点 | 告警 | 当前状态 | 责任人 |", template)
        self.assertIn("**确认根因：**", template)
        self.assertIn(".markdown-guide-dialog", css)
        self.assertIn("width:min(1040px,calc(100vw - 32px))", css)
        self.assertIn(".syntax-compare", css)
        self.assertIn("grid-template-columns:minmax(0,.95fr) minmax(0,1.05fr)", css)
        self.assertIn("@media(max-width:760px)", css)

    def test_rich_editor_tables_keep_visible_borders(self):
        css = (Path(__file__).resolve().parents[1] / "app/static/case-editor.css").read_text(encoding="utf-8")
        self.assertIn(".case-rich-editor th,.case-rich-editor td", css)
        self.assertIn("border:1px solid rgba(58,88,130,.38)", css)
        self.assertIn(".case-rich-editor tbody tr:nth-child(even)", css)
        self.assertIn(".editor-image-resize-handle", css)


if __name__ == "__main__":
    unittest.main()
