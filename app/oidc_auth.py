"""Small provider-neutral OAuth 2.0 adapter used by the web login flow.

The company deployment deliberately uses OAuth 2.0 Authorization Code only:
the server exchanges a short-lived code for an access token and calls the
provider's UserInfo API.  It does not request, parse, or validate an OIDC ID
Token, Discovery document, issuer, nonce, or JWKS.  The confirmed Huawei
UniPortal authorization endpoint and the same-path Token/UserInfo defaults are
built in; approved company Demo differences remain server-side overrides.

``OIDCSettings`` and ``OIDCClient`` remain import aliases for one migration
release so existing internal imports do not break.  They execute this OAuth
2.0-only implementation; no OIDC flow is retained.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Callable


UNIPORTAL_OAUTH_BASE_URL = "https://uniportal.huawei.com/saaslogin1/oauth2"
UNIPORTAL_AUTHORIZATION_URL = f"{UNIPORTAL_OAUTH_BASE_URL}/authorize"
UNIPORTAL_TOKEN_URL = f"{UNIPORTAL_OAUTH_BASE_URL}/token"
UNIPORTAL_USERINFO_URL = f"{UNIPORTAL_OAUTH_BASE_URL}/userinfo"
DEFAULT_SUPER_ADMIN_EMPLOYEE_IDS = "j00983211,j00456121"


class OAuth2Error(RuntimeError):
    """A safe, user-facing OAuth 2.0 integration error."""


# Compatibility name used by older route code and one release of tests.
OIDCError = OAuth2Error


def env_flag(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def csv_env(name: str, default: str = "") -> tuple[str, ...]:
    return tuple(item.strip() for item in os.getenv(name, default).split(",") if item.strip())


def _first_env(*names: str, default: str = "") -> str:
    """Return the first non-empty environment value.

    OIDC_* names are accepted only as a backwards-compatible migration input;
    the active protocol and all generated URLs are still OAuth 2.0 only.
    """
    for name in names:
        value = os.getenv(name, "").strip()
        if value:
            return value
    return default


def auth_provider_mode() -> str:
    value = os.getenv("AUTH_PROVIDER", "local").strip().lower()
    # ``oidc`` is a legacy spelling accepted temporarily, but now routes to
    # the OAuth2-only adapter and never enables an OIDC token flow.
    return value if value in {"local", "oauth2", "oidc", "hybrid"} else "local"


def oauth2_enabled() -> bool:
    return auth_provider_mode() in {"oauth2", "oidc", "hybrid"}


def local_auth_enabled() -> bool:
    return auth_provider_mode() in {"local", "hybrid"}


@dataclass(frozen=True)
class OAuth2Settings:
    provider_id: str
    provider_name: str
    authorization_url: str
    token_url: str
    userinfo_url: str
    client_id: str
    client_secret: str
    redirect_uri: str
    scope: str
    token_endpoint_auth_method: str
    subject_claims: tuple[str, ...]
    username_claims: tuple[str, ...]
    email_claims: tuple[str, ...]
    display_claims: tuple[str, ...]
    group_claims: tuple[str, ...]
    admin_groups: tuple[str, ...]
    reviewer_groups: tuple[str, ...]
    super_admin_employee_ids: tuple[str, ...]
    auto_provision: bool
    auto_link_local: bool
    sync_roles: bool
    timeout_seconds: float
    tenant_id: str = ""
    tenant_param: str = "tenant_id"
    tenant_locations: tuple[str, ...] = ("authorization", "userinfo")
    end_session_url: str = ""
    # These two fields are retained only so old callers can inspect settings;
    # OAuth2 mode never fetches or trusts an OIDC discovery document.
    issuer: str = ""
    discovery_url: str = ""
    legacy_env: bool = False

    @classmethod
    def from_env(cls, redirect_uri: str | None = None) -> "OAuth2Settings":
        legacy_env = bool(os.getenv("OIDC_ISSUER", "").strip() or os.getenv("OIDC_DISCOVERY_URL", "").strip()) and not os.getenv("OAUTH_AUTHORIZATION_URL", "").strip()
        authorization_url = _first_env("OAUTH_AUTHORIZATION_URL", default=UNIPORTAL_AUTHORIZATION_URL)
        token_url = _first_env("OAUTH_TOKEN_URL", default=UNIPORTAL_TOKEN_URL)
        userinfo_url = _first_env("OAUTH_USERINFO_URL", default=UNIPORTAL_USERINFO_URL)
        issuer = _first_env("OAUTH_PROVIDER_ISSUER", "OIDC_ISSUER")
        discovery_url = _first_env("OAUTH_DISCOVERY_URL", "OIDC_DISCOVERY_URL")
        if legacy_env and issuer and not discovery_url:
            discovery_url = f"{issuer.rstrip('/')}/.well-known/openid-configuration"

        client_id = _first_env("OAUTH_CLIENT_ID", "OIDC_CLIENT_ID")
        client_secret = _first_env("OAUTH_CLIENT_SECRET", "OIDC_CLIENT_SECRET")
        base_url = os.getenv("APP_BASE_URL", "http://127.0.0.1:8000").strip().rstrip("/")
        callback = (
            redirect_uri
            or _first_env("OAUTH_REDIRECT_URI", "OIDC_REDIRECT_URI")
            or f"{base_url}/authorize"
        )
        # Old OIDC tests/imports may provide a Discovery URL. It is not used
        # by the live OAuth2 path; new deployments use UniPortal defaults.
        missing = [
            name
            for name, value in (
                ("OAUTH_CLIENT_ID", client_id),
                ("OAUTH_CLIENT_SECRET", client_secret),
            )
            if not value
        ]
        if missing:
            raise OAuth2Error("IDaaS OAuth2 登录尚未完成配置：" + ", ".join(missing))

        method = _first_env("OAUTH_TOKEN_ENDPOINT_AUTH_METHOD", "OIDC_TOKEN_ENDPOINT_AUTH_METHOD", default="client_secret_basic").lower()
        if method not in {"client_secret_basic", "client_secret_post"}:
            raise OAuth2Error("OAUTH_TOKEN_ENDPOINT_AUTH_METHOD 仅支持 client_secret_basic 或 client_secret_post")
        try:
            timeout = max(2.0, min(float(_first_env("OAUTH_HTTP_TIMEOUT", "OIDC_HTTP_TIMEOUT", default="10")), 60.0))
        except ValueError:
            timeout = 10.0
        locations = tuple(
            item.lower()
            for item in csv_env("OAUTH_TENANT_LOCATIONS", "authorization,userinfo")
            if item.lower() in {"authorization", "token", "userinfo"}
        ) or ("authorization", "userinfo")
        super_admin_source = _first_env(
            "OAUTH_SUPER_ADMIN_EMPLOYEE_IDS",
            "OIDC_SUPER_ADMIN_EMPLOYEE_IDS",
            default=DEFAULT_SUPER_ADMIN_EMPLOYEE_IDS,
        )
        return cls(
            provider_id=_first_env("OAUTH_PROVIDER_ID", "OIDC_PROVIDER_ID", default="huawei-idaas") or "huawei-idaas",
            provider_name=_first_env("OAUTH_PROVIDER_NAME", "OIDC_PROVIDER_NAME", default="华为 UniPortal") or "华为 UniPortal",
            authorization_url=authorization_url,
            token_url=token_url,
            userinfo_url=userinfo_url,
            client_id=client_id,
            client_secret=client_secret,
            redirect_uri=callback,
            scope=_first_env("OAUTH_SCOPE", default="profile") or "profile",
            token_endpoint_auth_method=method,
            subject_claims=csv_env("OAUTH_SUBJECT_CLAIMS", "sub,uid,user_id,id,employee_id,employeeId"),
            username_claims=csv_env("OAUTH_USERNAME_CLAIMS", "preferred_username,employee_id,employeeId,uid,email,sub"),
            email_claims=csv_env("OAUTH_EMAIL_CLAIMS", "email,mail"),
            display_claims=csv_env("OAUTH_DISPLAY_NAME_CLAIMS", "name,display_name,cn,preferred_username"),
            group_claims=csv_env("OAUTH_GROUP_CLAIMS", "groups,roles,group"),
            admin_groups=csv_env("OAUTH_ADMIN_GROUPS", os.getenv("OIDC_ADMIN_GROUPS", "")),
            reviewer_groups=csv_env("OAUTH_REVIEWER_GROUPS", os.getenv("OIDC_REVIEWER_GROUPS", "")),
            # The company-designated highest administrator is kept as a
            # server-side default; deployments may replace it with a comma-
            # separated allowlist in OAUTH_SUPER_ADMIN_EMPLOYEE_IDS.
            super_admin_employee_ids=tuple(item.strip() for item in super_admin_source.split(",") if item.strip()),
            auto_provision=env_flag("OAUTH_AUTO_PROVISION", env_flag("OIDC_AUTO_PROVISION", True)),
            auto_link_local=env_flag("OAUTH_AUTO_LINK_LOCAL", env_flag("OIDC_AUTO_LINK_LOCAL", False)),
            sync_roles=env_flag("OAUTH_SYNC_ROLES", env_flag("OIDC_SYNC_ROLES", False)),
            timeout_seconds=timeout,
            tenant_id=_first_env("OAUTH_TENANT_ID"),
            tenant_param=_first_env("OAUTH_TENANT_PARAM", default="tenant_id") or "tenant_id",
            tenant_locations=locations,
            end_session_url=_first_env("OAUTH_END_SESSION_URL", "OIDC_END_SESSION_URL"),
            issuer=issuer,
            discovery_url=discovery_url,
            legacy_env=legacy_env,
        )


def _json_request(
    url: str,
    *,
    method: str = "GET",
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 10,
    opener: Callable[..., Any] | None = None,
) -> dict[str, Any]:
    request = urllib.request.Request(url, data=body, headers=headers or {}, method=method)
    open_fn = opener or urllib.request.urlopen
    try:
        with open_fn(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise OAuth2Error("IDaaS OAuth2 服务暂时不可达，请联系平台管理员检查内网、证书和代理配置。") from exc
    try:
        value = json.loads(payload)
    except (TypeError, ValueError):
        # OAuth2 token responses are normally JSON, but some compatible
        # gateways return application/x-www-form-urlencoded.  Accept that
        # standard representation while keeping UserInfo object-shaped.
        parsed = urllib.parse.parse_qs(payload, keep_blank_values=True)
        value = {key: values[-1] for key, values in parsed.items()}
        if not value:
            raise OAuth2Error("IDaaS OAuth2 返回了无法识别的数据。")
    if not isinstance(value, dict):
        raise OAuth2Error("IDaaS OAuth2 返回的数据格式不正确。")
    return value


def _claim_value(claims: dict[str, Any], names: tuple[str, ...], fallback: str = "") -> str:
    for name in names:
        value = claims.get(name)
        if isinstance(value, (str, int, float)) and str(value).strip():
            return str(value).strip()
    return fallback


def _claim_values(claims: dict[str, Any], names: tuple[str, ...]) -> tuple[str, ...]:
    values: list[str] = []
    for name in names:
        value = claims.get(name)
        if isinstance(value, str):
            raw = value.replace(";", ",").split(",")
            values.extend(item.strip() for item in raw if item.strip())
        elif isinstance(value, (list, tuple, set)):
            values.extend(str(item).strip() for item in value if str(item).strip())
    return tuple(dict.fromkeys(values))


def normalize_identity(claims: dict[str, Any], settings: OAuth2Settings) -> dict[str, Any]:
    """Convert OAuth2 UserInfo claims to the platform's stable identity shape."""
    subject = _claim_value(claims, settings.subject_claims)
    username = _claim_value(claims, settings.username_claims, subject)
    if not subject:
        raise OAuth2Error("IDaaS UserInfo 缺少稳定的用户标识（请配置 OAUTH_SUBJECT_CLAIMS）。")
    # In OAuth2 mode there is no issuer validation contract, so use the
    # configured provider namespace rather than trusting an arbitrary claim.
    # The legacy test/import path preserves the previous issuer-shaped key for
    # one migration release only.
    issuer = (
        str(claims.get("iss", settings.issuer or settings.provider_id)).strip().rstrip("/")
        if settings.legacy_env
        else (settings.issuer or settings.provider_id).strip().rstrip("/")
    )
    groups = _claim_values(claims, settings.group_claims)
    email = _claim_value(claims, settings.email_claims)
    display_name = _claim_value(claims, settings.display_claims, username)
    tenant_suffix = f"|{settings.tenant_id}" if settings.tenant_id else ""
    return {
        "provider": settings.provider_id,
        "subject": subject,
        "issuer": issuer,
        "external_key": f"{issuer}{tenant_suffix}|{subject}",
        "username": username,
        "email": email,
        "display_name": display_name,
        "groups": groups,
        "claims": claims,
    }


def _with_tenant(url: str, settings: OAuth2Settings, location: str) -> str:
    if not settings.tenant_id or location not in settings.tenant_locations:
        return url
    parsed = urllib.parse.urlsplit(url)
    query = urllib.parse.parse_qsl(parsed.query, keep_blank_values=True)
    if not any(key == settings.tenant_param for key, _ in query):
        query.append((settings.tenant_param, settings.tenant_id))
    return urllib.parse.urlunsplit(parsed._replace(query=urllib.parse.urlencode(query)))


class OAuth2Client:
    """OAuth 2.0 authorization code, PKCE, token exchange and UserInfo."""

    def __init__(self, settings: OAuth2Settings, opener: Callable[..., Any] | None = None):
        self.settings = settings
        self.opener = opener
        self._metadata: dict[str, Any] | None = None
        self._metadata_loaded_at = 0.0

    def endpoints(self) -> dict[str, str]:
        """Return configured static endpoints; legacy discovery is not fetched."""
        if self.settings.authorization_url and self.settings.token_url and self.settings.userinfo_url:
            return {
                "authorization_endpoint": self.settings.authorization_url,
                "token_endpoint": self.settings.token_url,
                "userinfo_endpoint": self.settings.userinfo_url,
            }
        # Compatibility only: old unit tests may manually inject metadata.
        # New deployments use the built-in UniPortal defaults above.
        if self._metadata:
            return self._metadata
        raise OAuth2Error("请配置 OAUTH_AUTHORIZATION_URL、OAUTH_TOKEN_URL 和 OAUTH_USERINFO_URL。")

    def discovery(self) -> dict[str, Any]:
        """Compatibility method; never performs OIDC discovery/network I/O."""
        return self.endpoints()

    @staticmethod
    def new_pkce() -> tuple[str, str]:
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
        return verifier, challenge

    def authorization_url(
        self,
        *,
        state: str,
        code_challenge: str,
        redirect_uri: str | None = None,
        nonce: str | None = None,
    ) -> str:
        endpoint = self.endpoints()["authorization_endpoint"]
        query = {
            "response_type": "code",
            "client_id": self.settings.client_id,
            "redirect_uri": redirect_uri or self.settings.redirect_uri,
            "scope": self.settings.scope,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        # Deliberately ignore nonce: it belongs to OIDC and must not be sent
        # when the company application is configured as OAuth2-only.
        endpoint = _with_tenant(endpoint, self.settings, "authorization")
        return endpoint + ("&" if "?" in endpoint else "?") + urllib.parse.urlencode(query)

    def exchange_code(self, code: str, verifier: str, redirect_uri: str | None = None) -> dict[str, Any]:
        endpoint = _with_tenant(self.endpoints()["token_endpoint"], self.settings, "token")
        values = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri or self.settings.redirect_uri,
            "code_verifier": verifier,
        }
        headers = {"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"}
        if self.settings.token_endpoint_auth_method == "client_secret_basic":
            raw = f"{self.settings.client_id}:{self.settings.client_secret}".encode("utf-8")
            headers["Authorization"] = "Basic " + base64.b64encode(raw).decode("ascii")
            values["client_id"] = self.settings.client_id
        else:
            values.update({"client_id": self.settings.client_id, "client_secret": self.settings.client_secret})
        response = _json_request(
            endpoint,
            method="POST",
            body=urllib.parse.urlencode(values).encode("utf-8"),
            headers=headers,
            timeout=self.settings.timeout_seconds,
            opener=self.opener,
        )
        if response.get("error"):
            raise OAuth2Error("IDaaS OAuth2 授权码交换失败，请检查客户端认证方式和回调地址。")
        if not response.get("access_token"):
            raise OAuth2Error("IDaaS OAuth2 未返回 access_token。")
        return response

    def userinfo(self, access_token: str) -> dict[str, Any]:
        endpoint = _with_tenant(self.endpoints()["userinfo_endpoint"], self.settings, "userinfo")
        return _json_request(
            endpoint,
            headers={"Accept": "application/json", "Authorization": f"Bearer {access_token}"},
            timeout=self.settings.timeout_seconds,
            opener=self.opener,
        )

    def identity_from_code(
        self,
        code: str,
        verifier: str,
        nonce: str | None = None,
        redirect_uri: str | None = None,
    ) -> dict[str, Any]:
        if not code:
            raise OAuth2Error("IDaaS 未返回授权码。")
        tokens = self.exchange_code(code, verifier, redirect_uri)
        claims = self.userinfo(str(tokens["access_token"]))
        # OAuth2 UserInfo is the only identity source.  No ID Token/JWKS path.
        claims.setdefault("iss", self.settings.issuer or self.settings.provider_id)
        return normalize_identity(claims, self.settings)

    def validate_id_token(self, token: str, nonce: str | None = None) -> dict[str, Any]:
        raise OAuth2Error("当前部署仅启用 OAuth2，不接受或解析 ID Token。")


# One-release compatibility aliases.  These names no longer imply an OIDC
# implementation; they point to the OAuth2-only settings/client above.
OIDCSettings = OAuth2Settings
OIDCClient = OAuth2Client
