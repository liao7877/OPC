"""OPC Connector wrapper around the defensive Feishu HTTP client."""
from __future__ import annotations

import hashlib
import json
import threading
from typing import Mapping

from opc_integrations import (
    AuthenticationConnectorError,
    Capabilities,
    Connector,
    PermanentConnectorError,
    RetryableConnectorError,
    ValidationConnectorError,
)
from integrations.feishu import (
    ApiError,
    ConfigurationError,
    FeishuClient,
    ResponseValidationError,
    TransportError,
)


class FeishuBitableConnector(Connector):
    """One-table connector. Writes are serialized and field-allowlisted."""

    capabilities = Capabilities(
        pull=True, push=True, delete=False, idempotency=False,
        optimistic_versioning=True,
        ordered_versions=False,
    )

    def __init__(self, client: FeishuClient, app_token: str, table_id: str,
                 field_map: Mapping[str, str] | None = None):
        self.client = client
        self.app_token = app_token
        self.table_id = table_id
        self.field_map = dict(field_map or {})
        self._write_lock = threading.Lock()

    @staticmethod
    def _version(fields):
        raw = json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _normalize(self, fields):
        return {local: fields.get(remote) for local, remote in self.field_map.items()} if self.field_map else dict(fields)

    def _externalize(self, fields):
        reverse = {local: remote for local, remote in self.field_map.items()}
        return {reverse.get(name, name): value for name, value in fields.items()}

    def _translate(self, exc):
        if isinstance(exc, ConfigurationError):
            return AuthenticationConnectorError(str(exc))
        if isinstance(exc, (ResponseValidationError, ValueError, TypeError)):
            return ValidationConnectorError(str(exc))
        if isinstance(exc, TransportError):
            return RetryableConnectorError(str(exc))
        if isinstance(exc, ApiError):
            if exc.status in (401, 403):
                return AuthenticationConnectorError(str(exc))
            if exc.status in (500, 502, 503, 504):
                return RetryableConnectorError(str(exc))
            return PermanentConnectorError(str(exc))
        return PermanentConnectorError(str(exc))

    def pull(self, external_id):
        try:
            record = self.client.get_bitable_record(self.app_token, self.table_id, external_id)
        except ApiError as exc:
            if str(exc.code) == "1254043" or exc.status == 404:
                return None
            raise self._translate(exc) from exc
        except Exception as exc:
            raise self._translate(exc) from exc
        fields = self._normalize(record.fields)
        return {"external_id": record.record_id, "fields": fields,
                "version": self._version(fields), "deleted": False}

    def push(self, external_id, fields, expected_version, idempotency_key):
        del idempotency_key
        with self._write_lock:
            current = self.pull(external_id)
            if expected_version is not None and current["version"] != str(expected_version):
                from opc_integrations import VersionConflictError
                raise VersionConflictError("Feishu record changed before update")
            try:
                record = self.client.update_bitable_record(
                    self.app_token, self.table_id, external_id,
                    self._externalize(fields),
                )
            except Exception as exc:
                raise self._translate(exc) from exc
            normalized = dict(current["fields"])
            normalized.update(self._normalize(record.fields))
            return {"external_id": record.record_id, "fields": normalized,
                    "version": self._version(normalized), "deleted": False}

    def delete(self, external_id, expected_version, idempotency_key):
        del external_id, expected_version, idempotency_key
        raise PermanentConnectorError("Feishu delete is disabled by OPC policy")
