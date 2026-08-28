#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
opc_model.py — OPC 实体共享读取器（唯一解析点）

职责：
  1. 发现实体（按公司维度）：task / project / employee / team / company
  2. 把实体卡（frontmatter）读成 (dict, body, has_fm) —— 不校验、不写死字段

为什么单独成模块（设计取舍，2026-08-28 廖哥拍板 X 方案）：
  - 所有 consumer（opc_dashboards.py / opc_tickets.py，含 C001 与
    company-template 两套）统一 import 本模块的 parse_frontmatter，禁止各脚本
    私写正则（呼应 P3 高内聚 / DRY）。加字段免费、改格式只动本文件一处。
  - 不做什么：不做 schema 校验、不做 FK 阻断、不报错拦下。改名类问题靠
    consumer 一处修，不做“校验不过就拦下”的复杂机制（避免“一堆检验过不了
    导致根本用不起来”）。
  - 仅用标准库（json + re + pathlib）。

用法（被其他脚本 import）：
  from opc_model import parse_frontmatter, build_indexes, discover_companies
  fm, body, has = parse_frontmatter(open(".../task.md").read())
  idx = build_indexes("C001-AI自动化公司")   # -> {task:{}, project:{}, team:{}, employee:{}}

命令行（可选，仅列举、非校验、不阻断）：
  python opc_model.py --list      # 列出 OPC 根下各公司与实体数量
"""

from __future__ import annotations
import argparse
import json
import os
import re
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 根目录发现
# ---------------------------------------------------------------------------
def _find_opc_root(start=None):
    """向上找含 opc.toml（组织根）的目录。"""
    d = Path(start or os.getcwd()).resolve()
    for _ in range(8):
        if (d / "opc.toml").is_file():
            return str(d)
        if d.parent == d:
            break
        d = d.parent
    return None


# ---------------------------------------------------------------------------
# 卡片解析（容错：列表/JSON 对象数组/裸值/空值；返回 body 与 has_fm）
# ---------------------------------------------------------------------------
def parse_frontmatter(text):
    """解析卡片 frontmatter -> (dict, body, has_fm)。

    支持的子集契约（刻意不支持完整 YAML）：
    - key: value / key: [a, b] / key:（空）
    - [a, b] 优先按 JSON 解析（支持对象数组，如 handoffs:[{...}]），失败回退逗号拆分
      ⚠️ 逗号拆分回退不处理引号内逗号——含逗号的字符串值请写合法 JSON 或避免逗号
    - 空值 -> None；裸值去引号；值内半角冒号会污染解析（建单工具已自动转全角）
    - 重复 key 后者静默覆盖前者（勿写重复键）
    - 无 --- 包裹 -> ( {}, text.strip(), False )（交由调用方跳过坏文件）
    """
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, text.strip(), False
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, text.strip(), False
    data = {}
    for line in lines[1:end]:
        s = line.strip()
        if not s or s.startswith("#") or ":" not in line:
            continue
        key, _, val = line.partition(":")
        key, val = key.strip(), val.strip()
        if val.startswith("[") and val.endswith("]"):
            inner = val[1:-1].strip()
            if not inner:
                data[key] = []
            else:
                try:
                    data[key] = json.loads(val)
                except Exception:
                    data[key] = [x.strip().strip('"').strip("'") for x in inner.split(",") if x.strip()]
        elif val == "":
            data[key] = None
        else:
            data[key] = val.strip('"').strip("'")
    body = "\n".join(lines[end + 1:]).strip()
    return data, body, True


def read_card(path):
    """读取单个实体卡文件，返回 (dict, body, has_fm)。文件不存在 -> ({}, '', False)。"""
    p = Path(path)
    if not p.is_file():
        return {}, "", False
    try:
        return parse_frontmatter(p.read_text(encoding="utf-8", errors="ignore"))
    except OSError:
        return {}, "", False


def extract_id(text, fm_key="id", prose_pat=r"ID[：:]\s*(\S+)"):
    """实体 ID 提取：优先 frontmatter 的 fm_key（如 id），回退散文「XX ID：...」。
    兼容 P0001（散文）与 P0002/P0003（frontmatter）两种注册格式，不强制单一写法。"""
    fm, _, _ = parse_frontmatter(text)
    if fm.get(fm_key):
        return fm[fm_key].strip()
    m = re.search(prose_pat, text)
    return m.group(1).strip() if m else None


def _read(p):
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


def build_indexes(company_root):
    """发现并索引公司内实体（task/project/team/employee），返回 dict。"""
    root = Path(company_root)
    tasks, projects, teams, employees = {}, {}, {}, {}
    for tm in root.glob("workbench/tasks/*/task.md"):
        fm, _, _ = parse_frontmatter(_read(tm))
        tid = fm.get("id")
        if tid:
            tasks[tid] = {"fm": fm, "path": str(tm)}
    for d in root.iterdir():
        if d.is_dir() and re.match(r"^P\d+", d.name):
            pm = d / "project.md"
            if pm.is_file():
                pid = extract_id(_read(pm), "id", r"项目\s*ID[：:]\s*(\S+)")
                if pid:
                    projects[pid] = {"path": str(pm)}
        elif d.is_dir() and re.match(r"^T\d+", d.name):
            tm = d / "team.md"
            if tm.is_file():
                tid = extract_id(_read(tm), "id", r"团队\s*ID[：:]\s*(\S+)")
                if tid:
                    teams[tid] = {"path": str(tm)}
    # roster 位置真相源在 opc.toml [company.DEFAULT].roster（当前约定 E0000 总管目录）；
    # 本读取器不依赖 manifest（保持零耦合），此处按同一约定 + E0000-* 扫描兜底发现。
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


def discover_companies(opc_root):
    """列出 OPC 根下全部公司目录（含 companies/ 稳定锚，按真实路径去重）。"""
    opc_root = Path(opc_root)
    skip = {".git", "companies", ".workbuddy", "scripts", "create-company", "company-template"}
    cands, seen = [], set()
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


def selftest():
    """内置自测：frontmatter 子集契约 + extract_id 双格式。全过返回 0。"""
    ok = True

    def check(name, cond):
        nonlocal ok
        print(("  ✓ " if cond else "  ✗ ") + name)
        if not cond:
            ok = False

    print("运行内置自测…")
    NL = chr(10)
    fm, body, has = parse_frontmatter(f"---{NL}id: P0002{NL}name: 乙{NL}team: [T001, T002]{NL}---{NL}正文")
    check("基础 kv + 数组", has and fm["id"] == "P0002" and fm["team"] == ["T001", "T002"] and body == "正文")
    fm2, _, _ = parse_frontmatter(f"---{NL}empty:{NL}quoted: \"带 空格\"{NL}---{NL}")
    check("空值 None + 裸值去引号", fm2["empty"] is None and fm2["quoted"] == "带 空格")
    fm3, _, has3 = parse_frontmatter("无包裹")
    check("无包裹识别", not has3 and fm3 == {})
    fm4, _, _ = parse_frontmatter(f"---{NL}handoffs: [{{\"from\":\"E1\"}}]{NL}---{NL}")
    check("JSON 对象数组", isinstance(fm4["handoffs"], list) and fm4["handoffs"][0]["from"] == "E1")
    check("extract_id frontmatter", extract_id(f"---{NL}id: P0009{NL}---{NL}") == "P0009")
    check("extract_id 散文兜底", extract_id("项目 ID：P0001" + NL) == "P0001")
    print("自测" + ("全部通过 ✓" if ok else "存在失败 ✗"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="OPC 实体共享读取器（列出发现的公司与实体）")
    ap.add_argument("--list", action="store_true", help="列出 OPC 根下各公司与实体数量")
    ap.add_argument("--selftest", action="store_true", help="内置自测（不碰真实数据）")

    ap.add_argument("--root", default=None, help="指定 OPC 根（默认向上查找 opc.toml）")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    root = a.root or _find_opc_root()
    if not root:
        print("[ERR] 找不到 opc.toml（OPC 组织根）")
        return 1
    comps = discover_companies(root)
    if not comps:
        print("未发现任何公司（无含 company.md 的目录）")
        return 0
    for c in comps:
        idx = build_indexes(c)
        print(f"{os.path.basename(c)}: task={len(idx['task'])} project={len(idx['project'])} "
              f"team={len(idx['team'])} employee={len(idx['employee'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
