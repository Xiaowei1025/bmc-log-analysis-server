import json
import os
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)
DB_PATH = Path(os.getenv("DATABASE_PATH", DATA_DIR / "bmc_hub.db"))


def connection():
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def init_db():
    db = connection()
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS users (
          id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE,
          password_hash TEXT NOT NULL,
          role TEXT NOT NULL DEFAULT 'contributor' CHECK(role IN ('contributor','reviewer','admin')),
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS cases (
          id INTEGER PRIMARY KEY, title TEXT NOT NULL, symptom TEXT NOT NULL,
          diagnosis TEXT NOT NULL, solution TEXT NOT NULL, tags TEXT NOT NULL DEFAULT '',
          keywords TEXT NOT NULL DEFAULT '', severity TEXT NOT NULL DEFAULT 'medium',
          match_mode TEXT NOT NULL DEFAULT 'all', rule_version INTEGER NOT NULL DEFAULT 1,
          created_by INTEGER NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(created_by) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS case_conditions (
          id INTEGER PRIMARY KEY, case_id INTEGER NOT NULL, file_pattern TEXT NOT NULL,
          expression TEXT NOT NULL, is_regex INTEGER NOT NULL DEFAULT 0,
          FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS analyses (
          id INTEGER PRIMARY KEY, original_name TEXT NOT NULL, storage_path TEXT NOT NULL,
          summary TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'completed',
          file_count INTEGER NOT NULL DEFAULT 0, match_count INTEGER NOT NULL DEFAULT 0,
          llm_summary TEXT, created_by INTEGER NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(created_by) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS analysis_matches (
          id INTEGER PRIMARY KEY, analysis_id INTEGER NOT NULL, case_id INTEGER NOT NULL,
          feature_version INTEGER NOT NULL DEFAULT 1, evidence TEXT NOT NULL,
          UNIQUE(analysis_id, case_id, feature_version),
          FOREIGN KEY(analysis_id) REFERENCES analyses(id) ON DELETE CASCADE,
          FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS analysis_skill_findings (
          id INTEGER PRIMARY KEY, analysis_id INTEGER NOT NULL,
          skill_name TEXT NOT NULL, skill_version TEXT NOT NULL DEFAULT '', rule_id TEXT NOT NULL,
          title TEXT NOT NULL, severity TEXT NOT NULL DEFAULT 'medium', summary TEXT NOT NULL DEFAULT '',
          diagnosis TEXT NOT NULL DEFAULT '', solution TEXT NOT NULL DEFAULT '',
          evidence TEXT NOT NULL DEFAULT '[]', metadata TEXT NOT NULL DEFAULT '{}',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(analysis_id, skill_name, rule_id),
          FOREIGN KEY(analysis_id) REFERENCES analyses(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS feature_versions (
          id INTEGER PRIMARY KEY, case_id INTEGER NOT NULL, version INTEGER NOT NULL,
          title TEXT NOT NULL, symptom TEXT NOT NULL, diagnosis TEXT NOT NULL,
          solution TEXT NOT NULL, keywords TEXT NOT NULL DEFAULT '', tags TEXT NOT NULL DEFAULT '',
          severity TEXT NOT NULL, match_mode TEXT NOT NULL, conditions TEXT NOT NULL,
          created_by INTEGER NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(case_id, version),
          FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE,
          FOREIGN KEY(created_by) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS feature_log_links (
          id INTEGER PRIMARY KEY, case_id INTEGER NOT NULL, analysis_id INTEGER NOT NULL,
          relation_type TEXT NOT NULL DEFAULT 'manual', linked_by INTEGER NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(case_id, analysis_id),
          FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE,
          FOREIGN KEY(analysis_id) REFERENCES analyses(id) ON DELETE CASCADE,
          FOREIGN KEY(linked_by) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS knowledge_cases (
          id INTEGER PRIMARY KEY, title TEXT NOT NULL, summary TEXT NOT NULL DEFAULT '',
          body TEXT NOT NULL DEFAULT '', created_by INTEGER NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(created_by) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS case_log_links (
          id INTEGER PRIMARY KEY, knowledge_case_id INTEGER NOT NULL, analysis_id INTEGER NOT NULL,
          linked_by INTEGER NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(knowledge_case_id, analysis_id),
          FOREIGN KEY(knowledge_case_id) REFERENCES knowledge_cases(id) ON DELETE CASCADE,
          FOREIGN KEY(analysis_id) REFERENCES analyses(id) ON DELETE CASCADE,
          FOREIGN KEY(linked_by) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS case_imports (
          id INTEGER PRIMARY KEY, knowledge_case_id INTEGER,
          original_name TEXT NOT NULL, storage_path TEXT NOT NULL,
          source_format TEXT NOT NULL, extracted_characters INTEGER NOT NULL DEFAULT 0,
          extraction_note TEXT NOT NULL DEFAULT '', extracted_body TEXT NOT NULL DEFAULT '', imported_by INTEGER NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(knowledge_case_id) REFERENCES knowledge_cases(id) ON DELETE CASCADE,
          FOREIGN KEY(imported_by) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS feature_case_links (
          id INTEGER PRIMARY KEY, case_id INTEGER NOT NULL, knowledge_case_id INTEGER NOT NULL,
          linked_by INTEGER NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(case_id, knowledge_case_id),
          FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE,
          FOREIGN KEY(knowledge_case_id) REFERENCES knowledge_cases(id) ON DELETE CASCADE,
          FOREIGN KEY(linked_by) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS feature_log_reviews (
          id INTEGER PRIMARY KEY, case_id INTEGER NOT NULL, analysis_id INTEGER NOT NULL,
          status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','confirmed','rejected')),
          requested_by INTEGER NOT NULL, reviewed_by INTEGER, note TEXT NOT NULL DEFAULT '',
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(case_id, analysis_id),
          FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE,
          FOREIGN KEY(analysis_id) REFERENCES analyses(id) ON DELETE CASCADE,
          FOREIGN KEY(requested_by) REFERENCES users(id),
          FOREIGN KEY(reviewed_by) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS requirement_requests (
          id INTEGER PRIMARY KEY, title TEXT NOT NULL, category TEXT NOT NULL DEFAULT 'feature',
          description TEXT NOT NULL, expected_value TEXT NOT NULL DEFAULT '',
          status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','accepted','planned','implemented','declined')),
          created_by INTEGER NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(created_by) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS requirement_review_events (
          id INTEGER PRIMARY KEY, requirement_id INTEGER NOT NULL, status TEXT NOT NULL,
          note TEXT NOT NULL DEFAULT '', reviewed_by INTEGER NOT NULL,
          reviewed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(requirement_id) REFERENCES requirement_requests(id) ON DELETE CASCADE,
          FOREIGN KEY(reviewed_by) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS chat_messages (
          id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL,
          role TEXT NOT NULL CHECK(role IN ('user','assistant')),
          content TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS tools (
          id INTEGER PRIMARY KEY, name TEXT NOT NULL, short_description TEXT NOT NULL,
          details TEXT NOT NULL, logo_path TEXT, created_by INTEGER NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(created_by) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS tool_versions (
          id INTEGER PRIMARY KEY, tool_id INTEGER NOT NULL, version TEXT NOT NULL,
          release_notes TEXT NOT NULL, file_path TEXT NOT NULL, file_name TEXT NOT NULL,
          downloads INTEGER NOT NULL DEFAULT 0, uploaded_by INTEGER NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(tool_id, version), FOREIGN KEY(tool_id) REFERENCES tools(id),
          FOREIGN KEY(uploaded_by) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS downloads (
          id INTEGER PRIMARY KEY, tool_version_id INTEGER NOT NULL, user_id INTEGER NOT NULL,
          downloaded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(tool_version_id) REFERENCES tool_versions(id), FOREIGN KEY(user_id) REFERENCES users(id)
        );
        CREATE TABLE IF NOT EXISTS feedback (
          id INTEGER PRIMARY KEY, tool_id INTEGER NOT NULL, body TEXT NOT NULL, created_by INTEGER NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
          FOREIGN KEY(tool_id) REFERENCES tools(id), FOREIGN KEY(created_by) REFERENCES users(id)
        );
        CREATE INDEX IF NOT EXISTS idx_knowledge_cases_creator ON knowledge_cases(created_by, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_case_log_links_case ON case_log_links(knowledge_case_id);
        CREATE INDEX IF NOT EXISTS idx_case_imports_case ON case_imports(knowledge_case_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_case_imports_draft ON case_imports(imported_by, knowledge_case_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_feature_case_links_feature ON feature_case_links(case_id);
        CREATE INDEX IF NOT EXISTS idx_feature_log_reviews_feature ON feature_log_reviews(case_id, status);
        CREATE INDEX IF NOT EXISTS idx_feature_versions_case ON feature_versions(case_id, version DESC);
        CREATE INDEX IF NOT EXISTS idx_analysis_skill_findings_analysis ON analysis_skill_findings(analysis_id, severity);
        CREATE INDEX IF NOT EXISTS idx_requirement_requests_status ON requirement_requests(status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_requirement_review_events_requirement ON requirement_review_events(requirement_id, reviewed_at DESC);
        """
    )
    # Existing local MVP databases are upgraded in place. SQLite has no
    # ADD COLUMN IF NOT EXISTS, hence the small schema check below.
    _add_column_if_missing(db, "cases", "keywords", "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(db, "users", "role", "TEXT NOT NULL DEFAULT 'contributor'")
    _add_column_if_missing(db, "cases", "severity", "TEXT NOT NULL DEFAULT 'medium'")
    _add_column_if_missing(db, "cases", "rule_version", "INTEGER NOT NULL DEFAULT 1")
    _add_column_if_missing(db, "analyses", "status", "TEXT NOT NULL DEFAULT 'completed'")
    _add_column_if_missing(db, "analyses", "file_count", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(db, "analyses", "match_count", "INTEGER NOT NULL DEFAULT 0")
    _add_column_if_missing(db, "analyses", "llm_summary", "TEXT")
    _add_column_if_missing(db, "case_imports", "extracted_body", "TEXT NOT NULL DEFAULT ''")
    _ensure_analysis_matches_schema(db)
    _backfill_feature_versions(db)
    # Operators can promote pre-existing local accounts during a controlled
    # deployment without manually editing SQLite.  New registrations never
    # receive elevated permissions.
    admin_usernames = {
        username.strip()
        for username in os.getenv("ADMIN_USERNAMES", "").split(",")
        if username.strip()
    }
    if admin_usernames:
        db.executemany(
            "UPDATE users SET role='admin' WHERE username=?",
            [(username,) for username in admin_usernames],
        )
    db.execute("CREATE INDEX IF NOT EXISTS idx_analysis_matches_active ON analysis_matches(analysis_id, case_id, feature_version)")
    db.execute(
        """INSERT OR IGNORE INTO feature_log_links (case_id,analysis_id,relation_type,linked_by)
        SELECT m.case_id,m.analysis_id,'automatic',a.created_by
        FROM analysis_matches m JOIN analyses a ON a.id=m.analysis_id"""
    )
    for report in db.execute("SELECT id,summary,file_count,match_count FROM analyses WHERE file_count=0 OR match_count=0").fetchall():
        try:
            summary = json.loads(report["summary"])
            db.execute("UPDATE analyses SET file_count=?,match_count=? WHERE id=?", (summary.get("file_count", report["file_count"]), summary.get("match_count", report["match_count"]), report["id"]))
        except (TypeError, ValueError):
            pass
    db.commit()
    db.close()


def _add_column_if_missing(db, table: str, column: str, definition: str):
    existing = {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def _ensure_analysis_matches_schema(db):
    """Upgrade the original match table without losing historical evidence.

    SQLite cannot add a foreign-key action or unique key in place.  Early local
    databases therefore need one small table rebuild so a feature can be safely
    deleted and every match carries the rule version that produced it.
    """
    columns = {row["name"] for row in db.execute("PRAGMA table_info(analysis_matches)")}
    foreign_keys = db.execute("PRAGMA foreign_key_list(analysis_matches)").fetchall()
    case_cascades = any(row["from"] == "case_id" and row["on_delete"].upper() == "CASCADE" for row in foreign_keys)
    unique_sets = {
        tuple(row[2] for row in db.execute(f"PRAGMA index_info({item['name']})").fetchall())
        for item in db.execute("PRAGMA index_list(analysis_matches)").fetchall()
        if item["unique"]
    }
    if "feature_version" in columns and case_cascades and ("analysis_id", "case_id", "feature_version") in unique_sets:
        return

    db.execute(
        """CREATE TABLE analysis_matches_upgrade (
          id INTEGER PRIMARY KEY, analysis_id INTEGER NOT NULL, case_id INTEGER NOT NULL,
          feature_version INTEGER NOT NULL DEFAULT 1, evidence TEXT NOT NULL,
          UNIQUE(analysis_id, case_id, feature_version),
          FOREIGN KEY(analysis_id) REFERENCES analyses(id) ON DELETE CASCADE,
          FOREIGN KEY(case_id) REFERENCES cases(id) ON DELETE CASCADE
        )"""
    )
    version_column = "feature_version" if "feature_version" in columns else "1"
    rows = db.execute(
        f"SELECT id,analysis_id,case_id,{version_column} AS feature_version,evidence FROM analysis_matches"
    ).fetchall()
    db.executemany(
        """INSERT OR IGNORE INTO analysis_matches_upgrade
        (id,analysis_id,case_id,feature_version,evidence) VALUES (?,?,?,?,?)""",
        [(row["id"], row["analysis_id"], row["case_id"], row["feature_version"] or 1, row["evidence"]) for row in rows],
    )
    db.execute("DROP TABLE analysis_matches")
    db.execute("ALTER TABLE analysis_matches_upgrade RENAME TO analysis_matches")


def _backfill_feature_versions(db):
    """Create an immutable baseline snapshot for features created before versioning."""
    for feature in db.execute("SELECT * FROM cases").fetchall():
        version = max(1, int(feature["rule_version"] or 1))
        conditions = [dict(row) for row in db.execute("SELECT file_pattern,expression,is_regex FROM case_conditions WHERE case_id=? ORDER BY id", (feature["id"],)).fetchall()]
        db.execute(
            """INSERT OR IGNORE INTO feature_versions
            (case_id,version,title,symptom,diagnosis,solution,keywords,tags,severity,match_mode,conditions,created_by)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                feature["id"], version, feature["title"], feature["symptom"], feature["diagnosis"],
                feature["solution"], feature["keywords"], feature["tags"], feature["severity"],
                feature["match_mode"], json.dumps(conditions, ensure_ascii=False), feature["created_by"],
            ),
        )
