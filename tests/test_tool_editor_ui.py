import unittest
from pathlib import Path
from types import SimpleNamespace

from app import main


class ToolEditorUiTests(unittest.TestCase):
    def render(self, template_name, tool=None):
        request = SimpleNamespace(url=SimpleNamespace(path='/tools/new'), session={'csrf_token': 'test-token'})
        return main.templates.get_template(template_name).render(
            request=request,
            user=SimpleNamespace(id=7, username='maintainer', role='contributor'),
            tool=tool,
            error=None,
            notice=None,
            help_title='工具帮助',
            help_text='测试',
            role_label=main.role_label,
            csrf_token='test-token',
            registration_enabled=False,
        )

    def test_new_tool_uses_shared_rich_markdown_editor(self):
        rendered = self.render('tool_form.html')
        self.assertIn('data-tool-editor-form', rendered)
        self.assertIn('data-tool-editor-mode="rich"', rendered)
        self.assertIn('data-tool-editor-mode="markdown"', rendered)
        self.assertIn('name="details"', rendered)
        self.assertIn('tool-preview-content', rendered)
        self.assertIn('工具说明写作提示', rendered)
        self.assertIn('/static/tool-editor.js?v=0.1.3', rendered)
        self.assertIn('data-tool-editor-command="image"', rendered)
        self.assertIn('id="tool-image-input"', rendered)
        for marker in ('data-tool-editor-command="table"', 'data-tool-editor-command="link"', 'data-tool-editor-command="hr"', 'data-tool-image-size', '/static/editor-media.js?v=0.2.0'):
            self.assertIn(marker, rendered)
        self.assertIn('单张不超过 2 MB', rendered)

    def test_tool_edit_reuses_editor_and_keeps_existing_markdown(self):
        rendered = self.render('tool_edit.html', SimpleNamespace(id=2, name='采集工具', short_description='简介', details='# 使用方法\n\n**重点**'))
        self.assertIn('action="/tools/2/edit"', rendered)
        self.assertIn('# 使用方法', rendered)
        self.assertIn('**重点**', rendered)
        self.assertIn('href="/tools/2"', rendered)
        self.assertIn('取消编辑', rendered)

    def test_editor_runtime_has_live_preview_and_submit_sync(self):
        source = (Path(__file__).resolve().parents[1] / 'app/static/tool-editor.js').read_text(encoding='utf-8')
        for marker in ('BmcMarkdown.renderTo', 'data-tool-editor-mode', 'syncMarkdown', "event.ctrlKey || event.metaKey", "form.addEventListener('submit'", 'FileReader', 'data:image', 'handlePaste', 'insertRichTable', 'selectImage', 'normalizeRenderedImages'):
            self.assertIn(marker, source)

    def test_markdown_renderer_supports_safe_images(self):
        source = (Path(__file__).resolve().parents[1] / 'app/static/llm_markdown.js').read_text(encoding='utf-8')
        self.assertIn('BMC_IMAGE_', source)
        self.assertIn('loading="lazy"', source)
        self.assertIn('data-image-width', source)
        self.assertIn('{width=', source)

    def test_markdown_tables_have_high_contrast_shared_styles(self):
        css = (Path(__file__).resolve().parents[1] / 'app/static/llm-output.css').read_text(encoding='utf-8')
        self.assertIn('.markdown-output .markdown-table-wrap,.stream-output .markdown-table-wrap', css)
        self.assertIn('border:1px solid rgba(58,88,130,.42)', css)
        self.assertIn('tbody tr:nth-child(even)', css)
        self.assertIn('html[data-theme=dark] .markdown-output th', css)


if __name__ == '__main__':
    unittest.main()
