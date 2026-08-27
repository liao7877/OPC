#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
三级看板数据生成器（零依赖，仅标准库）——落位规则（廖哥 2026-08-27 拍板）：
  公司级   -> 公司根/dashboard.html + dashboard-data.js
  团队级   -> T*/teamboard.html + teamboard-data.js
  个人级   -> E*/mydesk.html + mydesk-data.js（员工目录根，不套 workbench/）
  工具随看板走：本脚本、page-templates/、run_boards.bat 等都在公司根；
  workbench/ 只归工单系统（kanban/tasks/generate_tasks.py/tasks-data.js）。

扫描公司根各实体（roster / E*/workspace/worklog.md / T*/team.md+notices.md / P*/project.md），
复用工单产物 workbench/tasks-data.json（不重复解析 tasks/），一次扫描分头产出三级数据文件。

用法（在公司根下执行）：
    python generate_dashboard.py            # 单次生成
    python generate_dashboard.py --watch    # 监听数据源变动，自动重跑
    python generate_dashboard.py --selftest # 内置自测

设计要点（见 P0004/REQ-三级可视化看板系统.md）：
- 单一真相：员工→团队归属以 roster.md「团队」列为唯一权威（A1）；项目归属读 project.md team 字段。
- 交叉核验（A2）：worklog 工单型条目与 tasks-data.json 逐条核对，只告警不阻断。
- 统计口径（B1/§4.5）：完成率=已完成/全部有效条目（累计）；在途=计划中+进行中。
- 页面分发：teamboard/mydesk 的 HTML 模板放 page-templates/，每次生成同步到
  各实体目录（内容有变才写）——升级只改模板一处，下次生成全员自动刷新（§6 维护约定）。
- 容错家规：坏条目跳过+告警不阻断；日期规整；deliverable/ticket/team 引用失效标 ⚠️。
"""

import os
import sys
import re
import json
import time
import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
COMPANY_DIR = SCRIPT_DIR                          # 工具随看板走：脚本即在公司根
PAGE_TPL_DIR = os.path.join(SCRIPT_DIR, "page-templates")
TASKS_DATA = os.path.join(COMPANY_DIR, "workbench", "tasks-data.json")  # 复用工单产物
ROSTER_RELPATH = os.path.join("E0000-AI员工-总管", "roster.md")  # 总管花名册（相对公司根）

PAGE_VERSION = "v1.1"
WORKLOG_STATUS = {"计划中", "进行中", "已完成"}
STALE_DAYS_DEFAULT = 14          # 「N 天未动」缺省阈值（页面可调）
ACTIVE_TS = {"backlog", "in_progress", "review"}   # 工单活跃态（W4 在途口径；paused 显示不计数）
TODAY = datetime.date.today().strftime("%Y-%m-%d")

# 常设事务（机制扩展 #17，2026-08-28）：workbench/affairs/AFFxxxx-标题/
AFFAIRS_DIR = os.path.join(COMPANY_DIR, "workbench", "affairs")
AFF_STATUS = {"active", "paused", "closed"}
# cadence -> 逾期天数阈值（距上次 worklog 推进；按需不判定）
AFF_CADENCE_DAYS = {"每日": 2, "每周": 9, "每两周": 17, "每月": 35}

# ---------- DIP 改造（PoC 2026-08-28）：路径常量从 opc 命名空间 manifest 注入 ----------
# 高层（生成逻辑）只依赖 opc:// 符号；物理路径（目录名/布局）下沉到 opc.toml。
# 改名/改布局 = 只改 opc.toml 一行，本脚本与所有 consumer 零改动。
try:
    _ROOT = os.path.dirname(SCRIPT_DIR)                 # OPC 根（脚本位于 C001/ 下）
    if _ROOT not in sys.path:
        sys.path.insert(0, _ROOT)
    import opc_resolver as _opc
    _cfg = _opc.load_company("C001")
    COMPANY_DIR = _cfg.home_abs
    PAGE_TPL_DIR = _cfg.page_templates_abs
    TASKS_DATA = _cfg.tasks_data_abs
    ROSTER_RELPATH = _cfg.roster_rel
    AFFAIRS_DIR = _cfg.affairs_abs
    print(f"  [opc] 命名空间已注入：公司根={COMPANY_DIR}")
except Exception as _e:
    print(f"  [opc] 未加载 manifest，回退 __file__ 推导（{_e}）")


# ---------- 基础工具（与 generate_tasks.py 同构，保持家规一致） ----------

def parse_frontmatter(text):
    """极简 frontmatter 解析：key: value / key: [a, b] / key:(空)。返回 (dict, body, has_fm)。"""
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


def normalize_date(s):
    """规整为 YYYY-MM-DD（补前导零）；无法识别返回 None。"""
    if not s:
        return None
    m = re.match(r"^(\d{4})-(\d{1,2})-(\d{1,2})", str(s).strip())
    if not m:
        return None
    return "%04d-%02d-%02d" % (int(m.group(1)), int(m.group(2)), int(m.group(3)))


def read_text(path):
    if not os.path.isfile(path):
        return ""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return fh.read()
    except Exception as e:
        print(f"  [警告] 读取失败（疑似非 UTF-8）：{path}（{e}），按空处理")
        return ""


def atomic_write(path, text):
    tmp = path + ".tmp"
    # newline="" 禁止 \n→\r\n 翻译：保证页面分发副本与模板逐字节一致
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    os.replace(tmp, path)


def write_js(path, var_name, payload):
    """产出 file:// 可用的数据 js（内联全局变量；防 </script> 破坏字面量）。"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    js = "window.%s = %s;\n" % (var_name, json.dumps(payload, ensure_ascii=False, indent=2))
    js = js.replace("</script", "<\\/script")
    atomic_write(path, js)
    print(f"  [完成] {var_name} -> {path}")


def sync_file(src, dst):
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
        rel = os.path.relpath(dst, COMPANY_DIR)
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
    """扫描公司根：返回 (employees_dirs, teams_dirs, projects_dirs)，按代号排序。"""
    emp, team, proj = [], [], []
    if not os.path.isdir(base):
        return emp, team, proj
    for name in sorted(os.listdir(base)):
        if not os.path.isdir(os.path.join(base, name)):
            continue
        if re.match(r"^E\d{3,}-", name):
            emp.append(name)
        elif re.match(r"^T\d{3,}-", name):
            team.append(name)
        elif re.match(r"^P\d{3,}-", name):
            proj.append(name)
    return emp, team, proj


def dir_label(dirname, prefix_len):
    """E0001-AI员工-分析员 -> 分析员（去常量前缀）；P0001-示例项目 -> 示例项目。"""
    label = dirname.split("-", 1)[1] if "-" in dirname else dirname
    if label.startswith("AI员工-"):
        label = label[len("AI员工-"):]
    return label


def parse_roster(path):
    """解析 roster.md 表格 -> {eid: {role, status, teams[], note, rank}}；坏行跳过告警。
    防呆（P1，廖哥拍板）：eid/team 代号做正则校验，坏值报错跳过而不是静默吞掉。
    「角色」列（机制扩展 #8，2026-08-28）：lead=团队负责人（统筹团队 workflow/技能），
    缺省为普通成员；不写进状态枚举校验（自由文本，如 "lead" / "成员"）。"""
    roster = {}
    if not os.path.isfile(path):
        print(f"  [警告] 找不到花名册：{path}（员工将以目录扫描兜底、标记未登记）")
        return roster
    for line in read_text(path).splitlines():
        m = re.match(r"^\|\s*(E\d{3,})\s*\|(.+)\|\s*$", line)
        if not m:
            continue
        cells = [c.strip() for c in m.group(2).split("|")]
        # 列序：路径 | 岗位 | 状态 | 团队 | 角色 | 备注（后两列可缺失，容错）
        role = cells[1] if len(cells) > 1 else ""
        status = cells[2] if len(cells) > 2 else "在职"
        team_cell = cells[3] if len(cells) > 3 else "-"
        rank = cells[4] if len(cells) > 4 else ""
        note = cells[5] if len(cells) > 5 else ""
        teams, bad_teams = [], []
        for t in re.split(r"[，,、\s]+", team_cell):
            if re.match(r"^T\d+$", t):
                teams.append(t)
            elif t not in ("-", "", "无"):
                bad_teams.append(t)   # 形似代号但非法（如 T00O / T-01）
        eid = m.group(1)
        if bad_teams:
            print(f"  [错误] roster {eid} 团队列含非法代号 {bad_teams}（应为 T+数字），已忽略这些值——若该员工属于某团队请修正 roster")
        if not re.match(r"^(在职|休假|离职|未登记)$", status):
            print(f"  [错误] roster {eid} 状态列 {status!r} 不在 在职/休假/离职/未登记 内，按原文保留展示")
        roster[eid] = {"role": role, "status": status, "teams": teams, "rank": rank, "note": note}
    return roster


def parse_project(dirname):
    """解析 project.md（frontmatter 优先，markdown「键：值」兜底）。
    team 字段：单值或数组；markdown 兜底只认 T\\d+ 代号。"""
    pid = dirname.split("-", 1)[0]
    raw = read_text(os.path.join(COMPANY_DIR_cur[0], dirname, "project.md"))
    fm, _, has = parse_frontmatter(raw)
    if has:
        name = fm.get("name") or dir_label(dirname, 2)
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
        name = kv.get("name") or dir_label(dirname, 2)
        owner = kv.get("owner")
        status = kv.get("status") or "active"
        # team 归属只认 frontmatter 显式声明（REQ §4.2）：markdown 正文提到的 T 编号
        # 可能只是叙述性引用，抓取会导致项目被意外划归团队，故不兜底
        teams = []
    return {"pid": pid, "name": name, "owner": owner, "status": status, "teams": teams, "dir": dirname}


def parse_team(dirname):
    """解析 team.md -> {tid, name}（markdown 行兜底，无文件用目录名）。"""
    tid = dirname.split("-", 1)[0]
    raw = read_text(os.path.join(COMPANY_DIR_cur[0], dirname, "team.md"))
    kv = parse_md_kv(raw, {"团队 ID": "tid", "名称": "name"})
    return {"tid": kv.get("tid") or tid, "name": kv.get("name") or dir_label(dirname, 2), "dir": dirname}


def parse_notices(team_dir):
    """解析 T*/notices.md 公告块 -> [{title,date,author,body}]；坏块跳过告警。"""
    path = os.path.join(COMPANY_DIR_cur[0], team_dir, "notices.md")
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


def parse_skills(entity_dir):
    """扫描 {entity}/skills/*/SKILL.md frontmatter -> [{name, desc}]（资产索引/身份卡）。"""
    out = []
    sdir = os.path.join(COMPANY_DIR_cur[0], entity_dir, "skills")
    if not os.path.isdir(sdir):
        return out
    for name in sorted(os.listdir(sdir)):
        sk = os.path.join(sdir, name, "SKILL.md")
        if not os.path.isfile(sk):
            continue
        fm, _, _ = parse_frontmatter(read_text(sk))
        out.append({"name": fm.get("name") or name, "desc": fm.get("description") or ""})
    return out


def parse_worklog(eid, emp_dir, warnings):
    """解析 E*/workspace/worklog.md（热）+ worklog-archive/worklog-*.md（冷，机制扩展 #6
    年度归档，2026-08-28）多块记录 -> 条目列表（含校验告警）。
    归档只动文件位置不动数据：生成器全量扫描保证历史在看板照常显示（P4 管道不变）。
    家规（第五轮补定）：deliverable 路径以「员工目录根」为基准书写
    （如 ../P0004-xxx/报告.md 指向公司根下项目目录、roster.md 指向本目录文件）。"""
    entries = []
    base = os.path.join(COMPANY_DIR_cur[0], emp_dir, "workspace")
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
                # 基准约定：deliverable 相对「员工目录根」书写（docstring 家规）。
                # 校验真实存在性；同时换算成 mydesk.html（同在员工目录根）可用的纯相对链接，
                # 页面不再自己拼 ../ 前缀（避免双跳跳出公司根）。
                full = os.path.normpath(os.path.join(COMPANY_DIR_cur[0], emp_dir, deliverable))
                valid_deliv = os.path.exists(full)
                if not valid_deliv:
                    warnings.append({"scope": "核验", "msg": f"{eid}「{title}」deliverable 路径失效：{deliverable}"})
                else:
                    deliv_href = os.path.relpath(full, os.path.join(COMPANY_DIR_cur[0], emp_dir)).replace(os.sep, "/")
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
    done_7d=近7天新增完成数（P2 轻量补充：防止累计口径淹没近期表现）。"""
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


def load_tasks_data():
    """读工单产物（不重复解析 tasks/，见 §5-1）。"""
    if not os.path.isfile(TASKS_DATA_cur[0]):
        print(f"  [警告] 未找到 {TASKS_DATA_cur[0]}，工单联动模块将为空（请先运行 generate_tasks.py）")
        return {"tasks": [], "employees": {}, "projects": {}, "status_meta": {}}
    try:
        with open(TASKS_DATA_cur[0], "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception as e:
        print(f"  [警告] tasks-data.json 解析失败（{e}），工单联动模块将为空")
        return {"tasks": [], "employees": {}, "projects": {}, "status_meta": {}}


def cross_validate(emp_entries, tasks, warnings):
    """A2 交叉核验（只告警不阻断）：
    R1 工单型条目 ticket 不存在；R2 在途工单(in_progress/review)缺 worklog 记录；
    R3 在途工单有记录但状态不是进行中；R4 进行中条目对应工单已终态；
    R5 已完成条目对应工单仍未关（backlog/in_progress/review）。backlog/paused 双向豁免。"""
    tmap = {t["id"]: t for t in tasks}
    for eid, entries in emp_entries.items():
        for e in entries:
            if not e["ticket"]:
                continue
            t = tmap.get(e["ticket"])
            if t is None:
                warnings.append({"scope": "核验", "msg": f"{eid}「{e['title']}」引用的工单 {e['ticket']} 不存在"})
                continue
            if e["status"] == "进行中" and t["status"] in ("done", "failed", "cancelled"):
                warnings.append({"scope": "核验", "msg": f"{eid}「{e['title']}」记录进行中，但工单 {e['ticket']} 已{t['status']}"})
            if e["status"] == "已完成" and t["status"] in ACTIVE_TS:
                warnings.append({"scope": "核验", "msg": f"{eid}「{e['title']}」已完成，但工单 {e['ticket']} 仍未关（{t['status']}）——记得关单"})
    for t in tasks:
        if t.get("status") not in ("in_progress", "review") or not t.get("owner"):
            continue
        owner = t["owner"]
        mine = [e for e in emp_entries.get(owner, []) if e["ticket"] == t["id"]]
        if not mine:
            warnings.append({"scope": "核验", "msg": f"{owner} 名下在途工单 {t['id']}「{t['title']}」未记 worklog（A2 双账）"})
        elif all(e["status"] != "进行中" for e in mine):
            warnings.append({"scope": "核验", "msg": f"{owner} 的 {t['id']} 工单在途，但 worklog 记录非「进行中」"})
    # 未认领核验（机制扩展 #4，2026-08-28）：owner 有主且未终态，但 owner 的 worklog 全档无该单条目
    # → 「已派未领」黄条。认领=worklog 建计划中条目（认领≠开工，backlog 也应有账）。
    for t in tasks:
        if not t.get("owner") or t.get("status") in ("done", "failed", "cancelled"):
            continue
        mine = [e for e in emp_entries.get(t["owner"], []) if e["ticket"] == t["id"]]
        if not mine:
            warnings.append({"scope": "核验", "msg": f"{t['owner']} 的工单 {t['id']}「{t['title']}」未认领（worklog 无条目；按 ticket-system §1.5 认领）"})


def ticket_stats_by_project(tasks):
    """项目维度工单统计（联动③）：总数/状态分布/逾期中数。"""
    out = {}
    for t in tasks:
        pid = t.get("project") or "未关联"
        s = out.setdefault(pid, {"total": 0, "byStatus": {}, "overdue": 0})
        s["total"] += 1
        s["byStatus"][t["status"]] = s["byStatus"].get(t["status"], 0) + 1
        if t.get("status") in ACTIVE_TS and t.get("due") and t["due"] < TODAY:
            s["overdue"] += 1
    return out


def parse_affairs(warnings):
    """扫描 workbench/affairs/AFFxxxx-标题/affair.md -> 事务列表。
    last_touched 由 worklog（aff 字段）推导，不靠人工填报（P1 文件即真相）。
    坏事务跳过+告警（P11）。"""
    out = []
    if not os.path.isdir(AFFAIRS_DIR):
        return out
    for name in sorted(os.listdir(AFFAIRS_DIR)):
        full = os.path.join(AFFAIRS_DIR, name)
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
    """worklog 推导各事务 last_touched（含归档，全量扫描）：扫 aff 字段。"""
    touched = {}
    for eid, entries in emp_entries.items():
        for e in entries:
            aff = str(e.get("aff") or "").strip()
            if not aff:
                continue
            day = e.get("updated") or e.get("date") or ""
            if aff not in touched or day > touched[aff][0]:
                touched[aff] = (day, eid)
    for a in affairs:
        t = touched.get(a["id"])
        a["last_touched"] = t[0] if t else ""
        a["last_by"] = t[1] if t else ""
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


def verify_outputs(base_dir):
    """--verify：产出一致性专项检查（原 verify_boards.js 的职责并入，动态扫描不硬编码）。
    ①三级数据同批生成（generated_at 一致）；②mydesk 在途工单深链不死链。纯读不写。"""
    base_dir = base_dir or COMPANY_DIR
    problems = []
    # 收集所有数据文件（公司根 + 各实体目录，动态扫描）
    payloads = []  # (label, data)
    def _load(path, label):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                text = fh.read()
            m = re.match(r"^window\.\w+ = ([\s\S]*);\s*$", text)
            import json as _json
            payloads.append((label, _json.loads(m.group(1)) if m else _json.loads(text)))
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
    kd_path = os.path.join(base_dir, "workbench", "tasks-data.json")
    if os.path.isfile(kd_path):
        with open(kd_path, "r", encoding="utf-8") as fh:
            task_ids = {t["id"] for t in json.load(fh).get("tasks", [])}
        for label, p in payloads:
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


# COMPANY_DIR_cur / TASKS_DATA_cur：模块级可变基准（--selftest 用临时目录替换，不碰真实数据）
COMPANY_DIR_cur = [COMPANY_DIR]
TASKS_DATA_cur = [TASKS_DATA]


def generate_all(base_dir=None, workbench_dir=None):
    """主流程：扫描 -> 核验 -> 三级切片产出。参数化供自测。
    base_dir = 公司根（公司级看板与工具所在）；workbench_dir = 工单系统目录（tasks-data.json）。"""
    base_dir = base_dir or COMPANY_DIR
    workbench_dir = workbench_dir or os.path.join(base_dir, "workbench")
    COMPANY_DIR_cur[0] = base_dir
    TASKS_DATA_cur[0] = os.path.join(workbench_dir, "tasks-data.json")
    warnings = []

    emp_dirs, team_dirs, proj_dirs = scan_entity_dirs(base_dir)
    roster = parse_roster(os.path.join(base_dir, ROSTER_RELPATH))
    tasks_data = load_tasks_data()
    tasks = tasks_data.get("tasks", [])

    # ---- 员工注册表（B2 仲裁：目录在 roster 无 -> 未登记告警；roster 有目录无 -> 忽略告警）----
    dir_by_eid = {d.split("-", 1)[0]: d for d in emp_dirs}
    employees = []
    emp_entries = {}
    for eid in sorted(set(dir_by_eid) | set(roster)):
        d = dir_by_eid.get(eid)
        r = roster.get(eid)
        if d is None:
            # A4：roster 路径必须落在公司根内
            rel = (r or {}).get("path", "") if r else ""
            outside = rel.startswith("..") or os.path.isabs(rel)
            print(f"  [警告] roster 登记 {eid} 但公司根下无目录{'（路径不在公司根内，A4 收紧约定）' if outside else ''}，已忽略")
            continue
        name = dir_label(d, 1)
        registered = r is not None
        if not registered:
            print(f"  [警告] 员工目录 {d} 未在 roster.md 登记，看板标记「未登记」")
        role = (r or {}).get("role") or name
        status = (r or {}).get("status") or ("未登记" if not registered else "在职")
        teams = (r or {}).get("teams") or []
        rank = (r or {}).get("rank") or ""
        entries = parse_worklog(eid, d, warnings)
        emp_entries[eid] = entries
        employees.append({
            "eid": eid, "name": name, "role": role, "status": status, "teams": teams,
            "rank": rank, "registered": registered, "dir": d, "entries": entries, "stats": stats_of(entries),
        })

    # ---- 团队（成员以 roster 为准，team.md 只提供 ID/名称；lead 取 roster「角色」列）----
    teams = []
    for d in team_dirs:
        info = parse_team(d)
        members = [e for e in employees if info["tid"] in e["teams"]]
        if not members:
            print(f"  [警告] 团队 {info['tid']} 在 roster 中无任何成员")
        leads = [e["eid"] for e in members if "lead" in (e.get("rank") or "").lower()]
        if members and not leads:
            print(f"  [警告] 团队 {info['tid']} 无 lead（roster「角色」列标 lead 的成员为负责人，负责统筹团队 workflow/技能）")
        teams.append({**info, "leads": leads, "members": [e["eid"] for e in members]})
    known_tids = {t["tid"] for t in teams}

    # ---- 项目（team 字段引用校验）----
    projects = []
    for d in proj_dirs:
        p = parse_project(d)
        for tid in p["teams"]:
            if tid not in known_tids:
                print(f"  [警告] {p['pid']} team 字段引用了不存在的团队 {tid}")
        projects.append(p)
    proj_by_pid = {p["pid"]: p for p in projects}
    for t in tasks:
        pid = t.get("project")
        if pid and pid not in proj_by_pid:
            print(f"  [警告] 工单 {t['id']} project={pid} 无对应项目目录（看板回退裸代号）")

    cross_validate(emp_entries, tasks, warnings)
    ticket_stats = ticket_stats_by_project(tasks)

    # ---- 常设事务（机制扩展 #17）：扫描 + worklog 推导节奏 + 逾期告警 ----
    affairs = link_affairs(parse_affairs(warnings), emp_entries)
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
    common = {"generated_at": gen_at, "page_version": PAGE_VERSION, "config": {"stale_days": STALE_DAYS_DEFAULT}}

    # ================= 公司级 dashboard-data.js =================
    dash = {
        **common,
        "company": {"cid": os.path.basename(base_dir).split("-", 1)[0],
                    "name": dir_label(os.path.basename(base_dir), 1) if "-" in os.path.basename(base_dir) else os.path.basename(base_dir)},
        "employees": [{k: v for k, v in e.items() if k != "entries"} | {
            "mydesk": os.path.join(e["dir"], "mydesk.html").replace(os.sep, "/")} for e in employees],
        "teams": [{**{k: v for k, v in t.items() if k != "members"},
                   "member_count": len(t["members"]),
                   "teamboard": os.path.join(t["dir"], "teamboard.html").replace(os.sep, "/")} for t in teams],
        "projects": [{**p, "ticket_stats": ticket_stats.get(p["pid"], {"total": 0, "byStatus": {}, "overdue": 0})} for p in projects],
        "affairs": affairs,
        "activity": activity[:300],
        "risks": {"stale": stale_refs, "warnings": warnings},
        "links": {"kanban": "workbench/kanban.html"},
        "status_meta": tasks_data.get("status_meta", {}),
    }
    write_js(os.path.join(base_dir, "dashboard-data.js"), "DASHBOARD_DATA", dash)
    sync_file(os.path.join(PAGE_TPL_DIR, "dashboard.html"), os.path.join(base_dir, "dashboard.html"))

    # ================= 团队级 T*/teamboard-data.js + html =================
    team_tpl = os.path.join(PAGE_TPL_DIR, "teamboard.html")
    for t in teams:
        members = [e for e in employees if e["eid"] in t["members"]]
        agg = stats_of([w for e in members for w in e["entries"]])
        t_projects = [p for p in projects if t["tid"] in p["teams"]]
        t_activity = [a for a in activity if a["eid"] in t["members"]][:200]
        payload = {
            **common, "tid": t["tid"], "name": t["name"], "member_count": len(members),
            "members": [{k: v for k, v in e.items() if k != "entries"} | {
                "mydesk": os.path.join("..", e["dir"], "mydesk.html").replace(os.sep, "/")} for e in members],
            "stats": agg,
            "projects": [{**p, "ticket_stats": ticket_stats.get(p["pid"], {"total": 0, "byStatus": {}, "overdue": 0})} for p in t_projects],
            "activity": t_activity,
            "notices": parse_notices(t["dir"]),
            "assets": parse_skills(t["dir"]),
            "links": {"dashboard": "../dashboard.html", "kanban": "../workbench/kanban.html"},
            "status_meta": tasks_data.get("status_meta", {}),
        }
        write_js(os.path.join(base_dir, t["dir"], "teamboard-data.js"), "TEAMBOARD_DATA", payload)
        sync_file(team_tpl, os.path.join(base_dir, t["dir"], "teamboard.html"))

    # ================= 个人级 E*/workbench/mydesk-data.js + html =================
    desk_tpl = os.path.join(PAGE_TPL_DIR, "mydesk.html")
    for e in employees:
        tid_list = [t for t in teams if e["eid"] in t["members"]]
        my_tickets = []
        for t in tasks:
            if t.get("owner") != e["eid"]:
                continue
            if t["status"] in ACTIVE_TS or t["status"] == "paused":
                my_tickets.append({
                    "id": t["id"], "title": t["title"], "status": t["status"],
                    "due": t.get("due") or "", "priority": t.get("priority") or "",
                    "blocked_by": t.get("blocked_by") or [],
                    "paused": t["status"] == "paused",
                    "detail": "../workbench/kanban.html?id=" + t["id"],
                })
        my_warnings = [w for w in warnings if e["eid"] in w["msg"]]
        all_done_ids = [t["id"] for t in tasks if t["status"] == "done"]  # mydesk 阻塞判断用
        payload = {
            **common, "eid": e["eid"], "name": e["name"], "role": e["role"], "status": e["status"],
            "teams": [{"tid": t["tid"], "name": t["name"],
                       "teamboard": os.path.join("..", t["dir"], "teamboard.html").replace(os.sep, "/")} for t in tid_list],
            "entries": e["entries"], "stats": e["stats"], "tickets": my_tickets,
            "all_tasks_done": all_done_ids,
            "skills": parse_skills(e["dir"]),
            "links": {"dashboard": "../dashboard.html", "kanban": "../workbench/kanban.html"},
            "warnings": my_warnings,
        }
        write_js(os.path.join(base_dir, e["dir"], "mydesk-data.js"), "MYDESK_DATA", payload)
        sync_file(desk_tpl, os.path.join(base_dir, e["dir"], "mydesk.html"))

    print(f"  [完成] 员工 {len(employees)} / 团队 {len(teams)} / 项目 {len(projects)} / 动态 {len(activity)} / 告警 {len(warnings)}")
    return len(warnings)


# ---------- watch：轮询数据源 mtime ----------

def deps_mtime():
    """依赖文件集最新 mtime（roster/worklog/team/notices/project/skills/模板/tasks-data）。"""
    latest = 0
    paths = [os.path.join(COMPANY_DIR, ROSTER_RELPATH), TASKS_DATA]
    emp_dirs, team_dirs, proj_dirs = scan_entity_dirs(COMPANY_DIR)
    for d in emp_dirs:
        paths += [os.path.join(COMPANY_DIR, d, "workspace", "worklog.md")]
        arch = os.path.join(COMPANY_DIR, d, "workspace", "worklog-archive")
        if os.path.isdir(arch):  # 归档文件变更也触发重生成（历史可见性）
            for name in os.listdir(arch):
                if name.endswith(".md"):
                    paths.append(os.path.join(arch, name))
        paths.append(os.path.join(COMPANY_DIR, d, "skills"))
    for d in team_dirs:
        paths += [os.path.join(COMPANY_DIR, d, "team.md"), os.path.join(COMPANY_DIR, d, "notices.md"),
                  os.path.join(COMPANY_DIR, d, "skills")]
    for d in proj_dirs:
        paths.append(os.path.join(COMPANY_DIR, d, "project.md"))
    if os.path.isdir(PAGE_TPL_DIR):
        for f in os.listdir(PAGE_TPL_DIR):
            paths.append(os.path.join(PAGE_TPL_DIR, f))
    for p in paths:
        try:
            if os.path.isdir(p):  # skills 目录：取树内最新
                for root, _dirs, files in os.walk(p):
                    for f in files:
                        latest = max(latest, os.path.getmtime(os.path.join(root, f)))
            elif os.path.isfile(p):
                latest = max(latest, os.path.getmtime(p))
        except OSError:
            pass
    return latest


def safe_generate():
    try:
        generate_all()
    except Exception as e:
        print(f"  [错误] 生成失败：{e}，继续监听…")


def watch():
    print(f"监听中：{COMPANY_DIR}（每 3 秒检测变动，Ctrl+C 退出）")
    last = deps_mtime()
    safe_generate()
    try:
        while True:
            time.sleep(3.0)
            cur = deps_mtime()
            if cur != last:
                last = cur
                print(f"\n[{datetime.datetime.now().strftime('%H:%M:%S')}] 检测到变动，重新生成…")
                safe_generate()
    except KeyboardInterrupt:
        print("\n已停止监听。")


# ---------- selftest ----------

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
                     "| E0002 | E0002-x/ | 开发 | 在职 | T001 | 成员 |  |\n"
                     "| E0999 | ../外面/ | 幽灵 | 在职 | - |  |  |\n")
        ros = parse_roster(rp)
        check("roster 团队列多值", ros["E0001"]["teams"] == ["T001", "T002"])
        check("roster 角色列 lead", ros["E0001"]["rank"] == "lead" and ros["E0002"]["rank"] == "成员")
    # 2b) worklog 归档全量扫描 + archived 标记
    with tempfile.TemporaryDirectory() as tmp:
        global COMPANY_DIR_cur
        old = COMPANY_DIR_cur[0]
        COMPANY_DIR_cur[0] = tmp
        os.makedirs(os.path.join(tmp, "E0001-甲", "workspace", "worklog-archive"), exist_ok=True)
        with open(os.path.join(tmp, "E0001-甲", "workspace", "worklog.md"), "w", encoding="utf-8") as fh:
            fh.write("---\nwid: W1\ndate: 2026-08-27\ntitle: 热条目\ntype: 直聊\nstatus: 进行中\nupdated: 2026-08-27\n---\n")
        with open(os.path.join(tmp, "E0001-甲", "workspace", "worklog-archive", "worklog-2025.md"), "w", encoding="utf-8") as fh:
            fh.write("---\nwid: W0\ndate: 2025-12-01\ntitle: 归档条目\ntype: 直聊\nstatus: 已完成\nupdated: 2025-12-01\n---\n")
        ws = []
        ents = parse_worklog("E0001", "E0001-甲", ws)
        check("归档全量扫描(热+冷共2条)", len(ents) == 2)
        hot = [e for e in ents if not e["archived"]][0]
        cold = [e for e in ents if e["archived"]][0]
        check("archived 标记正确", hot["title"] == "热条目" and cold["title"] == "归档条目")
        COMPANY_DIR_cur[0] = old
    # 3) project.md 双格式解析
    with tempfile.TemporaryDirectory() as tmp:
        old = COMPANY_DIR_cur[0]
        COMPANY_DIR_cur[0] = tmp
        os.makedirs(os.path.join(tmp, "P0001-甲"), exist_ok=True)
        with open(os.path.join(tmp, "P0001-甲", "project.md"), "w", encoding="utf-8") as fh:
            fh.write("---\nid: P0001\nname: 甲\nteam: [T001]\n---\n")
        os.makedirs(os.path.join(tmp, "P0002-乙"), exist_ok=True)
        with open(os.path.join(tmp, "P0002-乙", "project.md"), "w", encoding="utf-8") as fh:
            fh.write("## 项目信息\n- 项目 ID：P0002\n- 名称：乙\n- 归属团队：T009-不存在（引用制）\n")
        p1, p2 = parse_project("P0001-甲"), parse_project("P0002-乙")
        check("project frontmatter team 数组", p1["teams"] == ["T001"])
        check("project markdown 兜底解析", p2["name"] == "乙" and p2["teams"] == [])
        COMPANY_DIR_cur[0] = old
    # 4) 交叉核验样例（R1/R2/R3/R4/R5 + 未认领）
    warns = []
    ee = {"E0001": [
        {"wid": "1", "date": "2026-08-27", "title": "a", "status": "进行中", "type": "工单",
         "ticket": "TSKX1", "project": "", "updated": "2026-08-27", "note": "", "deliverable": "", "deliverable_valid": True},
        {"wid": "2", "date": "2026-08-27", "title": "b", "status": "已完成", "type": "工单",
         "ticket": "TSKX2", "project": "", "updated": "2026-08-27", "note": "", "deliverable": "", "deliverable_valid": True},
        {"wid": "3", "date": "2026-08-27", "title": "c", "status": "进行中", "type": "工单",
         "ticket": "TSKX9", "project": "", "updated": "2026-08-27", "note": "", "deliverable": "", "deliverable_valid": True},
    ]}
    tasks = [
        {"id": "TSKX1", "title": "t1", "status": "done", "owner": "E0001"},        # R4
        {"id": "TSKX2", "title": "t2", "status": "in_progress", "owner": "E0001"},  # R3(已完成但工单在途)
        {"id": "TSKX3", "title": "t3", "status": "review", "owner": "E0002"},       # R2(他人未记不测)
        {"id": "TSKX4", "title": "t4", "status": "backlog", "owner": "E0002"},      # 未认领
        {"id": "TSKX5", "title": "t5", "status": "backlog", "owner": ""},           # 无 owner 不告警
    ]
    cross_validate(ee, tasks, warns)
    msgs = " | ".join(w["msg"] for w in warns)
    check("核验R4 进行中vs工单终态", "TSKX1" in msgs and "已done" in msgs)
    check("核验R5 已完成vs工单未关", "仍未关" in msgs)
    check("核验R1 ticket不存在", "TSKX9" in msgs)
    check("核验R2 在途未记worklog", "TSKX3" in msgs)
    check("核验未认领(backlog owner有主无账)", "未认领" in msgs and "TSKX4" in msgs)
    check("核验无owner不告未认领", "TSKX5" not in msgs)
    # 4b) 常设事务：节奏推导（link_affairs 纯函数测试，不落盘）
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
    check("事务 按需不判逾期", a2["overdue"] is False and a2["never_done"] is False)
    check("事务 从未推进标记", a3["never_done"] is True)
    # 5) 统计口径
    st = stats_of([{"status": "计划中"}, {"status": "进行中"}, {"status": "进行中"}, {"status": "已完成"}])
    check("统计 累计口径/在途", st["total"] == 4 and st["ongoing"] == 3 and st["rate"] == 0.25)
    # 6) 集成：临时公司全链路
    with tempfile.TemporaryDirectory(prefix="dash_it_") as tmp:
        base = os.path.join(tmp, "C001-测试公司")
        wb = os.path.join(base, "workbench")
        os.makedirs(wb, exist_ok=True)
        os.makedirs(os.path.join(base, "T001-开发"), exist_ok=True)
        os.makedirs(os.path.join(base, "E0001-分析员", "workspace"), exist_ok=True)
        with open(os.path.join(base, "T001-开发", "team.md"), "w", encoding="utf-8") as fh:
            fh.write("# T001\n- 团队 ID：T001\n- 名称：开发\n")
        with open(os.path.join(base, "E0001-分析员", "workspace", "worklog.md"), "w", encoding="utf-8") as fh:
            fh.write("---\nwid: W1\ndate: 2026-08-27\ntitle: 干活\ntype: 直聊\nstatus: 进行中\nupdated: 2026-08-27\n---\n")
        os.makedirs(os.path.join(base, "E0000-AI员工-总管"), exist_ok=True)
        with open(os.path.join(base, "E0000-AI员工-总管", "roster.md"), "w", encoding="utf-8") as fh:
            fh.write("| 员工 ID | 路径 | 岗位 | 状态 | 团队 | 备注 |\n|---|---|---|---|---|---|\n"
                     "| E0001 | E0001-分析员/ | 分析员 | 在职 | T001 | x |\n")
        with open(os.path.join(wb, "tasks-data.json"), "w", encoding="utf-8") as fh:
            json.dump({"tasks": [{"id": "TSK1", "title": "x", "status": "in_progress", "owner": "E0001", "project": "P1"}],
                       "employees": {}, "projects": {}, "status_meta": {"in_progress": "进行中"}}, fh)
        generate_all(base, wb)
        with open(os.path.join(base, "T001-开发", "teamboard-data.js"), encoding="utf-8") as fh:
            tj = fh.read()
        check("集成: 团队切片含成员统计", '"member_count": 1' in tj and '"E0001"' in tj)
        with open(os.path.join(base, "E0001-分析员", "mydesk-data.js"), encoding="utf-8") as fh:
            mj = fh.read()
        check("集成: 个人台含在途工单与警告", '"TSK1"' in mj and "未记 worklog" in mj)
        with open(os.path.join(base, "dashboard-data.js"), encoding="utf-8") as fh:
            dj = fh.read()
        check("集成: 公司级动态流", "干活" in dj)
    print("自测" + ("全部通过 ✓" if ok else "存在失败 ✗"))
    return 0 if ok else 1


if __name__ == "__main__":
    if "--watch" in sys.argv:
        watch()
    elif "--selftest" in sys.argv:
        sys.exit(selftest())
    elif "--verify" in sys.argv:
        sys.exit(verify_outputs(None))
    else:
        print("生成三级看板数据…")
        generate_all()
        print("完成。")
