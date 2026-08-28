#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
opc_patrol.py —— 公司心跳巡检器（机制层，OPC 根单例）

> 2026-08-28 新增（架构评审「公司自转」缺口）：此前所有节奏检测（脱期/升级/阻塞解锁）
> 都只在"有人触发生成/总管开会话"时才发生——用户三天不来，公司完全静止。
> 本脚本让公司拥有独立于用户注意力的心跳：挂计划任务/cron 每日一跑，
> 消费 skills/patrol/SKILL.md 定义的同一份巡检清单（机器与总管共享标准，不漂移）。

职责边界（与总管分工）：
  - 本脚本只「发现」：1~6 号检查项的机器可判定部分，异常写入 workbench/patrol-log.md
    （追加式、幂等去重），并打印待办清单；不做任何处置决策。
    例外（2026-08-29 拍板）：看板数据缺失/陈旧时自动重生成（auto_refresh）——浏览器「同步」
    只能重读文件，数据刷新必须由心跳完成，属机械性自愈而非处置决策。
  - 总管「处置」：读 patrol-log / 看板告警，答复、转派、催办、补号。
  - A+ 报警（2026-08-28 拍板）：有发现时弹系统通知（opc.toml [patrol].notify 可关）；
    B 阶段「自动处置」扩展位 [patrol].actor 预留，当前未启用。

用法（cwd 无关）：
    python opc_patrol.py --company C001              # 巡检 + 写 log
    python opc_patrol.py --company C001 --dry-run    # 只检查打印，不写
    python opc_patrol.py --company C001 --quiet      # 仅异常时输出（适合 cron）
    python opc_patrol.py --selftest

计划任务示例（Windows，管理员 PowerShell，在公司根执行一次即可注册每日 09:00 心跳）：
    schtasks /Create /TN "OPC-Patrol" /SC DAILY /ST 09:00 /TR ^
      "python E:\\OPC\\opc_patrol.py --company C001 --quiet"
macOS/Linux crontab：
    0 9 * * * cd /path/to/OPC && python3 opc_patrol.py --company C001 --quiet
"""

import os
import sys
import re
import json
import hashlib
import datetime
import subprocess

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
import opc_resolver
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
        if not re.match(rf"^{pe}\d{{3,}}-", name):
            continue
        wl = os.path.join(ctx.base, name, "workspace", "worklog.md")
        txt = _read(wl)
        n = len(re.findall(r"^date:\s*%s" % stale_year, txt, re.M))
        if n:
            ctx.findings.append(_mk(7, f"{name} 热文件含 {n} 条 {stale_year} 年条目，建议归档", ref=name))

    # 8) 知识库增量（B6 闭环，2026-08-29 拍板机器化）：methods/ 与各项目 knowledge/
    #    新条目 → 提示总管评审提炼（技能/制度/common 三选一）。基线存 patrol-state
    #    的 _meta（非 finding），首跑建基线不告警；基线随心跳推进，open 待办由
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
        if not re.match(rf"^{pe}\d{{3,}}-", name):
            continue
        sdir = os.path.join(ctx.base, name, "workspace", "sessions")
        if not os.path.isdir(sdir):
            continue
        for f in sorted(os.listdir(sdir)):
            if not f.endswith(".md"):
                continue
            card = _read(os.path.join(sdir, f))
            if "status: 工作中" not in card and "status: 工作中" not in card.replace("：", ": "):
                # 状态字段可能是 status: 工作中 或被改为其他；宽松匹配工作中
                if "工作中" not in card:
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
                ctx.findings.append(_mk(10, f"看板数据已 {int(age_h)} 小时未刷新（>24h），跑一次 run_boards once 或检查 watcher",
                                        ref="tasks-data"))
        except ValueError:
            pass


def write_log(ctx, dry):
    """发现写入 workbench/patrol-log.md（幂等：同日同条目不重复追加）。"""
    if not ctx.findings:
        return 0
    day = ctx.today.strftime("%Y-%m-%d")
    existing = _read(ctx.log)
    new_lines = []
    for f in sorted(ctx.findings, key=lambda x: (x["no"], x.get("ref") or "")):
        line = f"- [{day}] #{f['no']} {f['msg']}"
        if line not in existing:
            new_lines.append(line)
    if not new_lines or dry:
        return 0
    os.makedirs(os.path.dirname(ctx.log), exist_ok=True)
    if not existing:
        existing = "# 巡检日志（patrol-log）\n\n> opc_patrol.py 心跳自动追加，只增不删；处置由总管完成（在对应工单 messages.md 留痕）。\n"
    with open(ctx.log, "a", encoding="utf-8", newline="") as fh:
        if not existing.endswith("\n"):
            fh.write("\n")
        fh.write("\n".join(new_lines) + "\n")
    return len(new_lines)


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
            if re.match(r"^P\d{3,}-", name) and os.path.isdir(kdir):
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
    # #8 基线推进：本轮心跳已把当前知识库计数落账（open 待办仍在 state 里等处置）
    if getattr(ctx, "kb_count", None) is not None:
        state.setdefault("_meta", {})["knowledge_baseline"] = ctx.kb_count
        changed = True
    if changed or not os.path.isfile(ctx.state):
        save_state(ctx, state)
    return state


def write_pending(ctx, state):
    """open 态待办快照 patrol-pending.md：总管启动第 5 步读它（比全量日志轻），
    处置完在 state 置 handled，下次心跳本文件自动收敛。"""
    opens = [(k, v) for k, v in state.items()
             if not k.startswith("_") and v.get("status") != "handled"]   # _meta=机器态，非待办
    order = {"critical": 0, "warn": 1, "info": 2}
    opens.sort(key=lambda kv: (order.get(kv[1].get("severity"), 3),
                               kv[1].get("no", 99), kv[0]))
    lines = [
        "# 巡检待办（open 态快照，opc_patrol.py 生成）",
        "",
        "> 处置完成后在 patrol-state.json 把对应条目 status 置 \"handled\"（附 handled_at/by），下次心跳本文件自动收敛；审计流水见 patrol-log.md（只增不删）。",
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
        "$n.Dispose()\r\n" % (title, text)
    )
    ps = os.path.join(tempfile.gettempdir(), "opc-patrol-notify.ps1")
    with open(ps, "w", encoding="utf-8-sig", newline="") as fh:
        fh.write(script)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.Popen(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-WindowStyle", "Hidden", "-File", ps],
        creationflags=flags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ---------------------------------------------------------------------------
# 心跳注册（2026-08-29 拍板：自举化——register-patrol.{ps1,sh} 收敛为本模块的
# 薄壳，定时逻辑单一来源；--bootstrap 会自动调用，不依赖用户记得挂）
# ---------------------------------------------------------------------------

def heartbeat_task_name(cid):
    return f"OPC-Patrol-{cid}"


def _heartbeat_cron_line(root, cid, at):
    py = "python3" if not sys.platform.startswith("win") else "python"
    h, m = at.split(":")
    return f"{int(m)} {int(h)} * * * cd '{root}' && {py} opc_patrol.py --company {cid} --quiet"


def _run_decoded(cmd, **kw):
    """subprocess + 本地编码解码：schtasks/crontab 输出是系统 ANSI 代码页
    （中文 Windows 为 GBK），text=True 的 UTF-8 强解会炸（CI/本机实测）。"""
    r = subprocess.run(cmd, capture_output=True, check=False, **kw)
    enc = "mbcs" if sys.platform.startswith("win") else "utf-8"
    r.stdout = (r.stdout or b"").decode(enc, "replace")
    r.stderr = (r.stderr or b"").decode(enc, "replace")
    return r


def register_heartbeat(root, cid, at="09:00"):
    """注册每日心跳：Windows 用 schtasks（当前用户级，无需管理员）、
    macOS/Linux 追加 crontab（幂等，已有同任务则跳过）。
    返回 (ok, msg)。平台差异收敛在此一处（自举化后本函数是唯一实现）。"""
    if not re.match(r"^\d{1,2}:\d{2}$", at):
        return False, f"时间格式应为 HH:MM，收到 {at!r}"
    name = heartbeat_task_name(cid)
    if sys.platform.startswith("win"):
        py = sys.executable or "python"
        tr = f'"{py}" "{os.path.join(root, "opc_patrol.py")}" --company {cid} --quiet'
        r = _run_decoded(["schtasks", "/Create", "/TN", name, "/SC", "DAILY",
                          "/ST", at, "/TR", tr, "/F"])
        ok = r.returncode == 0
        detail = (r.stdout or r.stderr or "").strip().splitlines()
        return ok, f"{name}（每日 {at}）" + (f"：{detail[-1]}" if detail and not ok else "")
    # macOS / Linux：crontab 幂等追加
    mark = f"# {heartbeat_task_name(cid)}"
    line = _heartbeat_cron_line(root, cid, at)
    cur = ""
    try:
        cur = _run_decoded(["crontab", "-l"]).stdout or ""
    except OSError as e:
        return False, f"crontab 不可用：{e}"
    if mark in cur:
        return True, f"{name} 已存在（每日 {at}），跳过"
    new = (cur.rstrip("\n") + "\n" if cur.strip() else "") + f"{mark}\n{line}\n"
    r = _run_decoded(["crontab", "-"], input=new.encode("utf-8"))
    return (r.returncode == 0), (f"{name}（每日 {at}）" if r.returncode == 0 else r.stderr)


def heartbeat_registered(root, cid):
    """心跳是否已挂（doctor 提示用；查询失败视为未挂，只降级为提示不阻断）。"""
    if sys.platform.startswith("win"):
        r = _run_decoded(["schtasks", "/Query", "/TN", heartbeat_task_name(cid)])
        return r.returncode == 0
    try:
        cur = _run_decoded(["crontab", "-l"]).stdout or ""
    except OSError:
        return False
    return f"# {heartbeat_task_name(cid)}" in cur


def unregister_heartbeat(root, cid):
    """撤销心跳：Windows 删计划任务；*nix 从 crontab 移除标记块。幂等。"""
    name = heartbeat_task_name(cid)
    if sys.platform.startswith("win"):
        r = _run_decoded(["schtasks", "/Delete", "/TN", name, "/F"])
        return (r.returncode == 0), f"{name}" + ("（已删除）" if r.returncode == 0 else "（不存在或删除失败）")
    mark = f"# {heartbeat_task_name(cid)}"
    try:
        cur = _run_decoded(["crontab", "-l"]).stdout or ""
    except OSError as e:
        return False, f"crontab 不可用：{e}"
    if mark not in cur:
        return True, f"{name}（本就未注册）"
    out, skip = [], False
    for ln in cur.splitlines():
        if ln.strip() == mark:
            skip = True
            continue
        if skip:
            skip = False
            continue
        out.append(ln)
    r = _run_decoded(["crontab", "-"], input=("\n".join(out) + "\n").encode("utf-8"))
    return (r.returncode == 0), f"{name}（已从 crontab 移除）"


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
    # #8 知识库增量：首跑建基线 → 新增 → 告警 → 基线随心跳推进
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
    check("#8 基线随心跳推进", (st8.get("_meta") or {}).get("knowledge_baseline") == 1)
    ctxk3 = Ctx(cfg, tmp)
    find(ctxk3)
    check("#8 无新增不再告警", not any(f["no"] == 8 for f in ctxk3.findings))
    # 写日志幂等
    n1 = write_log(ctx, dry=False)
    n2 = write_log(ctx, dry=False)
    check("日志追加幂等", n1 > 0 and n2 == 0)
    check("干跑不写", write_log(Ctx(cfg, tmp), dry=True) == 0)
    print("自测" + ("全部通过 ✓" if ok else "存在失败 ✗"))
    return 0 if ok else 1


def auto_refresh(ctx, dry):
    """心跳数据自愈（2026-08-29 拍板）：看板数据缺失或陈旧（> PATROL.regen_stale_minutes）
    → 自动重生成。浏览器「同步」只能重读数据文件、跑不了生成器——数据刷新靠心跳，
    陈旧横幅才会在下一次同步后消失。dry-run / 刷新失败不阻断巡检（#10 会报告陈旧）。"""
    if dry:
        return
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


def main(argv):
    if "--selftest" in argv:
        return selftest()
    root = opc_resolver._find_root()
    # 心跳注册/撤销（--bootstrap 与 register-patrol 薄壳共用此入口）
    if "--register-heartbeat" in argv or "--unregister-heartbeat" in argv:
        company = None
        if "--company" in argv:
            company = argv[argv.index("--company") + 1]
        if not company:
            cids = opc_resolver.all_company_ids(root)
            if len(cids) != 1:
                print("需要 --company <cid>（多公司时无法自动确定）")
                return 1
            company = cids[0]
        at = "09:00"
        if "--at" in argv:
            at = argv[argv.index("--at") + 1]
        if "--register-heartbeat" in argv:
            ok, msg = register_heartbeat(root, company, at)
            print(("[ok] " if ok else "[ERR] ") + f"心跳注册：{msg}"
                  + ("" if ok else f"；撤销：schtasks /Delete /TN {heartbeat_task_name(company)} /F 或编辑 crontab"))
            return 0 if ok else 1
        ok, msg = unregister_heartbeat(root, company)
        print(("[ok] " if ok else "[ERR] ") + f"心跳撤销：{msg}")
        return 0 if ok else 1
    company = None
    if "--company" in argv:
        company = argv[argv.index("--company") + 1]
    ctx = resolve_ctx(company)
    dry = "--dry-run" in argv
    quiet = "--quiet" in argv
    auto_refresh(ctx, dry)          # 数据自愈在前：find() 的工单类检查消费的是新鲜投影
    find(ctx)
    if not ctx.findings:
        if not quiet:
            print(f"[patrol] {ctx.today} 巡检完成：无异常 ✓")
        # 无发现也要刷新待办快照：state 里残留的 open 项（等处置）保持可见，处置完即收敛
        write_pending(ctx, load_state(ctx))
        return 0
    written = write_log(ctx, dry)
    print(f"[patrol] {ctx.today} 巡检发现 {len(ctx.findings)} 项待办：")
    for f in sorted(ctx.findings, key=lambda x: (x["no"], x.get("ref") or "")):
        print(f"  #{f['no']} [{f['severity']}] {f['msg']}")
    if written:
        print(f"  已追加 {written} 条到 {ctx.log}（干跑模式不写）" if dry else f"  已追加 {written} 条到 {ctx.log}")
    if not dry:
        state = update_state(ctx)
        write_pending(ctx, state)
        opens = sum(1 for v in state.values() if v.get("status") != "handled")
        print(f"  闭环态已更新：{ctx.state}（open {opens} 项）→ 待办快照 {ctx.pending}")
    if ctx.findings and not dry and _patrol_cfg().get("notify", True):
        summary = "；".join(f["msg"] for f in sorted(ctx.findings, key=lambda x: x["no"])[:3])
        if notify_user(ctx, summary):
            print("  已发系统通知（A+ 报警通道；可在 opc.toml [patrol] notify=false 关闭）")
    return 1 if ctx.findings else 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")   # Windows cp1252 控制台/CI 下中文输出防崩（CI 实测）
    sys.exit(main(sys.argv))
