#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
opc_tickets.py —— 工单看板数据生成器（机制层，OPC 根单例）

> 2026-08-28 机制上提（廖哥拍板）：原 `workbench/generate_tasks.py` 从各公司目录
> 收敛到本模块。公司目录不再持有机制代码，只留数据（workbench/tasks/）与薄壳入口
> （run_boards.*）。修 bug 一处生效、开新公司零代码复制。

职责（单一）：
  - 扫描 workbench/tasks/ 下工单目录，解析 task.md，产出 tasks-data.json + tasks-data.js
  - 关系校验（blocked_by / parent / 交接链 / 升级信箱），只告警不阻断
  - --new 建单（含自动 worklog 建账）、--check-structure 结构契约自检

用法（cwd 无关，公司由 manifest 解析）：
    python opc_tickets.py --company C001                # 生成该公司数据
    python opc_tickets.py --dir <公司根目录>             # 按目录反查公司 ID（run_boards 用）
    python opc_tickets.py --company C001 --new TSK00001 标题 [--owner E0001] [--project P0001]
    python opc_tickets.py --company C001 --watch        # 监听 tasks/ 变动自动重跑
    python opc_tickets.py --company C001 --check-structure
    python opc_tickets.py --selftest                    # 内置自测（临时目录，不碰真实数据）

设计要点：
- 单一真相：workbench/tasks/ 为唯一数据源；看板是投影。
- 物理路径唯一真相源在 opc.toml（经 opc_resolver.load_company 解析），本模块零硬编码公司 ID。
- 离线友好：详情数据全部内联进 JSON（file:// 下浏览器无法 fetch 本地文件）。
- 容错：缺字段 / 坏 frontmatter 的工单跳过并告警，不中断整体生成。
"""

import os
import sys
import re
import json
import time
import datetime

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
from opc_model import parse_frontmatter          # 共享读取器（P25，禁私写正则）
import opc_resolver
from opc_schema import (TASK_STATUS as VALID_STATUS,          # 状态机唯一真相源（opc_schema）
                        TASK_STATUS_ORDER as STATUS_ORDER,
                        TASK_TERMINAL)


class Ctx:
    """一次生成的路径上下文（不可变，杜绝模块级可变全局）。
    company_dir=公司根；wb_dir=workbench；tasks_dir=工单目录；out_json/out_js=产物。"""

    def __init__(self, company_dir, wb_dir, tasks_dir, out_json, out_js):
        self.company_dir = company_dir
        self.wb_dir = wb_dir
        self.tasks_dir = tasks_dir
        self.out_json = out_json
        self.out_js = out_js


def resolve_ctx(company=None, company_dir=None):
    """--company CID（走 manifest）或 --dir 目录（反查 ID）。返回 Ctx。"""
    if company is None:
        if not company_dir:
            raise ValueError("需要 --company <cid> 或 --dir <公司根目录>")
        company_dir = os.path.abspath(company_dir)
        md = os.path.join(company_dir, "company.md")
        company = opc_resolver.extract_company_id(opc_resolver.read_text(md))
        if not company:
            raise FileNotFoundError(f"{md} 缺「公司 ID」声明，无法反查公司")
    cfg = opc_resolver.load_company(company)
    if not os.path.isdir(cfg.home_abs):
        raise FileNotFoundError(
            f"公司 {company} 根不存在：{cfg.home_abs}（锚未建或目录被删）"
            f"→ 在 OPC 根跑 `python opc_resolver.py --sync-links` 重建锚")
    wb = cfg._abs("workbench")
    return Ctx(cfg.home_abs, wb, os.path.join(wb, "tasks"),
               cfg._abs("tasks_data"),
               os.path.join(wb, "tasks-data.js"))


# ---- 基础工具 ----

def list_files(tasks_dir, directory):
    """列出 directory 下所有文件，rel_path 相对 tasks_dir（产物内引用稳定）。"""
    result = []
    if not os.path.isdir(directory):
        return result
    for root, _dirs, files in os.walk(directory):
        for f in files:
            full = os.path.join(root, f)
            rel = os.path.relpath(full, tasks_dir)
            result.append({"name": f, "rel_path": rel.replace(os.sep, "/")})
    result.sort(key=lambda x: x["rel_path"])
    return result


def read_text(path):
    if not os.path.isfile(path):
        return ""  # 文件不存在是正常情况（如 messages.md 可选），不告警
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except Exception as e:
        # 文件存在但读取失败：常见原因是非 UTF-8 编码（如 GBK）。告警避免内容静默丢失。
        print(f"  [警告] 读取失败（疑似非 UTF-8 编码）：{path}（{e}），内容按空处理")
        return ""


def dir_prefix_id(dirname):
    """从目录名 'TSK00001-标题' 提取 TSK00001。"""
    if "-" in dirname:
        return dirname.split("-", 1)[0]
    return dirname


def dir_title(dirname):
    if "-" in dirname:
        return dirname.split("-", 1)[1]
    return dirname


def build_input_item(ctx, dirname, idx, path, name):
    """构造单个输入物条目 {name, path, valid}。
    path 为相对 workbench/ 的引用（不复制文件，保持单一真相）；
    校验存在性：失效告警但不阻断（工单仍上板，详情标 ⚠️）。"""
    if not name:
        name = os.path.basename(path.rstrip("/\\")) or path
    valid = True
    if path:
        full = os.path.normpath(os.path.join(ctx.wb_dir, path))
        valid = os.path.exists(full)
        if not valid:
            print(f"  [警告] {dirname} inputs[{idx}] 路径不存在：{path}")
    return {"name": name, "path": path, "valid": valid}


def normalize_date(s):
    """规整日期为 YYYY-MM-DD 或 YYYY-MM-DD HH:MM[:SS]（补前导零，保证字典序=时间序）；
    无法识别返回 None。"""
    if not s:
        return None
    s = s.strip()
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


def build_record(ctx, task_dir, dirname):
    task_md = os.path.join(task_dir, "task.md")
    if not os.path.isfile(task_md):
        print(f"  [跳过] {dirname}/ 缺少 task.md")
        return None
    raw = read_text(task_md)
    fm, body, has_fm = parse_frontmatter(raw)
    if not has_fm:
        print(f"  [跳过] {dirname}/task.md 缺少 frontmatter（无 --- 包裹），视为坏文件，跳过")
        return None
    status = fm.get("status")
    if status not in VALID_STATUS:
        print(f"  [跳过] {dirname}/task.md status={status!r} 非法，跳过该工单")
        return None

    tid = fm.get("id") or dir_prefix_id(dirname)
    dir_id = dir_prefix_id(dirname)
    if fm.get("id") and dir_id and fm["id"] != dir_id:
        print(f"  [警告] {dirname} frontmatter id={fm['id']} 与目录名前缀 {dir_id} 不一致，以 id 为准（建议统一，避免看板与目录对不上）")
    if dir_id and not re.match(r"^TSK\d+$", dir_id):
        print(f"  [警告] {dirname} 目录名不是规范格式（TSKxxx-标题），当前前缀 {dir_id!r}")
    if tid and not re.match(r"^TSK\d+$", tid):
        print(f"  [警告] {dirname} id={tid!r} 不是规范编号格式（TSKxxx），建议修改")
    title = fm.get("title") or dir_title(dirname)

    # owner / project 容许空
    owner = fm.get("owner")
    project = fm.get("project")
    # 名称兜底字段（工单自包含）：当 owner/project 代号在目录注册表中尚不存在时使用
    owner_name = fm.get("owner_name")
    project_name = fm.get("project_name")

    # 列表型字段
    tags = fm.get("tags")
    if not isinstance(tags, list):
        tags = [tags] if tags else []

    # 实际完成时间：status=done 时应填写；未填则告警提示（不跳过）
    completed_at = fm.get("completed_at")
    if completed_at:
        c_norm = normalize_date(completed_at)
        if c_norm is None:
            print(f"  [警告] {dirname} completed_at={completed_at!r} 非日期格式，按原样保留")
        else:
            completed_at = c_norm
    if status == "done" and not completed_at:
        print(f"  [警告] {dirname} status=done 但未填 completed_at（实际完成时间），建议补填以便统计按期/逾期")

    # due 规整（与 completed_at / handoffs at 一致，保证排序与比较正确）
    due = fm.get("due")
    if due:
        due_n = normalize_date(due)
        if due_n is None:
            print(f"  [警告] {dirname} due={due!r} 非日期格式，按原样保留")
        else:
            due = due_n

    # 时间逻辑校验：due / completed_at 不应早于 created
    created = fm.get("created")
    if due and created:
        due_n, created_n = normalize_date(due), normalize_date(created)
        if due_n and created_n and due_n < created_n:
            print(f"  [警告] {dirname} due({due}) 早于 created({created})，截止日应在创建之后")
    if completed_at and created:
        c_n2, created_n2 = normalize_date(completed_at), normalize_date(created)
        if c_n2 and created_n2 and c_n2 < created_n2:
            print(f"  [警告] {dirname} completed_at({completed_at}) 早于 created({created})，逻辑异常")

    # 流转链（F1）：handoffs 数组，每条 {from, to, at, reason}
    handoffs = []
    raw_h = fm.get("handoffs")
    if isinstance(raw_h, list):
        for idx, item in enumerate(raw_h):
            if isinstance(item, dict):
                at_raw = str(item.get("at") or "")
                at_norm = normalize_date(at_raw) if at_raw else ""
                if at_raw and at_norm is None:
                    print(f"  [警告] {dirname} handoffs[{idx}] at={at_raw!r} 非日期格式，按原样保留")
                    at_norm = at_raw
                handoffs.append({
                    "from": str(item.get("from") or ""),
                    "to": str(item.get("to") or ""),
                    "at": at_norm,
                    "reason": str(item.get("reason") or ""),
                })
            elif isinstance(item, str) and item.strip():
                seg = item.split("->")
                handoffs.append({
                    "from": seg[0].strip() if seg else "",
                    "to": seg[1].strip() if len(seg) > 1 else "",
                    "at": "",
                    "reason": "",
                })
    # 流转链一致性校验（告警不阻断，避免"时间轴终点≠当前负责人"的自相矛盾数据上板无人知）
    if handoffs:
        last_h = handoffs[-1]
        if last_h["to"] and owner and last_h["to"] != owner:
            print(f"  [警告] {dirname} handoffs 最后交接给 {last_h['to']}，但当前 owner={owner!r}，二者不一致（漏改 owner 或漏记交接？）")
        if last_h["from"] and last_h["from"] == last_h["to"]:
            print(f"  [警告] {dirname} handoffs 最后一条 from==to（{last_h['from']}），无意义流转")
    # 流转链时间顺序校验（倒序提示）
    prev_at = ""
    for h in handoffs:
        if h["at"]:
            if prev_at and h["at"] < prev_at:
                print(f"  [警告] {dirname} handoffs 时间倒序：{prev_at} -> {h['at']}（流转链应按时间排列）")
            prev_at = h["at"]
    # 参与者（F5-②）：当前 owner + 流转链所有 from/to 去重
    participants = []
    for h in handoffs:
        for k in (h["from"], h["to"]):
            if k and k not in participants:
                participants.append(k)
    if owner and owner not in participants:
        participants.append(owner)
    # 最近一次流转时间（F5-④ 高亮依据；YYYY-MM-DD 字典序即时间序）
    last_handoff_at = ""
    for h in handoffs:
        if h["at"] and h["at"] > last_handoff_at:
            last_handoff_at = h["at"]
    # 预留字段（F2）：parent / children / links 空着不报错，未来扩展 C
    parent = fm.get("parent")
    if parent:
        parent = str(parent).strip()
    children = fm.get("children")
    if not isinstance(children, list):
        children = [children] if children else []
    links = fm.get("links")
    if not isinstance(links, list):
        links = [links] if links else []

    # 前置阻塞（机制扩展 #3）：blocked_by 单行数组，所列工单全部 done 前不得开工
    blocked_by = fm.get("blocked_by")
    if not isinstance(blocked_by, list):
        blocked_by = [blocked_by] if blocked_by else []
    blocked_by = [str(b).strip() for b in blocked_by if str(b).strip()]

    # 输入物：结构化引用外部文件（相对 workbench/ 基准，不复制不漂移）
    inputs = []
    raw_in = fm.get("inputs")
    if isinstance(raw_in, list):
        for idx, item in enumerate(raw_in):
            if isinstance(item, dict):
                path = str(item.get("path") or "").strip()
                name = str(item.get("name") or "").strip()
                inputs.append(build_input_item(ctx, dirname, idx, path, name))
            elif isinstance(item, str) and item.strip():
                inputs.append(build_input_item(ctx, dirname, idx, item.strip(), ""))

    # 状态变更时间线（可选）：status_history: [{to, at}] 记录状态何时切换（审计补充）
    status_history = []
    raw_sh = fm.get("status_history")
    if isinstance(raw_sh, list):
        for idx, item in enumerate(raw_sh):
            if isinstance(item, dict):
                to = str(item.get("to") or item.get("status") or "")
                at = str(item.get("at") or "")
                at_norm = normalize_date(at) if at else ""
                if at and at_norm is None:
                    print(f"  [警告] {dirname} status_history[{idx}] at={at!r} 非日期格式，按原样保留")
                    at_norm = at
                status_history.append({"to": to, "at": at_norm})
            elif isinstance(item, str) and item.strip():
                seg = item.split("@")
                status_history.append({"to": seg[0].strip(), "at": seg[1].strip() if len(seg) > 1 else ""})

    return {
        "id": tid,
        "title": title,
        "status": status,
        "owner": owner,
        "project": project,
        "owner_name": owner_name,
        "project_name": project_name,
        "priority": fm.get("priority"),
        "type": fm.get("type"),
        "due": due,
        "tags": tags,
        "created": fm.get("created"),
        "updated": fm.get("updated"),
        "completed_at": completed_at,
        "description": body,
        "messages": read_text(os.path.join(task_dir, "messages.md")),
        "escalations": extract_escalations(read_text(os.path.join(task_dir, "messages.md"))),
        "deliverables": list_files(ctx.tasks_dir, os.path.join(task_dir, "deliverables")),
        "logs": list_files(ctx.tasks_dir, os.path.join(task_dir, "logs")),
        "handoffs": handoffs,
        "participants": participants,
        "last_handoff_at": last_handoff_at,
        "parent": parent,
        "children": children,
        "links": links,
        "blocked_by": blocked_by,
        "inputs": inputs,
        "status_history": status_history,
    }


def extract_escalations(messages_text):
    """升级信箱识别（机制扩展 #18）：messages.md 中
    「[escalate: 原因] (日期)」标记行 -> [{reason, date}]。
    员工→总管的异步上报通道（workbuddy 子代理限制兜底）：总管处理时删除该行。"""
    out = []
    for m in re.finditer(r"^\s*\[escalate:\s*([^\]]+)\]\s*\(?(\d{4}-\d{2}-\d{2})?\)?\s*$", messages_text or "", re.M):
        out.append({"reason": m.group(1).strip(), "date": m.group(2) or ""})
    return out


def build_registry(ctx, tasks):
    """构建 员工/项目 代号→名称 映射（双来源，按优先级合并）：
      1) 公司根目录扫描（文件系统即真相，总管建的 E*/P* 目录）——权威来源；
      2) 各工单 task.md 声明的 owner_name / project_name——兜底来源。
    合并规则：目录优先；仅当某代号在目录中查不到时，才用该工单声明的名称补全。"""
    emp, proj = {}, {}
    for name in sorted(os.listdir(ctx.company_dir)) if os.path.isdir(ctx.company_dir) else []:
        full = os.path.join(ctx.company_dir, name)
        if not os.path.isdir(full):
            continue
        if re.match(r"^E\d{3,}-", name):
            code = name.split("-", 1)[0]
            label = name.split("-", 1)[1] if "-" in name else name
            if label.startswith("AI员工-"):
                label = label[len("AI员工-"):]
            emp[code] = label
        elif re.match(r"^P\d{3,}-", name):
            code = name.split("-", 1)[0]
            label = name.split("-", 1)[1] if "-" in name else name
            proj[code] = label
    # 来源2：工单声明兜底（引用了尚未建目录的代号时也能显示名称）
    for t in tasks:
        if t.get("owner") and t.get("owner_name") and t["owner"] not in emp:
            emp[t["owner"]] = t["owner_name"]
        if t.get("project") and t.get("project_name") and t["project"] not in proj:
            proj[t["project"]] = t["project_name"]
    return emp, proj


def generate(ctx):
    """扫描 ctx.tasks_dir 生成 ctx.out_json / ctx.out_js。"""
    tasks = []
    seen_ids = {}
    if os.path.isdir(ctx.tasks_dir):
        for name in sorted(os.listdir(ctx.tasks_dir)):
            full = os.path.join(ctx.tasks_dir, name)
            if os.path.isdir(full):
                rec = build_record(ctx, full, name)
                if rec:
                    if rec["id"] in seen_ids:
                        print(f"  [跳过] {name} id={rec['id']} 与 {seen_ids[rec['id']]} 重复，跳过该工单（避免看板 data-id 冲突点开错单）")
                        continue
                    seen_ids[rec["id"]] = name
                    tasks.append(rec)
    else:
        print(f"  [警告] tasks 目录不存在：{ctx.tasks_dir}")

    # 排序：状态顺序 -> 组内更新时间倒序（最新在前）-> id
    # 两次稳定排序：先按 updated 倒序，再按状态顺序（稳定排序保持组内 updated 倒序）
    tasks.sort(key=lambda t: t.get("updated") or t.get("created") or "", reverse=True)
    tasks.sort(key=lambda t: STATUS_ORDER.index(t["status"]) if t["status"] in STATUS_ORDER else 99)

    emp_reg, proj_reg = build_registry(ctx, tasks)

    # 引用校验：owner/project 指向目录中不存在的代号、且工单未提供兜底名 → 告警
    # （先派活后建目录是允许的，此时工单应写 owner_name/project_name 自包含；两者皆无则回退裸代号）
    for t in tasks:
        if t.get("owner") and t["owner"] not in emp_reg and not t.get("owner_name"):
            print(f"  [警告] {t['id']} owner={t['owner']} 未在公司目录中找到且未提供 owner_name，看板将回退显示裸代号（建议建目录或补 owner_name）")
        if t.get("project") and t["project"] not in proj_reg and not t.get("project_name"):
            print(f"  [警告] {t['id']} project={t['project']} 未在公司目录中找到且未提供 project_name，看板将回退显示裸代号（建议建目录或补 project_name）")

    # ---- 关系校验（机制扩展 #3/#5）：阻塞引用 + 父单闭环，只告警不阻断 ----
    tmap = {t["id"]: t for t in tasks if t.get("id")}
    children_map = {}
    for t in tasks:
        if t.get("parent"):
            children_map.setdefault(t["parent"], []).append(t["id"])
    for t in tasks:
        # blocked_by 引用有效性
        for b in t.get("blocked_by", []):
            up = tmap.get(b)
            if up is None:
                print(f"  [警告] {t['id']} blocked_by 引用的工单 {b} 不存在（找总管核对编号；上游取消则确认本单是否还做）")
            elif up["status"] == "cancelled":
                print(f"  [警告] {t['id']} 的前置工单 {b} 已 cancelled（需求可能变更，向总管确认本单是否还做）")
        # 阻塞未清就开工 → 告警
        if t["status"] in ("in_progress", "review", "done"):
            unmet = [b for b in t.get("blocked_by", [])
                     if tmap.get(b) and tmap[b]["status"] != "done"]
            if unmet:
                print(f"  [警告] {t['id']} 状态为 {t['status']} 但前置阻塞未清：{unmet}（开工前 blocked_by 应全部 done）")
        # 解锁提示（总管轻巡检信号源）：阻塞全部满足且本单还在 backlog
        if t["status"] == "backlog" and t.get("blocked_by"):
            unmet2 = [b for b in t["blocked_by"] if not (tmap.get(b) and tmap[b]["status"] == "done")]
            if not unmet2:
                print(f"  [提示] {t['id']} 前置阻塞已全部完成，可解锁开工（通知 owner={t.get('owner') or '?'}）")
        # 父单引用有效性
        if t.get("parent") and t["parent"] not in tmap:
            print(f"  [警告] {t['id']} parent 指向的父单 {t['parent']} 不存在（核对编号笔误）")
        # 父单闭环铁律：type=需求 的父单 done 时子单应全部 done
        if t.get("type") == "需求" and t["status"] == "done":
            kids = children_map.get(t["id"], [])
            not_done = [k for k in kids if tmap.get(k) and tmap[k]["status"] != "done"]
            if not_done:
                print(f"  [警告] 父单 {t['id']} 已 done 但子单未全部完成：{not_done}（父单只有子单全 done 才能 done）")

    # 升级信箱（机制扩展 #18）：待处理升级告警（总管巡检信号源，处理完删除标记行即消除）
    for t in tasks:
        for esc in t.get("escalations", []):
            print(f"  [告警] 升级待处理：{t['id']}「{t['title']}」owner={t.get('owner') or '?'} 请求：{esc['reason']}"
                  + (f"（{esc['date']}）" if esc["date"] else ""))

    payload = {
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": "workbench/tasks/",
        "status_meta": {k: v for k, v in VALID_STATUS.items()},
        "employees": emp_reg,
        "projects": proj_reg,
        "tasks": tasks,
        # 页面导航链接（kanban.html 的「公司驾驶舱」按钮等）由生成器按落位产出：
        # kanban.html 在 workbench/ 下，公司根 dashboard 即 ../dashboard.html
        "links": {"dashboard": "../dashboard.html"},
    }

    def _atomic_write(path, text):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.replace(tmp, path)

    _atomic_write(ctx.out_json, json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"  [完成] 生成 {len(tasks)} 条工单 -> {ctx.out_json}")

    # 兼容 file:// 双击打开：浏览器禁止 fetch 本地 JSON（CORS），
    # 故额外产出 tasks-data.js，把数据挂到全局变量，HTML 用 <script> 引入即可离线加载。
    # 防御：task.md 内容若含 </script> 会破坏 JS 字面量，需转义为 <\/script。
    js_text = "window.KANBAN_DATA = " + json.dumps(payload, ensure_ascii=False, indent=2) + ";\n"
    js_text = js_text.replace("</script", "<\\/script")
    _atomic_write(ctx.out_js, js_text)
    print(f"  [完成] 生成浏览器数据 -> {ctx.out_js}")
    return len(tasks)


def tasks_mtime(ctx):
    """tasks 目录树最新修改时间（用于监听）。"""
    latest = 0
    for root, _dirs, files in os.walk(ctx.tasks_dir):
        for f in files:
            try:
                m = os.path.getmtime(os.path.join(root, f))
                latest = max(latest, m)
            except OSError:
                pass
    return latest


def safe_generate(ctx):
    """generate 的容错包装：单次生成失败不中断 --watch 监听。"""
    try:
        generate(ctx)
    except Exception as e:
        print(f"  [错误] 生成失败：{e}，继续监听…")


def watch(ctx):
    print(f"监听中：{ctx.tasks_dir} （每 3 秒检测变动，Ctrl+C 退出）")
    last = tasks_mtime(ctx)
    safe_generate(ctx)
    try:
        while True:
            time.sleep(3.0)
            cur = tasks_mtime(ctx)
            if cur != last:
                last = cur
                print(f"\n[{datetime.datetime.now().strftime('%H:%M:%S')}] 检测到变动，重新生成…")
                safe_generate(ctx)
    except KeyboardInterrupt:
        print("\n已停止监听。")


def new_task(ctx, argv):
    """--new <TSKxxx> <标题> [--owner E0001] [--project P0001] [--parent x] [--blocked-by a,b]
    生成规范工单模板目录（含 task.md），降低 Agent 建单出错率。"""
    rest = argv[argv.index("--new") + 1:]
    if not rest:
        print("用法：opc_tickets.py --new <TSKxxx> <标题> [--owner E0001] [--project P0001]")
        return 1
    tid = rest[0]
    if not re.match(r"^TSK\d+$", tid):
        print(f"错误：编号 {tid!r} 不规范，应为 TSKxxx（如 TSK00009）")
        return 1
    owner, project = "", ""
    parent, blocked_by = "", []
    title_parts, i = [], 1
    while i < len(rest):
        a = rest[i]
        if a == "--owner" and i + 1 < len(rest):
            owner, i = rest[i + 1], i + 2
            continue
        if a == "--project" and i + 1 < len(rest):
            project, i = rest[i + 1], i + 2
            continue
        if a == "--parent" and i + 1 < len(rest):
            parent, i = rest[i + 1], i + 2
            continue
        if a == "--blocked-by" and i + 1 < len(rest):
            blocked_by = [x.strip() for x in re.split(r"[，,]", rest[i + 1]) if x.strip()]
            i += 2
            continue
        if a.startswith("--"):
            print(f"未知选项：{a}")
            return 1
        title_parts.append(a)
        i += 1
    title = " ".join(title_parts).strip() or "待定标题"
    # 半角冒号会污染 frontmatter（解析器按第一个冒号切分），替换为全角
    if ":" in title:
        print(f"  [警告] 标题含半角冒号，已替换为全角冒号（避免污染 frontmatter）：{title}")
        title = title.replace(":", "：")
    safe_title = re.sub(r'[\\/:*?"<>|]', "-", title)  # Windows 文件名非法字符
    task_dir = os.path.join(ctx.tasks_dir, f"{tid}-{safe_title}")
    if os.path.exists(task_dir):
        print(f"错误：目录已存在：{task_dir}")
        return 1
    os.makedirs(task_dir)
    today = datetime.date.today().strftime("%Y-%m-%d")
    parent_line = f"\nparent: {parent}" if parent else ""
    blocked_line = "\nblocked_by: [" + ", ".join(blocked_by) + "]" if blocked_by else ""
    tpl = (
        f"---\n"
        f"id: {tid}\n"
        f"title: {title}\n"
        f"status: backlog\n"
        f"owner: {owner}\n"
        f"project: {project}\n"
        f"priority: 中\n"
        f"type: 任务\n"
        f"due: \n"
        f"tags: []\n"
        f"created: {today}\n"
        f"updated: {today}\n"
        f"{parent_line}"
        f"{blocked_line}\n"
        f"---\n\n"
        f"（描述：这个工单要做什么、目标是什么）\n"
    )
    with open(os.path.join(task_dir, "task.md"), "w", encoding="utf-8") as fh:
        fh.write(tpl)
    print(f"已创建工单：{task_dir}")
    append_worklog_entry(ctx, owner, tid, title, project)
    print("已自动重算看板数据（建单即上板），可打开 kanban.html 查看。")
    safe_generate(ctx)
    return 0


def append_worklog_entry(ctx, owner, tid, title, project):
    """建单即建账（P0-1，2026-08-27 拍板）：指定 owner 建单时，
    自动在其 workspace/worklog.md 追加「计划中」条目（含 ticket）。
    双账从源头一致；员工开工只需推进状态。owner 为空或目录不存在则跳过。"""
    if not owner:
        return
    emp_dirs = [d for d in os.listdir(ctx.company_dir)
                if d.startswith(owner + "-") and os.path.isdir(os.path.join(ctx.company_dir, d))]
    if not emp_dirs:
        print(f"  [提示] 未找到 {owner} 的员工目录，跳过自动建账（该员工接单时按 worklog-discipline 自行补记）")
        return
    wl = os.path.join(ctx.company_dir, emp_dirs[0], "workspace", "worklog.md")
    day = datetime.date.today().strftime("%Y%m%d")
    today = day[:4] + "-" + day[4:6] + "-" + day[6:]
    existing = read_text(wl)
    seq = len(re.findall(r"^wid: W-%s-" % day, existing, re.M)) + 1
    block = (
        f"\n---\nwid: W-{day}-{seq:02d}\ndate: {today}\ntitle: {title}\n"
        f"status: 计划中\ntype: 工单\nticket: {tid}\nproject: {project}\nupdated: {today}\n---\n"
    )
    # 追加容错：自动建账失败不阻断建单主流程（员工可按 skill 自行补记）
    # 原子写（P12）：并发会话下不直接对旧文件盲追加，读→拼→临时文件→替换
    try:
        os.makedirs(os.path.dirname(wl), exist_ok=True)
        tmp = wl + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(existing + block)
        os.replace(tmp, wl)
        print(f"已自动建账：{emp_dirs[0]}/workspace/worklog.md 新增「计划中」条目（ticket={tid}）")
    except Exception as e:
        print(f"  [警告] 自动建账失败（{e}），请该员工按 worklog-discipline 技能自行补记")


def check_structure(ctx):
    """--check-structure：结构契约自检（机制扩展 #9）。
    校验公司根一级结构是否符合《目录结构说明书.md》声明的契约：
    必需目录/文件缺失 → 告警；出现未登记的一级条目 → 告警（防结构漂移）。
    注：生成器已上提 OPC 根（opc_tickets/opc_dashboards），公司根出现 generate_*.py
    即为历史遗留副本，会被作为未登记条目报出（机制代码不落公司目录）。"""
    company = ctx.company_dir
    required_dirs = ["skills", "workbench", "templates", "page-templates", "公司规章制度", "公司知识库"]
    required_files = ["company.md", "AGENTS.md", "CLAUDE.md", "workflow.md", "目录结构说明书.md"]
    # 已知一级条目：文件用模式匹配（跨平台入口脚本 .bat/.sh/.ps1/.py 等都认，P2a）
    known_extra_dirs = {".workbuddy", ".tools"}
    known_extra_file_patterns = [re.compile(p) for p in (
        r"^run_boards\.(bat|sh|command)$", r"^register-task\.ps1$", r"^register-patrol\.(ps1|sh)$",
        r"^verify_boards\.(js|py)$", r"^(dashboard|目录结构说明书)\.(html|md)$", r"^dashboard-data\.js$",
    )]
    entity_re = re.compile(r"^(E\d{3,}|T\d{3,}|P\d{3,})-")
    problems = []
    for d in required_dirs:
        if not os.path.isdir(os.path.join(company, d)):
            problems.append(f"缺少必需目录：{d}/")
    for f in required_files:
        if not os.path.isfile(os.path.join(company, f)):
            problems.append(f"缺少必需文件：{f}")
    if not any(n.startswith("E0000-") and os.path.isdir(os.path.join(company, n)) for n in os.listdir(company) if os.path.isdir(os.path.join(company, n))):
        problems.append("缺少总管目录（E0000-*）")
    known_subdirs = {"workbench": {"tasks", "affairs", "archive"}}  # affairs=常设事务区；archive=历史过程文档存档
    for name in sorted(os.listdir(company)):
        if name.startswith("."):
            continue
        full = os.path.join(company, name)
        if entity_re.match(name) or name in required_dirs or name in required_files or name in known_extra_dirs:
            continue
        if os.path.isfile(full) and any(p.match(name) for p in known_extra_file_patterns):
            continue
        problems.append(f"未登记的一级条目：{name}/（新增机制请同步更新《目录结构说明书.md》，本脚本 known_extra 清单，勿留野目录）")
    for parent_dir, allowed in known_subdirs.items():
        pfull = os.path.join(company, parent_dir)
        if not os.path.isdir(pfull):
            continue
        for name in sorted(os.listdir(pfull)):
            if name.startswith(".") or name in allowed or os.path.isfile(os.path.join(pfull, name)):
                continue
            problems.append(f"{parent_dir}/ 下未登记的子目录：{name}/（同步更新目录结构说明书 §已知子目录）")
    print("结构契约自检…")
    if problems:
        for p in problems:
            print(f"  ✗ {p}")
        print(f"结构自检存在 {len(problems)} 项问题 ✗")
        return 1
    print("  ✓ 结构契约全部通过")
    return 0


def selftest():
    """内置自测：解析 / 日期规整 / 状态枚举 / 坏文件容错 / ctx 全链路。全部通过返回 0。"""
    import tempfile
    ok = True

    def check(name, cond):
        nonlocal ok
        print(("  ✓ " if cond else "  ✗ ") + name)
        if not cond:
            ok = False

    print("运行内置自测…")
    fm, body, has = parse_frontmatter("---\nid: TSK00001\ntitle: 测试\nstatus: backlog\ntags: [a, b]\n---\n正文")
    check("frontmatter 基础解析", has and fm["id"] == "TSK00001" and fm["tags"] == ["a", "b"] and body == "正文")
    fm2, _, has2 = parse_frontmatter("无包裹文本")
    check("无 frontmatter 识别", not has2 and fm2 == {})
    fm3, _, _ = parse_frontmatter('---\nhandoffs: [{"from":"E1","to":"E2","at":"2026-8-1"}]\n---\n')
    check("JSON 对象数组解析", isinstance(fm3.get("handoffs"), list) and fm3["handoffs"][0]["from"] == "E1")
    check("日期规整 2026-8-1 -> 2026-08-01", normalize_date("2026-8-1") == "2026-08-01")
    check("日期规整带时间", normalize_date("2026-08-27 14:30") == "2026-08-27 14:30")
    check("非法日期返回 None", normalize_date("abc") is None)
    check("状态枚举含 cancelled", set(VALID_STATUS) == {"backlog", "in_progress", "review", "done", "failed", "paused", "cancelled"})
    tmp = tempfile.mkdtemp()
    d1 = os.path.join(tmp, "A-坏文件")
    os.makedirs(d1)
    with open(os.path.join(d1, "task.md"), "w", encoding="utf-8") as fh:
        fh.write("无frontmatter")
    ctx_tmp = Ctx(tmp, tmp, tmp, os.path.join(tmp, "o.json"), os.path.join(tmp, "o.js"))
    check("坏 frontmatter 跳过", build_record(ctx_tmp, d1, "A-坏文件") is None)
    d2 = os.path.join(tmp, "B-非法状态")
    os.makedirs(d2)
    with open(os.path.join(d2, "task.md"), "w", encoding="utf-8") as fh:
        fh.write("---\nid: TSKB\nstatus: 乱写\n---\n")
    check("非法 status 跳过", build_record(ctx_tmp, d2, "B-非法状态") is None)
    fm4, _, _ = parse_frontmatter('---\ndue: 2026-9-5\nstatus_history: [{"to":"in_progress","at":"2026-8-26"}]\n---\n')
    check("due 规整 2026-9-5 -> 2026-09-05", normalize_date(fm4["due"]) == "2026-09-05")
    check("status_history 数组解析", isinstance(fm4.get("status_history"), list) and fm4["status_history"][0]["to"] == "in_progress")
    # 升级信箱标记识别（机制扩展 #18）
    msg = "普通备注\n[escalate: 需要转给 E0002 处理] (2026-08-28)\n[escalate: 需求不明确需要澄清]\n普通备注2"
    escs = extract_escalations(msg)
    check("升级标记识别2条", len(escs) == 2 and escs[0]["reason"] == "需要转给 E0002 处理" and escs[0]["date"] == "2026-08-28" and escs[1]["date"] == "")
    check("无升级标记返回空", extract_escalations("普通内容") == [])

    # ---- 集成用例：generate(ctx) 全链路（临时目录隔离，不碰真实数据）----
    itmp = tempfile.mkdtemp(prefix="kanban_it_")
    itasks = os.path.join(itmp, "tasks")
    for sub in ["I1-进行中旧", "I2-进行中新", "I3-兜底外援", "I4-重复id"]:
        os.makedirs(os.path.join(itasks, sub), exist_ok=True)

    def _iw(path, text):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    _iw(os.path.join(itasks, "I1-进行中旧", "task.md"),
        "---\nid: TSKI1\ntitle: 进行中旧\nstatus: in_progress\nowner: E0001\ncreated: 2026-08-20\nupdated: 2026-08-20\n---\n")
    _iw(os.path.join(itasks, "I2-进行中新", "task.md"),
        "---\nid: TSKI2\ntitle: 进行中新\nstatus: in_progress\nowner: E0002\ncreated: 2026-08-27\nupdated: 2026-08-27\n---\n")
    _iw(os.path.join(itasks, "I3-兜底外援", "task.md"),
        "---\nid: TSKI3\ntitle: 兜底外援\nstatus: backlog\nowner: E999\nowner_name: 临时外援小王\ncreated: 2026-08-01\nupdated: 2026-08-01\n---\n")
    _iw(os.path.join(itasks, "I4-重复id", "task.md"),
        "---\nid: TSKI1\ntitle: 重复id\nstatus: done\nowner: E0003\ncreated: 2026-08-26\nupdated: 2026-08-26\n---\n")
    # 阻塞/父子关系集成用例（R1 上游 done 已解锁未开工、R2 阻塞未清就开工、R3 父单提前 done）
    for sub, md in [
        ("I5-父单需求", "---\nid: TSKI5\ntitle: 父单需求\nstatus: done\ntype: 需求\ncreated: 2026-08-01\nupdated: 2026-08-01\n---\n"),
        ("I6-子单A", "---\nid: TSKI6\ntitle: 子单A\nstatus: backlog\nparent: TSKI5\ncreated: 2026-08-01\nupdated: 2026-08-01\n---\n"),
        ("I7-已解锁", "---\nid: TSKI7\ntitle: 已解锁\nstatus: backlog\nblocked_by: [TSKI1]\ncreated: 2026-08-01\nupdated: 2026-08-01\n---\n"),
        ("I8-违规开工", "---\nid: TSKI8\ntitle: 违规开工\nstatus: in_progress\nblocked_by: [TSKI6]\ncreated: 2026-08-01\nupdated: 2026-08-01\n---\n"),
        ("I9-坏引用", "---\nid: TSKI9\ntitle: 坏引用\nstatus: backlog\nblocked_by: [TSKZZZ]\nparent: TSKYYY\ncreated: 2026-08-01\nupdated: 2026-08-01\n---\n"),
    ]:
        os.makedirs(os.path.join(itasks, sub), exist_ok=True)
        _iw(os.path.join(itasks, sub, "task.md"), md)
    ictx = Ctx(itmp, itmp, itasks, os.path.join(itmp, "out.json"), os.path.join(itmp, "out.js"))
    generate(ictx)
    with open(ictx.out_json, encoding="utf-8") as fh:
        idata = json.load(fh)
    i_ids = [t["id"] for t in idata["tasks"]]
    check("集成:id 去重(重复 TSKI1 跳过)", i_ids.count("TSKI1") == 1)
    i_ip = [t["id"] for t in idata["tasks"] if t["status"] == "in_progress"]
    check("集成:组内 updated 倒序(TSKI2 在 TSKI1 前)", i_ip[:2] == ["TSKI2", "TSKI1"])
    check("集成:注册表双来源合并(E999 兜底名生效)", idata["employees"].get("E999") == "临时外援小王")
    t_by_id = {t["id"]: t for t in idata["tasks"]}
    check("集成:blocked_by 解析入 payload", t_by_id.get("TSKI8", {}).get("blocked_by") == ["TSKI6"])
    check("集成:parent 解析入 payload", t_by_id.get("TSKI6", {}).get("parent") == "TSKI5")
    check("集成:无阻塞工单 blocked_by 为空数组", t_by_id.get("TSKI2", {}).get("blocked_by") == [])

    # ---- resolve_ctx 反查（--dir 模式）——身份提取统一走 resolver.extract_company_id（P25）----
    rtmp = tempfile.mkdtemp(prefix="ctx_it_")
    with open(os.path.join(rtmp, "company.md"), "w", encoding="utf-8") as fh:
        fh.write("# 测试公司\n- 公司 ID：CXXX（示例注释也应正确截断）\n")
    wb = os.path.join(rtmp, "workbench")
    os.makedirs(wb, exist_ok=True)
    with open(os.path.join(rtmp, "opc.toml"), "w", encoding="utf-8") as fh:
        fh.write("[company.DEFAULT]\nworkbench = \"workbench\"\ntasks_data = \"workbench/tasks-data.json\"\nroster = \"roster.md\"\naffairs = \"workbench/affairs\"\npage_templates = \"page-templates\"\n")
    txt = opc_resolver.read_text(os.path.join(rtmp, "company.md"))
    got = opc_resolver.extract_company_id(txt)
    check("resolve 反查公司 ID（含注释截断）", got == "CXXX")
    print("自测" + ("全部通过 ✓" if ok else "存在失败 ✗"))
    return 0 if ok else 1


def main(argv):
    if "--selftest" in argv:
        return selftest()
    company = None
    company_dir = None
    if "--company" in argv:
        company = argv[argv.index("--company") + 1]
    if "--dir" in argv:
        company_dir = argv[argv.index("--dir") + 1]
    ctx = resolve_ctx(company, company_dir)
    if "--watch" in argv:
        watch(ctx)
    elif "--new" in argv:
        return new_task(ctx, argv)
    elif "--check-structure" in argv:
        return check_structure(ctx)
    else:
        print("生成看板数据…")
        generate(ctx)
        print("完成。")
    return 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")   # Windows cp1252 控制台/CI 下中文输出防崩（CI 实测）
    sys.exit(main(sys.argv))
