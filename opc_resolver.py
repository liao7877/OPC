#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
opc_resolver —— OPC 命名空间解析器（DI 容器 / 依赖倒置的落点）

职责（单一，不碰业务逻辑）：
  - 从 opc.toml（全局单例）+ 公司级覆盖，合并出「逻辑符号 -> 物理路径」映射
  - 把 opc:// URI 解析成真实文件系统路径（支持 company 范围实体 + org 范围文档）
  - check_links：链接器自检（全文扫描所有 opc:// 引用，改名后跑一次列出失效点）
  - sync_links：稳定锚 companies/<cid> 重指向（零参数，靠 company.md ID 发现）
  - doctor：init 自检门禁（Python 版本 / 稳定锚 / pre-commit / 命名空间）

高层 consumer（opc_dashboards.py / opc_tickets.py / AGENTS.md / skill 指令）只依赖
opc:// 符号，物理路径（目录名、布局）全部下沉到 opc.toml。改目录名 = 只改 opc.toml 一行。

零第三方依赖：仅标准库（tomllib, Python 3.11+）。内置 --selftest。

URI 契约（与 opc-namespace-design.md §3 一致）：
  opc://company:<cid>                  -> 公司根（真实目录或稳定锚）
  opc://company:<cid>/<key>            -> manifest 注册 key（workbench/roster/...）
  opc://company:<cid>/<etype>/<eid>    -> 实体（skill/team/project/employee，须存在）
  opc://company:<cid>/<etype>/<eid>/<sub...> -> 实体下子路径（逐级校验存在）
  opc://org[/<name>]                   -> OPC 根文档（前缀归一发现）
  解析失败一律 raise（FileNotFoundError / ValueError），绝不静默返回假路径。
"""
import os
import re
import sys
import tomllib
import subprocess

# 实体类型内置默认（目录名前缀约定）；唯一真相在 opc.toml [entity_types]，可整体覆盖。
# 加新实体类型（如客户/供应商）= manifest 加一行，resolver/生成器/巡检/结构自检自动跟随
# （2026-08-29 拍板：实体类型注册表落地，消除「前缀正则散落 4+ 处」）。
_DEFAULT_ENTITY_TYPES = {"employee": "E", "team": "T", "project": "P"}


def entity_types(root=None):
    """实体类型注册表：{type: 目录名前缀}。manifest [entity_types] 覆盖默认值。"""
    reg = dict(_DEFAULT_ENTITY_TYPES)
    root = root or _find_root()
    if root:
        try:
            g = _load_toml(os.path.join(root, "opc.toml"))
            for k, v in g.get("entity_types", {}).items():
                reg[str(k)] = str(v)
        except Exception:
            pass    # manifest 缺失/损坏时回退默认（doctor 会另行报告）
    return reg


def _find_root():
    """从本文件向上找含 opc.toml 的目录（= OPC 根）。"""
    d = os.path.dirname(os.path.abspath(__file__))
    while True:
        if os.path.isfile(os.path.join(d, "opc.toml")):
            return d
        nd = os.path.dirname(d)
        if nd == d:
            return None
        d = nd


def _load_toml(p):
    with open(p, "rb") as f:
        return tomllib.load(f)


class CompanyConfig:
    """某公司命名空间：逻辑名 -> 绝对路径。"""

    def __init__(self, cid, root, merged):
        self.cid = cid
        self.root = root
        self.home = merged.get("home", cid)   # 默认 home = 公司 id
        self._m = merged

    # ---- 派生绝对路径（细节注入点）----
    @property
    def home_abs(self):
        return os.path.join(self.root, self.home)

    def _abs(self, key):
        rel = self._m.get(key)
        if rel is None:
            raise KeyError(f"未定义符号：opc://company:{self.cid}/{key}")
        return os.path.join(self.home_abs, rel)

    @property
    def workbench_abs(self):
        return self._abs("workbench")

    @property
    def tasks_data_abs(self):
        return self._abs("tasks_data")

    @property
    def roster_abs(self):
        return self._abs("roster")

    @property
    def roster_rel(self):
        """相对公司根的路径（供脚本 os.path.join(COMPANY_DIR, ...) 复用）。"""
        return self._m.get("roster")

    @property
    def affairs_abs(self):
        return self._abs("affairs")

    @property
    def page_templates_abs(self):
        return self._abs("page_templates")


def extract_company_id(text):
    """从 company.md 文本提取「公司 ID」值：去 markdown 加粗、截内联注释
    （（...）或 (...) 之后不算 ID——允许 ID 行带说明文字而不破坏发现机制）。
    公开 API：所有「从 company.md 认公司身份」的 consumer（生成器反查、
    巡检、计划任务脚本）统一走本函数，禁止各处私写正则（P25/P26），
    否则「ID 行带注释」这类输入在不同模块解析出不同结果。"""
    m = re.search(r'\*?\*?公司\s*ID\*?\*?\s*[:：]\s*\**\s*(\S+)', text)
    if not m:
        return None
    return m.group(1).strip().strip('*').split('（')[0].split('(')[0].strip()


def _discover_company_home(cid, root):
    """扫描发现式兜底：root 下找 company.md 中声明「公司 ID == cid」的目录。

    不依赖 opc.toml 的 home（物理路径细节），靠实体身份锚点（company.md 的 ID）
    现场认公司。对应 DIP：高层只认逻辑 ID，物理位置细节在此按身份发现。
    返回绝对路径，找不到返回 None。
    """
    if not root or not os.path.isdir(root):
        return None
    for entry in sorted(os.listdir(root)):
        d = os.path.join(root, entry)
        if not os.path.isdir(d):
            continue
        md = os.path.join(d, "company.md")
        if not os.path.isfile(md):
            continue
        got = extract_company_id(_read_file(md))
        if got and got == cid:
            return d
    return None


def load_company(cid):
    """读全局 + 公司级覆盖，合并返回 CompanyConfig（DI：细节在此注入）。

    严格性：cid 不在 manifest（且无法扫描发现）时直接抛错——宁可失败也不解析出假路径。
    自愈：opc.toml 的 home（物理路径）失效时，按 company.md 的「公司 ID」
    扫描发现真实目录——手动改公司目录名、忘了改 manifest 也能自动定位。
    """
    root = _find_root()
    if root is None:
        raise FileNotFoundError("未找到 opc.toml（OPC 根）")
    g = _load_toml(os.path.join(root, "opc.toml"))
    companies = g.get("company", {})
    defaults = companies.get("DEFAULT", {})
    if cid not in companies:
        # manifest 无此公司段：允许扫描发现兜底（如新建公司忘了写段），但发现不到即报错
        discovered = _discover_company_home(cid, root)
        if not discovered:
            raise FileNotFoundError(f"未知公司：{cid}（opc.toml 无 [company.{cid}] 段，扫描发现亦无 company.md 声明该 ID）")
        merged = {**defaults, "home": os.path.relpath(discovered, root)}
    else:
        override = companies.get(cid, {})
        merged = {**defaults, **override}        # 公司级覆盖全局
        if "home" not in merged:
            merged["home"] = cid
        # —— 自愈兜底：manifest home 失效 → 按 company.md 的 ID 扫描发现 ——
        home_abs = os.path.join(root, merged["home"])
        if not os.path.isdir(home_abs):
            discovered = _discover_company_home(cid, root)
            if discovered:
                merged["home"] = os.path.relpath(discovered, root)
    return CompanyConfig(cid, root, merged)


# ---------------------------------------------------------------------------
# 实体解析（约定式 + 扫描发现式）—— Repository / 查询抽象层
# ---------------------------------------------------------------------------

def resolve_company(company=None, company_dir=None):
    """生成器公共入口（D1 收敛，2026-08-29）：按 --company CID（走 manifest）或
    --dir 目录（反查 ID）返回 CompanyConfig；home 断链时明确报错。
    此前「读 company.md → 正则取 ID → load_company → 校验 home」在三份
    resolve_ctx 里各抄一遍——正是 P25 想消灭的漂移点。"""
    if company is None:
        if not company_dir:
            raise ValueError("需要 --company <cid> 或 --dir <公司根目录>")
        company_dir = os.path.abspath(company_dir)
        company = extract_company_id(read_text(os.path.join(company_dir, "company.md")))
        if not company:
            raise FileNotFoundError(f"{company_dir}/company.md 缺「公司 ID」声明，无法反查公司")
    cfg = load_company(company)
    if not os.path.isdir(cfg.home_abs):
        raise FileNotFoundError(
            f"公司 {company} 根不存在：{cfg.home_abs}（锚未建或目录被删）"
            f"→ 在 OPC 根跑 `python opc_resolver.py --ensure-links` 重建锚")
    return cfg


def _require_dir(path, what):
    """严格存在性校验：目录不存在即抛错（绝不返回假路径让悬空引用漏网）。"""
    if not os.path.isdir(path):
        raise FileNotFoundError(f"失效引用：{what} -> {path}（不存在）")
    return path


def _require_file(path, what):
    if not os.path.isfile(path):
        raise FileNotFoundError(f"失效引用：{what} -> {path}（不存在）")
    return path


def resolve_entity(cid, etype, eid, sub=None):
    """opc://company:C001/<type>/<id>[/<sub...>] -> 绝对路径。子路径逐级校验存在。"""
    cfg = load_company(cid)
    home = cfg.home_abs

    if etype == "skill":
        # 约定式：{home}/{skills}/{name}
        base = cfg._m.get("skills", "skills")
        p = _require_dir(os.path.join(home, base, eid),
                         f"opc://company:{cid}/skill/{eid}")
    elif etype in entity_types():
        # 校验 eid 与注册表前缀匹配（防 team/E0000 跨类错配；前缀真相在 [entity_types]）
        prefix = entity_types()[etype]
        if not re.match(rf"^{prefix}\d+$", eid):
            raise ValueError(f"实体 {etype}:{eid} 编号前缀不符（{etype} 应为 {prefix}+数字）")
        # 扫描发现式：home 下找 {id}-* 目录（实体即目录，id 是稳定前缀）
        if not os.path.isdir(home):
            raise FileNotFoundError(f"公司根不存在：{home}")
        hits = [e for e in sorted(os.listdir(home))
                if (e.startswith(eid + "-") or e == eid)]
        if len(hits) > 1:
            raise ValueError(f"实体 {etype}:{eid} 目录歧义：{home} 下多个匹配 {hits}（请改用唯一前缀）")
        if not hits:
            raise FileNotFoundError(
                f"未找到实体 {etype}:{eid}（扫描 {home} 无匹配 {eid}-*）")
        p = _require_dir(os.path.join(home, hits[0]), f"opc://company:{cid}/{etype}/{eid}")
    else:
        # 兼容 key 模式透传（opc://company:C001/workbench 等）
        if etype in cfg._m:
            return cfg._abs(etype)
        raise ValueError(f"不支持的实体类型：{etype}（可用：skill 或注册表 {sorted(entity_types())} 或 manifest key）")

    if sub:
        # 子路径逐级校验（SKILL.md 等具体文件）
        cur = p
        for part in sub:
            cur = os.path.join(cur, part)
        if not os.path.exists(cur):
            raise FileNotFoundError(f"失效引用：opc://company:{cid}/{etype}/{eid}/{'/'.join(sub)} -> {cur}（不存在）")
        return cur
    return p


def resolve(uri):
    """opc://... -> 绝对路径。支持 company 范围（key / 实体[+子路径]）与 org 范围文档。
    解析失败 raise，不静默。"""
    if uri.startswith("opc://company:"):
        rest = uri[len("opc://company:"):]
        cid, _, path = rest.partition("/")
        parts = [p for p in path.split("/") if p]
        if len(parts) == 0:
            cfg = load_company(cid)
            return _require_dir(cfg.home_abs, uri)
        if len(parts) == 1:
            p = load_company(cid)._abs(parts[0])
            if not os.path.exists(p):
                raise FileNotFoundError(f"失效引用：{uri} -> {p}（不存在）")
            return p
        return resolve_entity(cid, parts[0], parts[1], sub=parts[2:])

    if uri.startswith("opc://org"):
        # org 范围：OPC 根下文档，按 name 归一化前缀（去非字母数字、大小写不敏感）发现
        name = uri[len("opc://org"):].lstrip("/")
        root = _find_root()
        if not name:
            if root is None:
                raise FileNotFoundError("未找到 opc.toml（OPC 根）")
            return root
        if root and os.path.isdir(root):
            norm = lambda s: "".join(c for c in s.lower() if c.isalnum())
            target = norm(name)
            for entry in sorted(os.listdir(root)):
                if entry.startswith("."):
                    continue
                base = os.path.splitext(entry)[0]
                if norm(base).startswith(target):
                    return os.path.join(root, entry)
        raise FileNotFoundError(f"未找到 org 文档：{name}")

    raise ValueError(f"不支持的 URI 方案：{uri}（可用：opc://company:<cid>/... 或 opc://org/...）")


# ---------------------------------------------------------------------------
# 链接器自检（check-links）：全文扫描所有 opc:// 引用
# ---------------------------------------------------------------------------

_REF_RE = re.compile(r'opc://[A-Za-z0-9_:<>\-/][^\s"`\'\)\]\}>，。；！？（）：、…]*')


def scan_refs(root):
    """遍历 root，收集所有文件里的 opc:// 引用 -> {uri: [(file, line), ...]}。

    - 排除中文标点结尾的误吸（正文裸写 URI 后接句号/逗号，不是引用的一部分）
    - 不可解码文件（GBK 等）以 latin-1 兜底读取而非静默跳过——门禁不假绿
    """
    refs = {}
    skip_dirs = {".git", "node_modules", ".workbuddy"}
    exts = (".md", ".py", ".html", ".js", ".toml", ".json", ".txt", ".bat", ".ps1")
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for fn in files:
            if not fn.lower().endswith(exts):
                continue
            fp = os.path.join(dirpath, fn)
            try:
                fh = open(fp, encoding="utf-8")
            except OSError:
                continue
            try:
                for i, line in enumerate(fh, 1):
                    for m in _REF_RE.finditer(line):
                        uri = m.group(0)
                        if "<" in uri or ">" in uri:   # 文档示例占位，跳过
                            continue
                        if "..." in uri:                # 省略号示例（opc://company:C001/...），跳过
                            continue
                        if "{" in uri or uri.endswith(":"):
                            continue                    # f-string 模板/裸前缀（源码内），非真实引用
                        refs.setdefault(uri, []).append((fp, i))
            except UnicodeDecodeError:
                # 非 UTF-8 文件：latin-1 兜底（字节级 ASCII 前缀的 opc:// 仍可识别）
                try:
                    with open(fp, encoding="latin-1") as fh2:
                        for i, line in enumerate(fh2, 1):
                            for m in _REF_RE.finditer(line):
                                uri = m.group(0)
                                if "<" in uri or ">" in uri or "..." in uri:
                                    continue
                                refs.setdefault(uri, []).append((fp, i))
                except OSError:
                    pass
            except OSError:
                pass
            finally:
                fh.close()
    return refs


def audit_structure(root=None):
    """结构审计：把『company.md 锚点必须正确』这件维护职责从「人记忆」下沉到「工具门禁」。

    扫描 OPC 根下「像公司」的目录（含 company.md 或 workbench/），校验：
      - 必须有 company.md，且声明有效「公司 ID」（否则改名后无法被 sync_links 发现）；
      - 其 ID 必须在 opc.toml 的 [company.<cid>] 中有对应段（否则解析不到实体）。
    返回问题列表。被 check_links 调用，故 pre-commit 自动覆盖锚点漂移。
    """
    root = root or _find_root()
    issues = []
    if root is None or not os.path.isdir(root):
        return issues
    g = _load_toml(os.path.join(root, "opc.toml"))
    known_cids = {k for k in g.get("company", {}).keys() if k != "DEFAULT"}
    skip = {".git", "companies", ".workbuddy", "scripts",
            "create-company", "company-template"}
    declared = {}   # cid -> [目录名]：ID 全局唯一性校验（建司漏改模板 ID 时两处同 ID）
    for entry in sorted(os.listdir(root)):
        d = os.path.join(root, entry)
        if not os.path.isdir(d) or entry in skip:
            continue
        md = os.path.join(d, "company.md")
        has_md = os.path.isfile(md)
        has_wb = os.path.isdir(os.path.join(d, "workbench"))
        if not (has_md or has_wb):
            continue  # 非公司目录（普通文档/工具目录），跳过
        if not has_md:
            issues.append(f"孤儿公司目录：{entry}/ 缺 company.md，改名后将无法被 sync_links 发现")
            continue
        txt = _read_file(md)
        if not txt:
            issues.append(f"{entry}/company.md 不可读")
            continue
        cid = extract_company_id(txt)
        if not cid:
            issues.append(f"{entry}/company.md 缺「公司 ID」声明，无法被发现")
            continue
        declared.setdefault(cid, []).append(entry)
        if known_cids and cid not in known_cids:
            issues.append(
                f"{entry}/company.md 声明公司 ID={cid}，但 opc.toml 无 [company.{cid}] 段")
    for cid, dirs in sorted(declared.items()):
        if len(dirs) > 1:
            issues.append(
                f"公司 ID={cid} 被多个目录声明：{dirs}（ID 全局唯一；建司时漏改模板 ID？）")
    return issues


def all_company_ids(root=None):
    """manifest 中声明的全部公司 ID（不含 DEFAULT）。"""
    root = root or _find_root()
    if root is None:
        return []
    g = _load_toml(os.path.join(root, "opc.toml"))
    return [k for k in g.get("company", {}) if k != "DEFAULT"]


def check_links(cid=None, root=None):
    """链接器自检：① manifest 定义的 key 必须物理存在（遍历全部公司，不单查一家）；
    ② 全文 opc:// 引用必须可解析；③ 结构审计（锚点）。"""
    root = root or _find_root()
    issues = []

    # ① manifest 自身定义的 key 物理存在性（全部公司；即便暂时无人引用）
    for c in ([cid] if cid else all_company_ids(root)) or []:
        try:
            cfg = load_company(c)
            for key in ["workbench", "tasks_data", "roster",
                        "affairs", "page_templates", "skills"]:
                try:
                    p = cfg._abs(key)
                except KeyError:
                    issues.append(f"未定义符号：opc://company:{c}/{key}")
                    continue
                if not os.path.exists(p):
                    # tasks_data 是生成产物：源目录在而产物未生成（clone 后首跑前）不算失效
                    if key == "tasks_data" and os.path.isdir(cfg.workbench_abs):
                        continue
                    issues.append(f"失效引用：opc://company:{c}/{key} -> {p}（不存在）")
        except Exception as e:
            issues.append(f"加载公司 {c} 失败：{e}")

    # ② 全文扫描所有 opc:// 引用，逐个解析
    refs = scan_refs(root)
    for uri in sorted(refs):
        try:
            resolve(uri)
        except Exception as e:
            # 生成产物例外（与 ① 同口径）：tasks_data 是 run_boards 产物，
            # clone 后首跑前不存在属正常，不算失效引用（源目录在即可）
            if uri.startswith("opc://company:"):
                cid, _, key = uri[len("opc://company:"):].partition("/")
                if key == "tasks_data" and "/" not in key:
                    try:
                        if os.path.isdir(load_company(cid).workbench_abs):
                            continue
                    except Exception:
                        pass
            fp, ln = refs[uri][0]
            rel = os.path.relpath(fp, root)
            issues.append(f"失效引用 {uri} @ {rel}:{ln} -> {e}")

    # ③ 结构审计：company.md 锚点缺失/无效 → 改名后无法被发现（维护职责下沉到门禁）
    issues += audit_structure(root)

    return issues


# ---------------------------------------------------------------------------
# 稳定锚同步（sync_links）：把 companies/<cid> 重指向真实目录
# —— 零参数、零手动输入：靠 company.md 的「公司 ID」扫描发现真实位置。
# 手动改公司目录名后跑一次即可；未来 watcher 也只调本函数。
# ---------------------------------------------------------------------------

def _create_link(link, target):
    """创建 OS 级稳定锚 link -> target。
    Windows 用 junction 联接（普通用户可建、跨盘符无碍）；*nix 用 symlink。
    目标已存在时抛出可读错误（不裸栈）。"""
    if os.path.lexists(link):
        raise FileExistsError(
            f"锚位已存在且无法安全重建：{link}（companies/ 是受管锚命名空间，"
            f"请人工确认该条目后删除再跑 --sync-links）")
    if sys.platform.startswith("win"):
        # mklink 是 cmd 内建命令，必须经 cmd /c；路径加引号以兼容空格/中文
        r = subprocess.run(f'mklink /J "{link}" "{target}"', shell=True, check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if r.returncode != 0 or not os.path.lexists(link):
            raise OSError(f"mklink /J 失败（exit {r.returncode}）：{link} -> {target}")
    else:
        os.symlink(target, link, target_is_directory=True)


def _remove_link(link):
    """安全删除链接本身（不碰目标）。兼容 symlink / junction（含断链）。
    companies/ 是受管锚命名空间，内部链接由本函数独占重建，安全。
    返回是否删除成功。"""
    for fn in (
        lambda: os.unlink(link),
        lambda: os.rmdir(link),
        lambda: subprocess.run(
            ["cmd", "/c", "rmdir", link], shell=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False),
    ):
        try:
            fn()
            return not os.path.lexists(link)
        except OSError:
            continue
        except Exception:
            continue
    return not os.path.lexists(link)


def _link_resolves_to(link, target):
    """link 是否已指向 target（断链/不存在返回 False）。"""
    try:
        return os.path.realpath(link) == os.path.realpath(target)
    except OSError:
        return False


def sync_links(root=None):
    """重新同步所有公司的稳定锚 companies/<cid> -> 真实目录。

    发现逻辑（不依赖手动输入）：
      - home 缺失/失效（如真实目录被改名）→ 按 company.md 的「公司 ID」扫描发现真实位置；
      - home 指向稳定锚自身（标准配置 companies/<cid>）时直接用扫描发现定位真实目录。
    返回 (ok_list, err_list)。companies/ 是受管锚命名空间，内部链接可安全重建。
    """
    root = root or _find_root()
    if root is None:
        return [], ["未找到 opc.toml（OPC 根）"]
    g = _load_toml(os.path.join(root, "opc.toml"))
    companies = g.get("company", {})
    cids = [k for k in companies if k != "DEFAULT"]
    ok, err = [], []
    link_root = os.path.join(root, "companies")
    os.makedirs(link_root, exist_ok=True)

    for cid in cids:
        link = os.path.join(link_root, cid)
        # 标准配置下 home 即锚本身，直接扫描发现真实目录；home 是真实目录（非锚）则优先用
        home_rel = companies[cid].get("home")
        target = None
        if home_rel and os.path.normpath(home_rel).lower() != os.path.normpath(f"companies/{cid}").lower():
            cand = os.path.join(root, home_rel)
            if os.path.isdir(cand) and not _link_resolves_to(cand, link):
                target = cand
        if target is None:
            target = _discover_company_home(cid, root)
        if target is None:
            err.append(f"{cid}: 未发现真实目录（home 失效且无 company.md ID 匹配）")
            continue

        if _link_resolves_to(link, target):
            ok.append(f"{cid}: 已指向 {target}（无需改动）")
            continue
        if os.path.lexists(link) and not _remove_link(link):
            err.append(f"{cid}: 旧锚无法删除：{link}（请人工处理）")
            continue
        try:
            _create_link(link, target)
            ok.append(f"{cid}: 重指向 -> {target}")
        except Exception as e:
            err.append(f"{cid}: 建锚失败：{e}")
    return ok, err


# ---------------------------------------------------------------------------
# ensure_links：OS 级链接统一托管（2026-08-28 Q3 拍板）
# 稳定锚 companies/<cid> 与「各层技能披露链接」同属一类问题——不入库、
# clone 后必重建、断了会让 agent 行为退化——却曾有两套标准（锚有脚本+门禁，
# 披露链接三不管，doctor 门禁假绿）。现在统一：发现/创建/校验全在本模块。
# ---------------------------------------------------------------------------

def _platform_skill_links(root=None):
    """从 manifest [platform.*] 读披露配置，返回全部 (link_path, target_dir)。

    层自动发现：对公司 home（含 company-template 母版）扫「含 skills/ 的目录」
    ——公司根本身 + 一级子目录（E*/T*/templates 下含 skills/ 的实体层）。
    新员工/新团队建好 skills/ 即自动纳入，无需登记（呼应 P7）。
    """
    root = root or _find_root()
    if root is None:
        return []
    g = _load_toml(os.path.join(root, "opc.toml"))
    platforms = [(name, cfg.get("skill_link"))
                 for name, cfg in g.get("platform", {}).items() if cfg.get("skill_link")]
    if not platforms:
        return []
    company_dirs = []
    for cid in all_company_ids(root):
        try:
            company_dirs.append(load_company(cid).home_abs)
        except Exception:
            continue          # 锚断链时 doctor 的锚检查项会报，这里不重复
    tpl = os.path.join(root, "company-template")
    if os.path.isdir(tpl):
        company_dirs.append(tpl)   # 建司母版同样有披露层
    out = []
    for cdir in company_dirs:
        for layer in _skill_layers(cdir):
            for _name, rel in platforms:
                out.append((os.path.join(layer, rel), os.path.join(layer, "skills")))
    return out


def _skill_layers(company_dir):
    """一个公司内所有「技能层」目录（含 skills/ 的）：公司根 + 一级实体子目录。"""
    layers = []
    if not os.path.isdir(company_dir):
        return layers
    if os.path.isdir(os.path.join(company_dir, "skills")):
        layers.append(company_dir)
    for entry in sorted(os.listdir(company_dir)):
        d = os.path.join(company_dir, entry)
        if entry.startswith(".") or not os.path.isdir(d):
            continue
        if os.path.isdir(os.path.join(d, "skills")):
            layers.append(d)
    return layers


def ensure_links(root=None):
    """同步全部 OS 级链接（幂等，可反复跑）：
    ① 稳定锚 companies/<cid> -> 真实公司目录（复用 sync_links）；
    ② 各层技能披露 {层}/.workbuddy/skills -> {层}/skills（按 manifest [platform.*] 配置）。
    返回 (ok_list, err_list)。scripts/link-company 与未来 watcher 都只调本函数。"""
    root = root or _find_root()
    if root is None:
        return [], ["未找到 opc.toml（OPC 根）"]
    ok, err = sync_links(root)
    for link, target in _platform_skill_links(root):
        if _link_resolves_to(link, target):
            continue
        if os.path.lexists(link) and not _remove_link(link):
            err.append(f"{link}: 旧链接无法删除（请人工处理）")
            continue
        os.makedirs(os.path.dirname(link), exist_ok=True)
        try:
            _create_link(link, target)
            ok.append(f"技能披露 {os.path.relpath(link, root)} -> skills/")
        except Exception as e:
            err.append(f"{link}: 建链失败：{e}")
    return ok, err


def check_disclosure_links(root=None):
    """技能披露链接完整性（doctor 第 5 项，error 级）：根治「门禁假绿」——
    披露链接缺失/断链时平台不披露技能，agent 行为退化，此前 doctor 却报全绿。"""
    root = root or _find_root()
    issues = []
    for link, target in _platform_skill_links(root):
        rel = os.path.relpath(link, root) if root else link
        if not os.path.lexists(link):
            issues.append(f"技能披露链接缺失：{rel} → 跑 `--ensure-links` 重建")
        elif not _link_resolves_to(link, target):
            issues.append(f"技能披露链接失效/指错：{rel} → 跑 `--ensure-links` 重建")
    return issues


def diff_template(root=None, cid=None):
    """C001 ↔ company-template 双向 diff（2026-08-28 Q5 拍板：机制改动波及面
    「C001/总管/template/根文档」四处同步，靠人记必漂移——机器发现、人工决策）。

    归一化后比较（消除假差异）：
      - 换行符（CRLF/LF）；
      - 公司 ID 占位符：实例侧 `C001` ↔ 模板侧 `<本司ID>` 统一映射为 `<CID>`；
    排除实例专属内容（两边都不比）：实体数据目录 E*/T*/P*、workbench/tasks|archive、
    memory/、workspace/、.workbuddy、看板产物 *-data.js / tasks-data.json、台账/花名册。

    返回 dict：{same: n, diff: [(rel, plus, minus)], only_company: [...], only_template: [...]}。
    """
    root = root or _find_root()
    g = _load_toml(os.path.join(root, "opc.toml"))
    cids = [k for k in g.get("company", {}) if k != "DEFAULT"]
    cid = cid or (cids[0] if cids else None)
    if not cid:
        raise ValueError("manifest 无公司，无可比对实例")
    company_dir = load_company(cid).home_abs
    template_dir = os.path.join(root, "company-template")

    import difflib

    def _norm(text):
        t = text.replace("\r\n", "\n")
        t = (t.replace(f"companies/{cid}", "companies/<CID>")
              .replace(f"opc://company:{cid}", "opc://company:<CID>")
              .replace(cid, "<CID>").replace("<本司ID>", "<CID>")
              .replace("C00x", "<CID>"))   # 模板建司占位符（create-company 问卷用）
        return t

    _EXCL_DIRS = (".git", ".workbuddy", "workbench", "memory", "workspace", "node_modules")
    _EXCL_FILE = re.compile(r"(-data\.js|tasks-data\.json|task-index|roster\.md|patrol-log\.md|"
                            r"patrol-state\.json|patrol-pending\.md|INDEX\.md)$")
    _ENTITY = re.compile(r"^(E\d{3,}|T\d{3,}|P\d{3,})-")

    def _walk(base):
        """收集 {rel_path: abs_path}；workbench 只比 README/KANBAN_ARCHITECTURE 等机制文档，
        tasks/affairs/archive 等数据区排除；实体目录（实例专属）排除，templates/ 骨架保留。"""
        out = {}
        if not os.path.isdir(base):
            return out
        for dirpath, dirs, files in os.walk(base):
            rel_dir = os.path.relpath(dirpath, base)
            parts = [] if rel_dir == "." else rel_dir.split(os.sep)
            if any(p in _EXCL_DIRS or (p and _ENTITY.match(p)) for p in parts):
                dirs[:] = []
                continue
            if "workbench" in parts and parts[-1] != "workbench":
                dirs[:] = []      # workbench 数据子区（tasks/affairs/archive…）不比
            dirs[:] = [d for d in dirs if d not in _EXCL_DIRS and not _ENTITY.match(d)]
            if os.path.basename(dirpath) == "workbench":
                dirs[:] = [d for d in dirs if not _ENTITY.match(d)]
            for fn in files:
                if _EXCL_FILE.search(fn) or fn.endswith(".tmp"):
                    continue
                fp = os.path.join(dirpath, fn)
                rel = os.path.relpath(fp, base).replace(os.sep, "/")
                if rel == "dashboard.html":
                    continue      # 公司根 dashboard.html 是生成产物（模板真身在 page-templates/）
                out[rel] = fp
        return out

    a, b = _walk(company_dir), _walk(template_dir)
    diff, same = [], 0
    for rel in sorted(set(a) & set(b)):
        try:
            ta = _norm(_read_file(a[rel]))
            tb = _norm(_read_file(b[rel]))
        except OSError:
            continue
        if ta == tb:
            same += 1
            continue
        plus = sum(1 for l in difflib.ndiff(ta.splitlines(), tb.splitlines()) if l.startswith("+"))
        minus = sum(1 for l in difflib.ndiff(ta.splitlines(), tb.splitlines()) if l.startswith("-"))
        diff.append((rel, plus, minus))
    return {"cid": cid, "same": same, "diff": diff,
            "only_company": sorted(set(a) - set(b)),
            "only_template": sorted(set(b) - set(a))}


def _read_file(p):
    """读取文本文件，失败返回空串（用于钩子/配置探测）。"""
    try:
        with open(p, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


# 公开别名：跨模块读取文本统一走 read_text（原 _read_file 是私有命名，
# 却被 tickets/dashboards 当公共契约依赖——抽象泄漏，转正为公开 API）。
read_text = _read_file


def _hook_installed(root):
    """pre-commit 是否已装：认 .git/hooks/pre-commit 或 core.hooksPath=scripts 两种方式。"""
    hook = os.path.join(root, ".git", "hooks", "pre-commit")
    if os.path.isfile(hook) and "opc_resolver" in _read_file(hook):
        return True
    try:
        r = subprocess.run(["git", "config", "--get", "core.hooksPath"],
                           cwd=root, capture_output=True, text=True, check=False)
        hooks_path = r.stdout.strip()
    except OSError:
        hooks_path = ""
    if hooks_path:
        candidate = os.path.join(root, hooks_path, "pre-commit")
        if os.path.isfile(candidate) and "opc_resolver" in _read_file(candidate):
            return True
    return False


def install_hook(root=None):
    """安装 pre-commit 门禁（自举化）：把 scripts/pre-commit 复制到 .git/hooks/
    并加执行位。幂等（覆盖写）。返回 (ok, msg)。"""
    root = root or _find_root()
    src = os.path.join(root, "scripts", "pre-commit")
    if not os.path.isfile(src):
        return False, f"找不到 {src}"
    hooks_dir = os.path.join(root, ".git", "hooks")
    os.makedirs(hooks_dir, exist_ok=True)
    dst = os.path.join(hooks_dir, "pre-commit")
    with open(src, "rb") as f:
        data = f.read()
    with open(dst, "wb") as f:
        f.write(data)
    if not sys.platform.startswith("win"):
        os.chmod(dst, 0o755)
    return True, dst


def _repair(root):
    """doctor 自愈段（2026-08-29 拍板「系统自己完成初始化」）：凡是「安全 + 幂等 +
    可自动补」的前置条件，检查前先修——agent 按门禁跑 doctor 的那一刻，
    缺锚建锚、缺披露链接建链接、缺钩子装钩子、缺看板数据重生成。
    返回修复动作列表（供 doctor 打印 [fix] 行）。"""
    fixed = []
    ok, err = ensure_links(root)
    fixed += [f"OS 级链接：{m}" for m in ok if "无需改动" not in m]
    fixed += [f"OS 级链接（异常）：{m}" for m in err]
    if not _hook_installed(root):
        hok, hmsg = install_hook(root)
        if hok:
            fixed.append(f"pre-commit 门禁已装：{hmsg}")
        else:
            fixed.append(f"pre-commit 门禁安装失败：{hmsg}")
    # 看板数据缺失 → 重生成（仅缺产物时，避免每次 doctor 都重算）
    py = sys.executable or "python"
    for cid in all_company_ids(root):
        try:
            cfg = load_company(cid)
        except Exception:
            continue
        if not os.path.isfile(cfg.tasks_data_abs) and os.path.isdir(cfg.workbench_abs):
            for mod in ("opc_tickets.py", "opc_dashboards.py"):
                r = subprocess.run([py, os.path.join(root, mod), "--company", cid],
                                   cwd=root, capture_output=True, text=True, check=False)
                if r.returncode == 0:
                    fixed.append(f"看板数据已重建（{cid} ← {mod}）")
                else:
                    fixed.append(f"看板数据重建失败（{mod}）：{(r.stderr or r.stdout).strip().splitlines()[-1:]}")
    return fixed


def doctor(root=None, auto_fix=True):
    """系统初始化自检（init gate）：检查「系统正常跑」的前置条件。

    返回 (errors, warnings)。用于 agent 开工前门禁——全绿才进入业务。
    自愈（2026-08-29 拍板「系统自己完成初始化」）：auto_fix=True（默认）时，
    检查前先自动补齐安全幂等项（锚 / 技能披露链接 / pre-commit 钩子 / 缺失的
    看板数据），修复动作以 [fix] 行打印——新 clone 后 agent 跑一次 doctor
    即完成自举，不再依赖用户手补。
    退出码：有 error 则 1（阻断），仅 warning 则 0（放行）。
    """
    root = root or _find_root()
    if root is None:
        return ["未找到 opc.toml（OPC 根）——先在 OPC 仓库根目录运行"], []
    errors, warns = [], []
    if auto_fix:
        for m in _repair(root):
            print("[fix]", m)

    # 1. Python 版本 ≥ 3.11（tomllib 依赖）
    if sys.version_info < (3, 11):
        errors.append(f"Python 版本过低 {sys.version.split()[0]}，需 ≥3.11（opc_resolver 依赖 tomllib）")
    else:
        warns.append(f"Python {sys.version.split()[0]} ≥3.11 ✓")

    # 2. 稳定锚 companies/<cid> 存在且指向真实目录（运行时层物理入口）
    g = _load_toml(os.path.join(root, "opc.toml"))
    cids = [k for k in g.get("company", {}) if k != "DEFAULT"]
    if not cids:
        warns.append("opc.toml 无 [company.<cid>] 段（无公司需建锚）")
    for cid in cids:
        link = os.path.join(root, "companies", cid)
        if not os.path.lexists(link):
            errors.append(f"稳定锚缺失：companies/{cid} 不存在 → 跑 `python opc_resolver.py --bootstrap`")
        else:
            real = os.path.realpath(link)
            if not os.path.isdir(real):
                errors.append(f"稳定锚失效：companies/{cid} 未指向有效目录 → 跑 `python opc_resolver.py --bootstrap`")
            else:
                warns.append(f"稳定锚 companies/{cid} -> {real} ✓")

    # 3. pre-commit 门禁（自愈段已尝试安装；仍缺则提示手动）
    if _hook_installed(root):
        warns.append("pre-commit 门禁已装 ✓")
    else:
        warns.append("pre-commit 门禁未装（提交前不拦截失效引用）→ 跑 `python opc_resolver.py --bootstrap`")

    # 3b. 公司心跳（机器级状态：不自动注册——CI/临时环境不应写系统定时任务；缺失仅提示）
    try:
        import opc_patrol
        for cid in cids:
            if opc_patrol.heartbeat_registered(root, cid):
                warns.append(f"公司心跳已挂 ✓（{opc_patrol.heartbeat_task_name(cid)}，定期巡检+数据自愈+系统通知）")
            else:
                warns.append(f"公司心跳未挂（定期巡检与异常通知不会运行）→ `python opc_patrol.py --register-heartbeat --company {cid}` 或 --bootstrap")
    except Exception:
        pass

    # 4. 命名空间全文扫描（核心，失效即阻断）
    iss = check_links()
    if iss:
        errors.append(f"命名空间存在 {len(iss)} 处失效引用 → 跑 `python opc_resolver.py --check` 查看并修")
    else:
        warns.append("命名空间全文扫描自洽 ✓")

    # 5. OS 级链接完整性（稳定锚已在第 2 项；这里查各层技能披露，缺失即阻断——防门禁假绿）
    disc = check_disclosure_links(root)
    if disc:
        errors.extend(disc)
    else:
        warns.append("技能披露链接完整 ✓")

    return errors, warns


def bootstrap(root=None, heartbeat=True, heartbeat_every=30):
    """一键自举（2026-08-29 拍板「系统自己完成初始化，不依赖用户操作」）：
    新 clone / 新电脑上把全部「事先准备」自动做完——
      ① OS 级链接（稳定锚 + 各层技能披露，ensure_links）
      ② pre-commit 门禁钩子（install_hook）
      ③ 看板数据重建（opc_tickets / opc_dashboards，产物不入库 clone 后必缺）
      ④ 技能索引（opc_model --sync-index，INDEX.md 生成物）
      ⑤ 公司心跳（每 30 分钟：Windows 计划任务 / macOS·Linux crontab，按公司隔离；
         heartbeat=False 跳过——唯一的机器级副作用，故可关）
    最后跑 doctor 终检（其自愈段兜底）。返回 (errors, warnings)。
    """
    root = root or _find_root()
    if root is None:
        print("[ERR] 未找到 opc.toml（OPC 根）——请在 OPC 仓库根运行")
        return ["未找到 opc.toml"], []
    print("[init] OPC 自举开始……")
    py = sys.executable or "python"
    cids = all_company_ids(root)

    # ① ② doctor 自愈段统一做（幂等，结果随终检打印）；这里先补数据与索引：
    for cid in cids:
        for mod in ("opc_tickets.py", "opc_dashboards.py"):
            r = subprocess.run([py, os.path.join(root, mod), "--company", cid],
                               cwd=root, capture_output=True, text=True, check=False)
            tail = (r.stdout or r.stderr or "").strip().splitlines()
            print(f"[init] {mod} --company {cid} ->", "ok" if r.returncode == 0
                  else f"FAILED（{tail[-1] if tail else r.returncode}）")
    r = subprocess.run([py, os.path.join(root, "opc_model.py"), "--sync-index"],
                       cwd=root, capture_output=True, text=True, check=False)
    print("[init] opc_model --sync-index ->", "ok" if r.returncode == 0 else "FAILED")

    # ⑤ 心跳（唯一机器级副作用；默认注册，可 --no-heartbeat 关闭）
    if heartbeat and cids:
        import opc_patrol   # 运行时惰性导入（patrol 依赖本模块，避免环）
        for cid in cids:
            ok, msg = opc_patrol.register_heartbeat(root, cid, every=heartbeat_every)
            print(("[init] 心跳已挂：" if ok else "[init] 心跳注册失败：")
                  + f"{msg}" + ("" if ok else "（不影响本地使用，可稍后手动挂）"))
    elif not cids:
        print("[init] 无公司，跳过心跳与看板重建")

    errs, ws = doctor(root, auto_fix=True)
    print(f"[init] 自举完成：{'全绿 ✓' if not errs else f'{len(errs)} 项未过（见上）'}"
          + ("" if heartbeat and cids else f"（未挂心跳：--heartbeat-every 分钟 / 默认 {heartbeat_every}）"))
    return errs, ws


# ---------------------------------------------------------------------------
# selftest：核心解析行为的内置回归测试（临时目录，不碰真实数据）
# ---------------------------------------------------------------------------

def selftest():
    import tempfile
    ok = True

    def check(name, cond):
        nonlocal ok
        print(("  ✓ " if cond else "  ✗ ") + name)
        if not cond:
            ok = False

    print("运行内置自测…")
    # 0) 实体类型注册表：内置默认 + manifest 覆盖通道
    reg = entity_types()
    check("实体注册表默认三件套", reg == {"employee": "E", "team": "T", "project": "P"})
    # 1) URI 解析：未知公司必须报错（绝不静默返回假路径）
    try:
        resolve("opc:" + "//company:C999_NOPE/workbench")
        check("未知公司报错", False)
    except FileNotFoundError:
        check("未知公司报错", True)
    # 2) skill 不存在必须报错（原版静默拼接漏网）
    try:
        resolve_entity("C001", "skill", "不存在的技能" + "XYZ")
        check("不存在 skill 报错", False)
    except FileNotFoundError:
        check("不存在 skill 报错", True)
    # 3) 真实 skill 存在 → 解析成功
    try:
        p = resolve("opc:" + "//company:C001/skill/ticket-system")
        check("存在 skill 解析", os.path.isdir(p))
    except Exception:
        check("存在 skill 解析", False)
    # 4) 子路径不再被截断（原版 opc://.../skill/x/SKILL.md 静默丢 SKILL.md）
    try:
        p = resolve("opc:" + "//company:C001/skill/ticket-system/SKILL.md")
        check("实体子路径保留", os.path.isfile(p) and p.endswith("SKILL.md"))
    except Exception:
        check("实体子路径保留", False)
    # 5) 不存在的子路径报错
    try:
        resolve("opc:" + "//company:C001/skill/ticket-system/不存在.md")
        check("不存在子路径报错", False)
    except FileNotFoundError:
        check("不存在子路径报错", True)
    # 6) 实体类型前缀校验（team 配 E 编号必须拒绝）
    try:
        resolve("opc:" + "//company:C001/team/E0000")
        check("类型前缀校验", False)
    except ValueError:
        check("类型前缀校验", True)
    # 7) 真实实体解析（employee E0000）
    try:
        p = resolve("opc:" + "//company:C001/employee/E0000")
        check("实体解析 employee/E0000", os.path.isdir(p))
    except Exception:
        check("实体解析 employee/E0000", False)
    # 8) 不支持 scheme 报错（文档别名 opc:/@ 未实现，不得静默）
    try:
        resolve("opc:" + ":skill/ticket-system")
        check("别名 scheme 报错", False)
    except ValueError:
        check("别名 scheme 报错", True)
    # 9) 扫描器：中文标点不吸入 URI
    m = _REF_RE.search("见 opc:" + "//company:C001/roster。后续")
    check("中文句号不吸入", m is None or not m.group(0).endswith("。"))
    # 10) 扫描器：GBK 文件中的引用仍可发现（latin-1 兜底）
    with tempfile.TemporaryDirectory() as tmp:
        gb = os.path.join(tmp, "gb.md")
        with open(gb, "w", encoding="gbk") as fh:
            fh.write("引用 opc://company:C001/workbench 测试\n")
        found = scan_refs(tmp)
        check("GBK 文件引用可发现", "opc://company:C001/workbench" in found)
        # 中文标点场景再验一次文件级
        cn = os.path.join(tmp, "cn.md")
        with open(cn, "w", encoding="utf-8") as fh:
            fh.write("见 opc://company:C001/roster。完\n")
        found2 = scan_refs(tmp)
        uris = [u for u in found2 if u.startswith("opc://company:C001/roster")]
        check("正文句号后缀不吸入", all(not u.endswith("。") for u in uris))
    print("自测" + ("全部通过 ✓" if ok else "存在失败 ✗"))
    return 0 if ok else 1


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8", errors="replace")   # Windows cp1252 控制台/CI 下中文输出防崩（CI 实测）
    import argparse
    ap = argparse.ArgumentParser(description="OPC 命名空间解析 / 链接器自检")
    ap.add_argument("--check", action="store_true", help="校验命名空间路径自洽（含全文扫描）")
    ap.add_argument("--ensure-links", action="store_true",
                    help="同步全部 OS 级链接（稳定锚 + 各层技能披露；幂等，clone/改名后跑一次）")
    ap.add_argument("--sync-links", action="store_true",
                    help="--ensure-links 的别名（兼容 scripts/link-company 与既有文档）")
    ap.add_argument("--company", default=None, help="公司 id（--check 默认遍历全部公司）")
    ap.add_argument("--resolve", help="解析单个 opc:// URI 并打印绝对路径")
    ap.add_argument("--doctor", action="store_true",
                    help="系统初始化自检（init gate，带自愈）：自动补齐锚/披露链接/钩子/缺失看板数据后检查五项，全绿才开工")
    ap.add_argument("--bootstrap", action="store_true",
                    help="一键自举（新 clone/新电脑跑一次）：链接+钩子+看板数据+技能索引+公司心跳，最后 doctor 终检")
    ap.add_argument("--no-heartbeat", action="store_true", help="--bootstrap 跳过心跳注册")
    ap.add_argument("--heartbeat-every", default="30", help="心跳间隔（分钟，默认 30；配合通知去重只报新发现）")
    ap.add_argument("--diff-template", action="store_true",
                    help="实例公司 ↔ company-template 双向 diff（忽略换行符与公司 ID 占位符；机器发现、人工决策）")
    ap.add_argument("--selftest", action="store_true", help="内置自测（临时目录，不碰真实数据）")
    a = ap.parse_args()

    if a.resolve:
        print(resolve(a.resolve))
    elif a.diff_template:
        r = diff_template()
        print(f"[diff-template] 实例 {r['cid']} ↔ company-template（忽略换行符与 <CID> 占位符）")
        print(f"  一致：{r['same']} 份")
        if r["diff"]:
            print(f"  实质差异 {len(r['diff'])} 份（+ = 模板多此行 / - = 实例多此行）：")
            for rel, plus, minus in r["diff"]:
                print(f"    - {rel}（实例多 {minus} 行 / 模板多 {plus} 行）")
        if r["only_company"]:
            print(f"  仅实例有：{len(r['only_company'])} 份")
            for rel in r["only_company"]:
                print(f"    - {rel}")
        if r["only_template"]:
            print(f"  仅模板有：{len(r['only_template'])} 份")
            for rel in r["only_template"]:
                print(f"    - {rel}")
        if not (r["diff"] or r["only_company"] or r["only_template"]):
            print("  [ok] 双向零实质差异")
    elif a.selftest:
        sys.exit(selftest())
    elif a.bootstrap:
        errs, ws = bootstrap(heartbeat=not a.no_heartbeat, heartbeat_every=int(a.heartbeat_every))
        for w in ws:
            print("[i]", w)
        for e in errs:
            print("[✗]", e)
        sys.exit(1 if errs else 0)
    elif a.sync_links or getattr(a, "ensure_links", False):
        ok, err = ensure_links()
        for line in ok:
            print("[ok]", line)
        for line in err:
            print("[ERR]", line)
        if err:
            sys.exit(1)
        print("[done] OS 级链接同步完成（稳定锚 + 技能披露）")
    elif a.doctor:
        errs, ws = doctor()
        for w in ws:
            print("[i]", w)
        for e in errs:
            print("[✗]", e)
        if errs:
            print(f"[FAIL] 初始化自检未通过（{len(errs)} 项）：先按 README「系统初始化」章节补齐再开工")
            sys.exit(1)
        print("[ok] 初始化自检通过：可正常开工")
    elif a.check:
        iss = check_links(a.company)
        if iss:
            print("链接器报错：")
            for i in iss:
                print("  -", i)
            sys.exit(1)
        print(f"[ok] 命名空间自洽：扫描全项目 opc:// 引用均无失效")
