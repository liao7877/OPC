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

import opc_runtime
opc_runtime.ensure_supported()

import json
import hashlib
import ipaddress
from pathlib import Path
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
import opc_integration_bridge
import opc_model
import opc_projection
import opc_sync
import opc_patrol
import opc_resolver
import opc_tickets
import opc_privacy

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

def _iter_knowledge_dirs(company_dir):
    """公司内全部 knowledge/ 目录（公司级 + 员工/团队/项目级 + 建司骨架），供服务监听用。"""
    if not os.path.isdir(company_dir):
        return
    top = os.path.join(company_dir, "knowledge")
    if os.path.isdir(top):
        yield top
    for name in sorted(os.listdir(company_dir)):
        d = os.path.join(company_dir, name)
        if not os.path.isdir(d) or name.startswith("."):
            continue
        kb = os.path.join(d, "knowledge")
        if os.path.isdir(kb):
            yield kb
        if name == "templates":                      # 建司骨架（未分配实体 ID）
            for sub in sorted(os.listdir(d)):
                s = os.path.join(d, sub)
                if os.path.isdir(s) and os.path.isdir(os.path.join(s, "knowledge")):
                    yield os.path.join(s, "knowledge")


class Tenant:
    def __init__(self, cid):
        self.cid = cid
        self.pctx = opc_patrol.resolve_ctx(cid)                      # 巡检 ctx（base=公司根）
        self.tctx = opc_tickets.resolve_ctx(company=cid)             # 工单生成器 ctx
        self.dctx = opc_dashboards.resolve_ctx(company=cid)          # 驾驶舱生成器 ctx
        self.base = self.pctx.base
        self.gen_lock = threading.Lock()
        self.last_source_snapshot = None
        self.last_gen_epoch = 0.0
        self.last_findings = []      # 最近一轮巡检发现（/api/{cid}/patrol 用）
        self.last_error = ""         # 后台循环最近一次异常（/api/{cid}/ping 可查，防静默）
        self.last_integration_ok = True
        self.last_integration_error = ""

    # ---- 生成 + 巡检 ----

    def regenerate(self, why=""):
        """重算该公司双投影（单飞锁）；返回 (ok, errors)。"""
        with self.gen_lock, opc_model.generation_lock(self.base):
            # 进锁先置 + 完成后再置（2026-08-29 三轮体检）：生成全程对 watch 不可见——
            # 只在完成时置的话，生成期间 watch 采样到中间态 mtime 会排队再跑一遍全量重算
            self.last_gen_epoch = time.time()
            source_before = self._source_snapshot()
            errs = []
            # 组织结构是规范链的唯一真相：roster/团队变动被 watch 捕获后，
            # 先重建公司→团队→员工的直属声明，再生成看板；不要求 agent 另跑命令。
            try:
                _chain_actions, chain_issues = opc_resolver.sync_agent_chains(
                    self.pctx.cfg.root, cid=self.cid)
                errs.extend(f"agent-chain: {e}" for e in chain_issues)
            except Exception as e:
                errs.append(f"agent-chain: {e}")
            # External integrations are optional. Publish their connector-neutral shadow
            # before dashboard generation so this round can display the current state.
            try:
                self.sync_integrations()
            except Exception as e:
                self.last_integration_ok = False
                self.last_integration_error = str(e)
                self.last_error = f"{time.strftime('%m-%d %H:%M:%S')} integration: {e!r}"
            for name, fn, ctx in (("tickets", opc_tickets.generate, self.tctx),
                                  ("dashboards", opc_dashboards.generate_all, self.dctx)):
                try:
                    fn(ctx)
                except Exception as e:      # 单侧失败不阻断另一侧（沿 safe_generate 容错口径）
                    errs.append(f"{name}: {e}")
            # 知识库索引（决策 #19 §17.8）：条目一变动，INDEX.md 立即重生成——
            # agent 开工读到的永远是当前全貌，无需额外「感知变更」；差异另写 KB-CHANGELOG.md 给人看。
            try:
                opc_model.sync_kb_index(self.pctx.cfg.root, self.cid)
            except Exception as e:
                errs.append(f"kb-index: {e}")
            source_after = self._source_snapshot()
            if source_after != source_before:
                errs.append("source_changed_during_generation: pending retry")
            if not errs:
                try:
                    opc_projection.publish_legacy_snapshot(self.base, self.cid, install_loaders=False)
                except Exception as e:
                    errs.append(f"projection: {e}")
            self.last_gen_epoch = time.time()
            if not errs:
                self.last_source_snapshot = source_before
                if self.last_integration_ok:
                    self.last_error = ""
            else:
                self.last_error = "; ".join(errs)
            return (not errs), errs

    def sync_integrations(self):
        """Reconcile configured external bindings without blocking local OPC."""
        kernel = opc_sync.SyncKernel(self.base)
        opc_sync.register_configured_connectors(kernel)
        opc_integration_bridge.refresh_local_records(kernel, self.base)
        state = kernel.snapshot()
        results = kernel.reconcile() if state.get("bindings") else {}
        failed = [value for value in results.values() if isinstance(value, dict)
                  and value.get("status") in ("failed", "conflict")]
        self.last_integration_ok = not failed
        self.last_integration_error = "; ".join(str(value.get("message") or value.get("error_class") or value.get("status")) for value in failed)
        if failed:
            self.last_error = "integration: " + self.last_integration_error
        kernel.write_projection(os.path.join(self.base, ".opc-sync", "projection.json"))
        return results

    def patrol(self, quiet=True):
        """单轮巡检（数据自愈+发现+去重+实时通知由 opc_patrol.run_once 一体完成）。"""
        ctx, _fresh = opc_patrol.run_once(self.cid, quiet=quiet)
        self.last_findings = list(ctx.findings)
        return self.last_findings

    def _source_snapshot(self):
        records = []
        skip_dirs = {".git", ".workbuddy", ".opc-data", ".opc-sync", "node_modules",
                     "_AI工作区", "OpenMAIC", "memory"}
        skip_files = {"INDEX.md", "KB-CHANGELOG.md", "patrol-log.md", "patrol-pending.md",
                      "AGENTS.md", "CLAUDE.md"}
        for directory, dirs, files in os.walk(self.base):
            dirs[:] = [d for d in dirs if d not in skip_dirs and not os.path.islink(os.path.join(directory, d))]
            for name in sorted(files):
                rel = os.path.relpath(os.path.join(directory, name), self.base).replace(os.sep, "/")
                if name in skip_files or name.endswith((".lock", ".tmp", "-data.js")):
                    continue
                if not (name.endswith((".md", ".toml")) or rel.startswith("page-templates/")):
                    continue
                try:
                    path = Path(directory) / name
                    records.append((rel, hashlib.sha256(path.read_bytes()).hexdigest()))
                except FileNotFoundError:
                    records.append((rel, "deleted-during-scan"))
        manifest = Path(self.pctx.cfg.root) / "opc.toml"
        if manifest.is_file():
            records.append(("@manifest", hashlib.sha256(manifest.read_bytes()).hexdigest()))
        return tuple(sorted(records))

    def _watch_once(self):
        current = self._source_snapshot()
        if current == self.last_source_snapshot or self.gen_lock.locked():
            return False
        ok, _errors = self.regenerate("watch")
        if ok:
            self._patrol_async()
        return ok

    def _patrol_async(self):
        """watch 触发的巡检异步化：巡检要拿跨进程锁（patrol-state.json.lock），
        异常环境（沙箱拦 unlink / 持有者卡死）下锁等待会把串行调用拖满超时——
        2026-08-30 双机排查：watch 串行跑 patrol，锁超时把整个监听循环冻死。
        放独立线程后巡检再卡也只拖慢巡检自己，「数据变动即巡检」的时效保留
        （决策 #18 不弱化）；兜底仍有 _patrol_loop 周期线程。"""
        def _run():
            try:
                self.patrol()
            except Exception as e:
                self.last_error = f"{time.strftime('%m-%d %H:%M:%S')} patrol: {e!r}"
        threading.Thread(target=_run, daemon=True).start()

    def _watch_loop(self):
        while True:
            time.sleep(POLL_SECONDS)
            try:
                self._watch_once()
            except Exception as e:
                self.last_error = f"{time.strftime('%m-%d %H:%M:%S')} watch: {e!r}"

    def _periodic_once(self):
        ok, errors = self.regenerate("periodic")
        self.patrol()
        return ok, errors

    def _patrol_loop(self, interval_minutes):
        while True:
            time.sleep(max(1, int(interval_minutes)) * 60)
            try:
                self._periodic_once()
            except Exception as e:
                self.last_error = f"{time.strftime('%m-%d %H:%M:%S')} periodic: {e!r}"

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
        parsed = urllib.parse.urlparse(origin)
        return parsed.scheme == "http" and parsed.netloc == (headers.get("Host") or "")
    return headers.get("Sec-Fetch-Site") in (None, "same-origin", "none")


def _allowed_host(value, port):
    try:
        parsed = urllib.parse.urlsplit("http://" + (value or ""))
        return (parsed.hostname in ("127.0.0.1", "localhost", "::1")
                and parsed.port == port and not parsed.username and not parsed.password
                and not parsed.path and not parsed.query and not parsed.fragment)
    except ValueError:
        return False

def _static_allowed(tenant, rest):
    parts = rest.strip("/").split("/")
    if not parts or any(p in ("", ".", "..") for p in parts):
        return False
    if opc_privacy.private_path(rest):
        return False
    rel = "/".join(parts)
    if rel in ("dashboard.html", "dashboard-data.js", "workbench/kanban.html",
               "workbench/tasks-data.js", "workbench/tasks-data.json"):
        return True
    if len(parts) == 2 and parts[1] in ("mydesk.html", "mydesk-data.js", "teamboard.html", "teamboard-data.js"):
        kinds = opc_resolver.entity_types()
        prefix = kinds["employee"] if parts[1].startswith("mydesk") else kinds["team"]
        return bool(re.fullmatch(re.escape(prefix) + r"\d{3,}(?:-.+)?", parts[0]))
    return False

def make_handler(tenants, default_cid):
    from http.server import SimpleHTTPRequestHandler

    class H(SimpleHTTPRequestHandler):
        def parse_request(self):
            if not super().parse_request():
                return False
            if not _allowed_host(self.headers.get("Host"), self.server.server_port):
                self.send_error(403, "Untrusted Host")
                return False
            return True

        def list_directory(self, path):
            self.send_error(403, "Directory listing disabled")
            return None

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
            if not _static_allowed(tenant, rest):
                return os.path.join(tenant.base, "__opc_static_denied__")
            if rest.endswith(("-data.js", "tasks-data.json")):
                try:
                    pointer = opc_projection.read_current(tenant.base)
                    rel = pointer["artifacts"][rest.strip("/")]
                    data_root = Path(tenant.base) / ".opc-data"
                    return _safe_join(str(data_root), pointer["base"] + rel)
                except (OSError, ValueError, KeyError):
                    return os.path.join(tenant.base, "__opc_projection_unavailable__")
            return _safe_join(tenant.base, rest)

        def _json(self, obj, code=200, headers=None):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            for name, value in (headers or {}).items():
                self.send_header(name, value)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self._cc_done = True
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _redirect(self, loc):
            self.send_response(302)
            self.send_header("Location", loc)
            self.send_header("Content-Length", "0")
            self._cc_done = True
            self.end_headers()

        def end_headers(self):
            # 静态产物禁启发式缓存：SimpleHTTPRequestHandler 只发 Last-Modified，
            # 浏览器按「距修改时间的 10%」启发式缓存陈旧看板——/sync 重算后刷新
            # 仍可能整段不回源，被误判为「同步无效」。API 已自带 no-store 不重发。
            if not getattr(self, "_cc_done", False):
                self._cc_done = True
                self.send_header("Cache-Control", "no-cache")
            super().end_headers()

        # ---- 动词 ----

        def do_GET(self):
            p = urllib.parse.urlparse(self.path).path
            if p in ("/", ""):
                return self._redirect(f"/{default_cid}/dashboard.html")
            if p == "/api/ping":
                return self._json({"ok": True, "service": "opc-service",
                                   "root": _ROOT, "pid": os.getpid(),   # 根身份：多份 clone 排查（doctor 用）
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
                                   "last_error": t.last_error or None,
                                   "integration_ok": t.last_integration_ok,
                                   "integration_error": t.last_integration_error or None})
            if sub == "/sync":
                return self._json({"ok": False, "error": "/sync 只收 POST（GET 已退役，防跨站滥用）"}, 405)
            if sub in ("/tickets", "/dashboard"):
                legacy = "tasks-data.json" if sub == "/tickets" else "dashboard-data.js"
                try:
                    payload, pointer = opc_projection.load_current_artifact(t.base, legacy)
                    return self._json(payload, headers={"X-OPC-Batch-ID": pointer["batch_id"],
                                                        "ETag": '"' + pointer["batch_id"] + '"'})
                except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
                    return self._json({"ok": False, "error": "projection_unavailable", "detail": str(exc)}, 503)
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
            self._json({"ok": ok, "partial": ok and not t.last_integration_ok,
                        "integration_ok": t.last_integration_ok,
                        "integration_error": t.last_integration_error or None,
                        "company": t.cid,
                        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                        "patrol_findings": len(findings), "errors": errs},
                       200 if ok else 500)

    return H


# ---------------------------------------------------------------------------
# 探活 / 自检
# ---------------------------------------------------------------------------

def service_probe(port=None):
    """探活并取回服务身份：返回 (port, payload)——payload 含 root/pid，可判断
    端口上的服务是不是在伺服「本份」OPC 根。机器上可能同时存在多份 clone 的
    服务（目录搬家/旧 clone 残留自启项），只测 TCP 或只看「有响应」会把别人家
    的服务误当自己的——看板不同步的典型根因（2026-08-30 排查收口）。"""
    import urllib.request
    base = int(_service_cfg()["port"])
    ports = [port] if port else list(range(base, base + 10))
    for p in ports:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{p}/api/ping", timeout=0.5) as r:
                body = json.loads((r.read() or b"{}").decode("utf-8", errors="replace"))
            if body.get("service") == "opc-service":
                return p, body
        except Exception:
            continue
    return None, None


def service_alive(port=None):
    """布尔口径探活（兼容旧调用）；需要身份判断时用 service_probe。"""
    return service_probe(port)[0] is not None


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
    return os.path.join(os.environ.get("APPDATA", ""), "Microsoft", "Windows", "Start Menu", "Programs", "Startup")

def _launch_agent_path():
    return Path.home() / "Library" / "LaunchAgents" / "org.opc.service.plist"

def _startup_command():
    from opc_runtime import supported_python
    return [supported_python(), os.path.abspath(__file__)]

def _system_run(command, **kwargs):
    import subprocess
    try:
        return subprocess.run(command, capture_output=True, timeout=10, **kwargs)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"自启系统命令失败或超时：{command[0]}：{exc}") from exc

def startup_script_stale():
    here = os.path.abspath(__file__)
    if sys.platform == "darwin":
        import plistlib
        path = _launch_agent_path()
        if not path.exists():
            return False, "LaunchAgent 未注册"
        try:
            data = plistlib.loads(path.read_bytes())
            expected = _startup_command()
            return data.get("ProgramArguments", [])[:2] != expected, "LaunchAgent 路径或解释器陈旧"
        except (OSError, ValueError):
            return True, "LaunchAgent 内容无效"
    if sys.platform.startswith("win"):
        path = Path(_startup_dir()) / STARTUP_VBS
        if not path.exists():
            return False, "未注册"
        return here not in path.read_text(encoding="utf-8"), "VBS 路径陈旧"
    result = _system_run(["crontab", "-l"], text=True)
    lines = [line for line in result.stdout.splitlines() if line.startswith("@reboot") and "opc_service.py" in line]
    return (bool(lines) and not any(here in line for line in lines)), "crontab 路径状态"

def _cron_update(current, command=None):
    marker = "# OPC-Service"
    out, skip = [], False
    for line in current.splitlines():
        if line.strip() == marker:
            skip = True
            continue
        if skip:
            skip = False
            continue
        out.append(line)
    if command:
        out.extend([marker, command])
    return "\n".join(out).rstrip() + "\n"

def register_startup(port):
    command = _startup_command() + ["--port", str(port)]
    if sys.platform == "darwin":
        import plistlib
        path = _launch_agent_path()
        logs = Path(_ROOT) / "_AI工作区" / "运行日志"
        logs.mkdir(parents=True, exist_ok=True)
        data = {"Label": "org.opc.service", "ProgramArguments": command,
                "WorkingDirectory": _ROOT, "RunAtLoad": True,
                "KeepAlive": {"SuccessfulExit": False}, "ThrottleInterval": 10,
                "StandardOutPath": str(logs / "service.stdout.log"),
                "StandardErrorPath": str(logs / "service.stderr.log")}
        path.parent.mkdir(parents=True, exist_ok=True)
        content = plistlib.dumps(data).decode("utf-8")
        changed = not path.exists() or path.read_text(encoding="utf-8") != content
        if changed:
            opc_model.atomic_write(path, content)
        if not os.environ.get("CI"):
            target = f"gui/{os.getuid()}/org.opc.service"
            state = _system_run(["launchctl", "print", target], text=True)
            if changed and state.returncode == 0:
                _system_run(["launchctl", "bootout", target], text=True)
                state = None
            if state is None or state.returncode != 0:
                loaded = _system_run(["launchctl", "bootstrap", f"gui/{os.getuid()}", str(path)], text=True)
                if loaded.returncode:
                    raise RuntimeError(f"LaunchAgent 已保存但加载失败：{loaded.stderr.strip()}")
        return str(path)
    if sys.platform.startswith("win"):
        import subprocess
        py = command[0]
        pyw = str(Path(py).with_name("pythonw.exe"))
        if Path(pyw).exists():
            command[0] = pyw
        quoted = subprocess.list2cmdline(command).replace('"', '""')
        content = "' OPC service autostart\r\n" + 'CreateObject("WScript.Shell").Run "' + quoted + '", 0, False\r\n'
        path = Path(_startup_dir()) / STARTUP_VBS
        path.parent.mkdir(parents=True, exist_ok=True)
        opc_model.atomic_write(path, content)
        return str(path)
    import shlex
    current = _system_run(["crontab", "-l"], text=True)
    if current.returncode and (current.returncode != 1 or "no crontab" not in current.stderr.lower()):
        raise RuntimeError("无法可靠读取现有 crontab，拒绝覆盖：" + current.stderr.strip())
    new = _cron_update(current.stdout, "@reboot " + " ".join(shlex.quote(v) for v in command))
    written = _system_run(["crontab", "-"], input=new, text=True)
    if written.returncode:
        raise RuntimeError("crontab 写入失败：" + written.stderr.strip())
    return "crontab @reboot (# OPC-Service)"

def unregister_startup():
    if sys.platform == "darwin":
        path = _launch_agent_path()
        if not path.exists():
            return None
        if not os.environ.get("CI"):
            _system_run(["launchctl", "bootout", f"gui/{os.getuid()}/org.opc.service"], text=True)
        path.unlink()
        return str(path)
    if sys.platform.startswith("win"):
        path = Path(_startup_dir()) / STARTUP_VBS
        if path.exists():
            path.unlink()
            return str(path)
        return None
    current = _system_run(["crontab", "-l"], text=True)
    if current.returncode and "no crontab" not in current.stderr.lower():
        raise RuntimeError("无法可靠读取现有 crontab，拒绝删除")
    if "# OPC-Service" not in current.stdout:
        return None
    result = _system_run(["crontab", "-"], input=_cron_update(current.stdout), text=True)
    if result.returncode:
        raise RuntimeError("crontab 删除失败：" + result.stderr.strip())
    return "crontab OPC-Service removed"


def ensure_started(port=None, open_browser=False):
    """当场拉起服务（新 clone 零感知的关键：bootstrap 注册后立即生效，无需用户知道进程）。
    已在跑则跳过（幂等）；CI 环境跳过（临时环境不应留驻留进程）。返回启动命令 or None。
    端口上有**伺服别的 OPC 根**的服务（目录搬家/多 clone 残留）时明确告警——
    这种情况下看板/巡检永远看不到本根的数据变化，静默跳过会让用户误判「同步坏了」。"""
    if os.environ.get("CI"):
        return None
    p, body = service_probe(port)
    if p is not None:
        svc_root = (body or {}).get("root") or "(旧版本服务，无 root 字段)"
        if os.path.normcase(os.path.realpath(svc_root)) != os.path.normcase(os.path.realpath(_ROOT)):
            print(f"[service] ⚠️ 端口 {p} 上已有一个 opc 服务，但它伺服的是别的 OPC 根：{svc_root}")
            print(f"[service] ⚠️ 本根（{_ROOT}）的看板/巡检不会更新！处置：杀掉旧进程"
                  f"（Windows: taskkill /PID {(body or {}).get('pid')} /F）后重跑本次命令；"
                  f"并检查启动文件夹自启项是否指向旧目录")
            raise RuntimeError("已有服务属于其他 OPC 根，请先处理端口冲突")
        return None
    # Give the registered supervisor first ownership of the singleton process.
    if sys.platform == "darwin" and _launch_agent_path().exists():
        target = f"gui/{os.getuid()}/org.opc.service"
        state = _system_run(["launchctl", "print", target], text=True)
        if state.returncode == 0:
            _system_run(["launchctl", "kickstart", target], text=True)
            for _ in range(30):
                time.sleep(0.2)
                found, body = service_probe(port)
                if found and os.path.realpath((body or {}).get("root", "")) == os.path.realpath(_ROOT):
                    return ["launchctl", "kickstart", target]
            raise RuntimeError("launchd 服务未通过身份探活，请检查运行日志")
    import subprocess
    args = _startup_command()
    py = args[0]
    if port is not None:
        args.extend(["--port", str(port)])
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
    child = subprocess.Popen(args, **kw)
    for _ in range(30):
        time.sleep(0.2)
        found, body = service_probe(port)
        if found and os.path.realpath((body or {}).get("root", "")) == os.path.realpath(_ROOT):
            return args
        if child.poll() not in (None, 0):
            raise RuntimeError(f"OPC 服务启动后退出：{child.returncode}")
    raise RuntimeError("OPC 服务尚未通过身份探活；请检查运行日志")


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

    lock_path = Path(_ROOT) / "_AI工作区" / "运行日志" / "service-instance"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    from contextlib import ExitStack
    with ExitStack() as stack:
        try:
            stack.enter_context(opc_model.file_lock(lock_path, timeout=0.2))
        except TimeoutError:
            print("[service] 本仓库已有服务实例正在运行或启动")
            return 0
        return _serve(argv)


def _serve(argv):
    cfg = _service_cfg()
    if "--port" in argv:
        cfg["port"] = int(argv[argv.index("--port") + 1])
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
        _ok, errs = t.regenerate("startup")
        if errs:
            t.last_error = "; ".join(errs)   # 启动失败别静默（pythonw 无控制台，/ping 可查）
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
    opc_runtime.configure_output()
    sys.exit(main())
