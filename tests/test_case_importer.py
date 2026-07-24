import tempfile
import unittest
import zipfile
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from fastapi import UploadFile
from starlette.requests import Request

from app import database, main
from app.case_importer import extract_case_document, suggested_summary, suggested_title


WORD_DOCUMENT = """<?xml version="1.0" encoding="UTF-8"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
  <w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>风扇低转速故障排查</w:t></w:r></w:p>
  <w:p><w:r><w:t>现象：风扇 3 转速异常。</w:t></w:r></w:p>
  <w:tbl><w:tr><w:tc><w:p><w:r><w:t>表格中的日志证据</w:t></w:r></w:p></w:tc></w:tr></w:tbl>
  <w:p><w:pPr><w:numPr/></w:pPr><w:r><w:t>更换风扇模块</w:t></w:r></w:p>
</w:body></w:document>"""

SLIDE_ONE = """<?xml version="1.0" encoding="UTF-8"?>
<p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main" xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
  <p:cSld><p:spTree><p:sp><p:txBody><a:p><a:r><a:t>电源告警案例</a:t></a:r></a:p><a:p><a:r><a:t>检查 PSU 状态与 SEL</a:t></a:r></a:p></p:txBody></p:sp></p:spTree></p:cSld>
</p:sld>"""


class CaseImporterTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_docx_extracts_headings_paragraphs_lists_and_table_text(self):
        source = self.root / "fan-case.docx"
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("word/document.xml", WORD_DOCUMENT)

        body, source_format, note = extract_case_document(source, source.name)

        self.assertEqual("docx", source_format)
        self.assertIn("Word", note)
        self.assertIn("# 风扇低转速故障排查", body)
        self.assertIn("表格中的日志证据", body)
        self.assertIn("- 更换风扇模块", body)
        self.assertEqual("风扇低转速故障排查", suggested_title(source.name, body))

    def test_pptx_extracts_text_by_slide(self):
        source = self.root / "power-case.pptx"
        with zipfile.ZipFile(source, "w") as archive:
            archive.writestr("ppt/slides/slide1.xml", SLIDE_ONE)

        body, source_format, note = extract_case_document(source, source.name)

        self.assertEqual("pptx", source_format)
        self.assertIn("PowerPoint", note)
        self.assertIn("## 幻灯片 1", body)
        self.assertIn("电源告警案例", body)
        self.assertIn("检查 PSU 状态与 SEL", body)
        self.assertIn("电源告警案例", suggested_summary(body))

    def test_case_import_draft_is_scoped_to_its_creator(self):
        previous_db_path = database.DB_PATH
        database.DB_PATH = self.root / "bmc_hub.db"
        try:
            database.init_db()
            db = database.connection()
            owner_id = db.execute("INSERT INTO users (username,password_hash) VALUES (?,?)", ("owner", "not-used")).lastrowid
            other_id = db.execute("INSERT INTO users (username,password_hash) VALUES (?,?)", ("other", "not-used")).lastrowid
            import_id = db.execute(
                """INSERT INTO case_imports (original_name,storage_path,source_format,extracted_characters,imported_by)
                VALUES (?,?,?,?,?)""",
                ("case.docx", "/tmp/case.docx", "docx", 20, owner_id),
            ).lastrowid
            db.commit()

            self.assertEqual(import_id, main.draft_case_import(db, import_id, owner_id)["id"])
            self.assertIsNone(main.draft_case_import(db, import_id, other_id))
            db.close()
        finally:
            database.DB_PATH = previous_db_path

    def test_case_import_template_renders_supported_formats_and_warning(self):
        rendered = main.templates.get_template("knowledge_case_import.html").render(
            request=SimpleNamespace(url=SimpleNamespace(path="/cases/import")),
            user=SimpleNamespace(username="tester"),
            error=None,
            notice=None,
            help_title="导入案例帮助",
            help_text="测试帮助",
            supported_formats="DOCX、PPTX、Markdown、TXT、DOC、PPT",
        )

        self.assertIn('name="document"', rendered)
        self.assertIn("DOCX · PPTX · Markdown · TXT", rendered)
        self.assertIn("导入并生成草稿", rendered)

    def test_import_creates_recoverable_draft_then_attaches_it_on_publish(self):
        previous_db_path, previous_upload_dir = database.DB_PATH, main.UPLOAD_DIR
        database.DB_PATH = self.root / "bmc_hub.db"
        main.UPLOAD_DIR = self.root / "uploads"
        (main.UPLOAD_DIR / "case-imports").mkdir(parents=True)
        try:
            database.init_db()
            db = database.connection()
            user_id = db.execute("INSERT INTO users (username,password_hash) VALUES (?,?)", ("importer", "not-used")).lastrowid
            db.commit(); db.close()
            request = Request({"type": "http", "method": "POST", "path": "/cases/import", "headers": [], "query_string": b"", "session": {"user_id": user_id}})
            document_bytes = BytesIO()
            with zipfile.ZipFile(document_bytes, "w") as archive:
                archive.writestr("word/document.xml", WORD_DOCUMENT)
            document_bytes.seek(0)

            response = main.import_knowledge_case_source(request, UploadFile(filename="fan-case.docx", file=document_bytes))
            self.assertIn("已导入待发布草稿", response.body.decode("utf-8"))
            db = database.connection()
            draft = db.execute("SELECT * FROM case_imports").fetchone()
            self.assertIn("风扇低转速故障排查", draft["extracted_body"])
            db.close()

            publish = main.create_knowledge_case(
                request,
                title="风扇低转速故障排查",
                summary="导入草稿",
                body=draft["extracted_body"],
                import_id=draft["id"],
                bundles=[],
            )
            self.assertEqual("/cases/1", publish.headers["location"])
            db = database.connection()
            attached = db.execute("SELECT knowledge_case_id,extracted_body FROM case_imports WHERE id=?", (draft["id"],)).fetchone()
            self.assertEqual(1, attached["knowledge_case_id"])
            self.assertEqual("", attached["extracted_body"])
            db.close()
        finally:
            database.DB_PATH, main.UPLOAD_DIR = previous_db_path, previous_upload_dir


if __name__ == "__main__":
    unittest.main()
