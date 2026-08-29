#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
三级看板数据生成器（机制层，OPC 根单例）

> 2026-08-28 机制上提（廖哥拍板）：原各公司目录下的 generate_dashboard.py 收敛到
> 本模块。公司目录只留数据与薄壳入口（run_boards.*）。修 bug 一处生效、开新公司
> 零代码复制、cid 由 manifest 解析零硬编码。

扫描公司根各实体（roster / E*/workspace/worklog.md / T*/team.md+notices.md /
P*/project.md），复用工单产物 workbench/tasks-data.json（不重复解析 tasks/），
一次扫描分头产出三级数据文件：
  公司级   -> 公司根/dashboard.html + dashboard-data.js
  团队级   -> T*/teamboard.html + teamboard-data.js
  个人级   -> E*/mydesk.html + mydesk-data.js

用法（cwd 无关，公司由 manifest 解析）：
    python opc_dashboards.py --company C001          # 生成该公司三级看板
    python opc_dashboards.py --dir <公司根目录>       # 按目录反查公司 ID
    python opc_dashboards.py --company C001 --watch  # 监听数据源变动自动重跑
    python opc_dashboards.py --company C001 --verify # 产出一致性检查
    python opc_dashboards.py --selftest              # 内置自测（临时目录）

设计要点（见 P0004/REQ-三级可视化看板系统.md）：
- 单一真相：员工→团队归属以 roster.md「团队」列为唯一权威（A1）；项目归属读 project.md team 字段。
- 交叉核验（A2）：worklog 工单型条目与 tasks-data.json 逐条核对，只告警不阻断。
- 统计口径（B1/§4.5）：完成率=已完成/全部有效条目（累计）；在途=计划中+进行中。
- 页面分发：teamboard/mydesk 的 HTML 模板放 page-templates/（manifest 键），每次生成同步到
  各实体目录（内容有变才写）——升级只改模板一处，下次生成全员自动刷新。
- 容错家规：坏条目跳过+告警不阻断；日期规整；deliverable/ticket/team 引用失效标 ⚠️。
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
import opc_resolver
from opc_model import (parse_frontmatter,                    # 共享读取器（P25，禁私写正则）
                       normalize_day as normalize_date,    # 日期规整（D2 收敛）
                       read_text_warn as read_text,        # 告警读（D2 收敛）
                       atomic_write,                       # 原子写（D3 收敛）
                       parse_company_args)                 # CLI 参数提取（D 收敛）
from opc_schema import (WORKLOG_STATUS, TASK_ACTIVE as ACTIVE_TS,   # 状态机唯一真相源
                        TASK_STATUS_ORDER, TASK_TERMINAL, AFF_STATUS, AFF_CADENCE_DAYS,
                        PATROL, EMPLOYEE_STATUS)
WORKLOG_STATUS = set(WORKLOG_STATUS)
AFF_STATUS = set(AFF_STATUS)

PAGE_VERSION = "v1.3"
STALE_DAYS_DEFAULT = PATROL["worklog_stale_days"]   # 「N 天未动」阈值（opc_schema 统一）


class Ctx:
    """一次生成的全部路径上下文（取代原模块级可变全局 COMPANY_DIR_cur hack）。
    所有函数经参数接收 ctx，不再读模块级路径常量 → 可安全嵌套/并发/selftest。"""

    def __init__(self, cfg, base_dir, page_tpl_dir, tasks_data, roster_rel, affairs_dir):
        self.cfg = cfg
        self.cid = cfg.cid
        self.base = base_dir
        self.page_tpl = page_tpl_dir
        self.tasks_data = tasks_data
        self.roster_rel = roster_rel
        self.affairs_dir = affairs_dir
        self.warnings = []


def resolve_ctx(company=None, company_dir=None):
    """--company CID（走 manifest）或 --dir 目录（反查 ID）。返回 Ctx。
    身份反查/断链校验统一走 opc_resolver.resolve_company（D1 收敛）。"""
    cfg = opc_resolver.resolve_company(company, company_dir)
    # roster 路径取自愈版解析（roster_abs：总管目录改名后按 ID 前缀扫描兜底，决策 #17）
    roster_rel = os.path.relpath(cfg.roster_abs, cfg.home_abs)
    return Ctx(cfg, cfg.home_abs, cfg.page_templates_abs, cfg.tasks_data_abs,
               roster_rel, cfg.affairs_abs)


# ---------- 基础工具 ----------

def sibling_nav_links():
    """看板页内跳转链接（公司根下一级子目录页面 → 公司级页面/工单看板）。
    一律用纯相对路径（公司根下所有页面互为近邻），file:// 直开与 opc_service
    的 /CID/ 路由两种模式都成立——锚前缀 companies/<cid>/ 在服务模式下会与
    URL 里的 /CID/ 双重拼接导致 404（2026-08-29 跳转 bug 修复，锚前缀退役）。"""
    return {"dashboard": "../dashboard.html", "kanban": "../workbench/kanban.html"}


def split_blocks(text):
    """把多块 frontmatter 文本切成 [(fm_text, body)] 列表（worklog/notices 同构）。
    块外散落文本忽略（告警由调用方按需处理）。"""
    blocks, cur = [], None
    for line in text.splitlines():
        if line.strip() == "---":
            if cur is None:
                cur = []
            else:
                blocks.append(("\n".join(cur), None))
                cur = None
        elif cur is not None:
            cur.append(line)
    return blocks


def write_js(path, var_name, payload):
    """产出 file:// 可用的数据 js（内联全局变量；防 </script> 破坏字面量）。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    js = "window.%s = %s;\n" % (var_name, json.dumps(payload, ensure_ascii=False, indent=2))
    js = js.replace("</script", "<\\/script")
    atomic_write(path, js)
    print(f"  [完成] {var_name} -> {path}")


def sync_file(ctx, src, dst):
    """模板分发：内容有变才写（升级只改模板一处，下次生成自动刷新各副本）。"""
    if not os.path.isfile(src):
        return False
    with open(src, "r", encoding="utf-8", newline="") as fh:
        content = fh.read()
    if os.path.isfile(dst):
        with open(dst, "r", encoding="utf-8", newline="") as fh:
            if fh.read() == content:
                return False
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    atomic_write(dst, content)
    try:
        rel = os.path.relpath(dst, ctx.base)
    except ValueError:  # 跨盘（如自测临时目录在 C:，真实目录在 E:）无法算相对路径
        rel = dst
    print(f"  [完成] 页面同步 {rel}")
    return True


def parse_md_kv(text, keys):
    """从 markdown 正文提取「键：值」行（无 frontmatter 的实体文件兜底），如 project.md/team.md。
    keys 形如 {"项目 ID": "pid", "名称": "name"}；返回 dict。"""
    out = {}
    for line in text.splitlines():
        m = re.match(r"^\s*[-*]?\s*([^：:]{1,10})[：:]\s*(.+)$", line)
        if not m:
            continue
        k, v = m.group(1).strip(), m.group(2).strip()
        if k in keys:
            out[keys[k]] = v
    return out


# ---------- 实体扫描与解析 ----------

def scan_entity_dirs(base):
    """扫描公司根：返回 (employees_dirs, teams_dirs, projects_dirs)，按代号排序。
    前缀来自 resolver 实体类型注册表（2026-08-29：加类型/改前缀 = 改 manifest）。"""
    emp, team, proj = [], [], []
    if not os.path.isdir(base):
        return emp, team, proj
    reg = opc_resolver.entity_types()
    buckets = {"employee": emp, "team": team, "project": proj}
    for name in sorted(os.listdir(base)):
        if not os.path.isdir(os.path.join(base, name)):
            continue
        for etype, pfx in reg.items():
            if re.match(rf"^{pfx}\d{{3,}}(?:-|$)", name) and etype in buckets:
                buckets[etype].append(name)
                break
    return emp, team, proj


def dir_label(dirname):
    """目录名去 ID 前缀取显示名后缀（{ID}-{说明} -> {说明}，如 E0001 带后缀目录取「售前工程师」）。
    决策 #17 修订：目录后缀即显示名（目录自解释，目录名为准），
    roster 岗位列与之做一致性告警；裸 ID 目录（无后缀）回退 roster/原目录名。"""
    label = dirname.split("-", 1)[1] if "-" in dirname else dirname
    if label.startswith("AI员工-"):
        label = label[len("AI员工-"):]
    return label


# roster.md 的列语义按「表头名」映射（非列位置）：用户/总管在表中插列、调列序都不会静默错位。
_ROSTER_COL_ALIASES = {
    "员工id": "eid", "路径": "path", "岗位": "role", "状态": "status",
    "团队": "teams", "角色": "rank", "备注": "note",
}


def parse_roster(path, warnings):
    """解析 roster.md 表格 -> {eid: {role, status, teams[], note, rank}}；坏行跳过告警。
    列识别按表头名（大小写/空格不敏感，'员工ID'/'员工 ID' 均可）；出现未知表头列时
    告警提示（内容保留在 cols 供人工排查，但绝不静默吞掉）。缺关键列（状态/团队）按缺省。
    防呆（P1）：eid/team 代号做正则校验，坏值报错跳过而不是静默吞掉。
    「角色」列：lead=团队负责人，缺省为普通成员（自由文本）。"""
    roster = {}
    if not os.path.isfile(path):
        print(f"  [警告] 找不到花名册：{path}（员工将以目录扫描兜底、标记未登记）")
        return roster
    header = None
    colmap = None
    for line in read_text(path).splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if header is None:
            header = cells
            colmap = {}
            for idx, h in enumerate(header):
                key = _ROSTER_COL_ALIASES.get(re.sub(r"[*\s]+", "", h).lower())
                if key:
                    colmap[key] = idx
                elif h and not re.match(r"^-+$", h):
                    warnings.append({"scope": "roster", "msg": f"roster 出现未登记的表头列「{h}」（第{idx + 1}列），其内容不参与看板——若是新字段请同步更新生成器 _ROSTER_COL_ALIASES"})
            if "eid" not in colmap:
                print("  [错误] roster 缺「员工 ID」表头列，无法解析")
                return roster
            continue
        if all(re.match(r"^:?-+:?$", c) for c in cells if c):   # 分隔行 |---|---|
            continue
        get = lambda key: cells[colmap[key]] if key in colmap and colmap[key] < len(cells) else ""
        eid = get("eid")
        if not re.match(r"^E\d{3,}$", eid):
            continue
        role = get("role")
        status = get("status") or "在职"
        team_cell = get("teams") or "-"
        rank = get("rank")
        note = get("note")
        teams, bad_teams = [], []
        for t in re.split(r"[，,、\s]+", team_cell):
            if re.match(r"^T\d+$", t):
                teams.append(t)
            elif t not in ("-", "", "无"):
                bad_teams.append(t)   # 形似代号但非法（如 T00O / T-01）
        if bad_teams:
            print(f"  [错误] roster {eid} 团队列含非法代号 {bad_teams}（应为 T+数字），已忽略这些值——若该员工属于某团队请修正 roster")
        if status not in EMPLOYEE_STATUS:
            print(f"  [错误] roster {eid} 状态列 {status!r} 不在 {'/'.join(EMPLOYEE_STATUS)} 内，按原文保留展示")
        roster[eid] = {"role": role, "status": status, "teams": teams, "rank": rank, "note": note}
    return roster


def parse_project(ctx, dirname):
    """解析 project.md（frontmatter 优先，markdown「键：值」兜底）。
    team 字段：单值或数组；markdown 兜底只认 T\\d+ 代号。"""
    pid = dirname.split("-", 1)[0]
    raw = read_text(os.path.join(ctx.base, dirname, "project.md"))
    fm, _, has = parse_frontmatter(raw)
    if has:
        name = fm.get("name") or dir_label(dirname)
        owner = fm.get("owner")
        status = fm.get("status") or "active"
        team = fm.get("team")
        if isinstance(team, list):
            teams = [str(t).strip() for t in team if str(t).strip()]
        elif team:
            teams = [str(team).strip()]
        else:
            teams = []
    else:
        kv = parse_md_kv(raw, {"项目 ID": "pid", "名称": "name", "负责人": "owner", "状态": "status"})
        name = kv.get("name") or dir_label(dirname)
        owner = kv.get("owner")
        status = kv.get("status") or "active"
        # team 归属只认 frontmatter 显式声明（REQ §4.2）：markdown 正文提到的 T 编号
        # 可能只是叙述性引用，抓取会导致项目被意外划归团队，故不兜底
        teams = []
    return {"pid": pid, "name": name, "owner": owner, "status": status, "teams": teams, "dir": dirname}


def parse_team(ctx, dirname):
    """解析 team.md -> {tid, name}（markdown 行兜底，无文件用目录名）。"""
    tid = dirname.split("-", 1)[0]
    raw = read_text(os.path.join(ctx.base, dirname, "team.md"))
    kv = parse_md_kv(raw, {"团队 ID": "tid", "名称": "name"})
    return {"tid": kv.get("tid") or tid, "name": kv.get("name") or dir_label(dirname), "dir": dirname}


def parse_notices(ctx, team_dir):
    """解析 T*/notices.md 公告块 -> [{title,date,author,body}]；坏块跳过告警。"""
    path = os.path.join(ctx.base, team_dir, "notices.md")
    out = []
    if not os.path.isfile(path):
        return out
    for fm_text, _ in split_blocks(read_text(path)):
        fm, body, has = parse_frontmatter("---\n" + fm_text + "\n---")
        if not has or not fm.get("title"):
            print(f"  [警告] {team_dir}/notices.md 存在无 title 的坏块，已跳过")
            continue
        date = normalize_date(fm.get("date")) or str(fm.get("date") or "")
        out.append({"title": str(fm["title"]), "date": date,
                    "author": str(fm.get("author") or ""), "body": body or ""})
    out.sort(key=lambda n: n["date"], reverse=True)
    return out


def parse_skills(ctx, entity_dir):
    """扫描 {entity}/skills/*/SKILL.md frontmatter -> [{name, desc}]（资产索引/身份卡）。"""
    out = []
    sdir = os.path.join(ctx.base, entity_dir, "skills")
    if not os.path.isdir(sdir):
        return out
    for name in sorted(os.listdir(sdir)):
        sk = os.path.join(sdir, name, "SKILL.md")
        if not os.path.isfile(sk):
            continue
        fm, _, _ = parse_frontmatter(read_text(sk))
        out.append({"name": fm.get("name") or name, "desc": fm.get("description") or ""})
    return out


def parse_worklog(ctx, eid, emp_dir):
    """解析 E*/workspace/worklog.md（热）+ worklog-archive/worklog-*.md（冷，年度归档）
    多块记录 -> 条目列表（含校验告警）。归档只动文件位置不动数据：生成器全量扫描
    保证历史在看板照常显示（P4 管道不变）。
    家规：deliverable 路径以「员工目录根」为基准书写。"""
    entries = []
    warnings = ctx.warnings
    base = os.path.join(ctx.base, emp_dir, "workspace")
    wl_files = [os.path.join(base, "worklog.md")]
    arch = os.path.join(base, "worklog-archive")
    if os.path.isdir(arch):
        for name in sorted(os.listdir(arch)):
            if re.match(r"^worklog-\d{4}\.md$", name):
                wl_files.append(os.path.join(arch, name))
    seen_wid = set()
    for path in wl_files:
        rel = os.path.relpath(path, base).replace(os.sep, "/")
        if not os.path.isfile(path):
            continue  # 无 worklog = 零负荷，正常
        for fm_text, _ in split_blocks(read_text(path)):
            fm, _, has = parse_frontmatter("---\n" + fm_text + "\n---")
            title = fm.get("title")
            status = fm.get("status")
            if not has or not title or status not in WORKLOG_STATUS:
                print(f"  [警告] {emp_dir}/{rel} 存在坏条目（缺 title 或 status 非法），已跳过")
                continue
            wid = str(fm.get("wid") or "")
            if wid:
                if wid in seen_wid:
                    warnings.append({"scope": "worklog", "msg": f"{eid} worklog 重复 wid={wid}（跨热/归档文件），后者覆盖前者"})
                seen_wid.add(wid)
            typ = fm.get("type") or "自由"
            ticket = str(fm.get("ticket") or "").strip()
            if typ == "工单" and not ticket:
                warnings.append({"scope": "核验", "msg": f"{eid} 工单型条目「{title}」缺 ticket 字段（A2 规则）"})
            if typ != "工单" and ticket:
                warnings.append({"scope": "核验", "msg": f"{eid} 非 工单型条目「{title}」不应填 ticket（已忽略）"})
                ticket = ""
            date = normalize_date(fm.get("date"))
            updated = normalize_date(fm.get("updated")) or date or ""
            deliverable = str(fm.get("deliverable") or "").strip()
            valid_deliv = True
            deliv_href = ""
            if deliverable:
                # 两种写法都支持（PRINCIPLES P26 命名空间）：
                # ① opc:// 逻辑符号 —— 走 resolver 解析（文档层推荐写法，改名免疫）
                # ② 裸相对路径 —— 以「员工目录根」为基准（旧写法，兼容保留）
                if deliverable.startswith("opc://"):
                    try:
                        import opc_resolver   # 惰性导入：避免与 resolver 形成顶层循环依赖
                        full = opc_resolver.resolve(deliverable)
                    except Exception:
                        full = None            # 解析失败按失效处理（告警文案指向 URI 本身）
                else:
                    full = os.path.normpath(os.path.join(ctx.base, emp_dir, deliverable))
                valid_deliv = bool(full) and os.path.exists(full)
                if not valid_deliv:
                    warnings.append({"scope": "核验", "msg": f"{eid}「{title}」deliverable 路径失效：{deliverable}"})
                else:
                    deliv_href = os.path.relpath(full, os.path.join(ctx.base, emp_dir)).replace(os.sep, "/")
            entries.append({
                "wid": wid, "date": date or "", "title": str(title), "status": status,
                "type": typ, "ticket": ticket, "project": str(fm.get("project") or ""),
                "updated": updated, "note": str(fm.get("note") or ""),
                "aff": str(fm.get("aff") or "").strip(),   # 常设事务引用（type=事务/工单均可带）
                "deliverable": deliverable, "deliverable_valid": valid_deliv,
                "deliverable_href": deliv_href,
                "archived": rel != "worklog.md",   # 归档条目标记（mydesk「含归档」筛选用）
            })
    entries.sort(key=lambda e: (e["updated"] or e["date"]), reverse=True)
    return entries


def stats_of(entries):
    """§4.5 统计口径：完成率=已完成/全部（累计）；在途=计划中+进行中；
    done_7d=近7天新增完成数（防止累计口径淹没近期表现）。"""
    c = {"计划中": 0, "进行中": 0, "已完成": 0}
    week_ago = (datetime.date.today() - datetime.timedelta(days=7)).strftime("%Y-%m-%d")
    done_7d = 0
    for e in entries:
        if e["status"] in c:
            c[e["status"]] += 1
        if e["status"] == "已完成" and (e.get("updated") or "") >= week_ago:
            done_7d += 1
    total = sum(c.values())
    rate = round(c["已完成"] / total, 4) if total else None
    return {"planned": c["计划中"], "in_progress": c["进行中"], "done": c["已完成"],
            "total": total, "ongoing": c["计划中"] + c["进行中"], "rate": rate,
            "done_7d": done_7d}


def cross_validate(ctx, emp_entries, tasks):
    """A2 交叉核验（只告警不阻断）：
    R1 工单型条目 ticket 不存在；R3 在途工单有记录但状态不是进行中；
    R4 进行中条目对应工单已终态；R5 已完成条目对应工单仍未关。
    backlog/paused 双向豁免。
    「未认领」与「在途未记」合并为一条规则（原实现 R2/未认领对同一张单双重告警，
    面板噪音翻倍）：owner 有主且未终态 → worklog 无该单条目只报一次。"""
    warnings = ctx.warnings
    tmap = {t["id"]: t for t in tasks}
    terminal = tuple(TASK_TERMINAL)
    for eid, entries in emp_entries.items():
        for e in entries:
            if not e["ticket"]:
                continue
            t = tmap.get(e["ticket"])
            if t is None:
                warnings.append({"scope": "核验", "msg": f"{eid}「{e['title']}」引用的工单 {e['ticket']} 不存在"})
                continue
            if e["status"] == "进行中" and t["status"] in terminal:
                warnings.append({"scope": "核验", "msg": f"{eid}「{e['title']}」记录进行中，但工单 {e['ticket']} 已{t['status']}"})
            if e["status"] == "已完成" and t["status"] in ACTIVE_TS:
                warnings.append({"scope": "核验", "msg": f"{eid}「{e['title']}」已完成，但工单 {e['ticket']} 仍未关（{t['status']}）——记得关单"})
    # 认领核验（合并版）：owner 有主且未终态，但 owner 的 worklog 全档无该单条目
    # → 只报一条「未认领」。认领=worklog 建条目（认领≠开工，backlog 也应有账）。
    for t in tasks:
        if not t.get("owner") or t.get("status") in terminal:
            continue
        mine = [e for e in emp_entries.get(t["owner"], []) if e["ticket"] == t["id"]]
        if not mine:
            warnings.append({"scope": "核验", "msg": f"{t['owner']} 的工单 {t['id']}「{t['title']}」未认领（worklog 无条目；按 ticket-system §1.5 认领）"})
        elif t.get("status") in ("in_progress", "review") and all(e["status"] != "进行中" for e in mine):
            warnings.append({"scope": "核验", "msg": f"{t['owner']} 的 {t['id']} 工单在途，但 worklog 记录非「进行中」"})


def ticket_summary(tasks):
    """工单口径汇总（2026-08-29 拆对象统计）：在途=活跃态（待领/进行中/待审）；
    已完成=done；暂停/失败/取消单列不混入；逾期=在途且已过 due。
    工作条目(worklog)与工单是两套账，公司/团队统计分别成卡，不互相概括。"""
    today = datetime.date.today().strftime("%Y-%m-%d")
    s = {"total": len(tasks), "active": 0, "done": 0, "overdue": 0,
         "paused": 0, "failed": 0, "cancelled": 0, "byStatus": {}}
    for t in tasks:
        st = t["status"]
        s["byStatus"][st] = s["byStatus"].get(st, 0) + 1
        if st in ACTIVE_TS:
            s["active"] += 1
            if t.get("due") and t["due"] < today:
                s["overdue"] += 1
        elif st in ("done", "paused", "failed", "cancelled"):
            s[st] += 1
    return s


def ticket_stats_by_project(tasks):
    """项目维度工单统计（联动③）：总数/状态分布/逾期中数。
    「今天」函数内实时取（原模块级常量在 watch 长驻进程下会冻结，逾期判定失真）。"""
    today = datetime.date.today().strftime("%Y-%m-%d")
    out = {}
    for t in tasks:
        pid = t.get("project") or "未关联"
        s = out.setdefault(pid, {"total": 0, "byStatus": {}, "overdue": 0})
        s["total"] += 1
        s["byStatus"][t["status"]] = s["byStatus"].get(t["status"], 0) + 1
        if t.get("status") in ACTIVE_TS and t.get("due") and t["due"] < today:
            s["overdue"] += 1
    return out


def parse_affairs(ctx):
    """扫描 workbench/affairs/AFFxxxx-标题/affair.md -> 事务列表。
    last_touched 由 worklog（aff 字段）推导，不靠人工填报（P1 文件即真相）。
    坏事务跳过+告警（P11）。"""
    out = []
    if not os.path.isdir(ctx.affairs_dir):
        return out
    for name in sorted(os.listdir(ctx.affairs_dir)):
        full = os.path.join(ctx.affairs_dir, name)
        if not os.path.isdir(full) or not re.match(r"^AFF\d{3,}-", name):
            continue
        aff_id = name.split("-", 1)[0]
        raw = read_text(os.path.join(full, "affair.md"))
        if not raw:
            print(f"  [跳过] {name}/ 缺少 affair.md")
            continue
        fm, body, has = parse_frontmatter(raw)
        status = fm.get("status")
        if not has or status not in AFF_STATUS:
            print(f"  [跳过] {name}/affair.md status={status!r} 非法（应 active/paused/closed）")
            continue
        cadence = str(fm.get("cadence") or "按需")
        if cadence not in AFF_CADENCE_DAYS and cadence != "按需":
            print(f"  [警告] {aff_id} cadence={cadence!r} 非常规值（每日/每周/每两周/每月/按需），按需处理")
            cadence = "按需"
        out.append({
            "id": str(fm.get("id") or aff_id),
            "title": str(fm.get("title") or (name.split("-", 1)[1] if "-" in name else name)),
            "status": status,
            "owner": str(fm.get("owner") or ""),
            "cadence": cadence,
            "priority": str(fm.get("priority") or "中"),
            "created": normalize_date(fm.get("created")) or "",
            "updated": normalize_date(fm.get("updated")) or "",
            "body": body or "",
            "dir": name,
        })
    return out


def link_affairs(affairs, emp_entries):
    """worklog 推导各事务 last_touched（含归档，全量扫描）：扫 aff 字段。
    同时收集 touches 全量推进记录（供驾驶舱事务详情弹层展示），最新在前。"""
    touched = {}
    touches = {}
    for eid, entries in emp_entries.items():
        for e in entries:
            aff = str(e.get("aff") or "").strip()
            if not aff:
                continue
            day = e.get("updated") or e.get("date") or ""
            if aff not in touched or day > touched[aff][0]:
                touched[aff] = (day, eid)
            touches.setdefault(aff, []).append(
                {"date": day, "eid": eid, "title": e.get("title") or "",
                 "status": e.get("status") or ""})
    for a in affairs:
        t = touched.get(a["id"])
        a["last_touched"] = t[0] if t else ""
        a["last_by"] = t[1] if t else ""
        a["touches"] = sorted(touches.get(a["id"], []),
                              key=lambda x: x["date"], reverse=True)[:50]
        # 逾期判定：active + 有节奏 + 超阈值
        a["overdue"] = False
        a["never_done"] = False
        if a["status"] == "active" and a["cadence"] in AFF_CADENCE_DAYS:
            if not a["last_touched"]:
                a["never_done"] = True
            else:
                threshold = AFF_CADENCE_DAYS[a["cadence"]]
                d = normalize_date(a["last_touched"])
                if d and d < (datetime.date.today() - datetime.timedelta(days=threshold)).strftime("%Y-%m-%d"):
                    a["overdue"] = True
    return affairs


def verify_outputs(ctx):
    """--verify：产出一致性专项检查（动态扫描不硬编码）。
    ①三级数据同批生成（generated_at 一致）；②mydesk 在途工单深链不死链。纯读不写。"""
    base_dir = ctx.base
    problems = []
    payloads = []  # (label, data)

    def _load(path, label):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
            m = re.match(r"^window\.\w+ = ([\s\S]*);\s*$", text)
            payloads.append((label, json.loads(m.group(1)) if m else json.loads(text)))
        except Exception as e:
            problems.append(f"{label} 读取/解析失败：{e}")

    dash_path = os.path.join(base_dir, "dashboard-data.js")
    if os.path.isfile(dash_path):
        _load(dash_path, "dashboard")
    else:
        problems.append("缺少 dashboard-data.js（先运行生成器）")
    for name in sorted(os.listdir(base_dir)) if os.path.isdir(base_dir) else []:
        if re.match(r"^T\d{3,}-", name) and os.path.isfile(os.path.join(base_dir, name, "teamboard-data.js")):
            _load(os.path.join(base_dir, name, "teamboard-data.js"), name)
        if re.match(r"^E\d{3,}-", name) and os.path.isfile(os.path.join(base_dir, name, "mydesk-data.js")):
            _load(os.path.join(base_dir, name, "mydesk-data.js"), f"{name}/mydesk")
    # ① 同批生成
    gens = {p["generated_at"] for _, p in payloads if "generated_at" in p}
    if len(payloads) > 1 and len(gens) > 1:
        problems.append(f"三级数据非同批生成（generated_at 不一致：{gens}）——重新运行生成器")
    # ② 深链不死链（mydesk.tickets[].id 必须存在于 tasks-data.json）
    if os.path.isfile(ctx.tasks_data):
        with open(ctx.tasks_data, "r", encoding="utf-8") as fh:
            task_ids = {t["id"] for t in json.load(fh).get("tasks", [])}
        for label, p in payloads:
            # mydesk.tickets 是在途工单列表（深链校验对象）；dashboard/teamboard 的
            # tickets 是工单口径汇总 dict（2026-08-29），跳过
            if not isinstance(p.get("tickets"), list):
                continue
            for t in p.get("tickets", []):
                if t.get("id") and t["id"] not in task_ids:
                    problems.append(f"{label} 深链死链：{t['id']} 不存在于工单数据")
    print("产出一致性检查（--verify）…")
    if problems:
        for p in problems:
            print(f"  ✗ {p}")
        print(f"检查存在 {len(problems)} 项问题 ✗")
        return 1
    print(f"  ✓ {len(payloads)} 份数据同批生成，深链全部有效")
    return 0


def generate_all(ctx):
    """主流程：扫描 -> 核验 -> 三级切片产出。ctx 携带全部路径（可注入临时目录做自测）。"""
    base_dir = ctx.base
    ctx.warnings = []
    warnings = ctx.warnings

    emp_dirs, team_dirs, proj_dirs = scan_entity_dirs(base_dir)
    roster = parse_roster(os.path.join(base_dir, ctx.roster_rel), warnings)
    tasks_data = load_tasks_data(ctx)
    tasks = tasks_data.get("tasks", [])

    # ---- 员工注册表（B2 仲裁：目录在 roster 无 -> 未登记告警；roster 有目录无 -> 忽略告警）----
    dir_by_eid = {d.split("-", 1)[0]: d for d in emp_dirs}
    employees = []
    emp_entries = {}
    for eid in sorted(set(dir_by_eid) | set(roster)):
        d = dir_by_eid.get(eid)
        r = roster.get(eid)
        if d is None:
            print(f"  [警告] roster 登记 {eid} 但公司根下无目录，已忽略")
            continue
        # 显示名以目录名后缀为准（决策 #17 修订：目录自解释）；裸 ID 目录才退 roster 岗位
        name = dir_label(d)
        registered = r is not None
        if not registered:
            print(f"  [警告] 员工目录 {d} 未在 roster.md 登记，看板标记「未登记」")
        elif (r.get("role") or "") and r["role"] != name:
            warnings.append({"scope": "roster", "msg": f"{eid} 显示名不一致：目录后缀「{name}」≠ roster 岗位「{r['role']}」（目录名为准；改名请走 `python opc_resolver.py --rename-entity {eid} 新说明` 同步两者）"})
        role = name
        status = (r or {}).get("status") or ("未登记" if not registered else "在职")
        teams = (r or {}).get("teams") or []
        rank = (r or {}).get("rank") or ""
        entries = parse_worklog(ctx, eid, d)
        emp_entries[eid] = entries
        employees.append({
            "eid": eid, "name": name, "role": role, "status": status, "teams": teams,
            "rank": rank, "registered": registered, "dir": d, "entries": entries, "stats": stats_of(entries),
        })

    # ---- 团队（成员以 roster 为准，team.md 只提供 ID/名称；lead 取 roster「角色」列）----
    teams = []
    for d in team_dirs:
        info = parse_team(ctx, d)
        members = [e for e in employees if info["tid"] in e["teams"]]
        if not members:
            print(f"  [警告] 团队 {info['tid']} 在 roster 中无任何成员")
        leads = [e["eid"] for e in members if "lead" in (e.get("rank") or "").lower()]
        if members and not leads:
            print(f"  [警告] 团队 {info['tid']} 无 lead（roster「角色」列标 lead 的成员为负责人）")
        teams.append({**info, "leads": leads, "members": [e["eid"] for e in members]})
    known_tids = {t["tid"] for t in teams}

    # ---- 项目（team 字段引用校验）----
    projects = []
    for d in proj_dirs:
        p = parse_project(ctx, d)
        for tid in p["teams"]:
            if tid not in known_tids:
                print(f"  [警告] {p['pid']} team 字段引用了不存在的团队 {tid}")
        projects.append(p)
    proj_by_pid = {p["pid"]: p for p in projects}
    for t in tasks:
        pid = t.get("project")
        if pid and pid not in proj_by_pid:
            print(f"  [警告] 工单 {t['id']} project={pid} 无对应项目目录（看板回退裸代号）")

    cross_validate(ctx, emp_entries, tasks)
    ticket_stats = ticket_stats_by_project(tasks)

    # ---- 常设事务（机制扩展 #17）：扫描 + worklog 推导节奏 + 逾期告警 ----
    affairs = link_affairs(parse_affairs(ctx), emp_entries)
    for a in affairs:
        if a["never_done"]:
            warnings.append({"scope": "核验", "msg": f"事务 {a['id']}「{a['title']}」从未推进（owner={a['owner'] or '?'}；干完活记得 worklog 记 aff={a['id']}）"})
        elif a["overdue"]:
            warnings.append({"scope": "核验", "msg": f"事务 {a['id']}「{a['title']}」已脱期（{a['cadence']}节奏，上次推进 {a['last_touched']}）"})

    # ---- 全公司 activity（跨员工 worklog 时间线，最新在前）----
    activity = []
    for e in employees:
        for w in e["entries"]:
            activity.append({"eid": e["eid"], "name": e["name"], **{k: w[k] for k in
                             ("wid", "title", "status", "type", "ticket", "project", "updated", "date")}})
    activity.sort(key=lambda a: (a["updated"] or a["date"]), reverse=True)

    # ---- 风险（§4.5：进行中 > STALE_DAYS 天未动）----
    stale_refs = []
    for e in employees:
        for w in e["entries"]:
            if w["status"] == "进行中" and w["updated"] and w["updated"] < (datetime.date.today() - datetime.timedelta(days=STALE_DAYS_DEFAULT)).strftime("%Y-%m-%d"):
                stale_refs.append({"eid": e["eid"], "name": e["name"], "title": w["title"], "updated": w["updated"]})

    gen_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    common = {"generated_at": gen_at, "page_version": PAGE_VERSION, "config": {"stale_days": STALE_DAYS_DEFAULT,
                        "active_status": [s2 for s2 in TASK_STATUS_ORDER if s2 in ACTIVE_TS]}}

    # 公司名：company.md「公司名」为权威（P2 实体卡）；无卡片时才退回目录名。
    # Z 方案下 base 是稳定锚 companies/<cid>，目录名兜底会退化成裸 ID（历史 bug）。
    base_name = os.path.basename(base_dir)
    comp_name = (parse_md_kv(read_text(os.path.join(base_dir, "company.md")), {"公司名": "name"}).get("name")
                 or (dir_label(base_name) if "-" in base_name else base_name))

    # ================= 公司级 dashboard-data.js =================
    dash = {
        **common,
        "company": {"cid": ctx.cid, "name": comp_name},
        "employees": [{k: v for k, v in e.items() if k != "entries"} | {
            "mydesk": os.path.join(e["dir"], "mydesk.html").replace(os.sep, "/")} for e in employees],
        "teams": [{**{k: v for k, v in t.items() if k != "members"},
                   "member_count": len(t["members"]),
                   "teamboard": os.path.join(t["dir"], "teamboard.html").replace(os.sep, "/")} for t in teams],
        "projects": [{**p, "ticket_stats": ticket_stats.get(p["pid"], {"total": 0, "byStatus": {}, "overdue": 0})} for p in projects],
        "affairs": affairs,
        "tickets": ticket_summary(tasks),
        "activity": activity[:300],
        "risks": {"stale": stale_refs, "warnings": warnings},
        "links": {"kanban": "workbench/kanban.html"},
        "status_meta": tasks_data.get("status_meta", {}),
    }
    write_js(os.path.join(base_dir, "dashboard-data.js"), "DASHBOARD_DATA", dash)
    sync_file(ctx, os.path.join(ctx.page_tpl, "dashboard.html"), os.path.join(base_dir, "dashboard.html"))

    # ================= 团队级 T*/teamboard-data.js + html =================
    team_tpl = os.path.join(ctx.page_tpl, "teamboard.html")
    for t in teams:
        members = [e for e in employees if e["eid"] in t["members"]]
        agg = stats_of([w for e in members for w in e["entries"]])
        t_projects = [p for p in projects if t["tid"] in p["teams"]]
        t_activity = [a for a in activity if a["eid"] in t["members"]][:200]
        member_eids = set(t["members"])
        payload = {
            **common, "tid": t["tid"], "name": t["name"], "member_count": len(members),
            "leads": t["leads"],
            "members": [{k: v for k, v in e.items() if k != "entries"} | {
                "mydesk": os.path.join("..", e["dir"], "mydesk.html").replace(os.sep, "/")} for e in members],
            "stats": agg,
            "tickets": ticket_summary([x for x in tasks if x.get("owner") in member_eids]),
            "projects": [{**p, "ticket_stats": ticket_stats.get(p["pid"], {"total": 0, "byStatus": {}, "overdue": 0})} for p in t_projects],
            "activity": t_activity,
            "notices": parse_notices(ctx, t["dir"]),
            "assets": parse_skills(ctx, t["dir"]),
            "links": sibling_nav_links(),
            "status_meta": tasks_data.get("status_meta", {}),
        }
        write_js(os.path.join(base_dir, t["dir"], "teamboard-data.js"), "TEAMBOARD_DATA", payload)
        sync_file(ctx, team_tpl, os.path.join(base_dir, t["dir"], "teamboard.html"))

    # ================= 个人级 E*/mydesk-data.js + html =================
    desk_tpl = os.path.join(ctx.page_tpl, "mydesk.html")
    done_ids = [t["id"] for t in tasks if t["status"] == "done"]
    for e in employees:
        tid_list = [t for t in teams if e["eid"] in t["members"]]
        my_tickets = []
        needs_done_ids = False
        for t in tasks:
            if t.get("owner") != e["eid"]:
                continue
            if t["status"] in ACTIVE_TS or t["status"] == "paused":
                bb = [str(b) for b in (t.get("blocked_by") or [])]
                if bb:
                    needs_done_ids = True
                my_tickets.append({
                    "id": t["id"], "title": t["title"], "status": t["status"],
                    "due": t.get("due") or "", "priority": t.get("priority") or "",
                    "blocked_by": bb,
                    "paused": t["status"] == "paused",
                    "detail": "../workbench/kanban.html?id=" + t["id"],
                })
        my_warnings = [w for w in warnings if e["eid"] in w["msg"]]
        payload = {
            **common, "eid": e["eid"], "name": e["name"], "role": e["role"], "status": e["status"],
            "teams": [{"tid": t["tid"], "name": t["name"],
                       "teamboard": os.path.join("..", t["dir"], "teamboard.html").replace(os.sep, "/")} for t in tid_list],
            "entries": e["entries"], "stats": e["stats"], "tickets": my_tickets,
            "skills": parse_skills(ctx, e["dir"]),
            "links": sibling_nav_links(),
            "warnings": my_warnings,
        }
        if needs_done_ids:
            # 仅当本员工确有被阻塞工单才带全公司已完成单号（阻塞判断用）；
            # 无阻塞单的员工零冗余（原版每份 mydesk 背 O(任务) 列表，已裁剪）
            payload["all_tasks_done"] = done_ids
        write_js(os.path.join(base_dir, e["dir"], "mydesk-data.js"), "MYDESK_DATA", payload)
        sync_file(ctx, desk_tpl, os.path.join(base_dir, e["dir"], "mydesk.html"))

    print(f"  [完成] 员工 {len(employees)} / 团队 {len(teams)} / 项目 {len(projects)} / 动态 {len(activity)} / 告警 {len(warnings)}")
    return len(warnings)


def load_tasks_data(ctx):
    """读工单产物（不重复解析 tasks/）。"""
    if not os.path.isfile(ctx.tasks_data):
        print(f"  [警告] 未找到 {ctx.tasks_data}，工单联动模块将为空（请先运行 opc_tickets）")
        return {"tasks": [], "employees": {}, "projects": {}, "status_meta": {}}
    try:
        with open(ctx.tasks_data, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as e:
        print(f"  [警告] tasks-data.json 解析失败（{e}），工单联动模块将为空")
        return {"tasks": [], "employees": {}, "projects": {}, "status_meta": {}}


# ---------- watch：轮询数据源 mtime ----------

def deps_mtime(ctx):
    """依赖文件集最新 mtime（roster/worklog/team/notices/project/skills/模板/tasks-data）。"""
    latest = 0
    base_dir = ctx.base
    # company.md 在列：公司名等实体卡字段变化也要触发重生成（N1 修复后它是显示数据来源）
    paths = [os.path.join(base_dir, ctx.roster_rel), ctx.tasks_data,
             os.path.join(base_dir, "company.md")]
    emp_dirs, team_dirs, proj_dirs = scan_entity_dirs(base_dir)
    for d in emp_dirs:
        paths += [os.path.join(base_dir, d, "workspace", "worklog.md")]
        arch = os.path.join(base_dir, d, "workspace", "worklog-archive")
        if os.path.isdir(arch):
            for name in os.listdir(arch):
                if name.endswith(".md"):
                    paths.append(os.path.join(arch, name))
        paths.append(os.path.join(base_dir, d, "skills"))
    for d in team_dirs:
        paths += [os.path.join(base_dir, d, "team.md"), os.path.join(base_dir, d, "notices.md"),
                  os.path.join(base_dir, d, "skills")]
    for d in proj_dirs:
        paths.append(os.path.join(base_dir, d, "project.md"))
    if os.path.isdir(ctx.page_tpl):
        for f in os.listdir(ctx.page_tpl):
            paths.append(os.path.join(ctx.page_tpl, f))
    for p in paths:
        try:
            if os.path.isdir(p):
                for root, _dirs, files in os.walk(p):
                    for f in files:
                        latest = max(latest, os.path.getmtime(os.path.join(root, f)))
            elif os.path.isfile(p):
                latest = max(latest, os.path.getmtime(p))
        except OSError:
            pass
    return latest


def safe_generate(ctx):
    try:
        generate_all(ctx)
    except Exception as e:
        print(f"  [错误] 生成失败：{e}，继续监听…")


def watch(ctx):
    print(f"监听中：{ctx.base}（每 3 秒检测变动，Ctrl+C 退出）")
    last = deps_mtime(ctx)
    safe_generate(ctx)
    try:
        while True:
            time.sleep(3.0)
            cur = deps_mtime(ctx)
            if cur != last:
                last = cur
                print(f"\n[{datetime.datetime.now().strftime('%H:%M:%S')}] 检测到变动，重新生成…")
                safe_generate(ctx)
    except KeyboardInterrupt:
        print("\n已停止监听。")


def selftest():
    import tempfile
    ok = True

    def check(name, cond):
        nonlocal ok
        print(("  ✓ " if cond else "  ✗ ") + name)
        if not cond:
            ok = False

    print("运行内置自测…")
    # 1) 块切分与 worklog 解析
    blocks = split_blocks("---\nwid: A\n---\nbody1\n\n---\nwid: B\n---\nbody2")
    check("split_blocks 两块", len(blocks) == 2)
    fm, body, has = parse_frontmatter("---\n" + blocks[0][0] + "\n---")
    check("块内 frontmatter", has and fm["wid"] == "A")
    # 2) roster 表格解析（含团队列/多团队/角色列）
    with tempfile.TemporaryDirectory() as tmp:
        rp = os.path.join(tmp, "roster.md")
        with open(rp, "w", encoding="utf-8") as fh:
            fh.write("| 员工 ID | 路径 | 岗位 | 状态 | 团队 | 角色 | 备注 |\n|---|---|---|---|---|---|---|\n"
                     "| E0001 | E0001-x/ | 分析员 | 在职 | T001,T002 | lead |  |\n"
                     "| E0002 | E0002-x/ | 开发 | 在职 | T001 | 成员 |  |\n")
        ros = parse_roster(rp, [])
        check("roster 团队列多值", ros["E0001"]["teams"] == ["T001", "T002"])
        check("roster 角色列 lead", ros["E0001"]["rank"] == "lead" and ros["E0002"]["rank"] == "成员")
    # 2b) worklog 归档全量扫描 + archived 标记（ctx 注入临时目录，不碰全局）
    with tempfile.TemporaryDirectory() as tmp:
        cfg = opc_resolver.CompanyConfig("C999", tmp, {})
        ctx = Ctx(cfg, tmp, os.path.join(tmp, "page-templates"),
                  os.path.join(tmp, "tasks-data.json"), "roster.md", os.path.join(tmp, "affairs"))
        os.makedirs(os.path.join(tmp, "E0001-甲", "workspace", "worklog-archive"), exist_ok=True)
        with open(os.path.join(tmp, "E0001-甲", "workspace", "worklog.md"), "w", encoding="utf-8") as fh:
            fh.write("---\nwid: W1\ndate: 2026-08-27\ntitle: 热条目\ntype: 直聊\nstatus: 进行中\nupdated: 2026-08-27\n---\n")
        with open(os.path.join(tmp, "E0001-甲", "workspace", "worklog-archive", "worklog-2025.md"), "w", encoding="utf-8") as fh:
            fh.write("---\nwid: W0\ndate: 2025-12-01\ntitle: 归档条目\ntype: 直聊\nstatus: 已完成\nupdated: 2025-12-01\n---\n")
        ents = parse_worklog(ctx, "E0001", "E0001-甲")
        check("归档全量扫描(热+冷共2条)", len(ents) == 2)
        hot = [e for e in ents if not e["archived"]][0]
        cold = [e for e in ents if e["archived"]][0]
        check("archived 标记正确", hot["title"] == "热条目" and cold["title"] == "归档条目")
        # 看板页内跳转链接：纯相对路径（file:// 与 opc_service /CID/ 路由双模式成立），
        # 锚前缀 companies/<cid>/ 在服务模式下与 URL 前缀双重拼接 → 404（跳转 bug 修复）
        check("页内跳转双模式相对路径", sibling_nav_links() == {"dashboard": "../dashboard.html",
                                                                "kanban": "../workbench/kanban.html"})
    # 3) project.md 双格式解析
    with tempfile.TemporaryDirectory() as tmp:
        cfg = opc_resolver.CompanyConfig("C999", tmp, {})
        ctx = Ctx(cfg, tmp, tmp, os.path.join(tmp, "tasks-data.json"), "roster.md", os.path.join(tmp, "affairs"))
        os.makedirs(os.path.join(tmp, "P0001-甲"), exist_ok=True)
        with open(os.path.join(tmp, "P0001-甲", "project.md"), "w", encoding="utf-8") as fh:
            fh.write("---\nid: P0001\nname: 甲\nteam: [T001]\n---\n")
        os.makedirs(os.path.join(tmp, "P0002-乙"), exist_ok=True)
        with open(os.path.join(tmp, "P0002-乙", "project.md"), "w", encoding="utf-8") as fh:
            fh.write("## 项目信息\n- 项目 ID：P0002\n- 名称：乙\n- 归属团队：T009-不存在（引用制）\n")
        p1, p2 = parse_project(ctx, "P0001-甲"), parse_project(ctx, "P0002-乙")
        check("project frontmatter team 数组", p1["teams"] == ["T001"])
        check("project markdown 兜底解析", p2["name"] == "乙" and p2["teams"] == [])
    # 4) 交叉核验（未认领合并后单条）
    ctx4 = Ctx(opc_resolver.CompanyConfig("C999", "", {}), "", "", "", "", "")
    warns = ctx4.warnings
    ee = {"E0001": [
        {"wid": "1", "date": "2026-08-27", "title": "a", "status": "进行中", "type": "工单",
         "ticket": "TSKX1", "project": "", "updated": "2026-08-27", "note": "", "deliverable": "", "deliverable_valid": True},
        {"wid": "2", "date": "2026-08-27", "title": "b", "status": "已完成", "type": "工单",
         "ticket": "TSKX2", "project": "", "updated": "2026-08-27", "note": "", "deliverable": "", "deliverable_valid": True},
        {"wid": "3", "date": "2026-08-27", "title": "c", "status": "进行中", "type": "工单",
         "ticket": "TSKX9", "project": "", "updated": "2026-08-27", "note": "", "deliverable": "", "deliverable_valid": True},
    ]}
    tasks = [
        {"id": "TSKX1", "title": "t1", "status": "done", "owner": "E0001"},
        {"id": "TSKX2", "title": "t2", "status": "in_progress", "owner": "E0001"},
        {"id": "TSKX3", "title": "t3", "status": "review", "owner": "E0002"},
        {"id": "TSKX4", "title": "t4", "status": "backlog", "owner": "E0002"},
        {"id": "TSKX5", "title": "t5", "status": "backlog", "owner": ""},
    ]
    cross_validate(ctx4, ee, tasks)
    msgs = " | ".join(w["msg"] for w in warns)
    check("核验R4 进行中vs工单终态", "TSKX1" in msgs and "已done" in msgs)
    check("核验R5 已完成vs工单未关", "仍未关" in msgs)
    check("核验R1 ticket不存在", "TSKX9" in msgs)
    check("核验未认领单条(review)", msgs.count("TSKX3") == 1 and "未认领" in msgs)
    check("核验未认领(backlog)", "未认领" in msgs and "TSKX4" in msgs)
    check("核验无owner不告未认领", "TSKX5" not in msgs)
    # 4b) 常设事务：节奏推导
    affairs = [
        {"id": "AFF0001", "title": "周内容运营", "status": "active", "owner": "E0002",
         "cadence": "每周", "priority": "中", "created": "2026-08-01", "updated": "2026-08-01", "body": "", "dir": "AFF0001-x"},
        {"id": "AFF0002", "title": "按需维护", "status": "active", "owner": "E0001",
         "cadence": "按需", "priority": "低", "created": "2026-08-01", "updated": "2026-08-01", "body": "", "dir": "AFF0002-x"},
        {"id": "AFF0003", "title": "从未推进", "status": "active", "owner": "E0001",
         "cadence": "每周", "priority": "中", "created": "2026-08-01", "updated": "2026-08-01", "body": "", "dir": "AFF0003-x"},
    ]
    ee2 = {"E0002": [{"wid": "9", "date": "2026-08-20", "title": "运营推进", "status": "已完成", "type": "事务",
                      "ticket": "", "project": "", "aff": "AFF0001", "updated": "2026-08-20", "note": "",
                      "deliverable": "", "deliverable_valid": True}]}
    link_affairs(affairs, ee2)
    a1 = [a for a in affairs if a["id"] == "AFF0001"][0]
    a2 = [a for a in affairs if a["id"] == "AFF0002"][0]
    a3 = [a for a in affairs if a["id"] == "AFF0003"][0]
    check("事务 last_touched 推导", a1["last_touched"] == "2026-08-20" and a1["last_by"] == "E0002")
    check("事务 touches 推进记录", len(a1["touches"]) == 1 and a1["touches"][0]["eid"] == "E0002"
          and a1["touches"][0]["status"] == "已完成")
    check("事务 无推进 touches 为空", a3["touches"] == [])
    check("事务 按需不判逾期", a2["overdue"] is False and a2["never_done"] is False)
    check("事务 从未推进标记", a3["never_done"] is True)
    # 4c) 工单口径汇总（与 worklog 条目分账）
    ts = ticket_summary([
        {"id": "A", "status": "backlog"}, {"id": "B", "status": "in_progress", "due": "2000-01-01"},
        {"id": "C", "status": "review"}, {"id": "D", "status": "done"},
        {"id": "E", "status": "paused"}, {"id": "F", "status": "failed"}, {"id": "G", "status": "cancelled"},
    ])
    check("工单汇总 在途/完成/单列", ts["active"] == 3 and ts["done"] == 1
          and ts["paused"] == 1 and ts["failed"] == 1 and ts["cancelled"] == 1 and ts["total"] == 7)
    check("工单汇总 逾期=在途且过due", ts["overdue"] == 1)
    # 5) 统计口径
    st = stats_of([{"status": "计划中"}, {"status": "进行中"}, {"status": "进行中"}, {"status": "已完成"}])
    check("统计 累计口径/在途", st["total"] == 4 and st["ongoing"] == 3 and st["rate"] == 0.25)
    # 6) 集成：临时公司全链路
    with tempfile.TemporaryDirectory(prefix="dash_it_") as tmp:
        base = os.path.join(tmp, "C888-测试公司")
        wb = os.path.join(base, "workbench")
        os.makedirs(wb, exist_ok=True)
        with open(os.path.join(base, "company.md"), "w", encoding="utf-8") as fh:
            fh.write("# C888 | 测试\n- 公司 ID：C888\n- 公司名：测试公司甲\n")
        os.makedirs(os.path.join(base, "T001-开发"), exist_ok=True)
        os.makedirs(os.path.join(base, "E0001-分析员", "workspace"), exist_ok=True)
        os.makedirs(os.path.join(base, "page-templates"), exist_ok=True)
        with open(os.path.join(base, "T001-开发", "team.md"), "w", encoding="utf-8") as fh:
            fh.write("# T001\n- 团队 ID：T001\n- 名称：开发\n")
        with open(os.path.join(base, "E0001-分析员", "workspace", "worklog.md"), "w", encoding="utf-8") as fh:
            fh.write("---\nwid: W1\ndate: 2026-08-27\ntitle: 干活\ntype: 直聊\nstatus: 进行中\nupdated: 2026-08-27\n---\n")
        os.makedirs(os.path.join(base, "E0000"), exist_ok=True)
        with open(os.path.join(base, "E0000", "roster.md"), "w", encoding="utf-8") as fh:
            fh.write("| 员工 ID | 路径 | 岗位 | 状态 | 团队 | 角色 | 备注 |\n|---|---|---|---|---|---|---|\n"
                     "| E0001 | E0001-分析员/ | 分析员 | 在职 | T001 | lead | x |\n")
        with open(os.path.join(wb, "tasks-data.json"), "w", encoding="utf-8") as fh:
            json.dump({"tasks": [{"id": "TSK1", "title": "x", "status": "in_progress", "owner": "E0001", "project": "P1",
                                  "blocked_by": []}],
                       "employees": {}, "projects": {}, "status_meta": {"in_progress": "进行中"}}, fh)
        roster_rel = os.path.join("E0000", "roster.md")
        cfg = opc_resolver.CompanyConfig("C888", tmp, {})
        ctx = Ctx(cfg, base, os.path.join(base, "page-templates"), os.path.join(wb, "tasks-data.json"),
                  roster_rel, os.path.join(wb, "affairs"))
        generate_all(ctx)
        with open(os.path.join(base, "T001-开发", "teamboard-data.js"), encoding="utf-8") as fh:
            tj = fh.read()
        check("集成: 团队切片含成员统计", '"member_count": 1' in tj and '"E0001"' in tj)
        tj_data = json.loads(re.match(r"^window\.\w+ = ([\s\S]*);\s*$", tj).group(1))
        check("集成: 团队切片含 lead 与工单汇总", tj_data["leads"] == ["E0001"]
              and tj_data["tickets"]["active"] == 1)
        check("集成: 团队切片跳转纯相对路径", tj_data["links"] == {"dashboard": "../dashboard.html",
                                                                   "kanban": "../workbench/kanban.html"})
        with open(os.path.join(base, "E0001-分析员", "mydesk-data.js"), encoding="utf-8") as fh:
            mj = fh.read()
        check("集成: 个人台含在途工单与未认领告警", '"TSK1"' in mj and "未认领" in mj)
        check("集成: 个人台工单深链纯相对路径", '"../workbench/kanban.html?id=TSK1"' in mj)
        with open(os.path.join(base, "dashboard-data.js"), encoding="utf-8") as fh:
            dj = fh.read()
        check("集成: 公司级动态流", "干活" in dj)
        dj_data = json.loads(re.match(r"^window\.\w+ = ([\s\S]*);\s*$", dj).group(1))
        check("集成: 公司级工单汇总", dj_data["tickets"]["active"] == 1 and dj_data["tickets"]["total"] == 1)
        check("集成: cid 来自 manifest 非目录名解析", '"cid": "C888"' in dj)
        check("集成: 公司名来自 company.md 实体卡", '"name": "测试公司甲"' in dj)
    print("自测" + ("全部通过 ✓" if ok else "存在失败 ✗"))
    return 0 if ok else 1


def main(argv):
    if "--selftest" in argv:
        return selftest()
    company, company_dir = parse_company_args(argv)
    ctx = resolve_ctx(company, company_dir)
    if "--watch" in argv:
        watch(ctx)
    elif "--verify" in argv:
        return verify_outputs(ctx)
    else:
        print("生成三级看板数据…")
        generate_all(ctx)
        print("完成。")
    return 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")   # Windows cp1252 控制台/CI 下中文输出防崩（CI 实测）
    sys.exit(main(sys.argv))
