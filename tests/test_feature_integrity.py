import sqlite3
import tempfile
import unittest
from pathlib import Path

from app import database, main


class FeatureIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_db_path = database.DB_PATH
        database.DB_PATH = Path(self.temp_dir.name) / "bmc_hub.db"
        database.init_db()
        self.db = database.connection()
        self.user_id = self.db.execute(
            "INSERT INTO users (username,password_hash) VALUES (?,?)", ("tester", "not-used-in-test")
        ).lastrowid

    def tearDown(self):
        self.db.close()
        database.DB_PATH = self.previous_db_path
        self.temp_dir.cleanup()

    def create_feature(self, expression: str):
        feature_id, _ = main.save_feature(
            self.db,
            None,
            "风扇异常",
            "风扇告警",
            "风扇需要检查",
            "检查风扇模块",
            "fan",
            "散热",
            "high",
            "all",
            [("*", expression, False)],
            self.user_id,
            [],
        )
        self.db.commit()
        return feature_id

    def create_report(self, content: str = "Fan 3 failed\n"):
        path = Path(self.temp_dir.name) / "source.log"
        path.write_text(content, encoding="utf-8")
        report = main.create_analysis(self.db, self.user_id, path, path.name)
        self.db.commit()
        return report["id"], path

    def test_deleting_feature_cascades_current_and_historical_matches(self):
        feature_id = self.create_feature("Fan 3 failed")
        report_id, _ = self.create_report()
        self.assertEqual(1, self.db.execute("SELECT COUNT(*) FROM analysis_matches WHERE analysis_id=?", (report_id,)).fetchone()[0])

        self.db.execute("DELETE FROM cases WHERE id=?", (feature_id,))
        self.db.commit()

        self.assertEqual(0, self.db.execute("SELECT COUNT(*) FROM analysis_matches WHERE analysis_id=?", (report_id,)).fetchone()[0])
        self.assertEqual(0, self.db.execute("SELECT COUNT(*) FROM feature_log_links WHERE analysis_id=?", (report_id,)).fetchone()[0])
        self.assertEqual(0, self.db.execute("SELECT COUNT(*) FROM feature_versions WHERE case_id=?", (feature_id,)).fetchone()[0])

    def test_existing_match_table_is_upgraded_without_losing_evidence(self):
        feature_id = self.create_feature("Fan 3 failed")
        report_id, _ = self.create_report()
        self.db.commit()
        self.db.close()

        legacy = sqlite3.connect(database.DB_PATH)
        legacy.execute("ALTER TABLE analysis_matches RENAME TO analysis_matches_current")
        legacy.execute(
            """CREATE TABLE analysis_matches (
            id INTEGER PRIMARY KEY, analysis_id INTEGER NOT NULL, case_id INTEGER NOT NULL,
            evidence TEXT NOT NULL, FOREIGN KEY(analysis_id) REFERENCES analyses(id) ON DELETE CASCADE,
            FOREIGN KEY(case_id) REFERENCES cases(id))"""
        )
        legacy.execute(
            """INSERT INTO analysis_matches (id,analysis_id,case_id,evidence)
            SELECT id,analysis_id,case_id,evidence FROM analysis_matches_current"""
        )
        legacy.execute("DROP TABLE analysis_matches_current")
        legacy.commit()
        legacy.close()

        database.init_db()
        self.db = database.connection()
        match = self.db.execute("SELECT feature_version,evidence FROM analysis_matches WHERE analysis_id=?", (report_id,)).fetchone()
        foreign_keys = self.db.execute("PRAGMA foreign_key_list(analysis_matches)").fetchall()

        self.assertEqual(1, match["feature_version"])
        self.assertIn("Fan 3 failed", match["evidence"])
        self.assertTrue(any(row["from"] == "case_id" and row["on_delete"] == "CASCADE" for row in foreign_keys))
        self.db.execute("DELETE FROM cases WHERE id=?", (feature_id,))
        self.db.commit()
        self.assertEqual(0, self.db.execute("SELECT COUNT(*) FROM analysis_matches WHERE analysis_id=?", (report_id,)).fetchone()[0])

    def test_rule_edit_preserves_history_and_recalculates_active_results(self):
        feature_id = self.create_feature("Fan 3 failed")
        report_id, _ = self.create_report()
        first_match = self.db.execute(
            "SELECT feature_version,evidence FROM analysis_matches WHERE analysis_id=?", (report_id,)
        ).fetchone()
        self.assertEqual(1, first_match["feature_version"])
        self.assertIn("Fan 3 failed", first_match["evidence"])

        main.save_feature(
            self.db,
            feature_id,
            "风扇异常",
            "风扇告警",
            "风扇需要检查",
            "检查风扇模块",
            "fan",
            "散热",
            "high",
            "all",
            [("*", "Power failed", False)],
            self.user_id,
            [],
        )
        refresh = main.refresh_feature_matches(self.db, feature_id, self.user_id)
        self.db.commit()

        self.assertEqual({"rechecked": 1, "matched": 0, "failed": []}, refresh)
        self.assertEqual(2, self.db.execute("SELECT rule_version FROM cases WHERE id=?", (feature_id,)).fetchone()[0])
        self.assertEqual(1, self.db.execute("SELECT COUNT(*) FROM analysis_matches WHERE analysis_id=?", (report_id,)).fetchone()[0])
        self.assertEqual(0, self.db.execute("SELECT match_count FROM analyses WHERE id=?", (report_id,)).fetchone()[0])
        self.assertEqual(0, self.db.execute("SELECT COUNT(*) FROM feature_log_links WHERE analysis_id=?", (report_id,)).fetchone()[0])

        main.save_feature(
            self.db,
            feature_id,
            "风扇异常",
            "风扇告警",
            "风扇需要检查",
            "检查风扇模块",
            "fan",
            "散热",
            "high",
            "all",
            [("*", "Fan 3 failed", False)],
            self.user_id,
            [],
        )
        main.refresh_feature_matches(self.db, feature_id, self.user_id)
        self.db.commit()

        self.assertEqual(3, self.db.execute("SELECT rule_version FROM cases WHERE id=?", (feature_id,)).fetchone()[0])
        self.assertEqual(2, self.db.execute("SELECT COUNT(*) FROM analysis_matches WHERE analysis_id=?", (report_id,)).fetchone()[0])
        self.assertEqual(1, self.db.execute("SELECT match_count FROM analyses WHERE id=?", (report_id,)).fetchone()[0])
        self.assertEqual(1, self.db.execute("SELECT COUNT(*) FROM feature_log_links WHERE analysis_id=?", (report_id,)).fetchone()[0])

    def test_source_review_reextracts_each_condition_from_actual_log(self):
        feature_id = self.create_feature("Fan 3 failed")
        report_id, _ = self.create_report("prefix\nFan 3 failed\nsuffix\n")
        self.db.execute(
            "INSERT INTO feature_log_reviews (case_id,analysis_id,status,requested_by) VALUES (?,?,?,?)",
            (feature_id, report_id, "pending", self.user_id),
        )
        self.db.commit()

        feature, conditions, reviews = main.feature_review_context(self.db, feature_id)
        evidence = reviews[0]["source_evidence"]

        self.assertEqual(feature_id, feature["id"])
        self.assertEqual(1, len(conditions))
        self.assertTrue(evidence["matches_current_rule"])
        self.assertEqual("source.log", evidence["conditions"][0]["found"]["file"])
        self.assertEqual(2, evidence["conditions"][0]["found"]["line"])
        self.assertIn("Fan 3 failed", evidence["conditions"][0]["found"]["excerpt"])


if __name__ == "__main__":
    unittest.main()
