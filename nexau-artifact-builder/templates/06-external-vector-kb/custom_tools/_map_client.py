"""MAP OpenAPI low-level client: token cache + signed POST helpers.

Stdlib-only (urllib + ssl + json) — zero extra dependencies, so it works no
matter what the runtime image ships.

NOTE on where this runs: custom_tools are imported and executed **inside the
agent-runtime process**, not inside the sandbox. That process therefore reads
`MAP_*` from the *runtime-scope* environment (the same scope `${env.*}` in
agent.yaml resolves against). Sandbox-scope variables are invisible here.
If you prefer a real HTTP client, the agent-runtime image already ships
httpx / requests — stdlib is a portability choice, not a hard constraint.

Endpoints:
- POST {host}/platform/api/v2/auth/getSessionToken    → access_token (TTL 7200s)
- POST {host}/platform/api/v2/auth/refreshToken       → renew access_token
- POST {host}/interface/api/kb/...                    → vector KB search APIs

⚠️ SECURITY — read before deploying:

1. TLS certificate verification is **OFF by default**. MAP gateways in
   private-deployment scenarios typically expose HTTPS with a self-signed
   certificate (curl needs `-k`, urllib needs a CERT_NONE context), so an
   opt-out default is what makes this template work out of the box. The cost
   is real: `getSessionToken` POSTs your **app_secret** over that connection,
   so with verification off the credential exchange is MITM-able — anyone who
   can intercept the route can present any certificate, take the secret, and
   proxy the traffic. Set `MAP_VERIFY_SSL=true` (plus a properly CA-signed
   gateway, or your enterprise CA in the trust store) before going to
   production. The client logs a warning on every process that runs with
   verification disabled.

2. There is **no default host**. `MAP_HOST` must be set explicitly; the client
   refuses to build otherwise. This is deliberate: an earlier revision fell
   back to a public demo box (`https://<第三方演示机>`), which meant a
   user who configured their own MAP_APP_KEY / MAP_APP_SECRET but forgot
   MAP_HOST would silently ship their credentials to a third-party machine
   over an unverified connection. Format example only — do not use as-is:
   `https://<your-map-gateway>:10002`.
"""

from __future__ import annotations

import json
import logging
import os
import ssl
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger(__name__)

# Emit the "TLS verification disabled" warning once per process, not per call.
_INSECURE_WARNED = False


def _verify_ssl_enabled() -> bool:
    """True only when the operator explicitly opts in via MAP_VERIFY_SSL."""
    return os.environ.get("MAP_VERIFY_SSL", "").strip().lower() in (
        "1", "true", "yes", "on",
    )


def _make_ssl_context(host: str) -> ssl.SSLContext | None:
    global _INSECURE_WARNED
    parsed = urllib.parse.urlparse(host)
    if parsed.scheme != "https":
        return None
    ctx = ssl.create_default_context()
    if not _verify_ssl_enabled():
        # Self-signed cert is the norm for private MAP deployments, so this
        # stays the default — but say out loud what it costs.
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        if not _INSECURE_WARNED:
            _INSECURE_WARNED = True
            logger.warning(
                "MAP client: TLS certificate verification is DISABLED for %s. "
                "app_secret is exchanged over this connection, so it can be "
                "intercepted by anyone able to MITM the route. Set "
                "MAP_VERIFY_SSL=true (and use a CA-signed gateway or install "
                "your enterprise CA) in production.",
                host,
            )
    return ctx


class MapApiError(RuntimeError):
    """Raised when the MAP API responds with success=false or non-2xx."""


# Process-level cache: (host, app_key, user_id) → {access_token, refresh_token, exp_at}
_TOKEN_CACHE: dict[tuple[str, str, str], dict[str, Any]] = {}
_TOKEN_LOCK = threading.Lock()


class MapClient:
    """Stateless façade — token cache lives at module level so multiple tool
    invocations within the same Runtime process share the same access_token."""

    def __init__(
        self,
        *,
        host: str,
        app_key: str,
        app_secret: str,
        user_id: str,
        timeout: int = 30,
    ):
        if not host:
            # ⚠️ 刻意不给默认 host：见模块 docstring 第 2 条。
            raise MapApiError(
                "MAP_HOST is not configured. Set the MAP_HOST runtime variable "
                "to your own MAP gateway (e.g. https://map.example.internal:10002) "
                "before calling any map_vec_* tool — this client will never fall "
                "back to a shared/demo host, because doing so would send your "
                "app_secret to a machine you do not control."
            )
        # normalise: strip trailing slash
        self.host = host.rstrip("/")
        self.app_key = app_key
        self.app_secret = app_secret
        self.user_id = user_id
        self.timeout = timeout
        self._ssl_ctx = _make_ssl_context(self.host)

    # ------------------------------------------------------------------ HTTP

    def _post_json(
        self,
        path: str,
        body: dict[str, Any],
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[int, bytes, dict[str, str]]:
        url = f"{self.host}{path}"
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Accept": "*/*",
        }
        if extra_headers:
            headers.update(extra_headers)
        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=self._ssl_ctx) as resp:
                return resp.status, resp.read(), dict(resp.headers)
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read() if exc.fp else b"", dict(exc.headers or {})

    def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        *,
        extra_headers: dict[str, str] | None = None,
    ) -> tuple[int, bytes, dict[str, str]]:
        qs = urllib.parse.urlencode(params or {}, doseq=True)
        url = f"{self.host}{path}" + (f"?{qs}" if qs else "")
        headers = {"Accept": "*/*"}
        if extra_headers:
            headers.update(extra_headers)
        req = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=self._ssl_ctx) as resp:
                return resp.status, resp.read(), dict(resp.headers)
        except urllib.error.HTTPError as exc:
            return exc.code, exc.read() if exc.fp else b"", dict(exc.headers or {})

    # ------------------------------------------------------------------ auth

    def _cache_key(self) -> tuple[str, str, str]:
        return (self.host, self.app_key, self.user_id)

    def _fetch_new_token(self) -> dict[str, Any]:
        status, raw, _ = self._post_json(
            "/platform/api/v2/auth/getSessionToken",
            {
                "app_key": self.app_key,
                "app_secret": self.app_secret,
                "user_id": self.user_id,
            },
        )
        if status >= 400:
            raise MapApiError(
                f"getSessionToken HTTP {status}: {raw[:300].decode('utf-8', 'replace')}"
            )
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise MapApiError(f"getSessionToken non-JSON response: {raw[:300]!r}") from exc
        if not payload.get("success"):
            raise MapApiError(
                f"getSessionToken failed: state={payload.get('state')} "
                f"message={payload.get('message')}"
            )
        data = payload.get("data") or {}
        access_token = data.get("access_token")
        refresh_token = data.get("refresh_token")
        expires_in = int(data.get("expires_in") or 7200)
        if not access_token:
            raise MapApiError(f"getSessionToken returned no access_token: {payload}")
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            # Refresh 60s before expiry to be safe.
            "exp_at": time.time() + max(expires_in - 60, 60),
        }

    def get_access_token(self) -> str:
        key = self._cache_key()
        with _TOKEN_LOCK:
            cached = _TOKEN_CACHE.get(key)
            if cached and cached["exp_at"] > time.time():
                return cached["access_token"]
            fresh = self._fetch_new_token()
            _TOKEN_CACHE[key] = fresh
            return fresh["access_token"]

    def invalidate_token(self, rejected_token: str | None = None) -> None:
        """Remove a rejected token without discarding a concurrent refresh."""
        with _TOKEN_LOCK:
            key = self._cache_key()
            cached = _TOKEN_CACHE.get(key)
            if cached is None:
                return
            if rejected_token is None or cached.get("access_token") == rejected_token:
                _TOKEN_CACHE.pop(key, None)

    # ------------------------------------------------------------------ api

    def _auth_headers(self) -> dict[str, str]:
        return {
            "accessToken": self.get_access_token(),
            "userId": self.user_id,
        }

    @staticmethod
    def _is_ok(payload: dict[str, Any]) -> bool:
        # /interface/api/* uses `result`/`succeed`; auth uses `success`.
        return bool(
            payload.get("success") or payload.get("result") or payload.get("succeed")
        )

    def _parse_payload(self, path: str, status: int, raw: bytes) -> dict[str, Any]:
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            raise MapApiError(
                f"{path} non-JSON response (HTTP {status}): {raw[:300]!r}"
            ) from exc
        if status >= 400:
            raise MapApiError(
                f"{path} HTTP {status}: "
                f"state={payload.get('state')} resultCode={payload.get('resultCode')} "
                f"message={payload.get('message')}"
            )
        if not self._is_ok(payload):
            raise MapApiError(
                f"{path} failed: "
                f"state={payload.get('state')} resultCode={payload.get('resultCode')} "
                f"message={payload.get('message')}"
            )
        return payload

    def _looks_like_auth_failure(self, status: int, payload: dict[str, Any]) -> bool:
        if status in (401, 403):
            return True
        if self._is_ok(payload):
            return False

        # MAP reports an expired/invalid access token as HTTP 500 with
        # state=28201 instead of an HTTP authentication status.
        codes = (
            str(payload.get("state") or ""),
            str(payload.get("resultCode") or ""),
        )
        if any(code == "28201" or code.startswith(("401", "403")) for code in codes):
            return True

        message = "".join(str(payload.get("message") or "").lower().split())
        return "token无效" in message or "invalidtoken" in message

    def call_json(self, path: str, body: dict[str, Any]) -> Any:
        """POST and return `data`; refresh and retry once on auth failure."""
        return self._call(self._post_json, path, body=body, return_full=False)

    def call_full(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        """POST and return the FULL parsed payload (for endpoints whose
        attributes / messages we also need)."""
        return self._call(self._post_json, path, body=body, return_full=True)

    def call_get(self, path: str, params: dict[str, Any]) -> Any:
        """GET and return the JSON `data` field."""
        return self._call(self._get, path, params=params, return_full=False)

    def call_full_get(self, path: str, params: dict[str, Any]) -> dict[str, Any]:
        """GET and return the FULL parsed payload."""
        return self._call(self._get, path, params=params, return_full=True)

    def _call(
        self,
        verb,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        return_full: bool,
    ) -> Any:
        # Retry once after an auth failure (token invalidation), independently
        # of up to two transient retries. Keeping separate retry budgets ensures
        # that a late auth failure still gets one request with the fresh token.
        auth_refreshed = False
        transient_retries = 0
        while True:
            headers = self._auth_headers()
            if body is not None:
                status, raw, _ = verb(path, body, extra_headers=headers)
            else:
                status, raw, _ = verb(path, params, extra_headers=headers)
            try:
                preview = json.loads(raw.decode("utf-8"))
                preview_dict = preview if isinstance(preview, dict) else {}
            except Exception:
                preview_dict = {}
            auth_failure = self._looks_like_auth_failure(status, preview_dict)
            if auth_failure and not auth_refreshed:
                self.invalidate_token(headers["accessToken"])
                auth_refreshed = True
                continue
            if (
                not auth_failure
                and transient_retries < 2
                and self._looks_like_transient(status, preview_dict)
            ):
                transient_retries += 1
                time.sleep(0.6)
                continue
            payload = self._parse_payload(path, status, raw)
            return payload if return_full else payload.get("data")

    @staticmethod
    def _looks_like_transient(status: int, payload: dict[str, Any]) -> bool:
        # Demo's update/permission endpoints intermittently return state=20001
        # ("服务未知异常") on the first request after a cold path; the same
        # body succeeds on a quick retry. Treat that as transient.
        if status >= 500:
            return True
        if status == 200 and not (
            payload.get("success") or payload.get("result") or payload.get("succeed")
        ):
            state = str(payload.get("state", ""))
            if state == "20001":
                return True
        return False
