"""Defensive Feishu Open Platform HTTP transport.

Supported surface: internal-app tenant authentication, read-only Bitable/wiki/docx
access, and one-record Bitable updates constrained by a field allowlist. Credentials
are resolved only through environment-variable references.

Run offline tests with ``python integrations/feishu.py --selftest``.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol, Sequence


DEFAULT_BASE_URL = "https://open.feishu.cn"
DEFAULT_APP_ID_ENV = "FEISHU_APP_ID"
DEFAULT_APP_SECRET_ENV = "FEISHU_APP_SECRET"
TENANT_TOKEN_PATH = "/open-apis/auth/v3/tenant_access_token/internal"
BITABLE_PREFIX = "/open-apis/bitable/v1"
WIKI_PREFIX = "/open-apis/wiki/v2"
DOCX_PREFIX = "/open-apis/docx/v1"
_MAX_RESPONSE_BYTES = 4 * 1024 * 1024
_MAX_JSON_DEPTH = 32
_MAX_COLLECTION_ITEMS = 10_000
_ENV_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class FeishuError(Exception):
    """Base class for stable, non-secret-bearing errors."""


class ConfigurationError(FeishuError):
    """Local configuration is invalid or incomplete."""


class NotSupportedError(FeishuError):
    """An intentionally disabled or unverified operation was requested."""


class TransportError(FeishuError):
    """No valid HTTP response was available."""


class ResponseValidationError(FeishuError):
    """A third-party response failed boundary validation."""


class ApiError(FeishuError):
    """Feishu returned a structurally valid error response."""

    def __init__(
        self,
        message: str,
        *,
        code: int | str | None = None,
        status: int | None = None,
        request_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status = status
        self.request_id = request_id


@dataclass(frozen=True)
class CredentialRef:
    """Environment-variable names containing app credentials, never values."""

    app_id_env: str = DEFAULT_APP_ID_ENV
    app_secret_env: str = DEFAULT_APP_SECRET_ENV

    def __post_init__(self) -> None:
        for label, name in (
            ("app_id_env", self.app_id_env),
            ("app_secret_env", self.app_secret_env),
        ):
            if not isinstance(name, str) or not _ENV_NAME_RE.fullmatch(name):
                raise ConfigurationError(f"{label} is not a valid environment name")

    def is_configured(self) -> bool:
        return bool(os.environ.get(self.app_id_env)) and bool(
            os.environ.get(self.app_secret_env)
        )

    def resolve(self) -> tuple[str, str]:
        app_id = os.environ.get(self.app_id_env)
        app_secret = os.environ.get(self.app_secret_env)
        missing = [
            name
            for name, value in (
                (self.app_id_env, app_id),
                (self.app_secret_env, app_secret),
            )
            if not value
        ]
        if missing:
            raise ConfigurationError(
                "missing Feishu credential environment variable(s): "
                + ", ".join(missing)
            )
        return app_id, app_secret


@dataclass(frozen=True)
class HttpRequest:
    method: str
    url: str
    headers: Mapping[str, str] = field(default_factory=dict)
    body: bytes | None = field(default=None, repr=False)
    timeout: float = 10.0


@dataclass(frozen=True)
class HttpResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


class HttpTransport(Protocol):
    def send(self, request: HttpRequest) -> HttpResponse:
        """Send exactly one request."""


class UrllibHttpTransport:
    """Standard-library HTTP implementation with bounded response reads."""

    def __init__(self, *, max_response_bytes: int = _MAX_RESPONSE_BYTES) -> None:
        if not isinstance(max_response_bytes, int) or not 1 <= max_response_bytes <= 64 * 1024 * 1024:
            raise ConfigurationError("max_response_bytes must be between 1 and 64 MiB")
        self.max_response_bytes = max_response_bytes

    def send(self, request: HttpRequest) -> HttpResponse:
        raw = urllib.request.Request(
            request.url,
            data=request.body,
            headers=dict(request.headers),
            method=request.method,
        )
        try:
            with urllib.request.urlopen(raw, timeout=request.timeout) as response:
                return HttpResponse(
                    int(response.status),
                    dict(response.headers.items()),
                    self._read_bounded(response),
                )
        except urllib.error.HTTPError as exc:
            try:
                body = self._read_bounded(exc)
            except ResponseValidationError:
                body = b""
            return HttpResponse(
                int(exc.code),
                dict(exc.headers.items()) if exc.headers else {},
                body,
            )
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as exc:
            reason = getattr(exc, "reason", None)
            detail = type(reason or exc).__name__
            raise TransportError(f"Feishu HTTP transport failed ({detail})") from exc

    def _read_bounded(self, response: Any) -> bytes:
        body = response.read(self.max_response_bytes + 1)
        if len(body) > self.max_response_bytes:
            raise ResponseValidationError("Feishu response exceeded the size limit")
        return body


@dataclass(frozen=True)
class RetryPolicy:
    """Conservative retries; provider-specific 429 handling defaults off."""

    max_attempts: int = 3
    base_delay: float = 0.2
    max_delay: float = 2.0
    retry_http_429: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.max_attempts, int) or not 1 <= self.max_attempts <= 5:
            raise ConfigurationError("max_attempts must be between 1 and 5")
        if self.base_delay < 0 or self.max_delay < self.base_delay:
            raise ConfigurationError("retry delays are invalid")

    def delay(self, failed_attempt: int) -> float:
        return min(self.max_delay, self.base_delay * (2 ** (failed_attempt - 1)))


@dataclass(frozen=True)
class Capability:
    name: str
    supported: bool
    enabled: bool
    verified: bool
    detail: str


@dataclass(frozen=True)
class CapabilityReport:
    credential_refs_configured: bool
    capabilities: tuple[Capability, ...]

    def get(self, name: str) -> Capability:
        for capability in self.capabilities:
            if capability.name == name:
                return capability
        raise KeyError(name)


@dataclass(frozen=True)
class BitableRecord:
    record_id: str
    fields: Mapping[str, Any]


@dataclass(frozen=True)
class BitableRecordPage:
    items: tuple[BitableRecord, ...]
    has_more: bool
    page_token: str | None
    total: int | None


@dataclass(frozen=True)
class WikiNode:
    node_token: str
    obj_token: str
    obj_type: str
    title: str | None
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class Document:
    document_id: str
    revision_id: int | None
    title: str
    metadata: Mapping[str, Any]


@dataclass(frozen=True)
class DocumentBlock:
    block_id: str
    block_type: int
    parent_id: str | None
    children: tuple[str, ...]
    content: Mapping[str, Any]


@dataclass(frozen=True)
class DocumentBlockPage:
    items: tuple[DocumentBlock, ...]
    has_more: bool
    page_token: str | None


@dataclass(frozen=True)
class _Token:
    value: str = field(repr=False)
    expires_at: float


class FeishuClient:
    """Client for the explicitly supported Feishu HTTP API subset."""

    def __init__(
        self,
        *,
        credential_ref: CredentialRef | None = None,
        transport: HttpTransport | None = None,
        retry_policy: RetryPolicy | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout: float = 10.0,
        allowed_update_fields: Sequence[str] = (),
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        parsed = urllib.parse.urlsplit(base_url)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ConfigurationError("base_url must be an absolute HTTPS URL")
        if parsed.query or parsed.fragment or parsed.username or parsed.password:
            raise ConfigurationError("base_url must not contain credentials, query, or fragment")
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 0 < timeout <= 120:
            raise ConfigurationError("timeout must be greater than 0 and at most 120 seconds")
        update_fields = frozenset(allowed_update_fields)
        if any(not isinstance(name, str) or not name.strip() for name in update_fields):
            raise ConfigurationError("allowed_update_fields must contain non-empty strings")

        self.credential_ref = credential_ref or CredentialRef()
        self.transport = transport or UrllibHttpTransport()
        self.retry_policy = retry_policy or RetryPolicy()
        self.base_url = base_url.rstrip("/")
        self.timeout = float(timeout)
        self.allowed_update_fields = update_fields
        self._sleep = sleep
        self._clock = clock
        self._token: _Token | None = None
        self._token_lock = threading.Lock()

    def probe_capabilities(self, *, check_auth: bool = False) -> CapabilityReport:
        """Report local support and optionally verify tenant-token acquisition.

        Endpoint permissions cannot be inferred from a tenant token. Data API
        capabilities remain unverified until called with a real resource.
        """

        configured = self.credential_ref.is_configured()
        auth_verified = False
        auth_detail = "credential references are not configured"
        if configured:
            auth_detail = "credential references configured; token not requested"
        if check_auth:
            if configured:
                self.get_tenant_access_token()
                auth_verified = True
                auth_detail = "tenant token acquisition succeeded"
            else:
                auth_detail = "authentication check skipped: credential references missing"

        read_detail = "implemented; tenant permissions and resource access not probed"
        update_enabled = bool(self.allowed_update_fields)
        capabilities = (
            Capability("transport.http", True, True, True, "stdlib/fake HTTP boundary"),
            Capability("auth.tenant_token", True, configured, auth_verified, auth_detail),
            Capability("bitable.records.read", True, True, False, read_detail),
            Capability(
                "bitable.records.update_single",
                True,
                update_enabled,
                False,
                "enabled only for explicitly allowed fields"
                if update_enabled
                else "disabled: no update field allowlist configured",
            ),
            Capability("wiki.node.read", True, True, False, read_detail),
            Capability("docx.document.read", True, True, False, read_detail),
            Capability("docx.blocks.read", True, True, False, read_detail),
            Capability(
                "api.version_discovery",
                False,
                False,
                False,
                "disabled; endpoint versions are pinned by this module",
            ),
            Capability(
                "retry.http_429",
                True,
                self.retry_policy.retry_http_429,
                False,
                "generic bounded HTTP-status retry; disabled by default",
            ),
            Capability(
                "rate_limit.provider_semantics",
                False,
                False,
                False,
                "provider quotas, Retry-After, and event semantics are unverified",
            ),
            Capability("events", False, False, False, "event semantics are not implemented"),
            Capability("transport.external_cli", False, False, False, "no CLI dependency"),
        )
        return CapabilityReport(configured, capabilities)

    def require_capability(self, name: str) -> None:
        capability = self.probe_capabilities().get(name)
        if not capability.supported or not capability.enabled:
            raise NotSupportedError(f"capability {name!r} is unavailable: {capability.detail}")

    def get_tenant_access_token(self, *, force_refresh: bool = False) -> str:
        """Acquire and cache an internal-app tenant token."""

        now = self._clock()
        token = self._token
        if not force_refresh and token is not None and token.expires_at > now:
            return token.value
        with self._token_lock:
            now = self._clock()
            token = self._token
            if not force_refresh and token is not None and token.expires_at > now:
                return token.value
            app_id, app_secret = self.credential_ref.resolve()
            envelope = self._request_json(
                "POST",
                TENANT_TOKEN_PATH,
                body={"app_id": app_id, "app_secret": app_secret},
                authenticated=False,
                retryable=True,
            )
            value = _required_str(envelope, "tenant_access_token", "tenant token response")
            expire = _required_int(envelope, "expire", "tenant token response", minimum=1)
            lifetime = max(1.0, float(expire) - min(60.0, float(expire) * 0.1))
            self._token = _Token(value, now + lifetime)
            return value

    def clear_token_cache(self) -> None:
        with self._token_lock:
            self._token = None

    def list_bitable_records(
        self,
        app_token: str,
        table_id: str,
        *,
        page_size: int = 100,
        page_token: str | None = None,
        view_id: str | None = None,
    ) -> BitableRecordPage:
        _validate_page_size(page_size)
        query: dict[str, Any] = {"page_size": page_size}
        if page_token is not None:
            query["page_token"] = _nonempty(page_token, "page_token")
        if view_id is not None:
            query["view_id"] = _nonempty(view_id, "view_id")
        data = self._request_data(
            "GET", self._records_path(app_token, table_id), query=query, retryable=True
        )
        return _parse_bitable_page(data)

    def get_bitable_record(
        self, app_token: str, table_id: str, record_id: str
    ) -> BitableRecord:
        path = self._records_path(app_token, table_id) + "/" + _segment(record_id, "record_id")
        data = self._request_data("GET", path, retryable=True)
        return _parse_bitable_record(_required_mapping(data, "record", "Bitable response"))

    def update_bitable_record(
        self,
        app_token: str,
        table_id: str,
        record_id: str,
        fields: Mapping[str, Any],
    ) -> BitableRecord:
        """Update one record and only explicitly allowlisted fields.

        Writes are not automatically retried because provider idempotency and
        conflict semantics have not been verified here.
        """

        if not self.allowed_update_fields:
            raise NotSupportedError("Bitable updates require allowed_update_fields")
        if not isinstance(fields, Mapping) or not fields:
            raise ConfigurationError("fields must be a non-empty mapping")
        if len(fields) > 100:
            raise ConfigurationError("a single update may contain at most 100 fields")
        if any(not isinstance(key, str) or not key for key in fields):
            raise ConfigurationError("Bitable field names must be non-empty strings")
        disallowed = sorted(set(fields) - self.allowed_update_fields)
        if disallowed:
            raise NotSupportedError(
                "Bitable update contains fields outside the allowlist: " + ", ".join(disallowed)
            )
        safe_fields = dict(fields)
        _validate_json_value(safe_fields, "Bitable update fields")
        path = self._records_path(app_token, table_id) + "/" + _segment(record_id, "record_id")
        data = self._request_data(
            "PUT", path, body={"fields": safe_fields}, retryable=False
        )
        return _parse_bitable_record(
            _required_mapping(data, "record", "Bitable update response")
        )

    def get_wiki_node(self, token: str, *, obj_type: str = "wiki") -> WikiNode:
        data = self._request_data(
            "GET",
            f"{WIKI_PREFIX}/spaces/get_node",
            query={"token": _nonempty(token, "token"), "obj_type": _nonempty(obj_type, "obj_type")},
            retryable=True,
        )
        return _parse_wiki_node(_required_mapping(data, "node", "wiki response"))

    def get_document(self, document_id: str) -> Document:
        data = self._request_data(
            "GET",
            f"{DOCX_PREFIX}/documents/{_segment(document_id, 'document_id')}",
            retryable=True,
        )
        return _parse_document(_required_mapping(data, "document", "document response"))

    def list_document_blocks(
        self,
        document_id: str,
        *,
        page_size: int = 100,
        page_token: str | None = None,
        document_revision_id: int | None = None,
    ) -> DocumentBlockPage:
        _validate_page_size(page_size)
        query: dict[str, Any] = {"page_size": page_size}
        if page_token is not None:
            query["page_token"] = _nonempty(page_token, "page_token")
        if document_revision_id is not None:
            if (
                isinstance(document_revision_id, bool)
                or not isinstance(document_revision_id, int)
                or document_revision_id < 0
            ):
                raise ConfigurationError("document_revision_id must be a non-negative integer")
            query["document_revision_id"] = document_revision_id
        data = self._request_data(
            "GET",
            f"{DOCX_PREFIX}/documents/{_segment(document_id, 'document_id')}/blocks",
            query=query,
            retryable=True,
        )
        return _parse_document_block_page(data)

    def subscribe_events(self, *_args: Any, **_kwargs: Any) -> None:
        raise NotSupportedError("Feishu event semantics are not implemented")

    def _records_path(self, app_token: str, table_id: str) -> str:
        return (
            f"{BITABLE_PREFIX}/apps/{_segment(app_token, 'app_token')}"
            f"/tables/{_segment(table_id, 'table_id')}/records"
        )

    def _request_data(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, Any] | None = None,
        body: Mapping[str, Any] | None = None,
        retryable: bool,
    ) -> Mapping[str, Any]:
        envelope = self._request_json(
            method,
            path,
            query=query,
            body=body,
            authenticated=True,
            retryable=retryable,
        )
        return _required_mapping(envelope, "data", "Feishu API response")

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        query: Mapping[str, Any] | None = None,
        body: Mapping[str, Any] | None = None,
        authenticated: bool,
        retryable: bool,
    ) -> Mapping[str, Any]:
        method = method.upper()
        if method not in {"GET", "POST", "PUT"}:
            raise NotSupportedError(f"HTTP method {method!r} is not supported")
        if not path.startswith("/open-apis/") or ".." in path:
            raise ConfigurationError("Feishu API path is invalid")

        url = self.base_url + path
        if query:
            safe_query: dict[str, str | int] = {}
            for key, value in query.items():
                if not isinstance(key, str) or not key:
                    raise ConfigurationError("query names must be non-empty strings")
                if not isinstance(value, (str, int)) or isinstance(value, bool):
                    raise ConfigurationError(f"query parameter {key!r} has an invalid type")
                safe_query[key] = value
            url += "?" + urllib.parse.urlencode(safe_query)

        headers = {"Accept": "application/json", "User-Agent": "OPC-Feishu-Transport/1"}
        encoded_body = None
        if body is not None:
            _validate_json_value(body, "request body")
            encoded_body = json.dumps(
                body, ensure_ascii=True, separators=(",", ":"), allow_nan=False
            ).encode("utf-8")
            headers["Content-Type"] = "application/json; charset=utf-8"
        if authenticated:
            headers["Authorization"] = "Bearer " + self.get_tenant_access_token()

        response = self._send_with_retry(
            HttpRequest(method, url, headers, encoded_body, self.timeout),
            retryable=retryable,
        )
        payload = _decode_json_response(response)
        code = _required_int(payload, "code", "Feishu API envelope")
        message = payload.get("msg", "")
        if not isinstance(message, str):
            raise ResponseValidationError("Feishu API envelope.msg must be a string")
        if code != 0:
            raise ApiError(
                message or "Feishu API request failed",
                code=code,
                status=response.status,
                request_id=_request_id(response.headers),
            )
        return payload

    def _send_with_retry(self, request: HttpRequest, *, retryable: bool) -> HttpResponse:
        for attempt in range(1, self.retry_policy.max_attempts + 1):
            try:
                response = self.transport.send(request)
            except TransportError:
                if not retryable or attempt >= self.retry_policy.max_attempts:
                    raise
                self._sleep(self.retry_policy.delay(attempt))
                continue
            _validate_http_response(response)
            if 200 <= response.status < 300:
                return response
            retry_status = response.status in {500, 502, 503, 504} or (
                response.status == 429 and self.retry_policy.retry_http_429
            )
            if retryable and retry_status and attempt < self.retry_policy.max_attempts:
                self._sleep(self.retry_policy.delay(attempt))
                continue
            raise _http_api_error(response)
        raise AssertionError("retry loop exhausted unexpectedly")


class FakeHttpTransport:
    """FIFO fake for deterministic tests; never opens a network connection."""

    def __init__(self, responses: Sequence[HttpResponse | Exception]) -> None:
        self._responses = list(responses)
        self.requests: list[HttpRequest] = []

    def send(self, request: HttpRequest) -> HttpResponse:
        self.requests.append(request)
        if not self._responses:
            raise AssertionError("fake HTTP transport has no queued response")
        result = self._responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def assert_drained(self) -> None:
        if self._responses:
            raise AssertionError(f"fake HTTP transport has {len(self._responses)} unused responses")


def _validate_http_response(response: Any) -> None:
    if not isinstance(response, HttpResponse):
        raise ResponseValidationError("HTTP transport returned an invalid response object")
    if isinstance(response.status, bool) or not isinstance(response.status, int) or not 100 <= response.status <= 599:
        raise ResponseValidationError("HTTP response status is invalid")
    if not isinstance(response.headers, Mapping):
        raise ResponseValidationError("HTTP response headers must be a mapping")
    if any(not isinstance(k, str) or not isinstance(v, str) for k, v in response.headers.items()):
        raise ResponseValidationError("HTTP response headers must contain strings")
    if not isinstance(response.body, bytes):
        raise ResponseValidationError("HTTP response body must be bytes")
    if len(response.body) > _MAX_RESPONSE_BYTES:
        raise ResponseValidationError("Feishu response exceeded the size limit")


def _decode_json_response(response: HttpResponse) -> Mapping[str, Any]:
    content_type = _header(response.headers, "content-type")
    if content_type is not None and not content_type.lower().startswith("application/json"):
        raise ResponseValidationError("Feishu response Content-Type is not JSON")
    try:
        decoded = response.body.decode("utf-8")
        payload = json.loads(decoded)
    except UnicodeDecodeError as exc:
        raise ResponseValidationError("Feishu response is not valid UTF-8") from exc
    except (json.JSONDecodeError, ValueError) as exc:
        raise ResponseValidationError("Feishu response is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise ResponseValidationError("Feishu response root must be an object")
    _validate_json_value(payload, "response")
    return payload


def _http_api_error(response: HttpResponse) -> ApiError:
    code: int | str | None = None
    message = f"Feishu HTTP request failed with status {response.status}"
    if response.body:
        try:
            payload = _decode_json_response(response)
        except ResponseValidationError:
            payload = None
        if payload is not None:
            raw_code = payload.get("code")
            if isinstance(raw_code, (int, str)) and not isinstance(raw_code, bool):
                code = raw_code
            raw_message = payload.get("msg") or payload.get("message")
            if isinstance(raw_message, str) and raw_message:
                message = raw_message
    return ApiError(
        message,
        code=code,
        status=response.status,
        request_id=_request_id(response.headers),
    )


def _header(headers: Mapping[str, str], name: str) -> str | None:
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value
    return None


def _request_id(headers: Mapping[str, str]) -> str | None:
    return _header(headers, "x-tt-logid") or _header(headers, "x-request-id")


def _validate_json_value(value: Any, context: str, *, _depth: int = 0) -> None:
    if _depth > _MAX_JSON_DEPTH:
        raise ResponseValidationError(f"{context} exceeds the JSON nesting limit")
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ResponseValidationError(f"{context} contains a non-finite number")
        return
    if isinstance(value, Mapping):
        if len(value) > _MAX_COLLECTION_ITEMS:
            raise ResponseValidationError(f"{context} contains too many object entries")
        for key, child in value.items():
            if not isinstance(key, str):
                raise ResponseValidationError(f"{context} contains a non-string object key")
            _validate_json_value(child, context, _depth=_depth + 1)
        return
    if isinstance(value, (list, tuple)):
        if len(value) > _MAX_COLLECTION_ITEMS:
            raise ResponseValidationError(f"{context} contains too many array entries")
        for child in value:
            _validate_json_value(child, context, _depth=_depth + 1)
        return
    raise ResponseValidationError(f"{context} contains unsupported type {type(value).__name__}")


def _required_mapping(value: Mapping[str, Any], key: str, context: str) -> Mapping[str, Any]:
    result = value.get(key)
    if not isinstance(result, dict):
        raise ResponseValidationError(f"{context}.{key} must be an object")
    return result


def _required_str(value: Mapping[str, Any], key: str, context: str) -> str:
    result = value.get(key)
    if not isinstance(result, str) or not result:
        raise ResponseValidationError(f"{context}.{key} must be a non-empty string")
    return result


def _optional_str(value: Mapping[str, Any], key: str, context: str) -> str | None:
    result = value.get(key)
    if result is None:
        return None
    if not isinstance(result, str):
        raise ResponseValidationError(f"{context}.{key} must be a string or null")
    return result


def _required_int(
    value: Mapping[str, Any], key: str, context: str, *, minimum: int | None = None
) -> int:
    result = value.get(key)
    if isinstance(result, bool) or not isinstance(result, int):
        raise ResponseValidationError(f"{context}.{key} must be an integer")
    if minimum is not None and result < minimum:
        raise ResponseValidationError(f"{context}.{key} must be at least {minimum}")
    return result


def _optional_int(
    value: Mapping[str, Any], key: str, context: str, *, minimum: int | None = None
) -> int | None:
    result = value.get(key)
    if result is None:
        return None
    if isinstance(result, bool) or not isinstance(result, int):
        raise ResponseValidationError(f"{context}.{key} must be an integer or null")
    if minimum is not None and result < minimum:
        raise ResponseValidationError(f"{context}.{key} must be at least {minimum}")
    return result


def _parse_bitable_record(value: Mapping[str, Any]) -> BitableRecord:
    record_id = _required_str(value, "record_id", "Bitable record")
    fields = _required_mapping(value, "fields", "Bitable record")
    _validate_json_value(fields, "Bitable record.fields")
    return BitableRecord(record_id, dict(fields))


def _parse_bitable_page(data: Mapping[str, Any]) -> BitableRecordPage:
    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        raise ResponseValidationError("Bitable page.items must be an array")
    items = []
    for index, item in enumerate(raw_items):
        if not isinstance(item, dict):
            raise ResponseValidationError(f"Bitable page.items[{index}] must be an object")
        items.append(_parse_bitable_record(item))
    has_more = data.get("has_more")
    if not isinstance(has_more, bool):
        raise ResponseValidationError("Bitable page.has_more must be a boolean")
    page_token = _optional_str(data, "page_token", "Bitable page")
    if has_more and not page_token:
        raise ResponseValidationError("Bitable page requires page_token when has_more is true")
    total = _optional_int(data, "total", "Bitable page", minimum=0)
    return BitableRecordPage(tuple(items), has_more, page_token, total)


def _parse_wiki_node(node: Mapping[str, Any]) -> WikiNode:
    _validate_json_value(node, "wiki node")
    return WikiNode(
        _required_str(node, "node_token", "wiki node"),
        _required_str(node, "obj_token", "wiki node"),
        _required_str(node, "obj_type", "wiki node"),
        _optional_str(node, "title", "wiki node"),
        dict(node),
    )


def _parse_document(document: Mapping[str, Any]) -> Document:
    _validate_json_value(document, "document")
    return Document(
        _required_str(document, "document_id", "document"),
        _optional_int(document, "revision_id", "document", minimum=0),
        _required_str(document, "title", "document"),
        dict(document),
    )


def _parse_document_block(block: Mapping[str, Any]) -> DocumentBlock:
    _validate_json_value(block, "document block")
    raw_children = block.get("children", [])
    if not isinstance(raw_children, list) or any(
        not isinstance(item, str) or not item for item in raw_children
    ):
        raise ResponseValidationError("document block.children must be an array of strings")
    return DocumentBlock(
        _required_str(block, "block_id", "document block"),
        _required_int(block, "block_type", "document block", minimum=1),
        _optional_str(block, "parent_id", "document block"),
        tuple(raw_children),
        dict(block),
    )


def _parse_document_block_page(data: Mapping[str, Any]) -> DocumentBlockPage:
    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        raise ResponseValidationError("document block page.items must be an array")
    items = []
    for index, item in enumerate(raw_items):
        if not isinstance(item, dict):
            raise ResponseValidationError(f"document block page.items[{index}] must be an object")
        items.append(_parse_document_block(item))
    has_more = data.get("has_more", False)
    if not isinstance(has_more, bool):
        raise ResponseValidationError("document block page.has_more must be a boolean")
    page_token = _optional_str(data, "page_token", "document block page")
    if has_more and not page_token:
        raise ResponseValidationError(
            "document block page requires page_token when has_more is true"
        )
    return DocumentBlockPage(tuple(items), has_more, page_token)


def _segment(value: str, label: str) -> str:
    return urllib.parse.quote(_nonempty(value, label), safe="")


def _nonempty(value: str, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{label} must be a non-empty string")
    if len(value) > 1024:
        raise ConfigurationError(f"{label} is too long")
    return value


def _validate_page_size(page_size: int) -> None:
    # Local safety bound, not a claim about the provider's maximum.
    if isinstance(page_size, bool) or not isinstance(page_size, int) or not 1 <= page_size <= 100:
        raise ConfigurationError("page_size must be an integer between 1 and 100")


def _json_response(payload: Mapping[str, Any], status: int = 200) -> HttpResponse:
    return HttpResponse(
        status,
        {"Content-Type": "application/json; charset=utf-8"},
        json.dumps(payload, ensure_ascii=True).encode("utf-8"),
    )


def selftest() -> int:
    """Exercise contracts using only fake HTTP responses."""

    env_names = ("OPC_FEISHU_TEST_APP_ID", "OPC_FEISHU_TEST_APP_SECRET")
    previous = {name: os.environ.get(name) for name in env_names}
    os.environ[env_names[0]] = "fixture-app-id"
    os.environ[env_names[1]] = "fixture-app-secret"
    ref = CredentialRef(*env_names)
    token = {"code": 0, "msg": "ok", "tenant_access_token": "fixture-token", "expire": 7200}
    try:
        fake = FakeHttpTransport(
            [
                _json_response(token),
                _json_response({"code": 0, "msg": "ok", "data": {
                    "items": [{"record_id": "rec-1", "fields": {"Status": "Open"}}],
                    "has_more": False, "total": 1,
                }}),
                _json_response({"code": 0, "msg": "ok", "data": {
                    "record": {"record_id": "rec-1", "fields": {"Status": "Done"}}
                }}),
                _json_response({"code": 0, "msg": "ok", "data": {"node": {
                    "node_token": "wikcn1", "obj_token": "doccn1",
                    "obj_type": "docx", "title": "Fixture",
                }}}),
                _json_response({"code": 0, "msg": "ok", "data": {"document": {
                    "document_id": "doccn1", "revision_id": 2, "title": "Fixture",
                }}}),
                _json_response({"code": 0, "msg": "ok", "data": {
                    "items": [{"block_id": "blk1", "block_type": 1, "children": ["blk2"]}],
                    "has_more": False,
                }}),
            ]
        )
        client = FeishuClient(
            credential_ref=ref,
            transport=fake,
            allowed_update_fields=("Status",),
            sleep=lambda _delay: None,
        )
        page = client.list_bitable_records("app/unsafe", "table id")
        assert page.items[0].record_id == "rec-1" and page.total == 1
        updated = client.update_bitable_record(
            "app/unsafe", "table id", "rec-1", {"Status": "Done"}
        )
        assert updated.fields["Status"] == "Done"
        assert client.get_wiki_node("wikcn1").obj_token == "doccn1"
        assert client.get_document("doccn1").revision_id == 2
        assert client.list_document_blocks("doccn1").items[0].children == ("blk2",)
        assert client.probe_capabilities(check_auth=True).get("auth.tenant_token").verified
        assert client.probe_capabilities().get("events").supported is False
        assert len([r for r in fake.requests if TENANT_TOKEN_PATH in r.url]) == 1
        assert "app%2Funsafe" in fake.requests[1].url and "table%20id" in fake.requests[1].url
        assert fake.requests[2].method == "PUT"
        fake.assert_drained()

        try:
            client.update_bitable_record("app", "table", "record", {"Owner": "x"})
        except NotSupportedError:
            pass
        else:
            raise AssertionError("field allowlist was not enforced")

        retry_fake = FakeHttpTransport([
            _json_response(token),
            _json_response({"code": 999, "msg": "temporary"}, status=503),
            _json_response({"code": 0, "msg": "ok", "data": {
                "items": [], "has_more": False, "total": 0,
            }}),
        ])
        retry_client = FeishuClient(
            credential_ref=ref, transport=retry_fake, sleep=lambda _delay: None
        )
        assert retry_client.list_bitable_records("app", "table").items == ()
        assert len(retry_fake.requests) == 3

        write_fake = FakeHttpTransport([
            _json_response(token),
            _json_response({"code": 999, "msg": "failed"}, status=503),
        ])
        write_client = FeishuClient(
            credential_ref=ref,
            transport=write_fake,
            allowed_update_fields=("Status",),
            sleep=lambda _delay: None,
        )
        try:
            write_client.update_bitable_record("app", "table", "record", {"Status": "Done"})
        except ApiError as exc:
            assert exc.status == 503
        else:
            raise AssertionError("failed write did not raise ApiError")
        assert len(write_fake.requests) == 2

        malformed_fake = FakeHttpTransport([
            _json_response(token),
            _json_response({"code": 0, "msg": "ok", "data": {
                "items": "not-an-array", "has_more": False,
            }}),
        ])
        malformed_client = FeishuClient(
            credential_ref=ref, transport=malformed_fake, sleep=lambda _delay: None
        )
        try:
            malformed_client.list_bitable_records("app", "table")
        except ResponseValidationError:
            pass
        else:
            raise AssertionError("malformed response crossed the boundary")

        try:
            client.subscribe_events()
        except NotSupportedError:
            pass
        else:
            raise AssertionError("unsupported event semantics were enabled")
    finally:
        for name, value in previous.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value

    print("[ok] Feishu transport selftest passed (fake HTTP only)")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Feishu HTTP transport utilities")
    parser.add_argument(
        "--selftest", action="store_true", help="run offline tests with fake HTTP responses"
    )
    args = parser.parse_args(argv)
    if args.selftest:
        return selftest()
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
