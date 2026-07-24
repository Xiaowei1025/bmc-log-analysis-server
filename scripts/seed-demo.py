#!/usr/bin/env python3
"""Create clearly labelled demo content for a local walkthrough.

Run only in a disposable local environment. It creates one demo user, one fan
failure case and a small placeholder tool file; it never runs automatically.
"""
import os
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.database import connection, init_db
from app.security import hash_password

UPLOADS = ROOT / "uploads"


def main():
    init_db()
    for folder in ("tools", "logos", "logs"):
        (UPLOADS / folder).mkdir(parents=True, exist_ok=True)
    db = connection()
    try:
        user = db.execute("SELECT id FROM users WHERE username='demo-maintainer'").fetchone()
        if user:
            print("Demo data already exists; nothing changed.")
            return
        user_id = db.execute(
            "INSERT INTO users (username,password_hash) VALUES (?,?)",
            ("demo-maintainer", hash_password("demo-password-please-change")),
        ).lastrowid
        case_id = db.execute(
            """INSERT INTO cases (title,symptom,diagnosis,solution,tags,match_mode,created_by)
            VALUES (?,?,?,?,?,?,?)""",
            ("演示：风扇 3 转速异常", "BMC 报告风扇低转速或 0 RPM。", "风扇 3 故障或线缆/背板连接异常。", "断电后检查风扇模块和连接器；替换风扇后复测 SEL 与转速。", "演示,风扇,BMC,SEL", "all", user_id),
        ).lastrowid
        db.execute(
            "INSERT INTO case_conditions (case_id,file_pattern,expression,is_regex) VALUES (?,?,?,0)",
            (case_id, "*", "Fan 3 failed"),
        )
        tool_file = UPLOADS / "tools" / "demo_fan_diagnostic_1.0.0.zip"
        with zipfile.ZipFile(tool_file, "w") as archive:
            archive.writestr("README.txt", "Demo package only. Replace this with an approved internal tool.")
        tool_id = db.execute(
            "INSERT INTO tools (name,short_description,details,created_by) VALUES (?,?,?,?)",
            ("风扇状态采集脚本（演示）", "演示工具版本、下载和反馈流程。", "这是占位演示工具，不会执行任何诊断操作。正式工具应说明依赖、权限、参数和回滚方式。", user_id),
        ).lastrowid
        db.execute(
            """INSERT INTO tool_versions (tool_id,version,release_notes,file_path,file_name,uploaded_by)
            VALUES (?,?,?,?,?,?)""",
            (tool_id, "1.0.0-demo", "演示初始版本。", str(tool_file), tool_file.name, user_id),
        )
        db.commit()
        print("Demo data created. Login: demo-maintainer / demo-password-please-change")
    finally:
        db.close()


if __name__ == "__main__":
    main()
