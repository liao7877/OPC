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

import opc_runtime
opc_runtime.ensure_supported()
import argparse
import datetime
import hashlib
import json
import locale
import os
import re
import secrets
import sys
import threading
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


def strip_inline_comment(value):
    """截内联注释：（...）或 (...) 之后不算值——允许「ID：xxx（说明）」行带说明
    文字而不破坏解析。唯一实现在此（P25：消灭口径漂移），resolver 与本模块共用。"""
    return str(value).split("（")[0].split("(")[0].strip()


def extract_id(text, fm_key="id", prose_pat=r"ID[：:]\s*(\S+)"):
    """实体 ID 提取：优先 frontmatter 的 fm_key（如 id），回退散文「XX ID：...」。
    兼容 P0001（散文）与 P0002/P0003（frontmatter）两种注册格式，不强制单一写法。
    散文兜底与 resolver.extract_company_id 同样截内联注释（strip_inline_comment）。"""
    fm, _, _ = parse_frontmatter(text)
    if fm.get(fm_key):
        return fm[fm_key].strip()
    m = re.search(prose_pat, text)
    return strip_inline_comment(m.group(1)) if m else None


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
    try:
        datetime.date(int(y), int(mo), int(d))
        if h is not None:
            datetime.time(int(h), int(mi), int(se or 0))
    except ValueError:
        return None
    base = "%04d-%02d-%02d" % (int(y), int(mo), int(d))
    if h is not None:
        base += " %02d:%02d" % (int(h), int(mi))
        if se:
            base += ":%02d" % int(se)
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
    """P12 原子写：临时文件落盘后替换目标，失败时清理临时文件。"""
    tmp = f"{path}.{os.getpid()}.{time.time_ns()}.tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    finally:
        try:
            if os.path.exists(tmp):
                os.unlink(tmp)
        except OSError:
            pass


# ---- 并发互斥（2026-08-29 拍板：锁原语落地；原子写只防「写一半被读」，防不了「后写覆盖先写」）----

LOCK_STALE_SECONDS = 30.0   # 仅用于无效/不可探测持有者的残留兜底
LOCK_HEARTBEAT_SECONDS = 5.0


def _pid_alive(pid):
    """锁持有者进程存活判定（file_lock 抢占用）。
    Windows 刻意不用 os.kill(pid, 0)：≤3.12 对任意非 CTRL 信号直接 TerminateProcess
    （探测=误杀）；3.13 改为探测，但对「已退出而句柄未关」的进程不抛异常（死误判活）。
    一律走 OpenProcess(SYNCHRONIZE)+WaitForSingleObject：终止进程内核对象必然已
    signaled，判定无歧义。POSIX 用信号 0 惯例。"""
    if not isinstance(pid, int) or pid <= 0:
        return False
    if sys.platform == "win32":
        import ctypes
        SYNCHRONIZE = 0x00100000
        WAIT_OBJECT_0 = 0
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(SYNCHRONIZE, False, pid)
        if not h:
            return False            # 打不开 = 进程不存在（无权限场景由 30s 过期兜底）
        try:
            # WAIT_OBJECT_0=进程已终止（signaled）；WAIT_TIMEOUT=仍在运行 → 活
            return k32.WaitForSingleObject(h, 0) != WAIT_OBJECT_0
        finally:
            k32.CloseHandle(h)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True                 # 进程存在但无权发信号 = 活着
    except OSError:
        return False


def _write_lock_heartbeat(lock_path, token):
    current = _read_lock(lock_path)
    if current.get("token") != token:
        return False
    current["heartbeat"] = time.time()
    try:
        atomic_write(lock_path, json.dumps(current))
        return True
    except OSError:
        return False


def _read_lock(lock_path):
    try:
        with open(lock_path, encoding="utf-8") as fh:
            raw = fh.read().strip()
        if raw.startswith("{"):
            import json
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}
        return {"pid": int(raw), "token": "legacy"}
    except (OSError, ValueError, TypeError):
        return {}


def _break_lock(lock_path, token=None):
    """抢占/清理锁文件：优先 rename 旁路——部分沙箱（safe-delete fail-closed）与
    Windows 文件占用会让 os.unlink 失败，rename 不触发删除语义通常仍可用；
    挪走后的孤儿文件再尽力删，删不掉也无害（名字已不带锁语义）。"""
    if token is not None:
        current = _read_lock(lock_path)
        if current.get("token") != token:
            return False
    trash = f"{lock_path}.stolen.{os.getpid()}.{time.time_ns()}"
    try:
        os.rename(lock_path, trash)
    except OSError:
        try:
            os.unlink(lock_path)
        except OSError:
            return False
        return True
    try:
        os.unlink(trash)
    except OSError:
        pass
    return True


@contextmanager
def file_lock(path, timeout=10.0, poll=0.05):
    """跨平台建议锁（纯标准库）：O_EXCL 锁文件 + 忙等超时 + 三重自愈抢占。
    用法：`with file_lock(target_path):` 锁文件为 target+".lock"，内容=持有者 PID。
    约束：只约束「同样走本锁」的写方（机制层全部走；agent 侧用 --append 命令）；
    锁内写必须经 atomic_write 落盘，临界区保持极短。
    抢占口径（2026-08-30 双机排查收口）：① mtime 超 30s（崩溃/卡死残留）；
    ② 锁内 PID 已失活（持有者早退了没清理）——②不依赖时间，孤儿锁立即可抢；
    抢占与释放均走 _break_lock（rename 旁路），沙箱拦 unlink 的环境不再永久死锁。"""
    lock_path = str(path) + ".lock"
    deadline = time.monotonic() + timeout
    token = secrets.token_hex(16)
    acquired = False
    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            payload = {"pid": os.getpid(), "token": token,
                       "acquired_at": time.time(), "heartbeat": time.time()}
            os.write(fd, json.dumps(payload).encode())
            os.fsync(fd)
            break
        except FileExistsError:
            holder = _read_lock(lock_path)
            holder_pid = holder.get("pid")
            # 空/半写锁是创建窗口，等待而不是抢占。
            holder_dead = bool(holder_pid) and not _pid_alive(int(holder_pid))
            heartbeat = holder.get("heartbeat")
            try:
                stale = time.time() - float(heartbeat) > LOCK_STALE_SECONDS
            except (TypeError, ValueError):
                try:
                    stale = time.time() - os.path.getmtime(lock_path) > LOCK_STALE_SECONDS
                except OSError:
                    stale = False
            # 有 PID 的锁只有在持有者已死亡时抢占；旧格式/空锁仅在长期残留时兜底回收。
            if (holder_dead or (stale and not holder_pid)) and _break_lock(lock_path, token=holder.get("token")):
                continue
            if time.monotonic() >= deadline:
                raise TimeoutError(f"获取锁超时（{timeout}s）：{lock_path}（他人持有且未过期）")
            time.sleep(poll)
    acquired = True
    stop_heartbeat = threading.Event()
    def _heartbeat_loop():
        while not stop_heartbeat.wait(LOCK_HEARTBEAT_SECONDS):
            _write_lock_heartbeat(lock_path, token)
    heartbeat_thread = threading.Thread(target=_heartbeat_loop, daemon=True)
    heartbeat_thread.start()
    try:
        yield
    finally:
        stop_heartbeat.set()
        heartbeat_thread.join(timeout=LOCK_HEARTBEAT_SECONDS + 1)
        os.close(fd)
        if acquired:
            _break_lock(lock_path, token=token)


_generation_state = threading.local()

@contextmanager
def generation_lock(company):
    key = str(Path(company).resolve())
    held = getattr(_generation_state, "held", set())
    if key in held:
        yield
        return
    lock = Path(company) / ".opc-data" / "generation"
    lock.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(lock, timeout=60):
        _generation_state.held = held | {key}
        try:
            yield
        finally:
            _generation_state.held = held

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


# ---- worklog 门禁追加（2026-08-31 双告警的治本层）----
# 两类坏数据都产生于「agent 手工拼块 + 裸追加」：wid 凭感觉编号（两个会话同编
# -001，后者在看板覆盖前者）与实体卡占位符惯例（ticket: -）带进 worklog（A2 校验
# 把 "-" 当已填）。门禁让正确写法成为唯一走得通的写法，而不是靠会话自觉；
# 漏网的（手改文件等写路径）由 opc_dashboards 校验 + opc_patrol 17 号兜底发现。

WORKLOG_TYPES = ("工单", "直聊", "事务", "自由")
WORKLOG_LEGACY_TYPES = ("机制", "运维")  # 历史条目兼容；新条目优先使用四类规范枚举


def unplaceholder(v):
    """实体卡惯例的「不适用」占位符（- / — / –）在 worklog 数值字段里视同留空。
    单一真相在 opc_model（dashboards 共享导入，P25 同款收敛）。"""
    v = str(v or "").strip()
    return "" if v in ("-", "—", "–") else v


def _wids_in_text(text):
    return {m.group(1).strip() for m in re.finditer(r"^wid:\s*(\S.*)$", text, re.M)}


def worklog_workspace(target):
    target = str(target)
    target_dir = os.path.dirname(target)
    if re.match(r"^worklog-\d{4}\.md$", os.path.basename(target)):
        return os.path.dirname(target_dir)
    return target_dir


def locked_worklog_update(path, transform):
    """在员工 workspace 级锁内执行 worklog 读改写。"""
    path = str(path)
    with file_lock(os.path.join(worklog_workspace(path), ".worklog")):
        existing = _read(Path(path))
        atomic_write(path, transform(existing))


def worklog_wid_pool(target, existing):
    """撞号判定 / 序号分配的数据面：持锁快照 existing + 热/归档目录全量 wid。
    归档文件追加时也必须看到热文件和全部归档；归档是只增不改的冷数据，锁外读安全。"""
    target = str(target)
    target_dir = os.path.dirname(target)
    if re.match(r"^worklog-\d{4}\.md$", os.path.basename(target)):
        workspace = os.path.dirname(target_dir)
    else:
        workspace = target_dir
    pool = _wids_in_text(existing)
    hot = os.path.join(workspace, "worklog.md")
    if os.path.normcase(hot) != os.path.normcase(target) and os.path.isfile(hot):
        try:
            pool |= _wids_in_text(Path(hot).read_text(encoding="utf-8"))
        except OSError:
            pass
    arch = os.path.join(workspace, "worklog-archive")
    if os.path.isdir(arch):
        for name in sorted(os.listdir(arch)):
            if re.match(r"^worklog-\d{4}\.md$", name):
                path = os.path.join(arch, name)
                if os.path.normcase(path) == os.path.normcase(target):
                    continue
                try:
                    pool |= _wids_in_text(Path(path).read_text(encoding="utf-8"))
                except OSError:
                    pass
    return pool


def worklog_gate(content, wid_pool, today=None):
    """worklog 条目块门禁（纯函数，selftest 直测；文件/锁层见 main 的 --append 分支）。

    逐块校验 title/status/type/date，规整占位符；wid 缺省自动分配（当天已有最大
    序号+1），显式 wid 撞号拒收；A2 规则：工单型缺 ticket 拒收、非工单条目 ticket
    （含 "-" 占位）强制清空。返回 (规整后内容, notes)；违规 raise ValueError。
    非条目块（首行非 ---，如归档指针注释）原样放行——worklog 允许非条目内容。"""
    from opc_schema import WORKLOG_STATUS   # 状态机唯一真相源（惰性导入防顶层环）
    today = today or time.strftime("%Y-%m-%d")
    lines = content.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines or lines[0].strip() != "---":
        return content, []          # 非条目内容：不拦
    notes, out, pool = [], [], set(wid_pool)
    i, n = 0, len(lines)
    while i < n:
        # worklog 家规：闭合 --- 之后到下一个 --- 之间是该条目的正文（## 小节等），
        # 与生成器 split_blocks 同一口径；正文里再出现 --- 即视为下一条目开头。
        j = i + 1
        while j < n and lines[j].strip() != "---":
            j += 1
        if j >= n:
            raise ValueError("条目块缺闭合 ---（第 %d 行起）" % (i + 1))
        k = j + 1
        while k < n and lines[k].strip() != "---":
            k += 1
        fm, body, _ = parse_frontmatter("---\n" + "\n".join(lines[i + 1:j]) + "\n---")
        title = unplaceholder(fm.get("title"))
        if not title:
            raise ValueError("条目缺 title（必填，动词开头一句话说清做了什么）")
        status = unplaceholder(fm.get("status"))
        if status not in WORKLOG_STATUS:
            raise ValueError("status 非法：%r（只允许 %s）" % (status, "/".join(sorted(WORKLOG_STATUS))))
        typ = unplaceholder(fm.get("type")) or "自由"   # 与生成器同口径：缺省按自由
        if typ not in WORKLOG_TYPES and typ not in WORKLOG_LEGACY_TYPES:
            raise ValueError("type 非法：%r（新条目只允许 %s；历史兼容 %s）" %
                             (typ, "/".join(WORKLOG_TYPES), "/".join(WORKLOG_LEGACY_TYPES)))
        raw_date = unplaceholder(fm.get("date"))
        date = normalize_day(raw_date) if raw_date else today
        if raw_date and not date:
            raise ValueError("date 非法：%r（要 YYYY-MM-DD）" % raw_date)
        wid = unplaceholder(fm.get("wid"))
        if wid and not re.match(r"^W-\d{8}-\d+$", wid):
            raise ValueError("wid 格式非法：%r（必须 W-YYYYMMDD-序号；不填则自动分配）" % wid)
        if wid and wid[2:10] != date.replace("-", ""):
            raise ValueError("wid 日期与 date 不一致：%s / %s" % (wid, date))
        if not wid:
            prefix = "W-" + date.replace("-", "")   # 家规：W-YYYYMMDD-序号（紧凑日期）
            mx = max((int(m.group(1)) for w in pool
                      for m in [re.match(r"^%s-(\d+)$" % re.escape(prefix), w)] if m),
                     default=0)
            wid = "%s-%03d" % (prefix, mx + 1)
            notes.append("wid 自动分配为 %s（当天已有最大序号+1）" % wid)
        elif wid in pool:
            raise ValueError("wid 撞号：%s 已存在（热文件/归档范围）——别手工编号，"
                             "删掉 wid 让门禁按「当天最大+1」自动分配" % wid)
        pool.add(wid)
        ticket = unplaceholder(fm.get("ticket"))
        if typ == "工单" and not ticket:
            raise ValueError("工单型条目缺 ticket（A2 规则）——填 TSKxxxxx 或把 type 改对")
        if typ != "工单" and ticket:
            notes.append("非工单型条目已按 A2 规则清空 ticket（原值 %r）——"
                         "不填就留空，禁用 - 占位（校验器会把 - 当已填）" % ticket)
            ticket = ""
        canonical = {
            "wid": wid, "date": date, "title": title, "status": status, "type": typ,
            "ticket": ticket, "aff": unplaceholder(fm.get("aff")),
            "project": unplaceholder(fm.get("project")),
            "deliverable": unplaceholder(fm.get("deliverable")),
            "updated": normalize_day(unplaceholder(fm.get("updated"))) or date,
            "note": unplaceholder(fm.get("note")),
        }
        fm_lines = ["%s: %s" % (k, canonical[k]) for k in canonical]
        fm_lines += ["%s: %s" % (k, fm[k]) for k in fm           # 门禁不认识的扩展键原样保留
                     if k not in canonical and fm[k] not in (None, "")]
        # worklog 家规：闭合 --- 之后到下一个 --- 之间是该条目的正文（## 小节等），
        # 必须原样带回——parse_frontmatter 只喂了字段行，body 恒空，正文取原文切片。
        body_text = "\n".join(lines[j + 1:k]).strip()
        block = "---\n" + "\n".join(fm_lines) + "\n---"
        if body_text:
            block += "\n" + body_text
        out.append(block)
        i = k
    return "\n".join(out) + "\n", notes


def parse_company_args(argv):
    """--company / --dir 参数提取（生成器 CLI 共用，D 收敛）：取值缺失友好报错，不裸栈。"""
    vals = {}
    for flag in ("--company", "--dir"):
        if flag in argv:
            i = argv.index(flag)
            if i + 1 >= len(argv):
                raise SystemExit(f"[ERR] 参数 {flag} 缺少取值（示例：{flag} C001）")
            vals[flag] = argv[i + 1]
    return vals.get("--company"), vals.get("--dir")


def _unquote_path(s):
    """剥掉包在路径外的一层成对引号：cmd 桥接（MSYS→cmd / 各类 agent shell）
    会把引号原样带进 argv（实测 '"E:\\OPC\\中文\\x.txt"' 逐字符进 Python），
    os.path.exists 必然 False——中文路径因惯例被引号包裹而高频中招。
    含引号的合法文件名不受影响：只剥「首尾恰好成对」的一层。"""
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1]
    return s


def _decode_input(data):
    """字节流 → 文本：UTF-8 优先、UTF-16、本机编码兜底。Windows 管道下 sys.stdin
    默认走 ANSI 代码页（cp936/cp1252），而 agent/heredoc 喂进来的几乎总是 UTF-8——
    按 locale 解会把中文读成乱码甚至异常，故从 buffer 拿字节自己解码。"""
    for enc in ("utf-8", "utf-16", locale.getpreferredencoding(False)):
        try:
            return data.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return data.decode("utf-8", errors="replace")


def _read_stdin_text():
    return _decode_input(sys.stdin.buffer.read())


def build_indexes(company_root):
    """发现并索引公司内实体（task/project/team/employee），返回 dict。
    实体目录前缀唯一真相在 opc.toml [entity_types]（P25：消费注册表，不私写正则）。"""
    import opc_resolver    # 延迟导入（本模块零耦合 manifest 的口径不变；仅此一处按需取注册表）
    etypes = opc_resolver.entity_types()
    kind_of = {v: k for k, v in etypes.items()}          # 前缀 -> 类型
    emp_pfx = etypes.get("employee", "E")
    card_map = {"project": ("project.md", r"项目\s*ID[：:]\s*(\S+)"),
                "team": ("team.md", r"团队\s*ID[：:]\s*(\S+)")}
    root = Path(company_root)
    tasks, projects, teams, employees = {}, {}, {}, {}
    for tm in root.glob("workbench/tasks/*/task.md"):
        fm, _, _ = parse_frontmatter(_read(tm))
        tid = fm.get("id")
        if tid:
            tasks[tid] = {"fm": fm, "path": str(tm)}
    for d in root.iterdir():
        if not d.is_dir():
            continue
        kind = next((k for p, k in kind_of.items() if re.match(rf"^{p}\d+", d.name)), None)
        if kind not in card_map:
            continue
        card, prose_pat = card_map[kind]
        pm = d / card
        if pm.is_file():
            pid = extract_id(_read(pm), "id", prose_pat)
            if pid:
                (projects if kind == "project" else teams)[pid] = {"path": str(pm)}
    # roster 位置真相源在 opc.toml [company.*].roster（本读取器保持零耦合不读 manifest），
    # 此处按约定发现：E0000 目录（决策 #17 ID-only 命名）优先，E0000-* 遗留带名兜底。
    roster = root / f"{emp_pfx}0000" / "roster.md"
    if not roster.is_file():
        for d in root.iterdir():
            if d.is_dir() and re.match(rf"^{emp_pfx}0000", d.name):
                r2 = d / "roster.md"
                if r2.is_file():
                    roster = r2
                    break
    if roster.is_file():
        for line in _read(roster).splitlines():
            m = re.match(rf"\|\s*({emp_pfx}\d{{4}})\s*\|", line)
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
            tmp = f"{idx}.{os.getpid()}.{time.time_ns()}.tmp"   # 同上：多写者不互踩
            with open(tmp, "w", encoding="utf-8", newline="") as fh:
                fh.write("\n".join(lines))
            os.replace(tmp, idx)
            targets.append(str(idx))
    return targets


# ---------------------------------------------------------------------------
# 知识库索引（决策 #19 三级知识库，MECHANISM_PLAN §十七 / PRINCIPLES P33）
# ---------------------------------------------------------------------------

KB_DIR = "knowledge"
KB_SKIP_FILES = {"KB.md", "glossary.md", "INDEX.md", "KB-CHANGELOG.md"}
KB_URI_RE = re.compile(r"opc://company:([^/\s\"'`，。）)>]+)/([^\s\"'`，。）)>]+)")


def _glossary_map(kb_dir):
    """读 glossary.md 同义词表 -> {同义词: 标准词}。tag 归一用（防同义分裂致检索漏）。"""
    m = {}
    g = Path(kb_dir) / "glossary.md"
    if not g.is_file():
        return m
    for line in _read(g).splitlines():
        line = line.strip()
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) < 3 or not cells[0] or set(cells[0]) <= set("-: ") or cells[0] == "标准词":
            continue
        for syn in re.split(r"[、,，/]", cells[1]):
            syn = syn.strip()
            if syn and syn not in ("—", "-"):
                m[syn] = cells[0]
    return m


def _kb_layers(company_dir):
    """公司内全部知识库层 -> [(层目录, kind, 显示名)]，kind ∈ {company, team, employee, project}。

    kind 决定 URI 形态：company 走 manifest key 透传，其余走实体目录 + sub 路径。
    项目级（P*/knowledge/）同样生成索引——它跟项目生命周期（P31 第四问实体跟随），
    但不参与「员工→团队→公司」的上浮主路径。
    """
    out = []
    cd = Path(company_dir)
    if (cd / KB_DIR).is_dir():
        out.append((str(cd), "company", "公司级"))
    import opc_resolver
    pats = [(k, v) for k, v in opc_resolver.entity_types().items()]
    for d in sorted(cd.iterdir()):
        if d.name.startswith(".") or not d.is_dir() or not (d / KB_DIR).is_dir():
            continue
        for kind, pfx in pats:
            if re.match(rf"^{pfx}\d+(?:-|$)", d.name):
                out.append((str(d), kind, d.name))
                break
    tpl = cd / "templates"
    if tpl.is_dir():                       # 建司骨架（尚未分配实体 ID）
        for sub in sorted(tpl.iterdir()):
            if sub.is_dir() and (sub / KB_DIR).is_dir():
                out.append((str(sub), "employee", sub.name))
    return out


def _kb_entry_uri(cid, kind, layer_label, rel):
    """条目 URI（与 resolver 解析口径一致）：公司级走 key，实体级走 <type>/<id>/knowledge/<rel>。"""
    base = f"opc://company:{cid}"
    if kind == "company":
        return f"{base}/knowledge/{rel}"
    if kind in ("team", "employee", "project"):
        m = re.match(r"^([A-Za-z]\d+)", Path(layer_label).name)
        eid = m.group(1) if m else Path(layer_label).name
        return f"{base}/{kind}/{eid}/knowledge/{rel}"
    return f"{base}/knowledge/{rel}"


def _kb_hit_counts(scan_roots):
    """全仓 opc:// 引用计数 -> {uri: 次数}。

    hits 由**引用扫描**得出，不需要运行时状态文件：幂等、可重建、不写回用户文件
    （P1 文件系统即真相 + P4 单向管道）。被引用 ≈ 被读过，是零成本的热度信号。
    """
    from collections import Counter
    c = Counter()
    for base in scan_roots:
        if not os.path.isdir(base):
            continue
        for p in Path(base).rglob("*.md"):
            if any(part.startswith(".") for part in p.parts):
                continue
            try:
                txt = _read(p)
            except OSError:
                continue
            for cid, rest in KB_URI_RE.findall(txt):
                c["opc://company:%s/%s" % (cid, rest.rstrip(".,;)）"))] += 1
    return c


def _kb_entries(kb_dir, gloss):
    """扫描一层 knowledge/ 的条目。无 frontmatter 的文件跳过（P11 跳过不降级，不静默）。"""
    out, skipped = [], []
    root = Path(kb_dir)
    for p in sorted(root.rglob("*.md")):
        if p.name in KB_SKIP_FILES or any(part.startswith(".") for part in p.parts):
            continue
        txt = _read(p)
        fm, body, has_fm = parse_frontmatter(txt)
        if not has_fm:
            skipped.append(str(p.relative_to(root)).replace("\\", "/"))
            continue
        tags = fm.get("tags") or []
        if isinstance(tags, str):
            tags = [t.strip() for t in re.split(r"[、,，]", tags) if t.strip()]
        norm, loose = [], []
        for t in tags:
            t = str(t).strip()
            if not t:
                continue
            std = gloss.get(t, t)
            if std != t:
                loose.append(t)
            if std not in norm:
                norm.append(std)
        out.append({
            "rel": str(p.relative_to(root)).replace("\\", "/"),
            "title": str(fm.get("title") or p.stem),
            "type": str(fm.get("type") or "—"),
            "status": str(fm.get("status") or "草稿"),
            "tags": norm, "loose_tags": loose,
            "review_by": str(fm.get("review_by") or "—"),
            "author": str(fm.get("author") or "—"),
            "maintainer": str(fm.get("maintainer") or "—"),
            "summary": str(fm.get("summary") or ""),
            "tokens": max(1, len(txt) // 3),
        })
    return out, skipped


def _kb_index_snapshot(idx_path):
    """读已有 INDEX.md 的条目快照 -> {相对路径: 标题}，用于变更对比（生成物自己不进对比）。"""
    out = {}
    if not Path(idx_path).is_file():
        return out
    for ln in _read(idx_path).splitlines():
        if not ln.startswith("| **"):
            continue
        cells = [c.strip() for c in ln.strip("|").split("|")]
        if len(cells) >= 8:
            out[cells[7].strip("`")] = cells[0].strip("* ")
    return out


def _kb_write_changelog(kb, label, before, after):
    """索引差异写入 KB-CHANGELOG.md（决策 #19 §17.8）：**留痕给人看，agent 只看索引**。

    agent 不需要「感知变更」——它每次读到的 INDEX.md 都是最新的；CHANGELOG 服务的是
    人（用户/管理员）：改了目录结构后，人写的 KB.md 组织原则可能已过期，得有人同步。
    只增不删（同 worklog 纪律），并发安全走 locked_append。
    """
    added = sorted(r for r in after if r not in before)
    removed = sorted(r for r in before if r not in after)
    renamed = sorted((r, after[r], old_path, old_title)
                     for r in after
                     if r not in before
                     for old_path, old_title in before.items()
                     if after[r] == old_title and old_path not in after)
    for r, _t, old_path, _old_t in renamed:
        if r in added:
            added.remove(r)
        if old_path in removed:
            removed.remove(old_path)
    if not (added or removed or renamed):
        return ""
    import datetime as _dt
    lines = ["", "## %s · %s" % (_dt.datetime.now().strftime("%Y-%m-%d %H:%M"), label)]
    for r in added:
        lines.append(f"- 新增：{after[r]}（`{r}`）")
    for r in removed:
        lines.append(f"- 移除：{before[r]}（`{r}`）")
    for r, t, old_path, old_t in renamed:
        lines.append(f"- 移动：`{old_path}` → `{r}`（标题：{old_t}）")
    body = "\n".join(lines) + "\n"
    log = Path(kb) / "KB-CHANGELOG.md"
    if not log.is_file():
        body = ("# 知识库变更留痕（KB-CHANGELOG）\n\n"
                "> 由 `opc_model --sync-index` 自动追加（只增不删）。索引本身才是 agent 的入口，\n"
                "> 本文件服务的是**人**：你手动改了目录结构后，KB.md 里那段人写的组织原则可能已过期。\n") + body
        atomic_write(str(log), body)
    else:
        locked_append(str(log), body)
    return body


def sync_kb_index(root, cid=None):
    """在公司事务锁内重建知识索引；未指定公司时逐公司串行。"""
    root_path = Path(root)
    if cid:
        import opc_resolver
        company = next((Path(c) for c in discover_companies(str(root_path))
                        if opc_resolver.extract_company_id(_read(Path(c) / "company.md")) == cid), None)
        if company is None:
            raise FileNotFoundError(f"未找到公司 {cid}，无法同步知识索引")
        with file_lock(company / ".opc-kb-transaction", timeout=30):
            recovery = _recover_kb_journal(company)
            if recovery:
                raise RuntimeError(recovery)
            return _sync_kb_index_unlocked(str(root_path), cid)
    return _sync_kb_index_unlocked(str(root_path), None)


def _sync_kb_index_unlocked(root, cid=None):
    """把各层知识库条目写成 knowledge/INDEX.md（调用方负责事务锁）。"""
    root = Path(root)

    comp_dirs = [Path(c) for c in discover_companies(str(root))]
    tpl = root / "company-template"
    if tpl.is_dir() and (tpl / "company.md").is_file():
        comp_dirs.append(tpl)
    hits = _kb_hit_counts([str(root)])
    targets = []
    import opc_resolver
    for comp in comp_dirs:
        comp = Path(comp)
        cid_here = opc_resolver.extract_company_id(_read(comp / "company.md"))
        if not cid_here or not re.match(r"^C\d+$", cid_here):
            cid_here = None                 # 模板占位符：不用 opc://，全走相对路径
        if cid and cid_here != cid:
            continue
        for layer, kind, label in _kb_layers(comp):
            kb = Path(layer) / KB_DIR
            entries, skipped = _kb_entries(kb, _glossary_map(kb))
            lines = [
                "<!-- 本文件由 `python opc_model.py --sync-index` 生成，勿手改。",
                "     知识条目的唯一真相在各条目的 frontmatter（title/type/tags/summary/status）。",
                f"     重新生成：python opc_model.py --sync-index{(' --company ' + cid_here) if cid_here else ''} -->",
                "",
                f"# 知识库索引（{label} · {len(entries)} 条）",
                "",
                "> 加载纪律：先看本表（索引行）→ 命中才读该条目 `summary` → 确认有用才读全文（P33 ①）。",
                "",
                "| 标题 | 类型 | 标签 | 状态 | 复核 | 命中 | 全文 | 路径 |",
                "|---|---|---|---|---|---|---|---|",
            ]
            for e in entries:
                uri = (_kb_entry_uri(cid_here, kind, label, e["rel"])
                       if cid_here else e["rel"])
                tag_s = "、".join(e["tags"]) or "—"
                if e["loose_tags"]:
                    tag_s += "（归一自：%s）" % "、".join(e["loose_tags"])
                lines.append("| **%s** | %s | %s | %s | %s | %s | ~%s | `%s` |" % (
                    e["title"], e["type"], tag_s, e["status"], e["review_by"],
                    hits.get(uri, 0), e["tokens"], e["rel"]))
            if not entries:
                lines.append("| _（暂无条目）_ | | | | | | | |")
            if skipped:
                lines += ["", "> 已跳过 %d 个无 frontmatter 的文件（非知识条目）：%s%s" % (
                    len(skipped), "、".join(skipped[:6]), "…" if len(skipped) > 6 else "")]
            lines.append("")
            idx = kb / "INDEX.md"
            before = _kb_index_snapshot(idx)      # 生成前快照 → 写完后比对差异留痕
            tmp = f"{idx}.{os.getpid()}.{time.time_ns()}.tmp"      # 原子写，多写者不互踩
            with open(tmp, "w", encoding="utf-8", newline="") as fh:
                fh.write("\n".join(lines))
            os.replace(tmp, idx)
            targets.append(str(idx))
            _kb_write_changelog(kb, label, before,
                                {e["rel"]: e["title"] for e in entries})
    return targets


def _kb_entry_age(path):
    """条目年龄（天）：无 frontmatter 日期时退到文件 mtime。"""
    import datetime as _dt
    try:
        mt = _dt.datetime.fromtimestamp(os.path.getmtime(path))
        return (_dt.date.today() - mt.date()).days
    except OSError:
        return None


def kb_audit(root, cid=None, cfg=None):
    """知识库腐烂体检（决策 #19 §17.7）：**只发现，不处置**（P29 / P33 ③）。

    三类：过期（`review_by` 到期）/ 重复（同层标题近义）/ 失焦（长期零命中）。
    返回 [dict(kind, level, layer, title, msg)]，供 opc_patrol 转巡检项 #13/#14/#15。
    """
    import datetime as _dt
    from difflib import SequenceMatcher
    cfg = cfg or {}
    warn_days = int(cfg.get("review_warn_days", 7))
    cold_days = int(cfg.get("cold_hits_days", 90))
    dupe_sim = float(cfg.get("dupe_similarity", 0.75))
    today = _dt.date.today()
    root = Path(root)
    hits = _kb_hit_counts([str(root)])
    out = []
    import opc_resolver
    for comp in [Path(c) for c in discover_companies(str(root))]:
        cid_here = opc_resolver.extract_company_id(_read(comp / "company.md"))
        if not cid_here or not re.match(r"^C\d+$", cid_here):
            cid_here = None
        if cid and cid_here != cid:
            continue
        for layer, kind, label in _kb_layers(comp):
            kb = Path(layer) / KB_DIR
            entries, _ = _kb_entries(kb, _glossary_map(kb))
            for e in entries:
                uri = (_kb_entry_uri(cid_here, kind, label, e["rel"])
                       if cid_here else e["rel"])
                h = hits.get(uri, 0)
                dead = e["status"] in ("已归档", "已废弃", "已上浮")
                if not dead and re.match(r"^\d{4}-\d{2}-\d{2}$", e["review_by"]):
                    try:
                        left = (_dt.date.fromisoformat(e["review_by"]) - today).days
                    except ValueError:
                        left = None
                    if left is not None and left <= warn_days:
                        out.append({
                            "kind": "stale", "level": "critical" if left < 0 else "warn",
                            "layer": label, "title": e["title"],
                            "msg": ("知识条目「%s」（%s）%s（review_by=%s）"
                                    % (e["title"], label,
                                       f"已超期 {-left} 天" if left < 0 else f"还有 {left} 天到期",
                                       e["review_by"]))})
                if not dead and h == 0:
                    age = _kb_entry_age(kb / e["rel"])
                    if age is not None and age >= cold_days:
                        out.append({
                            "kind": "cold", "level": "info", "layer": label,
                            "title": e["title"],
                            "msg": f"知识条目「{e['title']}」（{label}）{age} 天零命中，"
                                   f"是否归档由人工判断（永不自动删）"})
            for i in range(len(entries)):
                for j in range(i + 1, len(entries)):
                    a, b = entries[i], entries[j]
                    if a["status"] in ("已上浮",) or b["status"] in ("已上浮",):
                        continue
                    r = SequenceMatcher(None, a["title"], b["title"]).ratio()
                    if r >= dupe_sim:
                        out.append({
                            "kind": "dupe", "level": "warn", "layer": label,
                            "title": a["title"],
                            "msg": f"疑似重复：「{a['title']}」与「{b['title']}」（{label}，"
                                   f"相似度 {r:.0%}）→ 人工合并，不自动删"})
    return out


def kb_structure_drift(root, cid=None):
    """KB.md 描述 vs 实际结构（决策 #19 §17.8）：不一致 → 告警，**人工改 KB.md**。

    KB.md 是三级知识库里**唯一人写**的部分，也是唯一会漂移的部分——用户手动整理了
    目录却没同步 KB.md，agent 就会照着过期说明找东西。机器只发现，人工改（P29）。
    只校验 KB.md 里以反引号标注的**单层主题目录**（`common/` 这类），占位符
    （E00xx / T00x / P00xx / C00x / <本司ID>）与本层目录名一律跳过，防误报。
    """
    root = Path(root)
    out = []
    import opc_resolver
    for comp in [Path(c) for c in discover_companies(str(root))]:
        cid_here = opc_resolver.extract_company_id(_read(comp / "company.md"))
        if not cid_here or not re.match(r"^C\d+$", cid_here):
            cid_here = None
        if cid and cid_here != cid:
            continue
        for layer, kind, label in _kb_layers(comp):
            kb = Path(layer) / KB_DIR
            kbmd = kb / "KB.md"
            if not kbmd.is_file():
                continue
            for m in re.finditer(r"`([A-Za-z\u4e00-\u9fa5][^`\s/]*)/`", _read(kbmd)):
                d = m.group(1)
                if d in (KB_DIR, "knowledge") or re.search(r"0+x|<", d):
                    continue                      # 占位符 / 本层目录名，不是主题目录
                if (kb / d).is_dir():
                    continue
                out.append({
                    "kind": "drift", "level": "info", "layer": label, "title": "KB.md",
                    "msg": f"{label} KB.md 提到的目录 `{d}/` 在磁盘上不存在——你手动整理过目录？"
                           f"请同步更新 KB.md 里的组织原则（机器只发现，人工改）"})
    return out


def _kb_resolve_target(comp, to):
    """上浮目标层目录：company / team:<id> / employee:<id> -> (目录, kind, label)。"""
    if to == "company":
        return Path(comp), "company", "公司级"
    if ":" not in to:
        raise ValueError("目标格式：company 或 team:<id> 或 employee:<id>")
    kind, eid = to.split(":", 1)
    if kind not in ("team", "employee", "project"):
        raise ValueError("目标类型仅支持 team / employee / project")
    import opc_resolver
    pfx = opc_resolver.entity_types().get(kind, "")
    if not re.match(rf"^{pfx}\d+$", eid):
        raise ValueError(f"{kind} 编号前缀不符（应为 {pfx}+数字）")
    hits = [d.name for d in sorted(Path(comp).iterdir())
            if d.is_dir() and (d.name.startswith(eid + "-") or d.name == eid)]
    if not hits:
        raise FileNotFoundError(f"未找到 {kind}:{eid}")
    return Path(comp) / hits[0], kind, hits[0].name


def _sha256_text(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _kb_journal_path(comp):
    return Path(comp) / ".opc-kb-promote.journal.json"


def _write_kb_journal(path, data):
    atomic_write(str(path), json.dumps(data, ensure_ascii=False, indent=2))


def _recover_kb_journal(comp):
    """前滚未完成的知识上浮；遇到用户改写则保留 journal 并报告冲突。"""
    jp = _kb_journal_path(comp)
    if not jp.is_file():
        return None
    try:
        tx = json.loads(_read(jp))
        src, dest, stub = Path(tx["source"]), Path(tx["destination_path"]), tx["stub"]
        expected = tx["source_hash"]
        if dest.exists() and _sha256_text(_read(dest)) != tx["destination_hash"]:
            return f"上浮事务冲突：目标已被其他内容修改，journal 保留：{jp}"
        if src.exists() and _sha256_text(_read(src)) not in (expected, _sha256_text(stub)):
            return f"上浮事务冲突：源文件已被其他内容修改，journal 保留：{jp}"
        if not dest.exists():
            atomic_write(str(dest), tx["destination"])
        if not src.exists() or _sha256_text(_read(src)) == expected:
            atomic_write(str(src), stub)
        elif _sha256_text(_read(src)) != _sha256_text(stub):
            return f"上浮事务冲突：存根无法安全写入，journal 保留：{jp}"
        jp.unlink()
        return None
    except (OSError, KeyError, TypeError, ValueError) as exc:
        return f"上浮事务恢复失败：{exc}，journal 保留：{jp}"


def promote_entry(root, src, to, actor=""):
    """在公司级锁内执行可恢复的知识归属转移。"""
    root, src = Path(root), Path(src)
    comp = next((Path(c) for c in discover_companies(str(root))
                 if os.path.commonpath((os.path.abspath(str(src)), os.path.abspath(str(c)))) == os.path.abspath(str(c))), None)
    if comp is None:
        return False, "未定位到源条目所属公司"
    lock_target = comp / ".opc-kb-transaction"
    with file_lock(lock_target, timeout=30):
        recovery = _recover_kb_journal(comp)
        if recovery:
            return False, recovery
        return _promote_entry_locked(root, src, to, actor, comp=comp)


def _promote_entry_locked(root, src, to, actor="", comp=None):
    """上浮（归属轴）：物理搬家 + 原处留真实存根 + 审批前查重（决策 #19 §17.4）。

    存根必须是真实 .md 文件而非索引里的一行——否则原路径的 opc:// 引用全部断链。
    查重命中疑似重复时**拒绝执行**，要求人工先合并（P28 审批门 / P33 ② 不复制）。
    返回 (ok, msg)。
    """
    import datetime as _dt
    import shutil
    from difflib import SequenceMatcher
    root, src = Path(root), Path(src)
    if comp is not None:
        recovery = _recover_kb_journal(comp)
        if recovery:
            return False, recovery
    if not src.is_file():
        return False, f"源条目不存在：{src}"
    txt = _read(src)
    fm, _body, has_fm = parse_frontmatter(txt)
    if not has_fm:
        return False, "源条目无 frontmatter，不视为知识条目（先补字段再上浮）"
    src_kb = next((p for p in src.parents if p.name == KB_DIR), None)
    if src_kb is None:
        return False, f"源条目不在任何 {KB_DIR}/ 目录下"
    comp = next((Path(c) for c in discover_companies(str(root))
                 if os.path.abspath(str(src)).startswith(os.path.abspath(str(c)))), None)
    if comp is None:
        return False, "未定位到源条目所属公司"
    try:
        tdir, tkind, tlabel = _kb_resolve_target(comp, to)
    except (ValueError, FileNotFoundError) as e:
        return False, str(e)
    tkb = tdir / KB_DIR
    if not tkb.is_dir():
        return False, f"目标层尚无 {KB_DIR}/ 目录：{tkb}"
    recovery = _recover_kb_journal(comp)
    if recovery:
        return False, recovery
    import opc_resolver
    cid_here = opc_resolver.extract_company_id(_read(comp / "company.md"))
    if not cid_here or not re.match(r"^C\d+$", cid_here):
        cid_here = None
    cfg = {}
    try:
        import tomllib
        with open(Path(root) / "opc.toml", "rb") as fh:
            cfg = tomllib.load(fh).get("knowledge") or {}
    except Exception:
        cfg = {}                      # 配置缺失走内置默认阈值（宁可少报，不可刷屏）
    dupe_sim = float(cfg.get("dupe_similarity", 0.75))
    title = str(fm.get("title") or src.stem)
    for e in _kb_entries(tkb, _glossary_map(tkb))[0]:
        r = SequenceMatcher(None, title, e["title"]).ratio()
        if r >= dupe_sim:
            return False, (f"疑似重复，已拒绝上浮：目标层已有「{e['title']}」（相似度 {r:.0%}）。"
                           "请先人工合并再上浮（P28 审批门 / P33 ② 不复制）")
    sub = src.parent.relative_to(src_kb)
    dest_dir = (tkb / sub) if str(sub) != "." else tkb
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    suffix = 1
    while dest.exists():
        suffix += 1
        dest = dest_dir / f"{src.stem}-v{suffix}{src.suffix}"
    # frontmatter 改写：maintainer 换成接手管理员，留 promoted 痕迹（作者不丢）
    lines = txt.split("\n")
    if lines and lines[0].strip() == "---":
        end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
        if end:
            seg = lines[1:end]
            for key, val in (("maintainer", actor or "—"),
                             ("status", str(fm.get("status") or "正式"))):
                for i, ln in enumerate(seg):
                    if re.match(rf"^{key}:", ln):
                        seg[i] = f"{key}: {val}"
                        break
                else:
                    seg.append(f"{key}: {val}")
            seg.append(f"promoted: {_dt.date.today().isoformat()} → {tlabel}")
            lines[1:end] = seg
    destination_text = "\n".join(lines)
    new_rel = str(dest.relative_to(tkb)).replace("\\", "/")
    new_uri = (_kb_entry_uri(cid_here, tkind, tlabel, new_rel)
               if cid_here else new_rel)
    # 原处留真实存根（承接历史 opc:// 引用，check_links 仍绿）
    stub = ("---\n"
            f"title: {title}（已上浮）\n"
            "status: 已上浮\n"
            f"maintainer: {actor or '—'}\n"
            f"supersedes: {new_uri}\n"
            "---\n\n"
            f"# {title}\n\n"
            f"> 本文已上浮至 `{new_uri}`（决策 #19：上浮 = 归属转移，物理只存一份）。\n"
            "> 本文件是**存根**，保留以承接历史 `opc://` 引用；内容请读新地址。\n")
    journal = {
        "version": 1, "txid": secrets.token_hex(12), "phase": "prepared",
        "cid": cid_here, "source": str(src), "destination_path": str(dest),
        "source_hash": _sha256_text(txt), "destination_hash": _sha256_text(destination_text),
        "stub_hash": _sha256_text(stub), "destination": destination_text,
        "stub": stub, "actor": actor,
    }
    jp = _kb_journal_path(comp)
    _write_kb_journal(jp, journal)
    atomic_write(str(dest), destination_text)
    journal["phase"] = "dest_written"
    _write_kb_journal(jp, journal)
    # 原文件用原子替换写成存根，避免 remove 与 stub 写入之间出现断链窗口。
    atomic_write(str(src), stub)
    journal["phase"] = "source_stubbed"
    _write_kb_journal(jp, journal)
    _sync_kb_index_unlocked(str(root), cid_here)
    journal["phase"] = "indexes_synced"
    _write_kb_journal(jp, journal)
    try:
        jp.unlink()
    except OSError:
        pass
    return True, (f"已上浮「{title}」→ {tlabel}：`{new_rel}`；"
                  f"原处留存根 `{src.name}` 承接旧引用（作者 {fm.get('author') or '—'} / "
                  f"维护人 {actor or '—'}）")


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
        leftovers = [p.name for p in Path(tmp).iterdir() if p.name != "aw.txt"]
        check("atomic_write 无 tmp 残留（唯一名 tmp 用完即换名）", not leftovers)
        atomic_write(str(f), "第二遍")
        check("atomic_write 幂等重写", f.read_text(encoding="utf-8") == "第二遍")
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
    # 锁自愈（2026-08-30 双机排查：持有者早退留孤儿锁 / 环境拦 unlink → 永久死锁）
    check("pid 存活判定：自己活着", _pid_alive(os.getpid()) is True)
    check("pid 存活判定：非法/不可能 PID 为死",
          _pid_alive(0) is False and _pid_alive(-5) is False and _pid_alive(2**31 - 1) is False)
    with tempfile.TemporaryDirectory() as tmp:
        lockfile = os.path.join(tmp, "res.lock")
        with file_lock(lockfile):
            check("file_lock：持锁期间锁文件在且含持有者 PID",
                  os.path.isfile(lockfile + ".lock")
                  and json.loads(Path(lockfile + ".lock").read_text(encoding="utf-8"))["pid"] == os.getpid())
        check("file_lock：正常释放后锁文件不残留", not os.path.exists(lockfile + ".lock"))
        # 模拟孤儿锁：持有者早退没清理（内容=已失活 PID）→ 应立即被抢占，不等 30s 过期
        Path(lockfile + ".lock").write_text(str(2**31 - 1), encoding="utf-8")
        t0 = time.monotonic()
        try:
            with file_lock(lockfile, timeout=3.0):
                check("file_lock：死 PID 孤儿锁立即抢占（不等过期）",
                      time.monotonic() - t0 < 2.0)
        except TimeoutError:
            check("file_lock：死 PID 孤儿锁立即抢占（不等过期）", False)
        check("file_lock：抢占后锁文件不残留", not os.path.exists(lockfile + ".lock"))
        # 无 PID 口径（旧版本锁文件/写入窗口）：mtime 过期仍可抢占
        Path(lockfile + ".lock").write_text("", encoding="utf-8")
        old = time.time() - LOCK_STALE_SECONDS - 5
        os.utime(lockfile + ".lock", (old, old))
        with file_lock(lockfile, timeout=3.0):
            check("file_lock：过期锁（空内容回退 mtime 口径）可抢占", True)
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
    # 知识库索引（决策 #19）：三级同构 + tag 归一 + 引用计数 hits + 跳过无 frontmatter
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        comp = root / "CX-测试公司"
        comp.mkdir()
        (comp / "company.md").write_text("公司 ID：C999" + NL, encoding="utf-8")
        kb = comp / KB_DIR
        kb.mkdir()
        (kb / "glossary.md").write_text(
            "| 标准词 | 同义 | 禁用 |" + NL + "|---|---|---|" + NL + "| 工单 | 任务、ticket | 待办 |" + NL,
            encoding="utf-8")
        (kb / "报价三板斧.md").write_text(
            "---" + NL + "title: 报价三板斧" + NL + "type: method" + NL + "status: 正式" + NL
            + "tags: [任务, 报价]" + NL + "summary: 三步报价法。" + NL + "---" + NL + "正文" * 400,
            encoding="utf-8")
        (kb / "README.md").write_text("无 frontmatter，应被跳过" + NL, encoding="utf-8")
        emp = comp / "E0001-测试员工"
        (emp / "knowledge").mkdir(parents=True)
        (emp / "knowledge" / "个人技巧.md").write_text(
            "---" + NL + "title: 个人技巧" + NL + "type: method" + NL + "tags: [报价]" + NL + "---" + NL,
            encoding="utf-8")
        (comp / "某文档.md").write_text(
            "参见 opc://company:C999/knowledge/报价三板斧.md" + NL, encoding="utf-8")
        wrote = sync_kb_index(str(root))
        check("sync_kb_index 公司级 + 员工级各一份", len(wrote) == 2)
        idx = (kb / "INDEX.md").read_text(encoding="utf-8")
        check("索引收录条目", "报价三板斧" in idx)
        check("tag 归一（任务 → 工单，留痕原词）", "工单" in idx and "归一自：任务" in idx)
        check("hits = 引用计数（无需状态文件）", "| 1 | ~" in idx)
        check("无 frontmatter 文件跳过且不静默", "已跳过 1 个" in idx and "README.md" in idx)
        check("员工级索引独立生成（三级同构）",
              "个人技巧" in (emp / "knowledge" / "INDEX.md").read_text(encoding="utf-8"))
        # 上浮（归属轴）：物理搬家 + 原处留真实存根 + 查重拒绝
        okp, msgp = promote_entry(str(root), str(emp / "knowledge" / "个人技巧.md"),
                                  "company", "E0000")
        check("上浮：物理搬家到目标层", okp and (kb / "个人技巧.md").is_file())
        stub = (emp / "knowledge" / "个人技巧.md").read_text(encoding="utf-8")
        check("上浮：原处留真实存根（承接历史 opc:// 引用）",
              "已上浮" in stub and "opc://company:C999/knowledge/个人技巧.md" in stub)
        moved = (kb / "个人技巧.md").read_text(encoding="utf-8")
        check("上浮：maintainer 换接手管理员，author 不丢",
              "maintainer: E0000" in moved and "promoted:" in moved)
        dup = emp / "knowledge" / "另一条.md"
        dup.write_text("---" + NL + "title: 个人技巧" + NL + "---" + NL, encoding="utf-8")
        okd, _ = promote_entry(str(root), str(dup), "company", "E0000")
        check("上浮：查重命中则拒绝，源文件不动（P28 审批门）",
              (not okd) and dup.is_file())
        # 腐烂体检（只发现不处置）
        (kb / "过期条目.md").write_text(
            "---" + NL + "title: 过期条目" + NL + "type: reference" + NL
            + "review_by: 2020-01-01" + NL + "---" + NL, encoding="utf-8")
        (emp / "knowledge" / "冷门条目.md").write_text(
            "---" + NL + "title: 冷门条目" + NL + "type: method" + NL + "---" + NL,
            encoding="utf-8")
        (emp / "knowledge" / "冷门条目B.md").write_text(
            "---" + NL + "title: 冷门条目B" + NL + "type: method" + NL + "---" + NL,
            encoding="utf-8")
        items = kb_audit(str(root), None,
                         {"review_warn_days": 7, "cold_hits_days": 0, "dupe_similarity": 0.75})
        check("腐烂体检：过期条目检出（stale/critical）",
              any(i["kind"] == "stale" and i["level"] == "critical" for i in items))
        check("腐烂体检：零命中条目检出（cold）",
              any(i["kind"] == "cold" and "冷门条目" in i["title"] for i in items))
        check("腐烂体检：疑似重复检出（dupe）",
              any(i["kind"] == "dupe" for i in items))
    # --append 路径参数健壮性（2026-08-30 排查：cmd 桥接把引号原样带进 argv →
    # 中文路径 exists=False → 误报「内容为空」且用户以为没写进去）
    check("路径引号规整：成对双引号剥除",
          _unquote_path('"E:\\OPC\\中文 目录\\块.txt"') == "E:\\OPC\\中文 目录\\块.txt")
    check("路径引号规整：成对单引号剥除 + 空白容忍",
          _unquote_path("  'C:\\日志.md'  ") == "C:\\日志.md")
    check("路径引号规整：不成对不剥（合法文件名可含单个引号）",
          _unquote_path("it's.md") == "it's.md" and _unquote_path("普通.md") == "普通.md")
    import io
    check("stdin 解码：UTF-8 字节流直读不乱码", _decode_input(io.BytesIO("中文内容".encode("utf-8")).read()) == "中文内容")
    enc = locale.getpreferredencoding(False)
    check("stdin 解码：本机编码兜底可解",
          _decode_input(io.BytesIO("中文内容".encode(enc)).read()) == "中文内容")

    # ---- worklog 门禁（2026-08-31 双告警治本层）----
    def gate(content, pool=()):
        return worklog_gate(content, set(pool), today="2030-01-02")

    blk = "---{n}wid:{n}date: 2030-01-02{n}title: 干了件活{n}status: 已完成{n}type: 自由{n}ticket: -{n}deliverable: -{n}---{n}正文{n}{n}## 小节{n}- 要点".format(n=NL)
    out, notes = gate(blk)
    fm_out, _, _ = parse_frontmatter(out)
    check("门禁：wid 自动分配（首条当天 001）",
          fm_out["wid"] == "W-20300102-001" and fm_out["ticket"] in ("", None)
          and fm_out["deliverable"] in ("", None))
    check("门禁：条目正文原样保留", "## 小节" in out and "- 要点" in out)
    out2, _ = gate(blk, pool={"W-20300102-001", "W-20300102-07"})
    fm_out2, _, _ = parse_frontmatter(out2)
    check("门禁：序号取当天最大+1（07 存在时分配 008）", fm_out2["wid"] == "W-20300102-008")
    blk_fixed = blk.replace("wid:", "wid: W-20300102-001")
    try:
        gate(blk_fixed, pool={"W-20300102-001"})
        check("门禁：显式 wid 撞号拒收", False)
    except ValueError:
        check("门禁：显式 wid 撞号拒收", True)
    try:
        gate(blk.replace("wid:", "wid: W-2030-1"))
        check("门禁：显式 wid 格式非法拒收", False)
    except ValueError:
        check("门禁：显式 wid 格式非法拒收", True)
    blk_tsk = blk.replace("type: 自由", "type: 工单")
    try:
        gate(blk_tsk)
        check("门禁：工单型缺 ticket 拒收", False)
    except ValueError:
        check("门禁：工单型缺 ticket 拒收", True)
    blk_ok_tsk = blk_tsk.replace("ticket: -", "ticket: TSK00010")
    out3, _ = gate(blk_ok_tsk)
    fm_out3, _, _ = parse_frontmatter(out3)
    check("门禁：工单型 ticket 合法放行", fm_out3["wid"] == "W-20300102-001" and fm_out3["ticket"] == "TSK00010")
    try:
        gate(blk.replace("status: 已完成", "status: 干完了"))
        check("门禁：status 非法拒收", False)
    except ValueError:
        check("门禁：status 非法拒收", True)
    try:
        gate(blk.replace("title: 干了件活", "title: -"))
        check("门禁：title 占位符视同缺失拒收", False)
    except ValueError:
        check("门禁：title 占位符视同缺失拒收", True)
    out4, notes4 = gate(blk.replace("type: 自由", "type: 直聊"))
    fm_out4, _, _ = parse_frontmatter(out4)
    check("门禁：非工单条目 `-` 占位静默清空（无 A2 提示）",
          fm_out4["ticket"] in ("", None) and not any("A2" in x for x in notes4))
    out4b, notes4b = gate(blk.replace("type: 自由", "type: 直聊").replace("ticket: -", "ticket: TSK00010"))
    fm_out4b, _, _ = parse_frontmatter(out4b)
    check("门禁：非工单条目真实 ticket 强制清空并提示",
          fm_out4b["ticket"] in ("", None) and any("A2" in x for x in notes4b))
    out5, _ = gate("<!-- 归档指针注释 -->" + NL)
    check("门禁：非条目内容原样放行", out5.startswith("<!--"))
    out6, _ = gate(blk + NL + NL + blk.replace("wid:", "wid: "), pool={"W-20300102-001"})
    fm_out6, _, _ = parse_frontmatter(out6)
    check("门禁：缺 wid 多块连加各分配不撞号", fm_out6["wid"] == "W-20300102-002")

    print("自测" + ("全部通过 ✓" if ok else "存在失败 ✗"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="OPC 实体共享读取器（列出发现的公司与实体 / 技能索引生成）")
    ap.add_argument("--list", action="store_true", help="列出 OPC 根下各公司与实体数量")
    ap.add_argument("--list-skills", action="store_true", help="列出全部技能层 skills/*/SKILL.md 元数据（name/triggers/summary）")
    ap.add_argument("--sync-index", action="store_true", help="把各层技能清单 + 知识库条目写成 INDEX.md（生成物，勿手改）")
    ap.add_argument("--promote", metavar="源条目", default=None,
                    help="上浮知识条目（物理搬家 + 原处留真实存根 + 审批前查重）")
    ap.add_argument("--to", default="company", help="上浮目标：company / team:<id> / employee:<id>（默认 company）")
    ap.add_argument("--actor", default="", help="操作者（登记为条目 maintainer）")
    ap.add_argument("--kb-audit", action="store_true", help="知识库腐烂体检（过期/重复/失焦，只发现不处置）")
    ap.add_argument("--kb-drift", action="store_true",
                    help="KB.md 结构漂移排查（**人工按需**，不进自动巡检：自由文本误报率高）")
    ap.add_argument("--append", nargs=2, metavar=("目标文件", "内容文件"),
                    action="store", help="锁内追加：把内容文件追加到目标（多会话安全；内容文件为 - 时读 stdin）")
    ap.add_argument("--worklog", action="store_true",
                    help="配合 --append：按 worklog 门禁处理（自动分配 wid / A2 校验 / 撞号拒收）。"
                         "目标文件名是 worklog.md 时自动生效，无需本开关（归档文件追加才需要）")
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
        target, src = (_unquote_path(a.append[0]), _unquote_path(a.append[1]))
        if src == "-":
            content = _read_stdin_text()
            if not content.strip():
                print("[ERR] stdin 无输入（用法：内容 | python opc_model.py --append 目标 - ；"
                      "或把内容写进文件传路径）")
                return 1
        else:
            p = Path(src)
            if not p.exists():
                print(f"[ERR] 内容文件不存在：{src}\n"
                      f"      路径含中文/空格时请整段加引号；若经 cmd 中转调用，"
                      f"检查引号是否被原样传进了参数（可先 ls/echo 验证）")
                return 1
            try:
                content = p.read_text(encoding="utf-8")
            except UnicodeDecodeError as e:
                print(f"[ERR] 内容文件不是有效 UTF-8：{src}（{e}）——"
                      f"请以 UTF-8 保存后重试（机制层全链路统一 UTF-8）")
                return 1
            if not content.strip():
                print(f"[ERR] 内容文件为空：{src}")
                return 1
        if a.worklog or os.path.basename(target) == "worklog.md":
            def _gate(existing):
                new, notes = worklog_gate(content, worklog_wid_pool(target, existing))
                _gate.notes = notes
                if not existing:
                    return new
                # 块间家规：条目块之间留一个空行；热文件无尾换行时先补（防 ---- 粘连）
                sep = "" if existing.endswith("\n\n") else ("\n" if existing.endswith("\n") else "\n\n")
                return existing + sep + new
            try:
                locked_worklog_update(target, _gate)
            except ValueError as e:
                print(f"[ERR] worklog 门禁拒绝（未写入）：{e}")
                return 1
            for nt in _gate.notes:
                print("[i] " + nt)
            print(f"[ok] 已过 worklog 门禁并追加 -> {target}")
        else:
            locked_append(target, content)
            print(f"[ok] 已锁内追加 {len(content)} 字符 -> {target}")
        return 0
    if a.promote:
        ok, msg = promote_entry(root, a.promote, a.to, a.actor)
        print(("[ok] " if ok else "[拒绝] ") + msg)
        return 0 if ok else 1
    if a.kb_audit:
        import tomllib
        cfg = {}
        try:
            with open(Path(root) / "opc.toml", "rb") as fh:
                cfg = tomllib.load(fh).get("knowledge") or {}
        except Exception:
            cfg = {}
        items = kb_audit(root, a.company, cfg)
        if not items:
            print("[ok] 知识库体检无发现")
            return 0
        for it in items:
            print(f"[{it['level']}] {it['kind']} · {it['layer']} · {it['msg']}")
        return 0
    if a.kb_drift:
        items = kb_structure_drift(root, a.company)
        if not items:
            print("[ok] KB.md 与实际结构一致")
            return 0
        print(f"[i] {len(items)} 处待人工核对（KB.md 是自由文本，含反例与兄弟目录，"
              f"需你自己判断哪些是真漂移）：")
        for it in items:
            print(f"  - {it['layer']}：{it['msg']}")
        return 0
    if a.sync_index:
        wrote = sync_index(root, a.company)
        print(f"[done] 已生成 {len(wrote)} 份 skills/INDEX.md：")
        for p in wrote:
            print("  -", p)
        kwrote = sync_kb_index(root, a.company)
        print(f"[done] 已生成 {len(kwrote)} 份 knowledge/INDEX.md：")
        for p in kwrote:
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
