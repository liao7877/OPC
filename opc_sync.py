#!/usr/bin/env python3
"""Platform-neutral OPC Level 3 synchronization kernel."""

from __future__ import annotations

import copy
import hashlib
import json
import time
import uuid
from pathlib import Path

import opc_model
from opc_integrations import (
    Binding,
    Conflict,
    ConnectorError,
    ExternalConnection,
    FakeConnector,
    SyncEvent,
    Tombstone,
    VersionConflictError,
)

SCHEMA_VERSION = 1


def _utc_now():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _stable_key(*parts):
    payload = json.dumps(parts, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def _version_order(value):
    text = "" if value is None else str(value)
    try:
        return 0, int(text)
    except ValueError:
        return 1, text


def _read_json(path, default):
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value
    except FileNotFoundError:
        return copy.deepcopy(default)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("cannot read sync state %s: %s" % (path, exc)) from exc


def _write_json(path, value):
    text = json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True) + "\n"
    opc_model.atomic_write(str(path), text)


def _capability(connection, connector, name):
    declared = getattr(connection.capabilities, name)
    implemented = getattr(getattr(connector, "capabilities", connection.capabilities), name)
    return declared and implemented


def register_configured_connectors(kernel):
    """Instantiate supported connectors from persisted non-secret connection config."""
    state = kernel.snapshot()
    for connection_id, raw in state["connections"].items():
        connection = ExternalConnection.from_dict(raw)
        if connection.connector_type == "fake":
            continue
        if connection.connector_type not in ("feishu-bitable", "feishu-knowledge"):
            continue
        config = dict(connection.config)
        from integrations.feishu import CredentialRef, FeishuClient
        from integrations.feishu_connector import FeishuBitableConnector
        credential = CredentialRef(
            app_id_env=config.get("app_id_env", "FEISHU_APP_ID"),
            app_secret_env=config.get("app_secret_env", "FEISHU_APP_SECRET"),
        )
        if connection.connector_type == "feishu-knowledge":
            from integrations.feishu_knowledge_connector import FeishuDocumentConnector
            kernel.register_connector(
                connection_id,
                FeishuDocumentConnector(FeishuClient(credential_ref=credential),
                                        resource_kind=config.get("resource_kind", "wiki")),
            )
            continue
        app_token = config.get("app_token")
        table_id = config.get("table_id")
        if not app_token or not table_id:
            raise ValueError("feishu-bitable connection requires app_token and table_id")
        allowed = tuple(config.get("allowed_update_fields") or ())
        field_map = config.get("field_map") or {}
        client = FeishuClient(
            credential_ref=credential,
            allowed_update_fields=tuple(field_map.get(name, name) for name in allowed),
        )
        kernel.register_connector(
            connection_id,
            FeishuBitableConnector(client, app_token, table_id, field_map=field_map),
        )


def apply_config(kernel, config):
    """Apply reviewed non-secret connection/binding declarations."""
    if not isinstance(config, dict):
        raise ValueError("integration config must be an object")
    for raw in config.get("connections") or []:
        connection = ExternalConnection.from_dict(raw)
        connector = FakeConnector() if connection.connector_type == "fake" else None
        if connector is None:
            with opc_model.file_lock(str(kernel.lock_path)):
                state = kernel._load_state()
                state["connections"][connection.connection_id] = connection.to_dict()
                kernel._save_state(state)
        else:
            kernel.register_connection(connection, connector)
    for raw in config.get("bindings") or []:
        kernel.add_binding(Binding.from_dict(raw))
    register_configured_connectors(kernel)


class SyncKernel:
    """Persistent connector-neutral synchronization coordinator."""

    def __init__(self, root, retry_delays=(0.1, 0.5, 1.0), sleep=time.sleep):
        self.root = Path(root).resolve()
        self.data_dir = self.root / ".opc-sync"
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.data_dir / "state.json"
        self.events_path = self.data_dir / "events.jsonl"
        self.lock_path = self.data_dir / "kernel"
        self.retry_delays = tuple(float(delay) for delay in retry_delays)
        self.sleep = sleep
        self._connectors = {}
        if not self.state_path.exists():
            with opc_model.file_lock(str(self.lock_path)):
                if not self.state_path.exists():
                    _write_json(self.state_path, self._empty_state())

    @staticmethod
    def _empty_state():
        return {
            "schema_version": SCHEMA_VERSION,
            "connections": {},
            "bindings": {},
            "locals": {},
            "shadows": {},
            "conflicts": {},
            "tombstones": {},
            "idempotency": {},
        }

    def _load_state(self):
        state = _read_json(self.state_path, self._empty_state())
        if state.get("schema_version") != SCHEMA_VERSION:
            raise RuntimeError("unsupported sync state schema")
        return state

    def _save_state(self, state):
        _write_json(self.state_path, state)

    def _append_event(self, event):
        line = json.dumps(event.to_dict(), ensure_ascii=True, sort_keys=True) + "\n"
        with opc_model.file_lock(str(self.events_path)):
            with self.events_path.open("a", encoding="utf-8", newline="") as handle:
                handle.write(line)
                handle.flush()

    def _event(self, binding, operation, direction, status, key, local_version=None,
               external_version=None, error_class=None, message=""):
        event = SyncEvent(
            event_id=uuid.uuid4().hex,
            binding_id=binding.binding_id,
            operation=operation,
            direction=direction,
            status=status,
            idempotency_key=key,
            occurred_at=_utc_now(),
            local_version=local_version,
            external_version=None if external_version is None else str(external_version),
            error_class=error_class,
            message=str(message),
        )
        self._append_event(event)
        return event

    def snapshot(self):
        """Return a copy safe for dashboards, patrol, and read-only APIs."""
        return copy.deepcopy(self._load_state())

    def write_projection(self, path):
        state = self.snapshot()
        safe_connections = {
            key: {"connection_id": key, "connector_type": value.get("connector_type"),
                  "enabled": bool(value.get("enabled", True))}
            for key, value in state["connections"].items()
        }
        safe_bindings, safe_shadows = {}, {}
        for binding_id, value in state["bindings"].items():
            binding = Binding.from_dict(value)
            safe_bindings[binding_id] = {
                "binding_id": binding_id, "connection_id": binding.connection_id,
                "local_id": binding.local_id, "external_id": binding.external_id,
                "entity_type": binding.entity_type,
            }
            shadow = state["shadows"].get(binding_id)
            if shadow:
                safe_shadows[binding_id] = {
                    key: copy.deepcopy(shadow.get(key)) for key in
                    ("binding_id", "external_id", "external_version", "deleted", "observed_at")
                }
                safe_shadows[binding_id]["fields"] = {
                    name: copy.deepcopy(shadow.get("fields", {}).get(name))
                    for name in binding.display_fields if name in shadow.get("fields", {})
                }
        projection = {
            "schema_version": state["schema_version"],
            "connections": safe_connections,
            "bindings": safe_bindings,
            "shadows": safe_shadows,
            "conflicts": state["conflicts"],
            "tombstones": state["tombstones"],
            "events_tail": self.list_events()[-100:],
        }
        _write_json(Path(path), projection)
        return projection

    def register_connection(self, connection, connector):
        if not isinstance(connection, ExternalConnection):
            raise TypeError("connection must be ExternalConnection")
        with opc_model.file_lock(str(self.lock_path)):
            state = self._load_state()
            state["connections"][connection.connection_id] = connection.to_dict()
            self._save_state(state)
        self._connectors[connection.connection_id] = connector

    def register_connector(self, connection_id, connector):
        state = self._load_state()
        if connection_id not in state["connections"]:
            raise KeyError("unknown connection: %s" % connection_id)
        self._connectors[connection_id] = connector

    def add_binding(self, binding):
        if not isinstance(binding, Binding):
            raise TypeError("binding must be Binding")
        with opc_model.file_lock(str(self.lock_path)):
            state = self._load_state()
            if binding.connection_id not in state["connections"]:
                raise KeyError("unknown connection: %s" % binding.connection_id)
            state["bindings"][binding.binding_id] = binding.to_dict()
            self._save_state(state)

    def put_local(self, local_id, fields, expected_version=None):
        with opc_model.file_lock(str(self.lock_path)):
            state = self._load_state()
            current = state["locals"].get(local_id)
            current_version = current["version"] if current else None
            if expected_version is not None and current_version != expected_version:
                raise VersionConflictError(
                    "expected local version %r, found %r" % (expected_version, current_version)
                )
            version = int(current_version or 0) + 1
            state["locals"][local_id] = {
                "local_id": local_id,
                "fields": copy.deepcopy(dict(fields)),
                "version": version,
                "deleted": False,
                "updated_at": _utc_now(),
            }
            self._save_state(state)
            return copy.deepcopy(state["locals"][local_id])

    def delete_local(self, local_id, expected_version=None):
        with opc_model.file_lock(str(self.lock_path)):
            state = self._load_state()
            current = state["locals"].get(local_id)
            current_version = current["version"] if current else None
            if expected_version is not None and current_version != expected_version:
                raise VersionConflictError(
                    "expected local version %r, found %r" % (expected_version, current_version)
                )
            version = int(current_version or 0) + 1
            state["locals"][local_id] = {
                "local_id": local_id,
                "fields": copy.deepcopy((current or {}).get("fields", {})),
                "version": version,
                "deleted": True,
                "updated_at": _utc_now(),
            }
            self._save_state(state)
            return copy.deepcopy(state["locals"][local_id])

    def get_local(self, local_id):
        return copy.deepcopy(self._load_state()["locals"].get(local_id))

    def list_conflicts(self):
        return list(copy.deepcopy(self._load_state()["conflicts"]).values())

    def list_tombstones(self):
        return list(copy.deepcopy(self._load_state()["tombstones"]).values())

    def list_events(self):
        events = []
        try:
            with self.events_path.open("r", encoding="utf-8") as handle:
                for line in handle:
                    if line.strip():
                        events.append(json.loads(line))
        except FileNotFoundError:
            pass
        return events

    def _call(self, operation, function, max_attempts):
        attempts = max(1, int(max_attempts))
        for attempt in range(attempts):
            try:
                return function()
            except ConnectorError as exc:
                if not exc.retryable or attempt + 1 >= attempts:
                    raise
                delay = self.retry_delays[min(attempt, len(self.retry_delays) - 1)] if self.retry_delays else 0
                if delay:
                    self.sleep(delay)
            except (TimeoutError, ConnectionError, OSError) as exc:
                if attempt + 1 >= attempts:
                    from opc_integrations import RetryableConnectorError
                    raise RetryableConnectorError(str(exc)) from exc
                delay = self.retry_delays[min(attempt, len(self.retry_delays) - 1)] if self.retry_delays else 0
                if delay:
                    self.sleep(delay)

    def _record_conflict(self, binding, state, kind, local, external_version, fields, message):
        conflict = Conflict(
            conflict_id=uuid.uuid4().hex,
            binding_id=binding.binding_id,
            kind=kind,
            local_version=(local or {}).get("version"),
            external_version=None if external_version is None else str(external_version),
            fields=tuple(sorted(fields)),
            detected_at=_utc_now(),
            message=str(message),
        )
        state["conflicts"][conflict.conflict_id] = conflict.to_dict()
        return conflict

    @staticmethod
    def _merge_fields(binding, local_fields, remote_fields):
        merged = copy.deepcopy(local_fields)
        conflicts = []
        all_fields = set(local_fields) | set(remote_fields)
        for name in all_fields:
            local_value = local_fields.get(name)
            remote_value = remote_fields.get(name)
            if local_value != remote_value:
                conflicts.append(name)
            if binding.field_policy.authority_for(name) == "external":
                if name in remote_fields:
                    merged[name] = copy.deepcopy(remote_value)
                else:
                    merged.pop(name, None)
        return merged, conflicts

    def _commit_candidate(self, binding, original, candidate, local, remote, idempotency_updates,
                          tombstone=None):
        with opc_model.file_lock(str(self.lock_path)):
            latest = self._load_state()
            latest_local = latest["locals"].get(binding.local_id)
            if latest_local != original["locals"].get(binding.local_id):
                conflict = self._record_conflict(
                    binding, latest, "local_version", latest_local,
                    (remote or {}).get("version"), (), "local record changed during reconcile"
                )
                self._save_state(latest)
                return False, conflict
            if local is not None:
                latest["locals"][binding.local_id] = local
            if remote is not None:
                latest["shadows"][binding.binding_id] = remote
            latest["idempotency"].update(idempotency_updates)
            if tombstone is not None:
                latest["tombstones"][tombstone.tombstone_id] = tombstone.to_dict()
            for conflict_id, value in candidate["conflicts"].items():
                if conflict_id not in original["conflicts"]:
                    latest["conflicts"][conflict_id] = value
            self._save_state(latest)
            return True, None

    def reconcile(self, binding_id=None, max_attempts=None):
        if binding_id is None:
            return {key: self.reconcile(key, max_attempts) for key in sorted(self._load_state()["bindings"])}
        original = self._load_state()
        try:
            binding = Binding.from_dict(original["bindings"][binding_id])
        except KeyError as exc:
            raise KeyError("unknown binding: %s" % binding_id) from exc
        open_conflicts = [value for value in original["conflicts"].values()
                          if value.get("binding_id") == binding_id and not value.get("resolved")]
        if open_conflicts:
            return {"binding_id": binding_id, "status": "conflict", "message": "open conflict must be resolved before reconcile"}
        connection = ExternalConnection.from_dict(original["connections"][binding.connection_id])
        connector = self._connectors.get(binding.connection_id)
        if connector is None:
            raise KeyError("no connector registered for %s" % binding.connection_id)
        if not binding.enabled or not connection.enabled:
            return {"binding_id": binding_id, "status": "disabled"}
        attempts = max_attempts if max_attempts is not None else len(self.retry_delays) + 1
        mutation_attempts = attempts if _capability(connection, connector, "idempotency") else 1
        if not _capability(connection, connector, "pull"):
            return {
                "binding_id": binding_id,
                "status": "failed",
                "error_class": "capability",
                "message": "pull not supported",
            }
        candidate = copy.deepcopy(original)
        local = copy.deepcopy(original["locals"].get(binding.local_id))
        old_shadow = copy.deepcopy(original["shadows"].get(binding.binding_id))
        result = {"binding_id": binding_id, "pull": "noop", "push": "noop", "delete": "noop"}
        key = _stable_key(binding_id, "pull", (old_shadow or {}).get("external_version"))
        try:
            pulled = self._call("pull", lambda: connector.pull(binding.external_id), attempts)
        except ConnectorError as exc:
            self._event(binding, "pull", "external_to_local", "failed", key,
                        (local or {}).get("version"), (old_shadow or {}).get("external_version"),
                        exc.error_class, exc)
            result.update(status="failed", error_class=exc.error_class, message=str(exc))
            return result
        remote = None
        if pulled is None and old_shadow:
            remote = copy.deepcopy(old_shadow)
            remote["deleted"] = True
            remote["observed_at"] = _utc_now()
            remote["external_version"] = "missing:" + _utc_now()
            result["pull"] = "missing"
        elif pulled is not None:
            remote = {
                "binding_id": binding.binding_id,
                "external_id": binding.external_id,
                "fields": copy.deepcopy(pulled.get("fields", {})),
                "external_version": str(pulled.get("version")),
                "deleted": bool(pulled.get("deleted")),
                "observed_at": _utc_now(),
                "checkpoint_local_version": (old_shadow or {}).get("checkpoint_local_version"),
                "checkpoint_local_fields": copy.deepcopy((old_shadow or {}).get("checkpoint_local_fields", {})),
            }
        if remote and old_shadow:
            same_version = (remote["external_version"] == old_shadow["external_version"]
                            and remote.get("deleted") == old_shadow.get("deleted")
                            and remote.get("fields") == old_shadow.get("fields"))
            older_version = (connection.capabilities.ordered_versions and
                             _version_order(remote["external_version"]) < _version_order(old_shadow["external_version"]))
            if same_version or older_version:
                remote = old_shadow
                result["pull"] = "ignored"
            else:
                result["pull"] = "applied"
        elif remote is not None:
            result["pull"] = "applied"
        tombstone = None
        idempotency_updates = {}
        if local is None and remote and not remote["deleted"]:
            imported_fields = {
                name: copy.deepcopy(value)
                for name, value in remote["fields"].items()
                if binding.field_policy.authority_for(name) == "external"
            }
            if imported_fields:
                local = {
                    "local_id": binding.local_id,
                    "fields": imported_fields,
                    "version": 1,
                    "deleted": False,
                    "updated_at": _utc_now(),
                }
        if remote and remote["deleted"]:
            origin = "external"
            version = remote["external_version"]
            if local and local.get("deleted"):
                origin, version = "local", str(local["version"])
            tombstone = Tombstone(
                _stable_key(binding.binding_id, "tombstone", origin, version),
                binding.binding_id, binding.local_id, binding.external_id,
                origin, version, _utc_now(), False
            )
            result["delete"] = "pending_confirmation"
        elif local and local["deleted"]:
            tombstone = Tombstone(
                _stable_key(binding.binding_id, "tombstone", "local", local["version"]),
                binding.binding_id, binding.local_id, binding.external_id,
                "local", str(local["version"]), _utc_now(), False
            )
            result["delete"] = "pending_confirmation"
        elif local and not local["deleted"]:
            remote_fields = {} if remote is None or remote["deleted"] else remote["fields"]
            checkpoint_local = (old_shadow or {}).get("checkpoint_local_fields", {})
            checkpoint_remote = (old_shadow or {}).get("fields", {})
            if old_shadow:
                local_changed = {name for name in set(local["fields"]) | set(checkpoint_local)
                                 if local["fields"].get(name) != checkpoint_local.get(name)}
                external_changed = {name for name in set(remote_fields) | set(checkpoint_remote)
                                    if remote_fields.get(name) != checkpoint_remote.get(name)}
                overlapping = {name for name in local_changed & external_changed
                               if local["fields"].get(name) != remote_fields.get(name)}
                if overlapping:
                    conflict = self._record_conflict(binding, candidate, "concurrent_change", local,
                                                     (remote or {}).get("external_version"), overlapping,
                                                     "both local and external changed since last checkpoint")
                    with opc_model.file_lock(str(self.lock_path)):
                        latest = self._load_state()
                        latest["conflicts"][conflict.conflict_id] = conflict.to_dict()
                        self._save_state(latest)
                    result.update(status="conflict", message=conflict.message)
                    return result
            merged, differing = self._merge_fields(binding, local["fields"], remote_fields)
            if merged != local["fields"]:
                local["fields"] = merged
                local["version"] += 1
                local["updated_at"] = _utc_now()
            push_fields = {
                name: copy.deepcopy(value)
                for name, value in local["fields"].items()
                if binding.field_policy.authority_for(name) == "local"
                and remote_fields.get(name) != value
            }
            if push_fields:
                if not _capability(connection, connector, "push"):
                    result.update(status="failed", error_class="capability", message="push not supported")
                    return result
                push_key = _stable_key(binding_id, "push", local["version"], push_fields)
                if push_key not in original["idempotency"]:
                    try:
                        pushed = self._call(
                            "push",
                            lambda: connector.push(
                                binding.external_id,
                                push_fields,
                                None if remote is None or remote["deleted"] else remote["external_version"],
                                push_key,
                            ),
                            mutation_attempts,
                        )
                    except ConnectorError as exc:
                        self._event(binding, "push", "local_to_external", "failed", push_key,
                                    local["version"], (remote or {}).get("external_version"),
                                    exc.error_class, exc)
                        if isinstance(exc, VersionConflictError):
                            conflict = self._record_conflict(
                                binding, candidate, "external_version", local,
                                (remote or {}).get("external_version"), differing, exc
                            )
                            with opc_model.file_lock(str(self.lock_path)):
                                latest = self._load_state()
                                latest["conflicts"][conflict.conflict_id] = conflict.to_dict()
                                self._save_state(latest)
                            result["push"] = "conflict"
                        result.update(status="failed", error_class=exc.error_class, message=str(exc))
                        return result
                    remote = {
                        "binding_id": binding.binding_id,
                        "external_id": binding.external_id,
                        "fields": copy.deepcopy(pushed.get("fields", {**remote_fields, **push_fields})),
                        "external_version": str(pushed.get("version")),
                        "deleted": False,
                        "observed_at": _utc_now(),
                    }
                    idempotency_updates[push_key] = {"operation": "push", "at": _utc_now()}
                    result["push"] = "applied"
        if remote is not None and local is not None:
            remote["checkpoint_local_version"] = local.get("version")
            remote["checkpoint_local_fields"] = copy.deepcopy(local.get("fields", {}))
        committed, conflict = self._commit_candidate(
            binding, original, candidate, local, remote, idempotency_updates, tombstone
        )
        if not committed:
            result.update(status="failed", error_class="version_conflict", message=conflict.message)
            return result
        result["status"] = "applied"
        if result["pull"] == result["push"] == result["delete"] == "noop":
            result["status"] = "noop"
            return result
        event_key = _stable_key(binding_id, "reconcile", (local or {}).get("version"),
                                (remote or {}).get("external_version"))
        self._event(binding, "reconcile", "bidirectional", "applied", event_key,
                    (local or {}).get("version"), (remote or {}).get("external_version"))
        return result


def _run_selftest():
    import tempfile
    import unittest
    from pathlib import Path

    from opc_integrations import (
        Binding,
        Capabilities,
        ExternalConnection,
        FakeConnector,
        FieldPolicy,
        RetryableConnectorError,
        VersionConflictError,
    )

    class SyncKernelTests(unittest.TestCase):
        def setUp(self):
            self.temp = tempfile.TemporaryDirectory()
            self.root = Path(self.temp.name)
            capabilities = Capabilities(ordered_versions=True)
            self.connector = FakeConnector(capabilities)
            self.kernel = SyncKernel(self.root, retry_delays=(0.0, 0.0))
            self.kernel.register_connection(
                ExternalConnection("fake-main", "fake", capabilities=capabilities), self.connector
            )

        def tearDown(self):
            self.temp.cleanup()

        def bind(self, policy=None):
            binding = Binding(
                "task-binding",
                "fake-main",
                "TSK00001",
                "remote-1",
                field_policy=policy or FieldPolicy(default_authority="local"),
            )
            self.kernel.add_binding(binding)
            return binding

        def test_duplicate_and_out_of_order_remote_versions_are_ignored(self):
            self.bind(FieldPolicy(default_authority="external"))
            self.connector.seed("remote-1", {"title": "v2"}, version=2)
            self.kernel.reconcile("task-binding")
            self.connector.seed("remote-1", {"title": "old"}, version=1)
            stale = self.kernel.reconcile("task-binding")
            duplicate = self.kernel.reconcile("task-binding")
            self.assertEqual("v2", self.kernel.get_local("TSK00001")["fields"]["title"])
            self.assertEqual("ignored", stale["pull"])
            self.assertEqual("ignored", duplicate["pull"])

        def test_version_conflict_is_recorded_without_overwriting_local(self):
            self.bind()
            self.kernel.put_local("TSK00001", {"title": "local"})
            self.connector.seed("remote-1", {"title": "remote"}, version=1)
            self.connector.inject_failure("push", VersionConflictError("raced"))
            result = self.kernel.reconcile("task-binding")
            self.assertEqual("conflict", result["push"])
            self.assertEqual("local", self.kernel.get_local("TSK00001")["fields"]["title"])
            self.assertEqual(1, len(self.kernel.list_conflicts()))

        def test_push_idempotency_survives_reloaded_kernel(self):
            self.bind()
            self.kernel.put_local("TSK00001", {"title": "one"})
            first = self.kernel.reconcile("task-binding")
            reloaded = SyncKernel(self.root, retry_delays=(0.0,))
            reloaded.register_connector("fake-main", self.connector)
            second = reloaded.reconcile("task-binding")
            self.assertEqual("applied", first["push"])
            self.assertEqual("noop", second["push"])
            self.assertEqual(1, self.connector.mutation_count)

        def test_local_delete_creates_tombstone_and_is_idempotent(self):
            self.bind()
            self.kernel.put_local("TSK00001", {"title": "one"})
            self.kernel.reconcile("task-binding")
            self.kernel.delete_local("TSK00001")
            first = self.kernel.reconcile("task-binding")
            second = self.kernel.reconcile("task-binding")
            self.assertEqual("pending_confirmation", first["delete"])
            self.assertEqual("pending_confirmation", second["delete"])
            self.assertEqual(1, len(self.kernel.list_tombstones()))
            self.assertIsNotNone(self.connector.get("remote-1"))

        def test_retry_after_lost_response_reuses_connector_idempotency(self):
            self.bind()
            self.kernel.put_local("TSK00001", {"title": "one"})
            self.connector.inject_failure(
                "push_after", RetryableConnectorError("response lost")
            )
            result = self.kernel.reconcile("task-binding", max_attempts=2)
            self.assertEqual("applied", result["push"])
            self.assertEqual(1, self.connector.mutation_count)
            self.assertEqual("one", self.connector.get("remote-1")["fields"]["title"])

        def test_non_idempotent_connector_does_not_retry_mutation(self):
            capabilities = Capabilities(idempotency=False)
            connector = FakeConnector(capabilities)
            kernel = SyncKernel(self.root / "non-idempotent", retry_delays=(0.0, 0.0))
            kernel.register_connection(
                ExternalConnection("unsafe", "fake", capabilities=capabilities), connector
            )
            kernel.add_binding(Binding("unsafe-binding", "unsafe", "local-2", "remote-2"))
            kernel.put_local("local-2", {"title": "one"})
            connector.inject_failure("push", RetryableConnectorError("offline"), count=2)
            result = kernel.reconcile("unsafe-binding", max_attempts=3)
            self.assertEqual("retryable", result["error_class"])
            self.assertEqual(1, len(connector._failures["push"]))
            self.assertIsNone(connector.get("remote-2"))

        def test_opaque_versions_are_not_sorted(self):
            opaque_connector = FakeConnector(Capabilities(ordered_versions=False))
            opaque_kernel = SyncKernel(self.root / "opaque", retry_delays=(0.0,))
            opaque_kernel.register_connection(
                ExternalConnection("opaque", "fake", capabilities=Capabilities(ordered_versions=False)),
                opaque_connector,
            )
            opaque_kernel.add_binding(Binding("opaque-binding", "opaque", "opaque-local", "opaque-remote",
                                             field_policy=FieldPolicy(default_authority="external")))
            opaque_connector.seed("opaque-remote", {"title": "first"}, version="ffff")
            opaque_kernel.reconcile("opaque-binding")
            opaque_connector.seed("opaque-remote", {"title": "second"}, version="0000")
            opaque_kernel.reconcile("opaque-binding")
            self.assertEqual("second", opaque_kernel.get_local("opaque-local")["fields"]["title"])

        def test_open_conflict_freezes_binding(self):
            self.bind()
            self.kernel.put_local("TSK00001", {"title": "local"})
            self.connector.seed("remote-1", {"title": "remote"}, version=1)
            self.connector.inject_failure("push", VersionConflictError("raced"))
            self.kernel.reconcile("task-binding")
            second = self.kernel.reconcile("task-binding")
            self.assertEqual("conflict", second["status"])

        def test_external_missing_creates_unpropagated_tombstone(self):
            self.bind(FieldPolicy(default_authority="external"))
            self.connector.seed("remote-1", {"title": "remote"}, version=1)
            self.kernel.reconcile("task-binding")
            self.connector._records["remote-1"]["deleted"] = True
            result = self.kernel.reconcile("task-binding")
            self.assertEqual("pending_confirmation", result["delete"])
            self.assertFalse(self.kernel.list_tombstones()[0]["propagated"])
            self.assertFalse(self.kernel.get_local("TSK00001")["deleted"])

        def test_retryable_external_failure_never_changes_local_record(self):
            self.bind(
                FieldPolicy(
                    default_authority="local",
                    authorities={"remote_note": "external"},
                )
            )
            self.kernel.put_local("TSK00001", {"title": "keep"})
            before = self.kernel.get_local("TSK00001")
            self.connector.seed(
                "remote-1", {"title": "old", "remote_note": "candidate"}, version=1
            )
            self.connector.inject_failure("push", RetryableConnectorError("offline"), count=3)
            result = self.kernel.reconcile("task-binding", max_attempts=3)
            self.assertEqual("retryable", result["error_class"])
            self.assertEqual(before, self.kernel.get_local("TSK00001"))
            self.assertNotIn("remote_note", self.kernel.get_local("TSK00001")["fields"])

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(SyncKernelTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument("--root", default=".")
    parser.add_argument("--status", action="store_true", help="print sync state summary")
    parser.add_argument("--project", action="store_true", help="write .opc-sync/projection.json")
    parser.add_argument("--config", help="apply reviewed non-secret connection/binding JSON")
    parser.add_argument("--reconcile", nargs="?", const="*", help="reconcile one binding or all")
    args = parser.parse_args()
    if args.selftest:
        raise SystemExit(_run_selftest())
    kernel = SyncKernel(args.root)
    if args.config:
        with open(args.config, "r", encoding="utf-8") as handle:
            apply_config(kernel, json.load(handle))
    if args.reconcile:
        register_configured_connectors(kernel)
        target = None if args.reconcile == "*" else args.reconcile
        result = kernel.reconcile(target)
        kernel.write_projection(Path(args.root) / ".opc-sync" / "projection.json")
        print(json.dumps(result, ensure_ascii=False))
        failed = (result.get("status") == "failed") if target is not None else any(
            isinstance(value, dict) and value.get("status") == "failed" for value in result.values())
        if failed:
            raise SystemExit(1)
    elif args.project:
        projection = kernel.write_projection(Path(args.root) / ".opc-sync" / "projection.json")
        print(json.dumps({"shadows": len(projection["shadows"]), "conflicts": len(projection["conflicts"]),
                          "tombstones": len(projection["tombstones"])}, ensure_ascii=False))
    elif args.status:
        state = kernel.snapshot()
        print(json.dumps({key: len(state[key]) for key in ("connections", "bindings", "shadows", "conflicts", "tombstones")}, ensure_ascii=False))
    else:
        parser.print_help()
