import json
import os
import unittest
import urllib.parse
from unittest.mock import patch

from app import main
from app.oidc_auth import (
    UNIPORTAL_AUTHORIZATION_URL,
    UNIPORTAL_TOKEN_URL,
    UNIPORTAL_USERINFO_URL,
    OAuth2Client,
    OAuth2Error,
    OAuth2Settings,
    auth_provider_mode,
)


class _Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def read(self):
        return self.payload


class OAuth2AuthTests(unittest.TestCase):
    def env(self, **overrides):
        values = {
            "AUTH_PROVIDER": "oauth2",
            "OAUTH_PROVIDER_ID": "huawei-idaas",
            "OAUTH_AUTHORIZATION_URL": "https://idaas.example.test/oauth/authorize",
            "OAUTH_TOKEN_URL": "https://idaas.example.test/oauth/token",
            "OAUTH_USERINFO_URL": "https://idaas.example.test/oauth/userinfo",
            "OAUTH_CLIENT_ID": "bmc-client",
            "OAUTH_CLIENT_SECRET": "server-secret",
            "OAUTH_REDIRECT_URI": "https://bmc.example.test/auth/oauth2/callback",
            "OAUTH_TENANT_ID": "5",
            "OAUTH_TENANT_PARAM": "tenantId",
            "OAUTH_TENANT_LOCATIONS": "authorization,userinfo",
        }
        values.update(overrides)
        return patch.dict(os.environ, values, clear=False)

    def test_oauth_mode_has_static_endpoints_and_no_oidc_requirements(self):
        with self.env():
            self.assertEqual("oauth2", auth_provider_mode())
            settings = OAuth2Settings.from_env()
            self.assertEqual("https://idaas.example.test/oauth/token", settings.token_url)
            self.assertEqual("5", settings.tenant_id)
            self.assertEqual("tenantId", settings.tenant_param)

    def test_uniportal_defaults_require_only_client_credentials(self):
        with patch.dict(
            os.environ,
            {
                "AUTH_PROVIDER": "oauth2",
                "APP_BASE_URL": "https://maintain.example.test",
                "OAUTH_CLIENT_ID": "uniportal-client",
                "OAUTH_CLIENT_SECRET": "uniportal-secret",
            },
            clear=True,
        ):
            settings = OAuth2Settings.from_env()
            self.assertEqual(UNIPORTAL_AUTHORIZATION_URL, settings.authorization_url)
            self.assertEqual(UNIPORTAL_TOKEN_URL, settings.token_url)
            self.assertEqual(UNIPORTAL_USERINFO_URL, settings.userinfo_url)
            self.assertEqual("https://maintain.example.test/authorize", settings.redirect_uri)
            self.assertEqual(("j00983211", "j00456121"), settings.super_admin_employee_ids)
            url = OAuth2Client(settings).authorization_url(state="state", code_challenge="challenge")
            self.assertEqual("uniportal.huawei.com", urllib.parse.urlsplit(url).hostname)
            self.assertEqual("/saaslogin1/oauth2/authorize", urllib.parse.urlsplit(url).path)
            self.assertNotIn("uniportal-secret", url)

    def test_authorize_callback_route_is_registered(self):
        route = next((item for item in main.app.routes if getattr(item, "path", "") == "/authorize"), None)
        self.assertIsNotNone(route)
        self.assertIn("GET", route.methods)

    def test_authorization_url_uses_code_pkce_and_tenant_without_nonce_or_secret(self):
        with self.env():
            settings = OAuth2Settings.from_env()
            client = OAuth2Client(settings)
            _, challenge = client.new_pkce()
            url = client.authorization_url(state="state", nonce="must-not-be-sent", code_challenge=challenge)
            query = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
            self.assertEqual(["code"], query["response_type"])
            self.assertEqual(["5"], query["tenantId"])
            self.assertNotIn("nonce", query)
            self.assertNotIn("server-secret", url)

    def test_code_exchange_basic_then_userinfo_is_the_only_identity_source(self):
        calls = []

        def opener(request, timeout):
            calls.append(request)
            if request.full_url.startswith("https://idaas.example.test/oauth/token"):
                self.assertEqual("Basic Ym1jLWNsaWVudDpzZXJ2ZXItc2VjcmV0", request.headers["Authorization"])
                return _Response({"access_token": "access-1", "token_type": "Bearer"})
            self.assertEqual("Bearer access-1", request.headers["Authorization"])
            self.assertIn("tenantId=5", request.full_url)
            return _Response({"uid": "j00983211", "employee_id": "j00983211", "display_name": "江小伟"})

        with self.env():
            settings = OAuth2Settings.from_env()
            identity = OAuth2Client(settings, opener=opener).identity_from_code("one-time-code", "verifier")
            self.assertEqual("j00983211", identity["subject"])
            self.assertEqual("j00983211", identity["username"])
            self.assertEqual("huawei-idaas|5|j00983211", identity["external_key"])
            self.assertEqual(2, len(calls))

    def test_missing_client_credentials_is_rejected(self):
        with patch.dict(
            os.environ,
            {"OAUTH_CLIENT_ID": "", "OAUTH_CLIENT_SECRET": ""},
            clear=True,
        ):
            with self.assertRaises(OAuth2Error):
                OAuth2Settings.from_env()


if __name__ == "__main__":
    unittest.main()
