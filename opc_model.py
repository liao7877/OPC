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
import time
from contextlib import contextmanager
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


# ---- 共享小工具（2026-08-29 D2/D3 收敛：日期规整 / 告警读 / 原子写原为多份复制）----

def normalize_dt(s):
    """规整日期/日期时间为 YYYY-MM-DD[ HH:MM[:SS]]（补前导零，保证字典序=时间序）；
    无法识别返回 None。superset 版：保留时间部分（工单 due/handoffs/completed_at 用）。"""
    if not s:
        return None
    s = str(s).strip()
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T](\d{1,2}):(\d{2})(?::(\d{2}))?)?$", s)
    if not m:
        return None
    y, mo, d, h, mi, se = m.groups()
    base = "%04d-%02d-%02d" % (int(y), int(mo), int(d))
    if h is not None:
        base += " %02d:%02d" % (int(h), int(mi))
        if se:
            base += ":" + se
    return base


def normalize_day(s):
    """规整为 YYYY-MM-DD（取日期部分，worklog/事务等日粒度字段用）；无法识别返回 None。"""
    dt = normalize_dt(s)
    return dt.split(" ")[0] if dt else None


def read_text_warn(path):
    """读取文本；文件不存在是正常情况返回空串（如 messages.md 可选），存在但读取失败
    （常见为非 UTF-8 编码）则告警——内容不能静默丢失（P11）。"""
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except Exception as e:
        print(f"  [警告] 读取失败（疑似非 UTF-8 编码）：{path}（{e}），内容按空处理")
        return ""


def atomic_write(path, text):
    """P12 原子写：临时文件 + os.replace。newline="" 禁止换行符翻译
    （保证模板分发副本与源逐字节一致）。"""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    os.replace(tmp, path)


# ---- 并发互斥（2026-08-29 拍板：锁原语落地；原子写只防「写一半被读」，防不了「后写覆盖先写」）----

LOCK_STALE_SECONDS = 30.0   # 锁文件超过该秒数视为持有者崩溃残留，允许抢占


@contextmanager
def file_lock(path, timeout=10.0, poll=0.05):
    """跨平台建议锁（纯标准库）：O_EXCL 锁文件 + 忙等超时 + 过期锁抢占。

    用法：`with file_lock(target_path):` 锁文件为 target+".lock"。
    约束：只约束「同样走本锁」的写方（机制层全部走；agent 侧用 --append 命令）；
    锁内写必须经 atomic_write 落盘，临界区保持极短。
    """
    lock_path = str(path) + ".lock"
    deadline = time.monotonic() + timeout
    fd = None
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            break
        except FileExistsError:
            try:
                if time.time() - os.path.getmtime(lock_path) > LOCK_STALE_SECONDS:
                    os.unlink(lock_path)      # 持有者崩溃残留，抢占（临界区短，风险有界）
                    continue
            except OSError:
                pass                           # 锁刚好被释放，重试
            if time.monotonic() >= deadline:
                raise TimeoutError(f"获取锁超时（{timeout}s）：{lock_path}（他人持有且未过期）")
            time.sleep(poll)
    try:
        os.write(fd, str(os.getpid()).encode())
        yield
    finally:
        os.close(fd)
        try:
            os.unlink(lock_path)
        except OSError:
            pass


def locked_append(path, text):
    """锁内追加：读 → 拼 → 原子替换，全程持锁（worklog/台账等追加型写路径的标准姿势）。
    目标不存在时先创建（首条追加）。"""
    path = str(path)
    with file_lock(path):
        existing = _read(Path(path))
        atomic_write(path, existing + text)


def locked_update(path, transform):
    """锁内变换：existing → transform(existing) → 原子替换，全程持锁。
    transform 读到的 existing 是持锁快照，wid 序号分配等「依赖现内容」的写
    必须走这里（locked_append 不满足序号分配场景）。"""
    path = str(path)
    with file_lock(path):
        existing = _read(Path(path))
        atomic_write(path, transform(existing))


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


# ---------------------------------------------------------------------------
# 技能发现与索引生成（2026-08-28 Q2 拍板：技能元数据唯一真相在 SKILL.md，
# INDEX.md 是投影/生成物，登记这个动作消失）
# ---------------------------------------------------------------------------

def list_skills(layer_dir):
    """扫 {layer}/skills/*/SKILL.md -> [{name, desc, triggers, summary}]。

    triggers/summary 读 frontmatter 结构化字段；缺失时回退从 description 的
    「触发词：…」段解析（仅展示兜底，行为依赖一律以结构化字段为准）。
    """
    out = []
    sdir = Path(layer_dir) / "skills"
    if not sdir.is_dir():
        return out
    for d in sorted(sdir.iterdir()):
        sk = d / "SKILL.md"
        if not sk.is_file():
            continue
        fm, _, _ = parse_frontmatter(_read(sk))
        desc = str(fm.get("description") or "")
        triggers = fm.get("triggers")
        if not isinstance(triggers, list) or not triggers:
            m = re.search(r"触发词[：:](.+?)(?:。|$)", desc)
            triggers = [w.strip(" 、，,;；") for w in re.split(r"[、，,;；/]", m.group(1))
                        if w.strip(" 、，,;；")] if m else []
        summary = str(fm.get("summary") or (desc.split("。")[0] + "。" if desc else ""))
        out.append({"name": str(fm.get("name") or d.name),
                    "desc": desc, "triggers": triggers, "summary": summary})
    return out


def _skill_layers_with_scope(company_dir):
    """公司内全部技能层 -> [(layer_path, is_company_level)]。
    公司根层=公司级；实体层（E*/T*/templates 子目录）=私有/团队级；
    templates/ 下的二级骨架层（employee-template）也算一层（建司模板自带索引）。"""
    layers = []
    if not Path(company_dir).is_dir():
        return layers
    if (Path(company_dir) / "skills").is_dir():
        layers.append((str(company_dir), True))
    for d in sorted(Path(company_dir).iterdir()):
        if d.name.startswith(".") or not d.is_dir():
            continue
        if (d / "skills").is_dir():
            layers.append((str(d), False))
        elif d.name == "templates":   # 二级骨架层
            for sub in sorted(d.iterdir()):
                if sub.is_dir() and (sub / "skills").is_dir():
                    layers.append((str(sub), False))
    return layers


def sync_index(root, cid=None):
    """把各层技能清单写成 skills/INDEX.md（生成物：头部声明「勿手改」）。

    层级口径：公司根层 INDEX 只列公司级技能；实体层 INDEX 列「本层私有 +
    公司级」（与既有手工 INDEX 的发现口径一致——私有技能平台披露覆盖不到，
    公司级是全员可用）。路径列：公司级用 opc:// 符号（resolver 可校验），
    私有用层内相对路径。返回写入的 INDEX 路径列表。
    """
    root = Path(root)
    targets = []
    comp_dirs = [Path(c) for c in discover_companies(str(root))]
    tpl = root / "company-template"
    if tpl.is_dir() and (tpl / "company.md").is_file():
        comp_dirs.append(tpl)   # 建司母版同样生成（其 ID 是占位符，路径一律走相对）
    for comp in comp_dirs:
        comp = Path(comp)
        # 公司身份提取统一走 resolver 公开 API（P25/P26；惰性 import 保持本模块零耦合立场）
        import opc_resolver
        cid_here = opc_resolver.extract_company_id(_read(comp / "company.md"))
        if not cid_here or not re.match(r"^C\d+$", cid_here):
            cid_here = None      # 模板占位符/非法 ID：不用 opc://，全走相对路径
        if cid and cid_here != cid:
            continue
        company_skills = None
        for layer, is_company in _skill_layers_with_scope(comp):
            skills = list_skills(layer)
            if is_company:
                company_skills = skills
                rows = skills
            else:
                rows = skills + (company_skills or [])
            if not rows:
                continue
            lines = [
                "<!-- 本文件由 `python opc_model.py --sync-index` 生成，勿手改。",
                "     技能元数据的唯一真相在各 SKILL.md frontmatter（triggers/summary）。",
                f"     重新生成：python opc_model.py --sync-index{(' --company ' + cid_here) if cid_here else ''} -->",
                "",
                f"# 技能披露索引（{Path(layer).name if not is_company else '公司级'}）",
                "",
                "| 技能 | 触发词（命中即加载） | 摘要 | 路径 |",
                "|---|---|---|---|",
            ]
            for s in rows:
                if is_company:
                    path = f"opc://company:{cid_here}/skill/{s['name']}" if cid_here else f"skills/{s['name']}/SKILL.md"
                else:
                    own = {x["name"] for x in skills}
                    path = (f"opc://company:{cid_here}/skill/{s['name']}"
                            if s["name"] not in own and cid_here else f"skills/{s['name']}/SKILL.md")
                lines.append("| **%s** | %s | %s | `%s` |" % (
                    s["name"], "、".join(s["triggers"]) or "—",
                    s["summary"] or s["desc"][:40], path))
            lines.append("")
            idx = Path(layer) / "skills" / "INDEX.md"
            tmp = str(idx) + ".tmp"
            with open(tmp, "w", encoding="utf-8", newline="") as fh:
                fh.write("\n".join(lines))
            os.replace(tmp, idx)
            targets.append(str(idx))
    return targets


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
    """内置自测：frontmatter 子集契约 + extract_id 双格式 + 技能发现。全过返回 0。"""
    import tempfile
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
    check("normalize_dt 带时间补零", normalize_dt("2026-8-1 9:05") == "2026-08-01 09:05")
    check("normalize_day 取日期部分", normalize_day("2026-8-1 9:05") == "2026-08-01")
    check("normalize 非法返回 None", normalize_dt("abc") is None)
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "aw.txt"
        atomic_write(str(f), "原子写内容")
        check("atomic_write 写后可读回", f.read_text(encoding="utf-8") == "原子写内容")
    # 并发锁：互斥 / 超时 / 过期抢占
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "wl.md"
        f.write_text("第一块\n", encoding="utf-8")
        with file_lock(f):
            try:
                with file_lock(f, timeout=0.1):
                    check("锁互斥：持有中不可再取", False)
            except TimeoutError:
                check("锁互斥：持有中不可再取", True)
        with file_lock(f):
            pass
        check("锁释放后可再取", True)
        stale = Path(str(f) + ".lock")
        stale.write_text("x", encoding="utf-8")
        old_ts = time.time() - LOCK_STALE_SECONDS - 5
        os.utime(stale, (old_ts, old_ts))
        with file_lock(f, timeout=1.0):
            pass
        check("过期锁自动抢占", not stale.exists())
        locked_append(f, "第二块\n")
        locked_append(f, "第三块\n")
        check("locked_append 追加有序", f.read_text(encoding="utf-8") == "第一块\n第二块\n第三块\n")
    # 技能发现：triggers/summary 结构化字段 + description 兜底解析
    with tempfile.TemporaryDirectory() as tmp:
        sk = Path(tmp) / "skills" / "demo"
        sk.mkdir(parents=True)
        (sk / "SKILL.md").write_text(
            f"---{NL}name: demo{NL}description: 演示技能。触发词：建单、流转{NL}"
            f"summary: 演示用。{NL}triggers: [建单, 流转]{NL}---{NL}正文", encoding="utf-8")
        sk2 = Path(tmp) / "skills" / "legacy"
        sk2.mkdir(parents=True)
        (sk2 / "SKILL.md").write_text(
            f"---{NL}name: legacy{NL}description: 旧技能无结构化字段。触发词：查询、导出。详情略{NL}---{NL}正文", encoding="utf-8")
        got = {s["name"]: s for s in list_skills(tmp)}
        check("list_skills 结构化 triggers", got["demo"]["triggers"] == ["建单", "流转"] and got["demo"]["summary"] == "演示用。")
        check("list_skills description 兜底", got["legacy"]["triggers"] == ["查询", "导出"])
    print("自测" + ("全部通过 ✓" if ok else "存在失败 ✗"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="OPC 实体共享读取器（列出发现的公司与实体 / 技能索引生成）")
    ap.add_argument("--list", action="store_true", help="列出 OPC 根下各公司与实体数量")
    ap.add_argument("--list-skills", action="store_true", help="列出全部技能层 skills/*/SKILL.md 元数据（name/triggers/summary）")
    ap.add_argument("--sync-index", action="store_true", help="把各层技能清单写成 skills/INDEX.md（生成物，勿手改）")
    ap.add_argument("--append", nargs=2, metavar=("目标文件", "内容文件"),
                    action="store", help="锁内追加：把内容文件追加到目标（多会话安全；内容文件为 - 时读 stdin）")
    ap.add_argument("--company", default=None, help="限定公司 ID（--sync-index 用）")
    ap.add_argument("--selftest", action="store_true", help="内置自测（不碰真实数据）")

    ap.add_argument("--root", default=None, help="指定 OPC 根（默认向上查找 opc.toml）")
    a = ap.parse_args()
    if a.selftest:
        return selftest()
    root = a.root or _find_opc_root()
    if not root:
        print("[ERR] 找不到 opc.toml（OPC 组织根）")
        return 1
    if a.append:
        target, src = a.append
        content = sys.stdin.read() if src == "-" else _read(Path(src))
        if not content:
            print("[ERR] 内容为空（文件不存在或 stdin 无输入）")
            return 1
        locked_append(target, content)
        print(f"[ok] 已锁内追加 {len(content)} 字符 -> {target}")
        return 0
    if a.sync_index:
        wrote = sync_index(root, a.company)
        print(f"[done] 已生成 {len(wrote)} 份 skills/INDEX.md：")
        for p in wrote:
            print("  -", p)
        return 0
    if a.list_skills:
        for comp in discover_companies(root):
            for layer, is_company in _skill_layers_with_scope(comp):
                tag = "公司级" if is_company else Path(layer).name
                for s in list_skills(layer):
                    print(f"[{tag}] {s['name']} | 触发词: {'、'.join(s['triggers']) or '—'} | {s['summary']}")
        return 0
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
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")   # Windows cp1252 控制台/CI 下中文输出防崩（CI 实测）
    sys.exit(main())
