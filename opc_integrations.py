#!/usr/bin/env python3
"""Connector contracts and data models for OPC Level 3 synchronization."""

from __future__ import annotations

import copy
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from typing import Any, Mapping


@dataclass(frozen=True)
class Capabilities:
    pull: bool = True
    push: bool = True
    delete: bool = False
    idempotency: bool = True
    optimistic_versioning: bool = True
    ordered_versions: bool = False


@dataclass(frozen=True)
class ExternalConnection:
    connection_id: str
    connector_type: str
    enabled: bool = True
    config: Mapping[str, Any] = field(default_factory=dict)
    capabilities: Capabilities = field(default_factory=Capabilities)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        data = dict(value)
        data["capabilities"] = Capabilities(**data.get("capabilities", {}))
        return cls(**data)


@dataclass(frozen=True)
class FieldPolicy:
    default_authority: str = "local"
    authorities: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self):
        valid = {"local", "external"}
        if self.default_authority not in valid:
            raise ValueError("default_authority must be local or external")
        if any(value not in valid for value in self.authorities.values()):
            raise ValueError("field authority must be local or external")

    def authority_for(self, field_name):
        return self.authorities.get(field_name, self.default_authority)

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class Binding:
    binding_id: str
    connection_id: str
    local_id: str
    external_id: str
    entity_type: str = "task"
    external_ref: Mapping[str, Any] = field(default_factory=dict)
    display_fields: tuple[str, ...] = ("title", "status", "due")
    field_policy: FieldPolicy = field(default_factory=FieldPolicy)
    delete_authority: str = "local"
    enabled: bool = True

    def __post_init__(self):
        if self.delete_authority not in {"local", "external"}:
            raise ValueError("delete_authority must be local or external")

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, value):
        data = dict(value)
        data["field_policy"] = FieldPolicy(**data.get("field_policy", {}))
        data["display_fields"] = tuple(data.get("display_fields", ("title", "status", "due")))
        return cls(**data)


@dataclass(frozen=True)
class ExternalShadow:
    binding_id: str
    external_id: str
    fields: Mapping[str, Any]
    external_version: str
    deleted: bool = False
    observed_at: str = ""

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class SyncEvent:
    event_id: str
    binding_id: str
    operation: str
    direction: str
    status: str
    idempotency_key: str
    occurred_at: str
    local_version: int | None = None
    external_version: str | None = None
    error_class: str | None = None
    message: str = ""

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class Conflict:
    conflict_id: str
    binding_id: str
    kind: str
    local_version: int | None
    external_version: str | None
    fields: tuple[str, ...]
    detected_at: str
    message: str = ""
    resolved: bool = False

    def to_dict(self):
        value = asdict(self)
        value["fields"] = list(self.fields)
        return value


@dataclass(frozen=True)
class Tombstone:
    tombstone_id: str
    binding_id: str
    local_id: str
    external_id: str
    origin: str
    version: str
    deleted_at: str
    propagated: bool = False

    def to_dict(self):
        return asdict(self)


class ConnectorError(RuntimeError):
    error_class = "permanent"
    retryable = False


class RetryableConnectorError(ConnectorError):
    error_class = "retryable"
    retryable = True


class AuthenticationConnectorError(ConnectorError):
    error_class = "authentication"


class ValidationConnectorError(ConnectorError):
    error_class = "validation"


class PermanentConnectorError(ConnectorError):
    error_class = "permanent"


class VersionConflictError(ConnectorError):
    error_class = "version_conflict"


class Connector(ABC):
    capabilities = Capabilities()

    @abstractmethod
    def pull(self, external_id):
        """Return ExternalShadow-like data or None when the record is absent."""

    @abstractmethod
    def push(self, external_id, fields, expected_version, idempotency_key):
        """Create or update an external record and return its representation."""

    @abstractmethod
    def delete(self, external_id, expected_version, idempotency_key):
        """Delete an external record and return its resulting version."""


class FakeConnector(Connector):
    """Deterministic in-memory connector for tests and offline development."""

    def __init__(self, capabilities=None):
        self.capabilities = capabilities or Capabilities()
        self._records = {}
        self._idempotent_results = {}
        self._failures = {}
        self.mutation_count = 0

    def seed(self, external_id, fields, version=1, deleted=False):
        self._records[external_id] = {
            "external_id": external_id,
            "fields": copy.deepcopy(dict(fields)),
            "version": str(version),
            "deleted": bool(deleted),
        }

    def get(self, external_id):
        record = self._records.get(external_id)
        if not record or record["deleted"]:
            return None
        return copy.deepcopy(record)

    def inject_failure(self, operation, error, count=1):
        self._failures.setdefault(operation, []).extend(
            copy.copy(error) for _unused in range(count)
        )

    def _raise_failure(self, operation):
        failures = self._failures.get(operation, [])
        if failures:
            raise failures.pop(0)

    def pull(self, external_id):
        self._raise_failure("pull")
        record = self._records.get(external_id)
        return copy.deepcopy(record) if record else None

    def push(self, external_id, fields, expected_version, idempotency_key):
        self._raise_failure("push")
        if idempotency_key in self._idempotent_results:
            return copy.deepcopy(self._idempotent_results[idempotency_key])
        current = self._records.get(external_id)
        current_version = current["version"] if current and not current["deleted"] else None
        expected = None if expected_version is None else str(expected_version)
        if self.capabilities.optimistic_versioning and current_version != expected:
            raise VersionConflictError(
                "expected external version %r, found %r" % (expected, current_version)
            )
        next_version = str(int(current_version or "0") + 1)
        result = {
            "external_id": external_id,
            "fields": copy.deepcopy(dict(fields)),
            "version": next_version,
            "deleted": False,
        }
        self._records[external_id] = copy.deepcopy(result)
        self._idempotent_results[idempotency_key] = copy.deepcopy(result)
        self.mutation_count += 1
        self._raise_failure("push_after")
        return result

    def delete(self, external_id, expected_version, idempotency_key):
        self._raise_failure("delete")
        if idempotency_key in self._idempotent_results:
            return copy.deepcopy(self._idempotent_results[idempotency_key])
        current = self._records.get(external_id)
        current_version = current["version"] if current and not current["deleted"] else None
        expected = None if expected_version is None else str(expected_version)
        if self.capabilities.optimistic_versioning and current_version != expected:
            raise VersionConflictError(
                "expected external version %r, found %r" % (expected, current_version)
            )
        next_version = str(int(current_version or expected or "0") + 1)
        result = {"external_id": external_id, "version": next_version, "deleted": True}
        self._records[external_id] = {
            "external_id": external_id,
            "fields": {},
            "version": next_version,
            "deleted": True,
        }
        self._idempotent_results[idempotency_key] = copy.deepcopy(result)
        self.mutation_count += 1
        self._raise_failure("delete_after")
        return result


__all__ = [
    "AuthenticationConnectorError",
    "Binding",
    "Capabilities",
    "Conflict",
    "Connector",
    "ConnectorError",
    "ExternalConnection",
    "ExternalShadow",
    "FakeConnector",
    "FieldPolicy",
    "PermanentConnectorError",
    "RetryableConnectorError",
    "SyncEvent",
    "Tombstone",
    "ValidationConnectorError",
    "VersionConflictError",
]
