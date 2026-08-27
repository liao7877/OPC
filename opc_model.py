#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
opc_model.py — OPC 领域模型（Repository + 校验器）

职责（设计见 opc-schema-design.md）：
  1. 发现实体：task / project / employee / team / company（按公司维度）
  2. 按 opc_schema.toml 解析 + schema 校验（枚举 / 必填 / 格式）
  3. 构建 FK 索引，做参照完整性校验（owner/project/blocked_by/parent/handoffs）
  4. 反规范化字段（derived）存储告警

数据组织：opc_schema.toml / opc.toml 在组织根（OPC 根）；实体数据在每个公司目录
（含 company.md，如 C001-AI自动化公司/ 或 companies/C001）。`opc validate` 默认校验
OPC 根下全部公司；`--root <公司目录>` 只校验单公司。

consumer（generate_dashboard.py / generate_tasks.py）应改调本模块，禁止私有正则（P3/DRY）。
仅用标准库（tomllib + re + pathlib）。

CLI:
  python opc_model.py --validate [--root DIR]    # 跑 schema + FK 校验
  python opc_model.py --schema                   # 打印已加载 schema
退出码：有 [ERR] 则 1。
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
import tomllib
from pathlib import Path

# ---------------------------------------------------------------------------
# 根目录发现
# ---------------------------------------------------------------------------
def _find_opc_root(start: str | None = None) -> str | None:
    """向上找含 opc.toml（组织根）的目录。"""
    d = Path(start or os.getcwd()).resolve()
    for _ in range(8):
        if (d / "opc.toml").is_file():
            return str(d)
        if d.parent == d:
            break
        d = d.parent
    return None


def load_schema(root: str | None = None) -> dict:
    """从组织根加载 opc_schema.toml（向上找）。"""
    d = Path(root or os.getcwd()).resolve()
    for _ in range(8):
        p = d / "opc_schema.toml"
        if p.is_file():
            with open(p, "rb") as f:
                return tomllib.load(f)
        if d.parent == d:
            break
        d = d.parent
    raise RuntimeError("找不到 opc_schema.toml（OPC 组织根）")


# ---------------------------------------------------------------------------
# frontmatter 解析（容错：列表/JSON 对象/裸值）
# ---------------------------------------------------------------------------
def parse_frontmatter(text: str) -> dict:
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}
    fm: dict[str, str] = {}
    for line in lines[1:end]:
        if ":" not in line or line.lstrip().startswith("#"):
            continue
        k, _, v = line.partition(":")
        fm[k.strip()] = v.strip()
    return fm


def parse_scalar_list(v: str) -> list[str]:
    v = v.strip()
    if v.startswith("[") and v.endswith("]"):
        inner = v[1:-1].strip()
        if not inner:
            return []
        try:
            data = json.loads(v)
            if isinstance(data, list):
                return [str(x) for x in data]
        except Exception:
            pass
        return [x.strip().strip("\"'") for x in inner.split(",") if x.strip()]
    return [v] if v else []


def parse_handoff_refs(v: str) -> list[str]:
    """handoffs 是 [{from,to,...}]；返回其中的员工 ID 列表。"""
    v = v.strip()
    try:
        data = json.loads(v)
        if isinstance(data, list):
            ids = []
            for item in data:
                if isinstance(item, dict):
                    for key in ("from", "to"):
                        if item.get(key):
                            ids.append(str(item[key]))
            return ids
    except Exception:
        pass
    return re.findall(r"E\d{4}", v)


# ---------------------------------------------------------------------------
# 实体发现 / 索引构建（按单个公司目录）
# ---------------------------------------------------------------------------
def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


def extract_id(text: str, fm_key: str = "id", prose_pat: str = r"ID[：:]\s*(\S+)") -> str | None:
    """实体 ID 提取：优先 frontmatter 的 fm_key（如 id），回退散文「XX ID：...」。
    兼容 P0001（散文）与 P0002/P0003（frontmatter）两种注册格式，不强制单一写法。"""
    fm = parse_frontmatter(text)
    if fm.get(fm_key):
        return fm[fm_key].strip()
    m = re.search(prose_pat, text)
    return m.group(1).strip() if m else None


def build_indexes(company_root: str) -> dict:
    root = Path(company_root)
    tasks: dict[str, dict] = {}
    projects: dict[str, dict] = {}
    teams: dict[str, dict] = {}
    employees: dict[str, dict] = {}

    for tm in root.glob("workbench/tasks/*/task.md"):
        fm = parse_frontmatter(_read(tm))
        tid = fm.get("id")
        if tid:
            tasks[tid] = {"fm": fm, "path": str(tm)}

    for d in root.iterdir():
        if d.is_dir() and re.match(r"^P\d+", d.name):
            pm = d / "project.md"
            if pm.is_file():
                txt = _read(pm)
                pid = extract_id(txt, "id", r"项目\s*ID[：:]\s*(\S+)")
                if pid:
                    projects[pid] = {"path": str(pm), "txt": txt}

    for d in root.iterdir():
        if d.is_dir() and re.match(r"^T\d+", d.name):
            tm = d / "team.md"
            if tm.is_file():
                txt = _read(tm)
                tid = extract_id(txt, "id", r"团队\s*ID[：:]\s*(\S+)")
                if tid:
                    teams[tid] = {"path": str(tm)}

    roster = root / "E0000-AI员工-总管" / "roster.md"
    if not roster.is_file():
        for d in root.iterdir():
            if d.is_dir() and re.match(r"^E0000", d.name):
                r2 = d / "roster.md"
                if r2.is_file():
                    roster = r2
                    break
    if roster.is_file():
        for line in _read(roster).splitlines():
            m = re.match(r"\|\s*(E\d{4})\s*\|", line)
            if m:
                employees[m.group(1)] = {"path": str(roster)}

    return {"task": tasks, "project": projects, "team": teams, "employee": employees}


def discover_companies(opc_root: str) -> list[str]:
    opc_root = Path(opc_root)
    skip = {".git", "companies", ".workbuddy", "scripts",
            "create-company", "company-template"}
    cands: list[str] = []
    seen: set[str] = set()
    for d in opc_root.iterdir():
        if d.is_dir() and d.name not in skip and (d / "company.md").is_file():
            rp = str(d.resolve())
            if rp not in seen:
                seen.add(rp)
                cands.append(str(d))
    comp_dir = opc_root / "companies"
    if comp_dir.is_dir():
        for d in comp_dir.iterdir():
            if d.is_dir() and (d / "company.md").is_file():
                rp = str(d.resolve())
                if rp not in seen:
                    seen.add(rp)
                    cands.append(str(d))
    return sorted(cands)


# ---------------------------------------------------------------------------
# 校验
# ---------------------------------------------------------------------------
def validate_task(tid: str, rec: dict, schema: dict, idx: dict,
                  data_root: str, issues: list[str]) -> None:
    fm = rec["fm"]
    fields = schema["entity"]["task"]["fields"]
    rel = os.path.relpath(rec["path"], data_root)

    for fname, spec in fields.items():
        val = fm.get(fname)
        if spec.get("required") and not val:
            issues.append(f"[ERR] {rel}: 缺必填字段 {fname}")
            continue
        if not val:
            continue
        if spec.get("type") == "enum" and "enum" in spec:
            if val not in spec["enum"]:
                issues.append(f"[ERR] {rel}: {fname}={val} 不在枚举 {spec['enum']}")
        if spec.get("type") == "string" and spec.get("pattern"):
            if not re.match(spec["pattern"], val):
                issues.append(f"[ERR] {rel}: {fname}={val} 不匹配格式 {spec['pattern']}")
        if spec.get("type") == "ref":
            table = idx.get(spec["ref"], {})
            if val not in table:
                issues.append(f"[ERR] {rel}: {fname}={val} 指向的{spec['ref']}不存在（FK 悬空）")
        if spec.get("type") == "ref_list":
            table = idx.get(spec["ref"], {})
            for item in parse_scalar_list(val):
                if item not in table:
                    issues.append(f"[ERR] {rel}: {fname}={item} 指向的{spec['ref']}不存在（FK 悬空）")

    if fm.get("handoffs"):
        for emp in parse_handoff_refs(fm["handoffs"]):
            if emp not in idx["employee"]:
                issues.append(f"[ERR] {rel}: handoffs 含员工 {emp} 不存在（FK 悬空）")

    for dname in schema["entity"]["task"].get("derived", {}):
        if fm.get(dname):
            issues.append(f"[WARN] {rel}: 存储了反规范化字段 {dname}（应由 FK 实时派生，见 opc_schema.toml derived）")


def validate_project(pid: str, rec: dict, idx: dict, data_root: str, issues: list[str]) -> None:
    txt = rec.get("txt", "")
    rel = os.path.relpath(rec["path"], data_root)
    m = re.search(r"负责人（owner）[：:]\s*(\S+)", txt)
    if m:
        emp = re.search(r"E\d{4}", m.group(1))
        if emp and emp.group(0) not in idx["employee"]:
            issues.append(f"[WARN] {rel}: owner 指向员工 {emp.group(0)} 不存在")
    t = re.search(r"归属团队[：:]\s*(\S+)", txt)
    if t:
        team = re.search(r"T\d+", t.group(1))
        if team and team.group(0) not in idx["team"]:
            issues.append(f"[WARN] {rel}: 归属团队 {team.group(0)} 不存在")


def validate_company(company_root: str, schema: dict) -> list[str]:
    issues: list[str] = []
    idx = build_indexes(company_root)
    for tid, rec in idx["task"].items():
        validate_task(tid, rec, schema, idx, company_root, issues)
    for pid, rec in idx["project"].items():
        validate_project(pid, rec, idx, company_root, issues)
    if not idx["task"]:
        issues.append(f"[WARN] {os.path.basename(company_root)}: 未发现任何 task")
    return issues


def validate_all(root: str | None = None) -> list[str]:
    opc_root = root or _find_opc_root()
    if not opc_root:
        return ["[ERR] 找不到 opc.toml（OPC 组织根）"]
    schema = load_schema(opc_root)
    companies = discover_companies(opc_root)
    if not companies:
        return ["[WARN] 未发现任何公司（无含 company.md 的目录）"]
    all_issues: list[str] = []
    for c in companies:
        name = os.path.basename(c)
        sub = validate_company(c, schema)
        if not sub:
            all_issues.append(f"[ok] {name}: schema + FK 校验全绿")
        else:
            all_issues.append(f"=== {name} ===")
            all_issues.extend(sub)
    return all_issues


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main() -> int:
    ap = argparse.ArgumentParser(description="OPC 领域模型校验（schema + FK）")
    ap.add_argument("--validate", action="store_true", help="跑 schema + FK 校验（默认校验全部公司）")
    ap.add_argument("--schema", action="store_true", help="打印已加载 schema")
    ap.add_argument("--root", default=None, help="指定公司目录（只校验该公司）；默认校验 OPC 根下全部公司")
    a = ap.parse_args()

    if a.schema:
        print(json.dumps(load_schema(a.root), ensure_ascii=False, indent=2))
        return 0

    if a.validate:
        if a.root:
            schema = load_schema(a.root)
            issues = validate_company(a.root, schema)
            if not issues:
                print(f"[ok] {os.path.basename(a.root)}: schema + FK 校验全绿")
            else:
                for i in issues:
                    print(i)
        else:
            issues = validate_all()
        if a.root:
            return 1 if any(i.startswith("[ERR]") for i in issues) else 0
        # 全部公司模式：汇总
        for i in issues:
            print(i)
        if any(i.startswith("[ERR]") for i in issues):
            return 1
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
