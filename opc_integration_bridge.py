"""Bridge OPC canonical task files into the connector-neutral sync kernel."""
from __future__ import annotations

import os
from pathlib import Path

import opc_model

TASK_FIELDS = ("title", "status", "owner", "project", "due", "priority")


def find_task_file(company_root, task_id):
    tasks = Path(company_root) / "workbench" / "tasks"
    if not tasks.is_dir():
        return None
    for path in sorted(tasks.iterdir()):
        if path.is_dir() and (path.name == task_id or path.name.startswith(task_id + "-")):
            candidate = path / "task.md"
            if candidate.is_file():
                return candidate
    return None


def load_task(company_root, task_id):
    path = find_task_file(company_root, task_id)
    if path is None:
        return None
    text = path.read_text(encoding="utf-8")
    fm, _body, has = opc_model.parse_frontmatter(text)
    if not has:
        return None
    return {name: fm.get(name) for name in TASK_FIELDS if fm.get(name) not in (None, "")}


def refresh_local_records(kernel, company_root):
    """Import canonical local fields without writing back task.md."""
    state = kernel.snapshot()
    refreshed = []
    for raw in state.get("bindings", {}).values():
        if raw.get("entity_type") != "task":
            continue
        local_id = raw.get("local_id") or ""
        if not local_id.startswith("TSK"):
            continue
        fields = load_task(company_root, local_id)
        if fields is None:
            continue
        current = kernel.get_local(local_id)
        if current and current.get("fields") == fields and not current.get("deleted"):
            continue
        kernel.put_local(local_id, fields, expected_version=(current or {}).get("version"))
        refreshed.append(local_id)
    return refreshed
