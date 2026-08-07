import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import database, main
from app.oidc_auth import OIDCClient, OIDCError, OIDCSettings, auth_provider_mode, normalize_identity


class OIDCAuthTests(unittest.TestCase):
    def settings(self, **overrides):
        values = {
            "AUTH_PROVIDER": "hybrid",
            "OIDC_ISSUER": "https://idaas.example.test",
            "OIDC_CLIENT_ID": "bmc-client",
            "OIDC_CLIENT_SECRET": "server-secret",
            "OIDC_REDIRECT_URI": "https://bmc.example.test/auth/oidc/callback",
            "OIDC_ADMIN_GROUPS": "platform-admins",
            "OIDC_REVIEWER_GROUPS": "platform-reviewers",
            "OIDC_SUPER_ADMIN_EMPLOYEE_IDS": "j00983211",
            "OIDC_SYNC_ROLES": "true",
        }
        values.update(overrides)
        return patch.dict("os.environ", values, clear=False)

    def test_mode_and_settings_are_environment_driven(self):
        with self.settings():
            self.assertEqual("hybrid", auth_provider_mode())
            settings = OIDCSettings.from_env()
            self.assertEqual("https://idaas.example.test/.well-known/openid-configuration", settings.discovery_url)
            self.assertEqual("https://bmc.example.test/auth/oidc/callback", settings.redirect_uri)
        with patch.dict("os.environ", {"AUTH_PROVIDER": "oidc"}, clear=False):
            self.assertEqual("oidc", auth_provider_mode())

    def test_pkce_authorization_never_contains_client_secret(self):
        with self.settings():
            settings = OIDCSettings.from_env()
            client = OIDCClient(settings)
            client._metadata = {
                "issuer": settings.issuer,
                "authorization_endpoint": "https://idaas.example.test/oauth/authorize",
                "token_endpoint": "https://idaas.example.test/oauth/token",
            }
            client._metadata_loaded_at = 9999999999
            verifier, challenge = client.new_pkce()
            url = client.authorization_url(state="state", nonce="nonce", code_challenge=challenge)
            self.assertIn("code_challenge_method=S256", url)
            self.assertIn("response_type=code", url)
            self.assertNotIn("server-secret", url)
            self.assertGreaterEqual(len(verifier), 43)

    def test_identity_normalization_and_role_claims(self):
        with self.settings():
            settings = OIDCSettings.from_env()
            identity = normalize_identity(
                {
                    "iss": settings.issuer,
                    "sub": "employee-00983211",
                    "employee_id": "00983211",
                    "name": "江小伟",
                    "email": "jiang@example.test",
                    "groups": ["platform-reviewers", "ops"],
                },
                settings,
            )
            self.assertEqual("https://idaas.example.test|employee-00983211", identity["external_key"])
            self.assertEqual("00983211", identity["username"])
            self.assertEqual(("platform-reviewers", "ops"), identity["groups"])
            self.assertEqual("reviewer", main._oidc_role(identity, settings))

    def test_configured_super_admin_employee_id_overrides_group_mapping(self):
        with self.settings():
            settings = OIDCSettings.from_env()
            identity = normalize_identity(
                {"iss": settings.issuer, "sub": "stable-sub", "employee_id": "j00983211", "groups": []},
                settings,
            )
            self.assertEqual("admin", main._oidc_role(identity, settings))

    def test_missing_settings_are_rejected_without_network_call(self):
        with patch.dict("os.environ", {"OIDC_ISSUER": "", "OIDC_DISCOVERY_URL": "", "OIDC_CLIENT_ID": "", "OIDC_CLIENT_SECRET": ""}, clear=False):
            with self.assertRaises(OIDCError):
                OIDCSettings.from_env()

    def test_next_path_cannot_become_an_open_redirect(self):
        self.assertEqual("/reports?q=1", main._safe_next_path("/reports?q=1"))
        self.assertEqual("/", main._safe_next_path("https://evil.example/collect"))
        self.assertEqual("/", main._safe_next_path("//evil.example/collect"))

    def test_provisioning_uses_external_key_and_syncs_configured_role(self):
        temp_dir = tempfile.TemporaryDirectory()
        previous = database.DB_PATH
        database.DB_PATH = Path(temp_dir.name) / "auth.db"
        try:
            database.init_db()
            db = database.connection()
            with self.settings():
                settings = OIDCSettings.from_env()
                identity = normalize_identity(
                    {"iss": settings.issuer, "sub": "sub-1", "preferred_username": "00983211", "groups": ["platform-admins"]},
                    settings,
                )
                user_id = main.provision_oidc_user(db, identity, settings)
                db.commit()
                user = db.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
                self.assertEqual("admin", user["role"])
                self.assertEqual("huawei-idaas", user["auth_provider"])
                self.assertEqual(identity["external_key"], user["external_subject"])
                self.assertEqual(user_id, main.provision_oidc_user(db, identity, settings))
                self.assertEqual(1, db.execute("SELECT COUNT(*) FROM users").fetchone()[0])
            db.close()
        finally:
            database.DB_PATH = previous
            temp_dir.cleanup()


if __name__ == "__main__":
    unittest.main()
