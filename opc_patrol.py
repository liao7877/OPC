#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
opc_patrol.py —— 公司巡检器（机制层，OPC 根单例）

> 2026-08-28 新增（架构评审「公司自转」缺口）：此前所有节奏检测（脱期/升级/阻塞解锁）
> 都只在"有人触发生成/总管开会话"时才发生——用户三天不来，公司完全静止。
> 2026-08-29 决策 #18：心跳计划任务退役，巡检由 **OPC 服务（opc_service.py）进程内调度**
> （数据变动即巡检 + 周期兜底），通知实时直达；本模块保留纯巡检实现与 CLI 手动入口。
> 消费 skills/patrol/SKILL.md 定义的同一份巡检清单（机器与总管共享标准，不漂移）。

职责边界（与总管分工）：
  - 本脚本只「发现」：1~13 号检查项的机器可判定部分，异常写入 workbench/patrol-log.md
    （追加式、幂等去重），并打印待办清单；不做任何处置决策。
    例外（2026-08-29 拍板）：看板数据缺失/陈旧时自动重生成（auto_refresh）——数据刷新
    由 OPC 服务完成，属机械性自愈而非处置决策。
  - 总管「处置」：读 patrol-log / 看板告警，答复、转派、催办、补号。
  - A+ 报警（2026-08-28 拍板）：有「新发现」时弹系统通知（opc.toml [patrol].notify 可关；
    通知去重：open 态旧待办不重复弹）；B 阶段「自动处置」扩展位 [patrol].actor 预留，当前未启用。
  - 11/12 号风险预警（决策 #18）：活跃工单已逾期/截止日临近/长期无进展——用户拍板的
    两类主动打扰之一，windows 弹窗直达用户。
  - 13 号依赖环（2026-08-29）：blocked_by/parent 成环 → 永久无法开工，告警交总管拆环。

用法（cwd 无关）：
    python opc_patrol.py --company C001              # 巡检 + 写 log
    python opc_patrol.py --company C001 --dry-run    # 只检查打印，不写
    python opc_patrol.py --company C001 --quiet      # 仅异常时输出
    python opc_patrol.py --selftest

调度：由 OPC 服务进程内调用 run_once()（常规），本 CLI 仅手动应急用。
"""

import os
import sys
import re
import json
import hashlib
import time
import datetime
import subprocess

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
import opc_model
import opc_resolver
import opc_tickets
from opc_schema import TASK_TERMINAL, TASK_ACTIVE, PATROL, PATROL_CHECKS


def _patrol_cfg():
    """读 opc.toml 的 [patrol] 段（A+ 通知开关 / B 阶段 actor 扩展位）。缺段或根找不到时用默认。"""
    try:
        root = opc_resolver._find_root()
        g = opc_resolver._load_toml(os.path.join(root, "opc.toml"))
        return g.get("patrol", {})
    except Exception:
        return {}


class Ctx:
    def __init__(self, cfg, base):
        self.cfg = cfg
        self.cid = cfg.cid
        self.base = base
        self.wb = os.path.join(base, "workbench")
        self.tasks_data = os.path.join(self.wb, "tasks-data.json")
        self.dash_data = os.path.join(base, "dashboard-data.js")
        self.log = os.path.join(self.wb, "patrol-log.md")
        self.state = os.path.join(self.wb, "patrol-state.json")     # 闭环机器态（可改）
        self.pending = os.path.join(self.wb, "patrol-pending.md")   # open 态待办快照（生成物）
        self.today = datetime.date.today()
        self.findings = []   # [dict]：{no, kind, severity, action, ref, owner, msg}（B 阶段处置的地基）
        self.kb_count = None  # #8 知识库条目计数（find() 填充，update_state 推进基线用）


def _mk(no, msg, ref="", owner=""):
    """构造结构化 finding：kind/severity/action 来自 opc_schema.PATROL_CHECKS 唯一真相源。"""
    meta = PATROL_CHECKS.get(no, {})
    return {"no": no, "kind": meta.get("kind", "other"),
            "severity": meta.get("severity", "info"),
            "action": meta.get("action", "notify_owner"),
            "ref": str(ref or ""), "owner": str(owner or ""), "msg": msg}


def fkey(f):
    """finding 稳定键（state 闭环用）：优先 #编号:引用对象；无 ref 时退消息指纹。"""
    if f.get("ref"):
        return f"{f['no']}:{f['ref']}"
    return "%s:md5:%s" % (f["no"], hashlib.md5(f["msg"].encode("utf-8")).hexdigest()[:8])


def resolve_ctx(company):
    """按 --company CID 返回 Ctx；身份解析/断链校验统一走 resolve_company（D1 收敛）。"""
    cfg = opc_resolver.resolve_company(company)
    return Ctx(cfg, cfg.home_abs)


def _read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            return fh.read()
    except OSError:
        return ""


def _load_json(path):
    """读 JSON；兼容看板产物 window.X = {...} 的 JS 包装格式。"""
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
        m = re.match(r"^window\.\w+ = ([\s\S]*);\s*$", text)
        return json.loads(m.group(1)) if m else json.loads(text)
    except Exception:
        return None


def find(ctx):
    """执行机器可判定的巡检项（1~6 号；7~10 需要处置联动，产出提示交总管）。"""
    pe = opc_resolver.entity_types()["employee"]   # 员工前缀唯一真相（实体注册表）
    td = _load_json(ctx.tasks_data)
    if td is None:
        # 首跑前 tasks-data 不存在：不算异常（clone 后未生成属正常），提示即可
        print(f"  [i] {ctx.tasks_data} 不存在（先跑 run_boards once 生成），跳过工单类检查")
        return
    tasks = td.get("tasks", [])
    tmap = {t["id"]: t for t in tasks}
    # 知识回流第 0 步的判定数据（最省口径：复用本次已加载工单，不重复扫描）
    ctx.has_failed = any(t.get("status") == "failed" for t in tasks)
    dd = _load_json(ctx.dash_data)
    if dd is None:
        # P11：投影损坏/未生成必须告警，绝不静默跳过检查项 2/3/4（认领/双账/脱期）
        if os.path.isfile(ctx.dash_data):
            print(f"  [警告] {ctx.dash_data} 存在但解析失败，检查项 2/3/4 本轮跳过——先跑 run_boards once 修复")
        else:
            print(f"  [i] {ctx.dash_data} 不存在（先跑 run_boards once），检查项 2/3/4 本轮跳过")
        dd = {}
    warnings = dd.get("risks", {}).get("warnings", [])

    # 1) 阻塞解锁：blocked_by 上游全 done 而本单还在 backlog
    for t in tasks:
        if t.get("status") != "backlog" or not t.get("blocked_by"):
            continue
        if all(tmap.get(b, {}).get("status") == "done" for b in t["blocked_by"]):
            ctx.findings.append(_mk(1, f"工单 {t['id']}「{t['title']}」前置已全部完成，仍 backlog——通知 owner={t.get('owner') or '?'} 开工",
                                    ref=t["id"], owner=t.get("owner") or ""))

    # 2) 认领缺口 + 3) 双账不一致（消费 dashboard 的核验告警，机器口径与生成器一致）
    for w in warnings:
        msg = w.get("msg", "")
        m_ref = re.search(r"TSK\d{4,}|AFF\d{3,}", msg)
        ref = m_ref.group(0) if m_ref else ""
        if "未认领" in msg:
            ctx.findings.append(_mk(2, msg, ref=ref))
        elif any(k in msg for k in ("未记", "非「进行中」", "已done", "仍未关", "不存在")):
            ctx.findings.append(_mk(3, msg, ref=ref))

    # 4) 脱期事务（机器可判定口径与生成器一致）
    for a in dd.get("affairs", []):
        if a.get("never_done"):
            ctx.findings.append(_mk(4, f"事务 {a['id']}「{a['title']}」从未推进（owner={a.get('owner') or '?'}）",
                                    ref=a["id"], owner=a.get("owner") or ""))
        elif a.get("overdue"):
            ctx.findings.append(_mk(4, f"事务 {a['id']}「{a['title']}」已脱期（{a.get('cadence')}，上次推进 {a.get('last_touched') or '?'}）",
                                    ref=a["id"], owner=a.get("owner") or ""))

    # 5) 升级信箱（发现即高优待办；severity=critical，唯一必须打扰用户的项）
    for t in tasks:
        for esc in t.get("escalations", []):
            ctx.findings.append(_mk(5, f"[高优] 工单 {t['id']}「{t['title']}」有未处理升级：{esc.get('reason')}（owner={t.get('owner') or '?'}）",
                                    ref=t["id"], owner=t.get("owner") or ""))

    # 6) 号池水位
    ti = _read(os.path.join(ctx.wb, "task-index.md"))
    m = re.search(r"TSK(\d{5})\s*[～~]\s*TSK(\d{5})", ti)
    if m:
        used = {t["id"] for t in tasks}
        lo, hi = int(m.group(1)), int(m.group(2))
        remaining = sum(1 for n in range(lo, hi + 1) if f"TSK{n:05d}" not in used)
        if remaining < PATROL["ticket_pool_min"]:
            ctx.findings.append(_mk(6, f"预留号池剩余 {remaining} 个（<{PATROL['ticket_pool_min']}），总管补号段", ref="pool"))

    # 7) 归档提醒（热文件含上一年度条目——仅提示计数，交总管处理）
    stale_year = str(ctx.today.year - 1)
    for name in sorted(os.listdir(ctx.base)) if os.path.isdir(ctx.base) else []:
        if not re.match(rf"^{pe}\d{{3,}}(?:-|$)", name):
            continue
        wl = os.path.join(ctx.base, name, "workspace", "worklog.md")
        txt = _read(wl)
        n = len(re.findall(r"^date:\s*%s" % stale_year, txt, re.M))
        if n:
            ctx.findings.append(_mk(7, f"{name} 热文件含 {n} 条 {stale_year} 年条目，建议归档", ref=name))

    # 8) 知识库增量（B6 闭环，2026-08-29 拍板机器化）：methods/ 与各项目 knowledge/
    #    新条目 → 提示总管评审提炼（技能/制度/common 三选一）。基线存 patrol-state
    #    的 _meta（非 finding），首跑建基线不告警；基线随巡检推进，open 待办由
    #    总管处置后置 handled 收敛。
    state8 = load_state(ctx)
    base_count = (state8.get("_meta") or {}).get("knowledge_baseline")
    kb = _count_knowledge(ctx)
    ctx.kb_count = kb
    if base_count is None:
        state8.setdefault("_meta", {})["knowledge_baseline"] = kb
        save_state(ctx, state8)          # 首跑建基线，不告警
    elif kb > base_count:
        ctx.findings.append(_mk(8, f"知识库新增 {kb - base_count} 条待评审（现 {kb} 条，基线 {base_count}）："
                                   f"methods/ 与各项目 knowledge/——总管三选一：提炼成技能/制度/common，或归档",
                                ref="knowledge"))

    # 9) 僵尸工位卡（工作中但 3 天未动）
    cutoff = (ctx.today - datetime.timedelta(days=3)).strftime("%Y%m%d")
    for name in sorted(os.listdir(ctx.base)) if os.path.isdir(ctx.base) else []:
        if not re.match(rf"^{pe}\d{{3,}}(?:-|$)", name):
            continue
        sdir = os.path.join(ctx.base, name, "workspace", "sessions")
        if not os.path.isdir(sdir):
            continue
        for f in sorted(os.listdir(sdir)):
            if not f.endswith(".md"):
                continue
            card = _read(os.path.join(sdir, f))
            if "工作中" not in card:    # 宽松匹配：状态字段写法各异，卡上出现「工作中」即视为在岗
                continue
            try:
                mt = datetime.datetime.fromtimestamp(os.path.getmtime(os.path.join(sdir, f)))
            except OSError:
                continue
            if mt.strftime("%Y%m%d") <= cutoff:
                ctx.findings.append(_mk(9, f"{name} 存在疑似僵尸工位卡 {f}（3 天未动），核对会话是否已结束→收口",
                                        ref=f"{name}:{f}"))

    # 10) 生成器健康：tasks-data 陈旧
    gen_at = td.get("generated_at", "")
    if gen_at:
        try:
            g = datetime.datetime.strptime(gen_at, "%Y-%m-%d %H:%M:%S")
            age_h = (datetime.datetime.now() - g).total_seconds() / 3600
            if age_h > 24:
                ctx.findings.append(_mk(10, f"看板数据已 {int(age_h)} 小时未刷新（>24h），跑一次 run_boards once 或检查 OPC 服务",
                                        ref="tasks-data"))
        except ValueError:
            pass

    # 11) 风险预警·工期：活跃单已逾期 / 截止日临近（决策 #18 用户拍板的两类主动打扰之一）
    #     逾期语义与看板一致：仅对活跃未完成生效；done/paused/failed/cancelled 不背锅
    due_soon = PATROL.get("due_soon_days", 3)
    for t in tasks:
        if t.get("status") not in TASK_ACTIVE or not t.get("due"):
            continue
        try:
            d = datetime.date.fromisoformat(str(t["due"])[:10])
        except ValueError:
            continue
        days = (d - ctx.today).days
        if days < 0:
            ctx.findings.append(_mk(11, f"工单 {t['id']}「{t['title']}」已逾期 {-days} 天（due={t['due']}，"
                                        f"owner={t.get('owner') or '?'}）", ref=t["id"], owner=t.get("owner") or ""))
        elif days <= due_soon:
            ctx.findings.append(_mk(11, f"工单 {t['id']}「{t['title']}」截止日将至（还剩 {days} 天，due={t['due']}，"
                                        f"owner={t.get('owner') or '?'}）", ref=t["id"], owner=t.get("owner") or ""))

    # 12) 风险预警·停滞：in_progress 超 N 天无 updated（决策 #18）
    stalled = PATROL.get("stalled_days", 3)
    cutoff12 = (ctx.today - datetime.timedelta(days=stalled)).isoformat()
    for t in tasks:
        if t.get("status") != "in_progress":
            continue
        upd = str(t.get("updated") or "")[:10]
        if upd and upd < cutoff12:
            idle = (ctx.today - datetime.date.fromisoformat(upd)).days
            ctx.findings.append(_mk(12, f"工单 {t['id']}「{t['title']}」进行中已 {idle} 天无更新（last={upd}，"
                                        f"owner={t.get('owner') or '?'}）——催办或转 paused", ref=t["id"], owner=t.get("owner") or ""))

    # 13) 依赖环（2026-08-29）：blocked_by/parent 成环 → 永久无法开工且无外力可解。
    #     图直接从本函数已加载的 tasks 构建，查环算法复用 opc_tickets.find_cycles（单一实现）
    dep_graph = {t["id"]: [b for b in t.get("blocked_by", []) if b in tmap] for t in tasks if t.get("id")}
    parent_graph = {t["id"]: [t["parent"]] for t in tasks if t.get("id") and t.get("parent") in tmap}
    for cyc in opc_tickets.find_cycles(dep_graph) + opc_tickets.find_cycles(parent_graph):
        ctx.findings.append(_mk(13, "工单依赖环（永久无法开工，找总管拆环）：" + " → ".join(cyc), ref="→".join(cyc)))


def write_log(ctx, dry):
    """发现写入 workbench/patrol-log.md（幂等：同日同条目不重复追加）。
    写路径全程持锁（opc_model.locked_update）：服务监听与周期兜底并发巡检时不重复追加。"""
    if not ctx.findings:
        return 0
    day = ctx.today.strftime("%Y-%m-%d")
    lines = [f"- [{day}] #{f['no']} {f['msg']}"
             for f in sorted(ctx.findings, key=lambda x: (x["no"], x.get("ref") or ""))]
    header = ("# 巡检日志（patrol-log）\n\n> OPC 服务巡检自动追加（opc_patrol.py），"
              "只增不删；处置由总管完成（在对应工单 messages.md 留痕）。\n")

    def _merge(existing):
        fresh = [l for l in lines if l not in existing]
        _merge.n = len(fresh)
        if not fresh:
            return existing
        body = existing or header
        if not body.endswith("\n"):
            body += "\n"
        return body + "\n".join(fresh) + "\n"
    _merge.n = 0

    if dry:
        _merge(_read(ctx.log))
        return 0
    os.makedirs(os.path.dirname(ctx.log), exist_ok=True)
    opc_model.locked_update(ctx.log, _merge)
    return _merge.n


def _count_knowledge(ctx):
    """知识库条目计数：公司知识库/methods/ + 各项目 P*/knowledge/ 下的 .md 文件数。"""
    n = 0
    methods = os.path.join(ctx.base, "公司知识库", "methods")
    if os.path.isdir(methods):
        for root, _dirs, files in os.walk(methods):
            n += sum(1 for f in files if f.endswith(".md"))
    if os.path.isdir(ctx.base):
        for name in sorted(os.listdir(ctx.base)):
            kdir = os.path.join(ctx.base, name, "knowledge")
            if re.match(r"^P\d{3,}(?:-|$)", name) and os.path.isdir(kdir):
                for root, _dirs, files in os.walk(kdir):
                    n += sum(1 for f in files if f.endswith(".md"))
    return n


def load_state(ctx):
    try:
        with open(ctx.state, encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:
        return {}


def save_state(ctx, state):
    tmp = ctx.state + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, ctx.state)


def update_state(ctx):
    """闭环机器态 patrol-state.json（A 方案 ③，B 阶段处置闭环的地基）。

    主从（P2）：patrol-log.md 是审计流水只增不删；state 是其派生态，可改、
    删了可从 log 重建。处置方（总管/未来 agent actor）把条目 status 置
    "handled"（附 handled_at/by）即闭环；同一问题再犯时本函数重开（reopened）。
    """
    state = load_state(ctx)
    day = ctx.today.strftime("%Y-%m-%d")
    changed = False
    for f in ctx.findings:
        k = fkey(f)
        cur = state.get(k)
        if cur is None:
            state[k] = {"no": f["no"], "kind": f["kind"], "severity": f["severity"],
                        "action": f["action"], "ref": f["ref"], "owner": f["owner"],
                        "msg": f["msg"], "status": "open", "first_seen": day}
            changed = True
        elif cur.get("status") == "handled":
            cur["status"] = "reopened"
            cur["reopened_at"] = day
            changed = True
    # #8 基线推进：本轮巡检已把当前知识库计数落账（open 待办仍在 state 里等处置）
    if getattr(ctx, "kb_count", None) is not None:
        state.setdefault("_meta", {})["knowledge_baseline"] = ctx.kb_count
        changed = True
    if changed or not os.path.isfile(ctx.state):
        save_state(ctx, state)
    return state


def write_pending(ctx, state):
    """open 态待办快照 patrol-pending.md：总管启动第 5 步读它（比全量日志轻），
    处置完在 state 置 handled，下次巡检本文件自动收敛。"""
    opens = [(k, v) for k, v in state.items()
             if not k.startswith("_") and v.get("status") != "handled"]   # _meta=机器态，非待办
    order = {"critical": 0, "warn": 1, "info": 2}
    opens.sort(key=lambda kv: (order.get(kv[1].get("severity"), 3),
                               kv[1].get("no", 99), kv[0]))
    lines = [
        "# 巡检待办（open 态快照，opc_patrol.py 生成）",
        "",
        "> 处置完成后在 patrol-state.json 把对应条目 status 置 \"handled\"（附 handled_at/by），下次巡检本文件自动收敛；审计流水见 patrol-log.md（只增不删）。",
        "",
    ]
    if not opens:
        lines.append("（当前无 open 待办）")
    else:
        lines.append(f"共 {len(opens)} 项：")
        lines.append("")
        for k, v in opens:
            lines.append(f"- #{v.get('no')} [{v.get('severity')}] {v.get('msg')}"
                         f"（首次发现 {v.get('first_seen', '?')}）key=`{k}`")
    tmp = ctx.pending + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write("\n".join(lines) + "\n")
    os.replace(tmp, ctx.pending)


def notify_allowed(severity, now_time, cfg):
    """勿扰屏蔽判定（OS 中断屏蔽字思路，纯函数可直测）：critical 恒放行；
    quiet_hours（"HH:MM-HH:MM"，支持跨零点如 "22:00-08:00"）启用时 warn/info
    在时段内被静默（并入每日摘要重提）。配置缺失/非法按未启用处理（容错不阻断）。"""
    if severity == "critical":
        return True
    m = re.match(r"^(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})$", str(cfg.get("quiet_hours") or "").strip())
    if not m:
        return True
    start = datetime.time(int(m.group(1)), int(m.group(2)))
    end = datetime.time(int(m.group(3)), int(m.group(4)))
    if start == end:
        return True
    in_window = (start <= now_time < end) if start < end else (now_time >= start or now_time < end)
    return not in_window


def notify_user(ctx, summary):
    """A+ 报警通道（2026-08-28 拍板）：发现异常时弹系统通知，用户不守着机器也能被 critical 打扰。
    跨平台尽力而为：Windows 弹 Toast（PowerShell BalloonTip）、macOS 弹 osascript 通知、
    Linux 走 notify-send；任何失败只打印提示，绝不影响巡检主流程（P11：通知是增益不是依赖）。
    B 阶段（自动处置）扩展位见 opc.toml [patrol].actor，本函数只管「让人知道」。"""
    title = "OPC 巡检 %s：%d 项待办" % (ctx.cid, len(ctx.findings))
    text = summary[:180]
    try:
        if sys.platform.startswith("win"):
            _notify_windows(title, text)
        elif sys.platform == "darwin":
            subprocess.Popen(["osascript", "-e",
                              'display notification "%s" with title "%s"'
                              % (text.replace('"', '\\"'), title.replace('"', '\\"'))],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen(["notify-send", title, text],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception as e:
        print(f"  [提示] 系统通知发送失败（不影响巡检结果）：{e}")
        return False


def _notify_windows(title, text):
    """Windows Toast 通知：经临时 .ps1（UTF-8 BOM，PS5.1 硬要求）执行 BalloonTip，
    避免命令行内联中文的编码/转义问题；固定文件名覆盖写，无临时垃圾。"""
    import tempfile
    title = title.replace("'", "''")
    text = text.replace("'", "''")
    script = (
        "Add-Type -AssemblyName System.Windows.Forms\r\n"
        "Add-Type -AssemblyName System.Drawing\r\n"
        "$n = New-Object System.Windows.Forms.NotifyIcon\r\n"
        "$n.Icon = [System.Drawing.SystemIcons]::Warning\r\n"
        "$n.Visible = $true\r\n"
        "$n.BalloonTipTitle = '%s'\r\n"
        "$n.BalloonTipText = '%s'\r\n"
        "$n.ShowBalloonTip(10000)\r\n"
        "Start-Sleep -Seconds 11\r\n"
        "$n.Dispose()\r\n"
        "Remove-Item -LiteralPath $PSCommandPath -ErrorAction SilentlyContinue\r\n" % (title, text)
    )
    # 唯一文件名：服务内多公司并发通知互不覆盖（固定名会串厂）
    ps = os.path.join(tempfile.gettempdir(), f"opc-patrol-notify-{os.getpid()}-{time.time_ns()}.ps1")
    with open(ps, "w", encoding="utf-8", newline="") as fh:
        fh.write(script)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-WindowStyle", "Hidden", "-File", ps],
        creationflags=flags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def new_findings(ctx, pre_open):
    """通知去重（2026-08-29 拍板「提频先去重」）：只返回「新出现」的 finding——
    fkey 不在既存 open 集合里的才算新。巡检高频化后，未处置的旧待办不再反复弹通知
    （它们始终可见于 patrol-pending.md），处置后再犯会因 reopened 重新进入新集合。"""
    return [f for f in sorted(ctx.findings, key=lambda x: x["no"]) if fkey(f) not in pre_open]


_KB_BACKFLOW_HINT = ("[提示] 检测到升级/失败工单——建议总管把教训一句话沉淀进 "
                     "公司知识库/methods/（P31 事实记录，细节优先），避免同类坑二次踩")


def kb_backflow_hint(ctx):
    """知识回流第 0 步（2026-08-29）：本轮发现升级（#5）或存在 failed 工单时，
    打一行沉淀提示——P29 自动化边界在「发现」，本函数只提示、不写 state、不弹通知、
    不做任何处置；教训回不回家的「路」由总管走。每轮最多提示一次。"""
    if any(f["no"] == 5 for f in ctx.findings) or getattr(ctx, "has_failed", False):
        print(_KB_BACKFLOW_HINT)


# 心跳注册已随决策 #18 退役：定时巡检/通知/自愈整体并入 OPC 服务（opc_service.py），
# 机器级副作用收敛为启动文件夹一条自启项（OPC-Service.vbs）。


def selftest():
    import tempfile
    ok = True

    def check(name, cond):
        nonlocal ok
        print(("  ✓ " if cond else "  ✗ ") + name)
        if not cond:
            ok = False

    print("运行内置自测…")
    tmp = tempfile.mkdtemp()
    wb = os.path.join(tmp, "workbench")
    os.makedirs(wb, exist_ok=True)
    now = datetime.datetime.now()
    # 工单场景：解锁待开 / 升级信箱 / 重复 id
    with open(os.path.join(wb, "tasks-data.json"), "w", encoding="utf-8") as fh:
        json.dump({
            "generated_at": (now - datetime.timedelta(hours=30)).strftime("%Y-%m-%d %H:%M:%S"),
            "tasks": [
                {"id": "TSKA", "title": "已解锁待开工", "status": "backlog", "owner": "E1", "blocked_by": ["TSKB"]},
                {"id": "TSKB", "title": "上游", "status": "done", "owner": ""},
                {"id": "TSKC", "title": "有升级", "status": "in_progress", "owner": "E2",
                 "escalations": [{"reason": "需求不明", "date": "2026-08-28"}]},
            ],
        }, fh, ensure_ascii=False)
    with open(os.path.join(tmp, "dashboard-data.js"), "w", encoding="utf-8") as fh:
        json.dump({"risks": {"warnings": [{"scope": "核验", "msg": "E2 的工单 TSKD「x」未认领"}]},
                   "affairs": [{"id": "AFF1", "title": "周报", "status": "active", "cadence": "每周",
                                "owner": "E1", "overdue": True, "last_touched": "2026-08-01"}]},
                  fh, ensure_ascii=False)
    # E1 僵尸卡
    e1 = os.path.join(tmp, "E0001-甲", "workspace", "sessions")
    os.makedirs(e1, exist_ok=True)
    card = os.path.join(e1, "seat-080000-aa.md")
    with open(card, "w", encoding="utf-8") as fh:
        fh.write("---\nkind: 工单\nstatus: 工作中\n---\n")
    old_ts = (datetime.datetime.now() - datetime.timedelta(days=5)).timestamp()
    os.utime(card, (old_ts, old_ts))

    cfg = opc_resolver.CompanyConfig("C999", tmp, {})
    ctx = Ctx(cfg, tmp)
    find(ctx)
    msgs = [f["msg"] for f in ctx.findings]
    check("#1 解锁待开工发现", any("TSKA" in m for m in msgs))
    check("#4 脱期事务发现", any("AFF1" in m for m in msgs))
    check("#5 升级信箱 critical", any(f["no"] == 5 and f["severity"] == "critical" for f in ctx.findings))
    check("#2 认领缺口发现", any("未认领" in m for m in msgs))
    check("#9 僵尸工位卡发现", any("僵尸" in m for m in msgs))
    check("#10 数据陈旧发现", any("未刷新" in m for m in msgs))
    check("findings 结构化（kind/action/ref）", all(f.get("kind") and f.get("action") and "ref" in f for f in ctx.findings))
    check("#13 无环不误报", not any(f["no"] == 13 for f in ctx.findings))
    # 13) 依赖环：blocked_by A↔B 互锁 + parent 父子互嵌 → 永久无法开工
    with open(os.path.join(wb, "tasks-data.json"), "w", encoding="utf-8") as fh:
        json.dump({
            "generated_at": now.strftime("%Y-%m-%d %H:%M:%S"),
            "tasks": [
                {"id": "TSKA", "title": "已解锁待开工", "status": "backlog", "owner": "E1", "blocked_by": ["TSKB"]},
                {"id": "TSKB", "title": "上游", "status": "done", "owner": ""},
                {"id": "TSKC", "title": "有升级", "status": "in_progress", "owner": "E2",
                 "escalations": [{"reason": "需求不明", "date": "2026-08-28"}]},
                {"id": "TSKX", "title": "环X", "status": "backlog", "owner": "E1", "blocked_by": ["TSKY"]},
                {"id": "TSKY", "title": "环Y", "status": "backlog", "owner": "E1", "blocked_by": ["TSKX"]},
                {"id": "TSKP", "title": "子嵌", "status": "backlog", "owner": "E1", "parent": "TSKQ"},
                {"id": "TSKQ", "title": "父嵌", "status": "backlog", "owner": "E1", "parent": "TSKP"},
            ],
        }, fh, ensure_ascii=False)
    ctxc = Ctx(cfg, tmp)
    find(ctxc)
    cyc_msgs = [f["msg"] for f in ctxc.findings if f["no"] == 13]
    check("#13 blocked_by 依赖环发现", any("TSKX → TSKY" in m or "TSKY → TSKX" in m for m in cyc_msgs))
    check("#13 parent 父子环发现", any("TSKP → TSKQ" in m or "TSKQ → TSKP" in m for m in cyc_msgs))
    # 闭环态：open → handled → 同问题再犯 reopened（A 方案 ③）
    state = update_state(ctx)
    check("state 初始全 open", state and all(v.get("status") == "open"
                                             for k, v in state.items() if not k.startswith("_")))
    k5 = [k for k, v in state.items() if not k.startswith("_") and v["no"] == 5][0]
    state[k5]["status"] = "handled"; state[k5]["handled_at"] = "2026-08-28"; save_state(ctx, state)
    ctx2 = Ctx(cfg, tmp)
    find(ctx2)
    state2 = update_state(ctx2)
    check("再犯重开 reopened", state2[k5]["status"] == "reopened")
    write_pending(ctx2, state2)
    pend = _read(ctx2.pending)
    check("pending 快照含 critical 置顶", "#5 [critical]" in pend)
    # #8 知识库增量：首跑建基线 → 新增 → 告警 → 基线随巡检推进
    mdir = os.path.join(tmp, "公司知识库", "methods")
    os.makedirs(mdir, exist_ok=True)
    ctxk = Ctx(cfg, tmp)
    find(ctxk)
    check("#8 首跑建基线不告警", not any(f["no"] == 8 for f in ctxk.findings))
    with open(os.path.join(mdir, "经验条目.md"), "w", encoding="utf-8") as fh:
        fh.write("经验")
    ctxk2 = Ctx(cfg, tmp)
    find(ctxk2)
    check("#8 新增条目告警", any(f["no"] == 8 for f in ctxk2.findings))
    st8 = update_state(ctxk2)
    check("#8 基线随巡检推进", (st8.get("_meta") or {}).get("knowledge_baseline") == 1)
    ctxk3 = Ctx(cfg, tmp)
    find(ctxk3)
    check("#8 无新增不再告警", not any(f["no"] == 8 for f in ctxk3.findings))
    # 通知去重：已在 open 集合里的不再算新（提频安全前提）
    pre = {fkey(f) for f in ctxk2.findings if f["no"] == 8}
    fresh = new_findings(ctxk3, pre)
    check("通知去重：open 项不算新", all(f["no"] != 8 for f in fresh))
    fresh_all = new_findings(ctxk2, set())
    check("通知去重：空集合全算新", any(f["no"] == 8 for f in fresh_all))
    # 知识回流第 0 步：含 #5 / failed 工单时提示出现，不含时不出现（P29：只提示不处置）
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    with redirect_stdout(buf):
        kb_backflow_hint(ctx)               # ctx 含 #5（TSKC 有升级）
    check("知识回流提示:含 #5 出现", "公司知识库/methods" in buf.getvalue())
    buf2 = io.StringIO()
    with redirect_stdout(buf2):
        kb_backflow_hint(Ctx(cfg, tmp))     # 无 #5 无 failed，且 find 未跑（无 has_failed）
    check("知识回流提示:不含不出现", buf2.getvalue() == "")
    ctxf = Ctx(cfg, tmp)
    ctxf.has_failed = True                  # 模拟 find() 复用已加载工单算出的 failed 标记
    buf3 = io.StringIO()
    with redirect_stdout(buf3):
        kb_backflow_hint(ctxf)
    check("知识回流提示:failed 工单触发", "公司知识库/methods" in buf3.getvalue())
    # 勿扰屏蔽（notify_allowed 纯函数）：critical 恒放行；warn/info 时段内静默
    cfgq = {"quiet_hours": "22:00-08:00"}   # 跨零点
    check("勿扰:critical 恒放行", notify_allowed("critical", datetime.time(23, 0), cfgq))
    check("勿扰:跨零点时段内屏蔽(warn/info)",
          not notify_allowed("warn", datetime.time(23, 30), cfgq)
          and not notify_allowed("info", datetime.time(2, 0), cfgq))
    check("勿扰:时段外放行", notify_allowed("warn", datetime.time(12, 0), cfgq))
    cfgn = {"quiet_hours": "12:00-14:00"}   # 普通时段
    check("勿扰:普通时段内屏蔽", not notify_allowed("warn", datetime.time(13, 0), cfgn))
    check("勿扰:未启用放行", notify_allowed("warn", datetime.time(23, 0), {}))
    check("勿扰:配置非法按未启用", notify_allowed("warn", datetime.time(23, 0), {"quiet_hours": "abc"}))
    # 写日志幂等
    n1 = write_log(ctx, dry=False)
    n2 = write_log(ctx, dry=False)
    check("日志追加幂等", n1 > 0 and n2 == 0)
    check("干跑不写", write_log(Ctx(cfg, tmp), dry=True) == 0)
    print("自测" + ("全部通过 ✓" if ok else "存在失败 ✗"))
    return 0 if ok else 1


def auto_refresh(ctx, dry):
    """看板数据自愈（2026-08-29 拍板）：看板数据缺失或陈旧（> PATROL.regen_stale_minutes）
    → 自动重生成。浏览器「同步」只能重读数据文件、跑不了生成器——数据刷新靠 OPC 服务，
    陈旧横幅才会在下一次同步后消失。dry-run / 刷新失败不阻断巡检（#10 会报告陈旧）。"""
    if dry:
        return
    # 链接自愈（决策 #17）：实体/公司目录被手动改名后，稳定锚与技能披露断链
    # → OPC 服务幂等重建（巡检周期兜底），无人值守自愈（改不改目录名都不影响公司运转）。
    okl, errl = opc_resolver.ensure_links(opc_resolver._find_root())
    for m in okl:
        if "无需改动" not in m:
            print(f"  [自愈] OS 级链接已重建：{m}")
    for m in errl:
        print(f"  [警告] OS 级链接自愈失败：{m}——请人工处理")
    stale_min = PATROL.get("regen_stale_minutes", 30)
    need = os.path.isdir(ctx.wb)
    if need and os.path.isfile(ctx.tasks_data):
        try:
            age = (datetime.datetime.now()
                   - datetime.datetime.fromtimestamp(os.path.getmtime(ctx.tasks_data))).total_seconds() / 60
            need = age > stale_min
        except OSError:
            need = True
    if not need:
        return
    import subprocess
    py = sys.executable or "python"
    root = os.path.dirname(os.path.abspath(__file__))
    for mod in ("opc_tickets.py", "opc_dashboards.py"):
        r = subprocess.run([py, os.path.join(root, mod), "--company", ctx.cid],
                           cwd=root, capture_output=True, text=True, check=False)
        if r.returncode == 0:
            print(f"  [自愈] 看板数据已自动刷新（{mod}，数据陈旧 > {stale_min} 分钟）")
        else:
            tail = (r.stderr or r.stdout or "").strip().splitlines()
            print(f"  [警告] 看板自动刷新失败（{mod}）：{tail[-1] if tail else r.returncode}——检查 #10 陈旧告警")


def run_once(company=None, dry=False, quiet=True):
    """单轮巡检（进程内复用入口，决策 #18）：数据自愈 → find → 写 log/state → 通知去重。
    返回 (ctx, fresh)：fresh=本轮新发现（通知已发出）。CLI main 与 OPC 服务共用同一实现，
    机器口径只有一份，不漂移。
    并发口径（2026-08-29 三轮体检）：全程持每公司 state 锁——服务内 watch//sync/周期
    兜底三触发源串行化，state 读改写与 pre_open→通知窗口不再互踩（丢 handled/重复弹通知）。"""
    ctx = resolve_ctx(company)
    with opc_model.file_lock(ctx.state, timeout=60.0):
        return _run_once_locked(ctx, dry, quiet)


def _run_once_locked(ctx, dry, quiet):
    auto_refresh(ctx, dry)          # 数据自愈在前：find() 的工单类检查消费的是新鲜投影
    find(ctx)
    pre_open = set()
    if not dry and ctx.findings:
        # 通知去重（2026-08-29 拍板「提频先去重」）：快照 update_state 之前的 open 集合
        pre_open = {k for k, v in load_state(ctx).items()
                    if not k.startswith("_") and v.get("status") != "handled"}
    if not ctx.findings:
        if not quiet:
            print(f"[patrol] {ctx.today} 巡检完成：无异常 ✓")
            kb_backflow_hint(ctx)   # failed 工单可能不伴随其他发现，无发现也要提示回流
        # 无发现也要刷新待办快照：state 里残留的 open 项（等处置）保持可见，处置完即收敛
        write_pending(ctx, load_state(ctx))
        return ctx, []
    written = write_log(ctx, dry)
    if not quiet:
        print(f"[patrol] {ctx.today} 巡检发现 {len(ctx.findings)} 项待办：")
        for f in sorted(ctx.findings, key=lambda x: (x["no"], x.get("ref") or "")):
            print(f"  #{f['no']} [{f['severity']}] {f['msg']}")
        kb_backflow_hint(ctx)   # 知识回流第 0 步：发现汇总之后轻量提示一次
        if written:
            print(f"  已追加 {written} 条到 {ctx.log}（干跑模式不写）" if dry else f"  已追加 {written} 条到 {ctx.log}")
    fresh = []
    if not dry:
        state = update_state(ctx)
        write_pending(ctx, state)
        if not quiet:
            opens = sum(1 for k2, v in state.items()
                        if not k2.startswith("_") and v.get("status") != "handled")
            print(f"  闭环态已更新：{ctx.state}（open {opens} 项）→ 待办快照 {ctx.pending}")
        pcfg = _patrol_cfg()
        if pcfg.get("notify", True):
            fresh = new_findings(ctx, pre_open)
            if fresh:
                # 勿扰屏蔽（2026-08-29）：quiet_hours 时段内 warn/info 静默（并入每日摘要），critical 恒放行
                now_t = datetime.datetime.now().time()
                allowed = [f for f in fresh if notify_allowed(f["severity"], now_t, pcfg)]
                muted = len(fresh) - len(allowed)
                if allowed:
                    summary = "；".join(f["msg"] for f in allowed[:3])
                    if notify_user(ctx, summary) and not quiet:
                        print(f"  已发系统通知（新发现 {len(allowed)} 项；A+ 报警通道，可在 opc.toml [patrol] notify=false 关闭）")
                if muted and not quiet:
                    print(f"  勿扰时段：{muted} 项已按勿扰配置静默（次日 09:00 摘要重提）")
            elif not quiet:
                print("  通知去重：无新发现（open 待办见 patrol-pending.md），不再重复打扰")
    return ctx, fresh


USAGE = (
    "用法：python opc_patrol.py --company <公司ID> [--dry-run] [--quiet]\n"
    "      python opc_patrol.py --selftest            # 自测（不碰真实数据）\n"
    "说明：日常巡检由 OPC 服务（opc_service.py）进程内自动调度，本入口仅用于手动跑一次/排查。"
)


def main(argv):
    if "-h" in argv or "--help" in argv:
        print(USAGE)
        return 0
    if "--selftest" in argv:
        return selftest()
    company, _dir = opc_model.parse_company_args(argv)
    if not company:          # 友好提示而非抛栈（旧版有唯一公司自动推断，重构后显式要求）
        print(USAGE)
        return 1
    try:
        ctx, _fresh = run_once(company, dry="--dry-run" in argv, quiet="--quiet" in argv)
    except SystemExit:
        raise
    except Exception:
        return 2    # 巡检自身崩溃（区别于「有发现」的 1；退出语义：0 无发现 / 1 有发现 / 2 崩溃）
    return 1 if ctx.findings else 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")   # Windows cp1252 控制台/CI 下中文输出防崩（CI 实测）
    sys.exit(main(sys.argv))
