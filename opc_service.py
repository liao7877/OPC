#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""opc_service.py —— OPC 服务（决策 #18：组织级常驻后台中枢）

定位：机器上唯一的常驻进程，承载一切「必须有进程才能实现」的机制。
文件仍是唯一真相和接口——本服务没有写业务数据的权力（只写自己的运行状态）。

架构：进程 = 宿主，公司 = 租户。
  启动时扫描 opc.toml 全部公司，每家装载独立的服务实例（看板/巡检/通知互不串
  数据），新公司自动纳管，不改进程代码。URL 按公司路由：
      http://127.0.0.1:8765/C001/dashboard.html
  旧的无前缀地址（/dashboard.html、/api/sync）自动落到默认公司，兼容不断链。

内置服务（按租户装配，opc.toml [service] 可配）：
  boards  静态托管 + /sync 即时重算（看板「同步」按钮直通生成器）+ 数据源监听重生成
  patrol  巡检实时化：数据变动即巡检（opc_patrol.run_once）+ 每 patrol_interval_minutes 兜底
  notify  新发现即时报（巡检 A+ 通道）+ 每日 digest_time 未处理项汇总重提；
          通道可插拔：windows 弹窗内置（opc_patrol.notify_user 唯一出口），
          将来 agent 平台/webhook 在此扩展 channel，配置驱动。

只读 API（给 agent 与未来外部服务；写边界只留一个显式重算动作）：
  GET  /api/ping                   服务健康 + 租户清单
  GET  /api/{CID}/ping             租户状态
  POST /api/{CID}/sync             重算该公司看板数据 + 联动巡检（看板「同步」按钮用；
                                   只收 POST 且同站校验——GET 已退役，防任意网页滥用）
  GET  /api/{CID}/tickets          工单投影 JSON
  GET  /api/{CID}/dashboard        驾驶舱投影 JSON
  GET  /api/{CID}/patrol           巡检待办（open 项）

开机自启：--register 写启动文件夹 OPC-Service.vbs（pythonw headless，免管理员，
删文件即卸载）。旧 schtasks 心跳（OPC-Patrol-*）已随本服务退役。

用法：
  python opc_service.py                # 前台运行
  python opc_service.py --open         # 运行并打开默认公司看板
  python opc_service.py --register     # 注册开机自启
  python opc_service.py --unregister
"""

import json
import os
import re
import sys
import threading
import time
import urllib.parse
import webbrowser
from http.server import ThreadingHTTPServer

_ROOT = os.path.dirname(os.path.abspath(__file__))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import opc_dashboards
import opc_patrol
import opc_resolver
import opc_tickets

POLL_SECONDS = 3.0
STARTUP_VBS = "OPC-Service.vbs"


def _service_cfg():
    """读 opc.toml [service] 段（进程级配置：端口/巡检兜底周期/每日摘要/通知通道）。缺段用默认。"""
    defaults = {"port": 8765, "patrol_interval_minutes": 5,
                "digest_time": "09:00", "notify_channels": ["windows"]}
    try:
        g = opc_resolver._load_toml(os.path.join(opc_resolver._find_root(), "opc.toml"))
        cfg = dict(g.get("service", {}))
        defaults.update({k: v for k, v in cfg.items() if v is not None})
    except Exception:
        pass
    return defaults


# ---------------------------------------------------------------------------
# 租户（一个公司一个实例）
# ---------------------------------------------------------------------------

class Tenant:
    def __init__(self, cid):
        self.cid = cid
        self.pctx = opc_patrol.resolve_ctx(cid)                      # 巡检 ctx（base=公司根）
        self.tctx = opc_tickets.resolve_ctx(company=cid)             # 工单生成器 ctx
        self.dctx = opc_dashboards.resolve_ctx(company=cid)          # 驾驶舱生成器 ctx
        self.base = self.pctx.base
        self.gen_lock = threading.Lock()
        self.last_gen_epoch = 0.0
        self.last_findings = []      # 最近一轮巡检发现（/api/{cid}/patrol 用）
        self.last_error = ""         # 后台循环最近一次异常（/api/{cid}/ping 可查，防静默）

    # ---- 生成 + 巡检 ----

    def regenerate(self, why=""):
        """重算该公司双投影（单飞锁）；返回 (ok, errors)。"""
        with self.gen_lock:
            # 进锁先置 + 完成后再置（2026-08-29 三轮体检）：生成全程对 watch 不可见——
            # 只在完成时置的话，生成期间 watch 采样到中间态 mtime 会排队再跑一遍全量重算
            self.last_gen_epoch = time.time()
            errs = []
            for name, fn, ctx in (("tickets", opc_tickets.generate, self.tctx),
                                  ("dashboards", opc_dashboards.generate_all, self.dctx)):
                try:
                    fn(ctx)
                except Exception as e:      # 单侧失败不阻断另一侧（沿 safe_generate 容错口径）
                    errs.append(f"{name}: {e}")
            self.last_gen_epoch = time.time()
            return (not errs), errs

    def patrol(self, quiet=True):
        """单轮巡检（数据自愈+发现+去重+实时通知由 opc_patrol.run_once 一体完成）。"""
        ctx, _fresh = opc_patrol.run_once(self.cid, quiet=quiet)
        self.last_findings = list(ctx.findings)
        return self.last_findings

    def _sources_mtime(self):
        return max(opc_tickets.tasks_mtime(self.tctx),
                   opc_dashboards.deps_mtime(self.dctx))

    def _watch_loop(self):
        """数据源监听：变动 → 重生成 → 即巡检（数据变动即巡检，决策 #18）。"""
        last = self._sources_mtime()
        while True:
            time.sleep(POLL_SECONDS)
            try:
                cur = self._sources_mtime()
                if cur == last:
                    continue
                if self.gen_lock.locked():
                    last = cur    # 有生成正在进行（/sync/兜底重算）：产物即将刷新，重定基线不叠加
                    continue
                last = cur
                # mtime 变化若只是上轮生成自己写的数据文件（如 /sync 刚跑过）→ 只重定基线
                if cur > self.last_gen_epoch + 1.0:
                    self.regenerate("watch")
                    self.patrol()
                last = self._sources_mtime()
            except Exception as e:
                # 监听线程永不退出（单轮失败不断服务），但异常必须可查（防静默失能）
                self.last_error = f"{time.strftime('%m-%d %H:%M:%S')} watch: {e!r}"

    def _patrol_loop(self, interval_minutes):
        """周期兜底巡检：数据源 mtime 之外的第二触发源（如 worklog 无 mtime 变化的语义问题）。"""
        while True:
            time.sleep(max(1, int(interval_minutes)) * 60)
            try:
                self.patrol()
            except Exception as e:
                self.last_error = f"{time.strftime('%m-%d %H:%M:%S')} patrol: {e!r}"

    def open_items(self):
        """state 里未处置（open/reopened）的待办，每日摘要重提用。"""
        state = opc_patrol.load_state(self.pctx)
        return [v for k, v in state.items()
                if not k.startswith("_") and isinstance(v, dict) and v.get("status") != "handled"]


# ---------------------------------------------------------------------------
# 通知（通道可插拔；windows 内置，其余通道加分支 + 配置即可）
# ---------------------------------------------------------------------------

def realtime_allowed(cfg):
    """实时弹窗判定：不在场模式（away_mode）下全部静默——摘要照常，绝不代决策（P29）。"""
    return not bool(cfg.get("away_mode"))


def _notify(tenant, title, text, force=False):
    cfg = _service_cfg()
    if not force and not realtime_allowed(cfg):
        print(f"[service] 不在场模式：实时通知已静默（摘要照常）——{title}")
        return
    for ch in cfg.get("notify_channels") or ["windows"]:
        if ch == "windows":
            try:
                opc_patrol.notify_user(tenant.pctx, text)   # A+ 报警唯一出口（toast 内部实现）
            except Exception:
                pass
        else:
            print(f"[service] 未知通知通道 {ch!r}（配置 [service].notify_channels），跳过")


def _digest_time():
    raw = _service_cfg().get("digest_time", "09:00")
    try:
        h, m = str(raw).split(":")
        return int(h), int(m)
    except ValueError:
        # 非法配置不再静默吞掉（曾致每日摘要永不触发且无任何提示）：回落默认并留痕
        print(f"[service] digest_time 配置非法（{raw!r}），回落 09:00")
        return 9, 0


def _digest_loop(tenants):
    """每日摘要：每天 digest_time 后首轮触发一次，把各公司未处置待办汇总重提（防遗忘不轰炸）。"""
    fired = None
    while True:
        time.sleep(30)
        try:
            now = time.localtime()
            hh, mm = _digest_time()
            today = time.strftime("%Y-%m-%d")
            if fired == today or (now.tm_hour, now.tm_min) < (hh, mm):
                continue
            fired = today
            for t in tenants.values():
                items = t.open_items()
                if not items:
                    continue
                summary = "；".join(i.get("msg", "") for i in items[:3])
                tail = f" 等共 {len(items)} 项" if len(items) > 3 else ""
                away = not realtime_allowed(_service_cfg())
                _notify(t, f"OPC 每日待办（{t.cid}）",
                        ("不在场模式：" if away else "") + f"未处理 {len(items)} 项：{summary}{tail}",
                        force=True)   # 摘要是不在场模式下的唯一触达通道，绕过实时静默
        except Exception:
            pass


# ---------------------------------------------------------------------------
# HTTP：公司路由 + 只读 API
# ---------------------------------------------------------------------------

def _safe_join(base, rest):
    """租户内路径解析（防目录穿越，P30 行为收敛在本函数）：
    段按 / 和 \\ 双分隔符切分并滤掉 . ..（Windows 下 URL 编码反斜杠 %5C 可绕过
    单一分隔符过滤），再以 realpath 前缀校验兜底——落点必须仍在租户 base 内，
    越界（绝对盘符、符号链等）一律落回租户根。"""
    parts = [s for s in re.split(r"[\\/]+", rest) if s and s not in (".", "..")]
    blocked = os.path.join(base, "__opc_traversal_blocked__")   # 不存在的路径 → 必然 404，不给列目录
    if not parts:
        return blocked    # 全是穿越段（如 /..\..）：拦下，绝不落回租户根做目录列表
    p = os.path.normpath(os.path.join(base, *parts))
    try:
        rb, rp = os.path.realpath(base), os.path.realpath(p)
        if rp == rb or rp.startswith(rb + os.sep):
            return p
    except (OSError, ValueError):
        pass
    return blocked


def _same_origin(headers):
    """同源校验（写动作 POST /sync 专用）：浏览器跨站上下文必带 Origin 或
    Sec-Fetch-Site: cross-site/same-site（same-site 不分端口，本机另一端口上的
    页面也算跨源——一并拒绝）；本机无头工具直连（两头皆空）放行。"""
    origin = headers.get("Origin")
    if origin:
        return urllib.parse.urlparse(origin).netloc == (headers.get("Host") or "")
    return headers.get("Sec-Fetch-Site") in (None, "same-origin", "none")


def make_handler(tenants, default_cid):
    from http.server import SimpleHTTPRequestHandler

    class H(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass    # pythonw 下无 stderr；看板轮询噪音也不值得记

        # ---- 路由辅助 ----

        def _route(self):
            """返回 (tenant, rest) or (None, path)。/CID/... 按租户；无前缀落默认公司（兼容）。"""
            p = urllib.parse.unquote(urllib.parse.urlparse(self.path).path)
            m = re.match(r"^/([A-Za-z]\d{3})(/.*)?$", p)
            if m:
                cid = m.group(1).upper()
                if cid in tenants:
                    return tenants[cid], m.group(2) or "/"
            return tenants.get(default_cid), p

        def translate_path(self, path):
            tenant, rest = self._route()
            if tenant is None:
                return super().translate_path(path)
            if rest.endswith("/"):
                rest += "index.html"
            return _safe_join(tenant.base, rest)

        def _json(self, obj, code=200):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _redirect(self, loc):
            self.send_response(302)
            self.send_header("Location", loc)
            self.send_header("Content-Length", "0")
            self.end_headers()

        # ---- 动词 ----

        def do_GET(self):
            p = urllib.parse.urlparse(self.path).path
            if p in ("/", ""):
                return self._redirect(f"/{default_cid}/dashboard.html")
            if p == "/api/ping":
                return self._json({"ok": True, "service": "opc-service",
                                   "companies": sorted(tenants), "default": default_cid,
                                   "config": _service_cfg()})   # 实时读：改 opc.toml 后 ping 不误报旧值
            # API 分发：裸路径 /api/C001/...（agent/外部服务用）→ 按 CID 定租户；
            # 公司前缀 /C001/api/...（前端「同步」用）→ 按前缀定租户；
            # 裸 /api/sync 等无 CID 的旧地址落默认公司（兼容）
            m = re.match(r"^/api/([A-Za-z]\d{3})(/.*)?$", p)
            if m:
                cid = m.group(1).upper()
                if cid not in tenants:
                    return self._json({"ok": False, "error": f"unknown company {cid}"}, 404)
                return self._api(tenants[cid], m.group(2) or "/")
            tenant, rest = self._route()
            if rest.startswith("/api/"):
                return self._api(tenant, rest[len("/api"):])
            return super().do_GET()

        def _api(self, t, sub):
            if sub == "/ping":
                return self._json({"ok": True, "company": t.cid, "base": t.base,
                                   "open_patrol_items": len(t.open_items()),
                                   "last_error": t.last_error or None})
            if sub == "/sync":
                return self._json({"ok": False, "error": "/sync 只收 POST（GET 已退役，防跨站滥用）"}, 405)
            if sub == "/tickets":
                return self._json(opc_patrol._load_json(t.tctx.out_json) or {})
            if sub == "/dashboard":
                return self._json(opc_patrol._load_json(t.pctx.dash_data) or {})
            if sub == "/patrol":
                return self._json({"company": t.cid, "last_findings": t.last_findings,
                                   "open_items": t.open_items()})
            return self._json({"ok": False, "error": f"unknown api {sub}"}, 404)

        def do_POST(self):
            # 写边界（架构铁律）：唯一带副作用的动作是 /sync（重算落盘），只收 POST
            # 且需同站——防任意网页 <img>/<form> 跨站触发全公司重算与通知
            if not _same_origin(self.headers):
                return self._json({"ok": False, "error": "cross-site request rejected"}, 403)
            p = urllib.parse.urlparse(self.path).path
            m = re.match(r"^/api/([A-Za-z]\d{3})(/.*)?$", p)
            if m:
                cid = m.group(1).upper()
                if cid not in tenants:
                    return self._json({"ok": False, "error": f"unknown company {cid}"}, 404)
                t, sub = tenants[cid], m.group(2) or "/"
            else:
                t, rest = self._route()
                if not rest.startswith("/api/"):
                    return self._json({"ok": False, "error": "no writable endpoint"}, 405)
                t, sub = t, rest[len("/api"):]
            if sub != "/sync":
                return self._json({"ok": False,
                                   "error": f"{sub} 无写接口（架构铁律）；仅 /sync 可 POST"}, 405)
            return self._api_sync(t)

        def _api_sync(self, t):
            ok, errs = t.regenerate("sync")
            findings = t.patrol() if ok else []
            self._json({"ok": ok, "company": t.cid,
                        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "patrol_findings": len(findings), "errors": errs},
                       200 if ok else 500)

    return H


# ---------------------------------------------------------------------------
# 探活 / 自检
# ---------------------------------------------------------------------------

def service_alive(port=None):
    """HTTP 探活：请求 /api/ping 并校验响应体——只测 TCP 会被占用端口的无关进程
    误报「服务在跑」，也不感知端口顺延。未指定端口时扫 [port, port+10)（与启动
    顺延口径一致）。0.5s 快速失败，不拖慢 doctor。"""
    import urllib.request
    base = int(_service_cfg()["port"])
    ports = [port] if port else list(range(base, base + 10))
    for p in ports:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{p}/api/ping", timeout=0.5) as r:
                if b"opc-service" in (r.read() or b""):
                    return True
        except Exception:
            continue
    return False


def selftest():
    """自检（P30：新行为必须过 CI 三平台矩阵——只测纯逻辑，不写机器状态）。"""
    ok = True

    def check(name, cond):
        nonlocal ok
        print(("  ✓ " if cond else "  ✗ ") + name)
        ok = ok and cond

    cfg = _service_cfg()
    check("[service] 配置默认值齐全（port/patrol_interval/digest_time/notify_channels/away_mode）",
          all(k in cfg for k in ("port", "patrol_interval_minutes", "digest_time", "notify_channels", "away_mode")))
    check("[service] away_mode 默认关闭", cfg.get("away_mode") is False)
    check("[service] realtime_allowed：默认放行", realtime_allowed({}) is True)
    check("[service] realtime_allowed：away_mode 静默", realtime_allowed({"away_mode": True}) is False)
    hh, mm = _digest_time()
    check("[service] digest_time 解析为合法时分", 0 <= hh <= 23 and 0 <= mm <= 59)
    # 目录穿越防护（含 Windows 反斜杠 / 绝对盘符，P30）
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        base = os.path.realpath(tmp)
        ok_join = _safe_join(base, "/dashboard.html") == os.path.normpath(os.path.join(base, "dashboard.html"))
        check("[service] _safe_join：正常路径落在租户内", ok_join)
        for evil in ("/..\\..\\..\\Windows\\win.ini",
                     "/..\\..\\secret", "/C:/Windows/win.ini", "/a/../../b"):
            res = _safe_join(base, evil)
            check(f"[service] _safe_join：穿越 {evil!r} 被拦回落回租户根",
                  res != base and os.path.realpath(res).startswith(base + os.sep))
    check("[service] 同站校验：跨站 Origin 拒绝",
          not _same_origin({"Origin": "http://evil.example", "Host": "127.0.0.1:8765"}))
    check("[service] 同源校验：same-site 也拒（same-site 不分端口，防本机跨端口触发重算）",
          not _same_origin({"Sec-Fetch-Site": "same-site"}))
    check("[service] 同站校验：同站 Origin / 无头本机工具放行",
          _same_origin({"Origin": "http://127.0.0.1:8765", "Host": "127.0.0.1:8765"})
          and _same_origin({}))
    check("[service] 探活：关闭端口返回 False（未启动属正常）",
          service_alive(1) is False)     # 端口 1 不可 bind/connect，稳定关闭
    check("[service] ensure_started CI 护栏（CI 环境不拉进程）",
          os.environ.get("CI") is None or ensure_started() is None)
    print("[service] 自检" + ("全部通过 ✓" if ok else "存在失败 ✗"))
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# 自启（启动文件夹 .vbs：免管理员、隐藏窗口、删文件即卸载）
# ---------------------------------------------------------------------------

def _startup_dir():
    return os.path.join(os.environ.get("APPDATA", ""),
                        "Microsoft", "Windows", "Start Menu", "Programs", "Startup")


def register_startup(port):
    """注册开机自启（P30 三平台收敛在本函数）：
    Windows → 启动文件夹 OPC-Service.vbs（pythonw headless）；macOS/Linux →
    crontab `@reboot` 标记块（幂等，沿旧心跳口径）。返回人类可读的落点描述。"""
    if sys.platform.startswith("win"):
        pyw = (sys.executable or "python").replace("python.exe", "pythonw.exe")
        vbs = (f"' OPC service autostart -- delete this file to uninstall\r\n"
               f"CreateObject(\"WScript.Shell\").Run \"\"\"{pyw}\"\" "
               f"\"\"{os.path.abspath(__file__)}\" --port {port}\"\", 0, False\r\n")
        os.makedirs(_startup_dir(), exist_ok=True)
        p = os.path.join(_startup_dir(), STARTUP_VBS)
        with open(p, "w", encoding="utf-8") as f:
            f.write(vbs)
        return p
    # macOS / Linux：crontab 幂等标记块
    import shlex
    import subprocess
    py = sys.executable or "python3"
    mark = "# OPC-Service"
    line = (f"@reboot {shlex.quote(py)} {shlex.quote(os.path.abspath(__file__))} "
            f"--port {port}\n")
    try:
        cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout or ""
    except OSError as e:
        raise RuntimeError(f"crontab 不可用：{e}")
    out, skip = [], False
    for ln in cur.splitlines():          # 幂等：先移除旧标记块
        if ln.strip() == mark:
            skip = True
            continue
        if skip:
            skip = False
            continue
        out.append(ln)
    new = ("\n".join(out).rstrip("\n") + "\n" if any(out) else "") + f"{mark}\n{line}"
    r = subprocess.run(["crontab", "-"], input=new.encode("utf-8"), capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"crontab 写入失败：{(r.stderr or b'').decode(errors='replace')}")
    return f"crontab @reboot（标记 {mark}）"


def unregister_startup():
    if sys.platform.startswith("win"):
        p = os.path.join(_startup_dir(), STARTUP_VBS)
        if os.path.isfile(p):
            os.remove(p)
            return p
        return None
    import subprocess
    mark = "# OPC-Service"
    try:
        cur = subprocess.run(["crontab", "-l"], capture_output=True, text=True).stdout or ""
    except OSError:
        return None
    if mark not in cur:
        return None
    out, skip = [], False
    for ln in cur.splitlines():
        if ln.strip() == mark:
            skip = True
            continue
        if skip:
            skip = False
            continue
        out.append(ln)
    subprocess.run(["crontab", "-"], input=("\n".join(out) + "\n").encode("utf-8"),
                   capture_output=True)
    return f"crontab 标记 {mark}（已移除）"


def ensure_started(port=None, open_browser=False):
    """当场拉起服务（新 clone 零感知的关键：bootstrap 注册后立即生效，无需用户知道进程）。
    已在跑则跳过（幂等）；CI 环境跳过（临时环境不应留驻留进程）。返回启动命令 or None。"""
    if os.environ.get("CI"):
        return None
    if service_alive(port):
        return None
    import subprocess
    py = sys.executable or "python"
    args = [py, os.path.abspath(__file__)]
    if open_browser:
        args.append("--open")
    kw = dict(cwd=_ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
              stdin=subprocess.DEVNULL)
    if sys.platform.startswith("win"):
        pyw = py.replace("python.exe", "pythonw.exe")
        if os.path.isfile(pyw):
            args[0] = pyw
        kw["creationflags"] = 0x00000008 | 0x00000200   # DETACHED_PROCESS | NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    subprocess.Popen(args, **kw)
    return args


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main(argv=None):
    argv = sys.argv[1:] if argv is None else list(argv)
    if "--register" in argv or "--unregister" in argv:
        if "--unregister" in argv:
            p = unregister_startup()
            print(f"[service] 自启已撤销：{p}" if p else "[service] 本就未注册")
            return 0
        try:
            p = register_startup(_service_cfg()["port"])
            print(f"[service] 开机自启已注册：{p}")
            return 0
        except RuntimeError as e:
            print(f"[ERR] 自启注册失败：{e}")
            return 1
    if "--selftest" in argv:
        return selftest()

    cfg = _service_cfg()
    cids = opc_resolver.all_company_ids(opc_resolver._find_root())
    tenants = {}
    for cid in cids:
        try:
            tenants[cid.upper()] = Tenant(cid)
        except Exception as e:
            print(f"[service] 公司 {cid} 装载失败（跳过，不影响其他公司）：{e}")
    if not tenants:
        print("[service] 无公司可装载（opc.toml 为空？）")
        return 1
    default_cid = sorted(tenants)[0]

    # 端口探测（占用则 +1 顺延，最多 10 个）
    srv = None
    for port in range(int(cfg["port"]), int(cfg["port"]) + 10):
        try:
            srv = ThreadingHTTPServer(("127.0.0.1", port),
                                      make_handler(tenants, default_cid))
            break
        except OSError:
            continue
    if srv is None:
        print(f"[service] 端口 {cfg['port']}~{int(cfg['port']) + 9} 均被占用")
        return 1

    print(f"[service] OPC 服务 · 公司 {'/'.join(sorted(tenants))} · "
          f"http://127.0.0.1:{port}/{default_cid}/dashboard.html")
    print(f"[service] 巡检兜底每 {cfg['patrol_interval_minutes']} 分钟 · "
          f"每日摘要 {cfg['digest_time']} · 通知通道 {cfg['notify_channels']}")
    for t in tenants.values():
        t.regenerate("startup")
        t.patrol()
        threading.Thread(target=t._watch_loop, daemon=True).start()
        threading.Thread(target=t._patrol_loop,
                         args=(cfg["patrol_interval_minutes"],), daemon=True).start()
    threading.Thread(target=_digest_loop, args=(tenants,), daemon=True).start()
    if "--open" in argv:
        threading.Timer(0.5, lambda: webbrowser.open(
            f"http://127.0.0.1:{port}/{default_cid}/dashboard.html")).start()
    srv.serve_forever()
    return 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
