#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""OPC projection releases: immutable artifacts plus one atomic current pointer."""
from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import shutil
import tempfile
import time
from pathlib import Path

import opc_model

SCHEMA_VERSION = 1
DATA_NAMES = ("tasks-data.json", "tasks-data.js", "dashboard-data.js")


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _safe_rel(rel: str) -> str:
    p = Path(rel.replace("\\", "/"))
    if p.is_absolute() or ".." in p.parts or not rel:
        raise ValueError(f"非法 projection 相对路径：{rel!r}")
    return p.as_posix()


def _data_root(company: str | os.PathLike) -> Path:
    return Path(company) / ".opc-data"


def _source_fingerprint(company: Path) -> str:
    """Fingerprint domain inputs and legacy projection sources deterministically."""
    files = []
    for root, dirs, names in os.walk(company):
        dirs[:] = [d for d in dirs if d not in {".git", ".opc-data", "OpenMAIC"}]
        for name in names:
            if name.endswith((".md", ".json", ".js")) and name not in {"INDEX.md", "KB-CHANGELOG.md"}:
                p = Path(root) / name
                rel = p.relative_to(company).as_posix()
                files.append((rel, _sha256(p)))
    payload = json.dumps(sorted(files), ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _artifact_paths(company: Path):
    for root, dirs, names in os.walk(company):
        dirs[:] = [d for d in dirs if d not in {".git", ".opc-data", "OpenMAIC"}]
        for name in names:
            if name in DATA_NAMES or name.endswith("-data.js"):
                p = Path(root) / name
                try:
                    if "OPC_PROJECTION_LOADER" in p.read_text(encoding="utf-8"):
                        continue
                except (OSError, UnicodeDecodeError):
                    pass
                yield p.relative_to(company).as_posix(), p


def _js_var_for(rel: str) -> str:
    name = Path(rel).name
    if name == "tasks-data.js":
        return "KANBAN_DATA"
    if name == "dashboard-data.js":
        return "DASHBOARD_DATA"
    if name == "teamboard-data.js":
        return "TEAMBOARD_DATA"
    return "MYDESK_DATA"


def _write_json(path: Path, value):
    opc_model.atomic_write(str(path), json.dumps(value, ensure_ascii=False, indent=2))


def _write_js(path: Path, var_name: str, value):
    text = f"window.{var_name} = " + json.dumps(value, ensure_ascii=False, indent=2) + ";\n"
    opc_model.atomic_write(str(path), text.replace("</script", "<\\/script"))


def _parse_js_payload(text: str):
    marker = " = "
    start = text.find(marker)
    if start < 0:
        raise ValueError("projection JS 缺少赋值")
    return json.loads(text[start + len(marker):].strip().rstrip(";"))


def _current_script(pointer: dict, release: Path) -> str:
    """Build a synchronous pointer script for file:// pages."""
    lines = ["window.OPC_CURRENT = " + json.dumps(pointer, ensure_ascii=False) + ";"]
    for rel, item in pointer.get("artifacts", {}).items():
        path = release / _safe_rel(item)
        try:
            if path.name.endswith(".json"):
                payload = json.loads(path.read_text(encoding="utf-8"))
                var = "KANBAN_DATA"
            else:
                text = path.read_text(encoding="utf-8")
                var = re.search(r"^window\.(\w+)\s*=", text, re.M).group(1)
                payload = _parse_js_payload(text)
            lines.append("window.%s = %s;" % (var, json.dumps(payload, ensure_ascii=False)))
        except (OSError, ValueError, TypeError, AttributeError, json.JSONDecodeError):
            continue
    return "\n".join(lines) + "\n"


def _write_loader(path: Path, var_name: str, current_rel: str, release_rel: str):
    text = (
        "// OPC_PROJECTION_LOADER: fixed file loads one immutable release artifact.\n"
        "(function(){\n"
        f"  var current = {json.dumps(current_rel)};\n"
        f"  var release = {json.dumps(release_rel)};\n"
        f"  var variable = {json.dumps(var_name)};\n"
        "  var s = document.createElement('script');\n"
        "  s.src = current + '#_=' + Date.now();\n"
        "  s.onload = function(){\n"
        "    var pointer = window.OPC_CURRENT;\n"
        "    if (!pointer || !pointer.manifest) return;\n"
        "    var r = document.createElement('script');\n"
        "    var currentUrl = new URL(current, document.baseURI);\n"
        "    var releaseUrl = new URL(pointer.base + pointer.artifacts[release], currentUrl);\n"
        "    r.src = releaseUrl.href + '#_=' + Date.now();\n"
        "    document.head.appendChild(r);\n"
        "  };\n"
        "  document.head.appendChild(s);\n"
        "})();\n"
    )
    opc_model.atomic_write(str(path), text)


def verify_release(release: Path, manifest: dict) -> list[str]:
    errors = []
    if manifest.get("schema_version") != SCHEMA_VERSION:
        errors.append("manifest schema_version 不支持")
    for key, item in manifest.get("artifacts", {}).items():
        try:
            rel = _safe_rel(item["path"])
            p = (release / rel).resolve()
            if os.path.commonpath((str(release.resolve()), str(p))) != str(release.resolve()):
                errors.append(f"artifact 越界：{key}")
                continue
            if not p.is_file():
                errors.append(f"artifact 缺失：{key}")
            elif _sha256(p) != item.get("sha256"):
                errors.append(f"artifact hash 不匹配：{key}")
        except (KeyError, OSError, ValueError) as exc:
            errors.append(f"artifact 无效 {key}：{exc}")
    return errors


def publish_legacy_snapshot(company: str | os.PathLike, cid: str, install_loaders=True) -> dict:
    """Publish the already-generated legacy projections as one immutable release."""
    company = Path(company).resolve()
    root = _data_root(company)
    staging = root / "staging"
    releases = root / "releases"
    root.mkdir(parents=True, exist_ok=True)
    staging.mkdir(exist_ok=True)
    releases.mkdir(exist_ok=True)
    with opc_model.file_lock(root / "publish", timeout=60):
        return _publish_locked(company, cid, install_loaders, root, staging, releases)


def _publish_locked(company: Path, cid: str, install_loaders: bool,
                    root: Path, staging: Path, releases: Path) -> dict:
    batch_id = time.strftime("%Y%m%dT%H%M%S") + "-" + secrets.token_hex(4)
    source_fp = _source_fingerprint(company)
    stage = staging / batch_id
    artifact_dir = stage / "artifacts"
    stage.mkdir()
    artifact_dir.mkdir()
    artifacts = {}
    for rel, source in _artifact_paths(company):
        target_rel = _safe_rel(rel)
        target = artifact_dir / target_rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        artifacts[rel] = {"path": f"artifacts/{target_rel}", "sha256": _sha256(target), "size": target.stat().st_size}
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "cid": cid,
        "batch_id": batch_id,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "source_fingerprint": source_fp,
        "artifacts": artifacts,
    }
    _write_json(stage / "manifest.json", manifest)
    if _source_fingerprint(company) != source_fp:
        shutil.rmtree(stage, ignore_errors=True)
        raise RuntimeError("projection 源文件在生成期间发生变化，批次未发布")
    errors = verify_release(stage, manifest)
    if errors:
        shutil.rmtree(stage, ignore_errors=True)
        raise RuntimeError("projection release 校验失败：" + "；".join(errors))
    release = releases / batch_id
    os.replace(stage, release)
    current = {"schema_version": SCHEMA_VERSION, "cid": cid, "batch_id": batch_id,
               "base": f"releases/{batch_id}/", "manifest": f"releases/{batch_id}/manifest.json",
               "artifacts": {rel: item["path"] for rel, item in artifacts.items()}}
    opc_model.atomic_write(str(root / "current.js"), _current_script(current, release))
    if install_loaders:
        for rel in artifacts:
            legacy = company / rel
            if legacy.suffix == ".js":
                var = _js_var_for(rel)
                _write_loader(legacy, var, _relative_current(rel), rel)
    return manifest


def _relative_current(rel: str) -> str:
    depth = len(Path(rel).parent.parts)
    return ("../" * depth) + ".opc-data/current.js"


def read_current(company: str | os.PathLike) -> dict:
    path = _data_root(company) / "current.js"
    text = path.read_text(encoding="utf-8")
    marker = "window.OPC_CURRENT = "
    if not text.startswith(marker) or not text.rstrip().endswith(";"):
        raise ValueError("current.js 格式无效")
    decoder = json.JSONDecoder()
    pointer, _end = decoder.raw_decode(text[len(marker):].lstrip())
    return pointer


def load_current_artifact(company: str | os.PathLike, legacy_rel: str):
    """Read one artifact from the published batch, never from a mixed live set."""
    company = Path(company).resolve()
    pointer = read_current(company)
    rel = pointer.get("artifacts", {}).get(legacy_rel)
    if not rel and legacy_rel == "tasks-data.json":
        rel = pointer.get("artifacts", {}).get("workbench/tasks-data.json")
        legacy_rel = "workbench/tasks-data.json"
    if not rel:
        raise FileNotFoundError(f"当前批次没有 artifact：{legacy_rel}")
    release = _data_root(company) / pointer["base"]
    artifact = (release / _safe_rel(rel)).resolve()
    if os.path.commonpath((str(release.resolve()), str(artifact))) != str(release.resolve()):
        raise ValueError("artifact 路径越界")
    if artifact.suffix == ".json":
        return json.loads(artifact.read_text(encoding="utf-8")), pointer
    text = artifact.read_text(encoding="utf-8")
    marker = " = "
    start = text.find(marker)
    if start < 0:
        raise ValueError("artifact JS 格式无效")
    return json.loads(text[start + len(marker):].rstrip().rstrip(";")), pointer


def verify_current(company: str | os.PathLike) -> list[str]:
    company = Path(company).resolve()
    try:
        pointer = read_current(company)
        release = _data_root(company) / pointer["base"]
        manifest = json.loads((release / "manifest.json").read_text(encoding="utf-8"))
        errors = verify_release(release, manifest)
        if pointer.get("batch_id") != manifest.get("batch_id"):
            errors.append("current batch_id 与 manifest 不一致")
        return errors
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        return [f"current 不可用：{exc}"]
