import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException

from app import database, main
from app.oidc_auth import OAuth2Settings, normalize_identity
from tests.test_access_control import make_request


class AdminManagementTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.previous_db = database.DB_PATH
        database.DB_PATH = Path(self.temp_dir.name) / "admin.db"
        database.init_db()
        self.db = database.connection()
        self.super_id = self.db.execute(
            "INSERT INTO users(username,password_hash,role,auth_provider) VALUES(?,?,?,?)",
            ("j00983211", "x", "admin", "huawei-idaas"),
        ).lastrowid
        self.second_super_id = self.db.execute(
            "INSERT INTO users(username,password_hash,role,auth_provider) VALUES(?,?,?,?)",
            ("j00456121", "x", "contributor", "huawei-idaas"),
        ).lastrowid
        self.staff_id = self.db.execute(
            "INSERT INTO users(username,password_hash,role) VALUES(?,?,?)",
            ("colleague", "x", "contributor"),
        ).lastrowid
        self.other_admin_id = self.db.execute(
            "INSERT INTO users(username,password_hash,role) VALUES(?,?,?)",
            ("another-admin", "x", "admin"),
        ).lastrowid
        self.db.commit()

    def tearDown(self):
        self.db.close()
        database.DB_PATH = self.previous_db
        self.temp_dir.cleanup()

    def test_employee_is_highest_admin_by_default(self):
        row = self.db.execute("SELECT * FROM users WHERE id=?", (self.super_id,)).fetchone()
        self.assertTrue(main.is_super_admin_user(row))
        second = self.db.execute("SELECT * FROM users WHERE id=?", (self.second_super_id,)).fetchone()
        self.assertTrue(main.is_super_admin_user(second))
        with patch.dict(
            "os.environ",
            {"OAUTH_SUPER_ADMIN_EMPLOYEE_IDS": "", "OIDC_SUPER_ADMIN_EMPLOYEE_IDS": ""},
            clear=False,
        ):
            self.assertEqual(
                {"j00983211", "j00456121"},
                main.configured_super_admin_employee_ids(),
            )

    def test_existing_second_highest_admin_is_promoted_on_oauth_login(self):
        with patch.dict(
            "os.environ",
            {
                "OAUTH_CLIENT_ID": "test-client",
                "OAUTH_CLIENT_SECRET": "test-secret",
                "OAUTH_SUPER_ADMIN_EMPLOYEE_IDS": "j00983211,j00456121",
                "OAUTH_SYNC_ROLES": "false",
            },
            clear=False,
        ):
            settings = OAuth2Settings.from_env()
            identity = normalize_identity(
                {"sub": "stable-j00456121", "employee_id": "j00456121", "name": "第二最高管理员"},
                settings,
            )
            self.db.execute(
                "UPDATE users SET external_subject=? WHERE id=?",
                (identity["external_key"], self.second_super_id),
            )
            main.provision_oidc_user(self.db, identity, settings)
            self.db.commit()
        role = self.db.execute("SELECT role FROM users WHERE id=?", (self.second_super_id,)).fetchone()["role"]
        self.assertEqual("admin", role)

    def test_non_admin_cannot_open_or_change_application_management(self):
        with self.assertRaises(HTTPException) as context:
            main.admin_dashboard(make_request(self.staff_id))
        self.assertEqual(403, context.exception.status_code)
        with self.assertRaises(HTTPException) as context:
            main.admin_update_user_role(make_request(self.staff_id, method="POST"), self.other_admin_id, "reviewer")
        self.assertEqual(403, context.exception.status_code)

    def test_highest_admin_can_change_colleague_role_but_not_demote_self(self):
        response = main.admin_update_user_role(make_request(self.super_id, method="POST"), self.staff_id, "reviewer")
        self.assertEqual(303, response.status_code)
        self.assertEqual("reviewer", self.db.execute("SELECT role FROM users WHERE id=?", (self.staff_id,)).fetchone()["role"])
        with self.assertRaises(HTTPException) as context:
            main.admin_update_user_role(make_request(self.super_id, method="POST"), self.super_id, "contributor")
        self.assertEqual(400, context.exception.status_code)

    def test_normal_admin_cannot_create_another_admin_or_demote_highest_admin(self):
        with self.assertRaises(HTTPException) as context:
            main.admin_update_user_role(make_request(self.other_admin_id, method="POST"), self.staff_id, "admin")
        self.assertEqual(403, context.exception.status_code)
        with self.assertRaises(HTTPException) as context:
            main.admin_update_user_role(make_request(self.other_admin_id, method="POST"), self.super_id, "reviewer")
        self.assertEqual(403, context.exception.status_code)

    def test_admin_template_exposes_user_management_and_audit_without_secrets(self):
        rendered = main.templates.get_template("admin.html").render(
            request=make_request(self.super_id),
            user=self.db.execute("SELECT * FROM users WHERE id=?", (self.super_id,)).fetchone(),
            users=self.db.execute("SELECT * FROM users").fetchall(),
            audit_events=[],
            super_admin_ids=["j00456121", "j00983211"],
            csrf_token="test-csrf",
            role_label=main.role_label,
            help_title="应用管理帮助",
            help_text="管理权限和审计",
            registration_enabled=False,
            local_auth_enabled=True,
            oauth2_enabled=True,
            oauth2_provider_name="华为 IDaaS",
            oidc_enabled=True,
            oidc_provider_name="华为 IDaaS",
        )
        self.assertIn("应用管理", rendered)
        self.assertIn("保存权限", rendered)
        self.assertIn("登录与操作审计", rendered)
        self.assertNotIn("client_secret", rendered)
        self.assertNotIn("access_token", rendered)


if __name__ == "__main__":
    unittest.main()
