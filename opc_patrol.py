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
import datetime
import subprocess

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
import opc_resolver
from opc_schema import TASK_TERMINAL, TASK_ACTIVE, PATROL


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
        self.today = datetime.date.today()
        self.findings = []   # [(check_no, msg)]


def resolve_ctx(company):
    cfg = opc_resolver.load_company(company)
    if not os.path.isdir(cfg.home_abs):
        raise FileNotFoundError(
            f"公司 {company} 根不存在：{cfg.home_abs}（锚未建或目录被删）"
            f"→ 在 OPC 根跑 `python opc_resolver.py --sync-links` 重建锚")
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
            ctx.findings.append((1, f"工单 {t['id']}「{t['title']}」前置已全部完成，仍 backlog——通知 owner={t.get('owner') or '?'} 开工"))

    # 2) 认领缺口 + 3) 双账不一致（消费 dashboard 的核验告警，机器口径与生成器一致）
    for w in warnings:
        msg = w.get("msg", "")
        if "未认领" in msg:
            ctx.findings.append((2, msg))
        elif any(k in msg for k in ("未记", "非「进行中」", "已done", "仍未关", "不存在")):
            ctx.findings.append((3, msg))

    # 4) 脱期事务（机器可判定口径与生成器一致）
    for a in dd.get("affairs", []):
        if a.get("never_done"):
            ctx.findings.append((4, f"事务 {a['id']}「{a['title']}」从未推进（owner={a.get('owner') or '?'}）"))
        elif a.get("overdue"):
            ctx.findings.append((4, f"事务 {a['id']}「{a['title']}」已脱期（{a.get('cadence')}，上次推进 {a.get('last_touched') or '?'}）"))

    # 5) 升级信箱（发现即高优待办）
    for t in tasks:
        for esc in t.get("escalations", []):
            ctx.findings.append((5, f"[高优] 工单 {t['id']}「{t['title']}」有未处理升级：{esc.get('reason')}（owner={t.get('owner') or '?'}）"))

    # 6) 号池水位
    ti = _read(os.path.join(ctx.wb, "task-index.md"))
    m = re.search(r"TSK(\d{5})\s*[～~]\s*TSK(\d{5})", ti)
    if m:
        used = {t["id"] for t in tasks}
        lo, hi = int(m.group(1)), int(m.group(2))
        remaining = sum(1 for n in range(lo, hi + 1) if f"TSK{n:05d}" not in used)
        if remaining < PATROL["ticket_pool_min"]:
            ctx.findings.append((6, f"预留号池剩余 {remaining} 个（<{PATROL['ticket_pool_min']}），总管补号段"))

    # 7) 归档提醒（热文件含上一年度条目——仅提示计数，交总管处理）
    stale_year = str(ctx.today.year - 1)
    for name in sorted(os.listdir(ctx.base)) if os.path.isdir(ctx.base) else []:
        if not re.match(r"^E\d{3,}-", name):
            continue
        wl = os.path.join(ctx.base, name, "workspace", "worklog.md")
        txt = _read(wl)
        n = len(re.findall(r"^date:\s*%s" % stale_year, txt, re.M))
        if n:
            ctx.findings.append((7, f"{name} 热文件含 {n} 条 {stale_year} 年条目，建议归档"))

    # 9) 僵尸工位卡（工作中但 3 天未动）
    cutoff = (ctx.today - datetime.timedelta(days=3)).strftime("%Y%m%d")
    for name in sorted(os.listdir(ctx.base)) if os.path.isdir(ctx.base) else []:
        if not re.match(r"^E\d{3,}-", name):
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
                ctx.findings.append((9, f"{name} 存在疑似僵尸工位卡 {f}（3 天未动），核对会话是否已结束→收口"))

    # 10) 生成器健康：tasks-data 陈旧
    gen_at = td.get("generated_at", "")
    if gen_at:
        try:
            g = datetime.datetime.strptime(gen_at, "%Y-%m-%d %H:%M:%S")
            age_h = (datetime.datetime.now() - g).total_seconds() / 3600
            if age_h > 24:
                ctx.findings.append((10, f"看板数据已 {int(age_h)} 小时未刷新（>24h），跑一次 run_boards once 或检查 watcher"))
        except ValueError:
            pass


def write_log(ctx, dry):
    """发现写入 workbench/patrol-log.md（幂等：同日同条目不重复追加）。"""
    if not ctx.findings:
        return 0
    day = ctx.today.strftime("%Y-%m-%d")
    existing = _read(ctx.log)
    new_lines = []
    for no, msg in sorted(ctx.findings):
        line = f"- [{day}] #{no} {msg}"
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
    msgs = " | ".join(m for _, m in ctx.findings)
    check("#1 解锁待开工发现", any("TSKA" in m for m in msgs.split(" | ")))
    check("#4 脱期事务发现", "AFF1" in msgs)
    check("#5 升级信箱高优", "高优" in msgs and "TSKC" in msgs)
    check("#2 认领缺口发现", "未认领" in msgs)
    check("#9 僵尸工位卡发现", "僵尸" in msgs)
    check("#10 数据陈旧发现", "未刷新" in msgs)
    # 写日志幂等
    n1 = write_log(ctx, dry=False)
    n2 = write_log(ctx, dry=False)
    check("日志追加幂等", n1 > 0 and n2 == 0)
    check("干跑不写", write_log(Ctx(cfg, tmp), dry=True) == 0)
    print("自测" + ("全部通过 ✓" if ok else "存在失败 ✗"))
    return 0 if ok else 1


def main(argv):
    if "--selftest" in argv:
        return selftest()
    company = None
    if "--company" in argv:
        company = argv[argv.index("--company") + 1]
    ctx = resolve_ctx(company)
    find(ctx)
    dry = "--dry-run" in argv
    quiet = "--quiet" in argv
    if not ctx.findings:
        if not quiet:
            print(f"[patrol] {ctx.today} 巡检完成：无异常 ✓")
        return 0
    written = write_log(ctx, dry)
    print(f"[patrol] {ctx.today} 巡检发现 {len(ctx.findings)} 项待办：")
    for no, msg in sorted(ctx.findings):
        print(f"  #{no} {msg}")
    if written:
        print(f"  已追加 {written} 条到 {ctx.log}（干跑模式不写）" if dry else f"  已追加 {written} 条到 {ctx.log}")
    if ctx.findings and not dry and _patrol_cfg().get("notify", True):
        summary = "；".join(m for _, m in sorted(ctx.findings)[:3])
        if notify_user(ctx, summary):
            print("  已发系统通知（A+ 报警通道；可在 opc.toml [patrol] notify=false 关闭）")
    return 1 if ctx.findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
