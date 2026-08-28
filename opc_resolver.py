#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
opc_resolver —— OPC 命名空间解析器（DI 容器 / 依赖倒置的落点）

职责（单一，不碰业务逻辑）：
  - 从 opc.toml（全局单例）+ 公司级覆盖，合并出「逻辑符号 -> 物理路径」映射
  - 把 opc:// URI 解析成真实文件系统路径（支持 company 范围实体 + org 范围文档）
  - check_links：链接器自检（全文扫描所有 opc:// 引用，改名后跑一次列出失效点）

高层 consumer（generate_dashboard.py / AGENTS.md / skill 指令）只依赖 opc:// 符号，
物理路径（目录名、布局）全部下沉到 opc.toml。改目录名 = 只改 opc.toml 一行。

零第三方依赖：仅标准库（tomllib, Python 3.11+）。
"""
import os
import re
import sys
import tomllib
import subprocess


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
        try:
            with open(md, encoding="utf-8") as f:
                txt = f.read()
        except OSError:
            continue
        m = re.search(r'公司\s*ID\s*[:：]\s*(\S+)', txt)
        if m and m.group(1).strip() == cid:
            return d
    return None


def load_company(cid):
    """读全局 + 公司级覆盖，合并返回 CompanyConfig（DI：细节在此注入）。

    自愈：opc.toml 的 home（物理路径）失效时，按 company.md 的「公司 ID」
    扫描发现真实目录——手动改公司目录名、忘了改 manifest 也能自动定位。
    """
    root = _find_root()
    if root is None:
        raise FileNotFoundError("未找到 opc.toml（OPC 根）")
    g = _load_toml(os.path.join(root, "opc.toml"))
    defaults = g.get("company", {}).get("DEFAULT", {})
    override = g.get("company", {}).get(cid, {})
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

def resolve_entity(cid, etype, eid):
    """opc://company:C001/<type>/<id> -> 绝对路径。"""
    cfg = load_company(cid)
    home = cfg.home_abs

    if etype == "skill":
        # 约定式：{home}/{skills}/{name}
        base = cfg._m.get("skills", "skills")
        return os.path.join(home, base, eid)

    if etype in ("team", "project", "employee"):
        # 扫描发现式：home 下找 {id}-* 目录（实体即目录，id 是稳定前缀）
        if not os.path.isdir(home):
            raise FileNotFoundError(f"公司根不存在：{home}")
        for entry in sorted(os.listdir(home)):
            if entry.startswith(eid + "-") or entry == eid:
                return os.path.join(home, entry)
        raise FileNotFoundError(
            f"未找到实体 {etype}:{eid}（扫描 {home} 无匹配 {eid}-*）")

    # 兼容 key 模式透传（opc://company:C001/workbench 等）
    if etype in cfg._m:
        return cfg._abs(etype)

    raise ValueError(f"不支持的实体类型：{etype}")


def resolve(uri):
    """opc://... -> 绝对路径。支持 company 范围（key / 实体）与 org 范围文档。"""
    if uri.startswith("opc://company:"):
        rest = uri[len("opc://company:"):]
        cid, _, path = rest.partition("/")
        parts = [p for p in path.split("/") if p]
        if len(parts) == 0:
            return load_company(cid).home_abs
        if len(parts) == 1:
            return load_company(cid)._abs(parts[0])
        return resolve_entity(cid, parts[0], parts[1])

    if uri.startswith("opc://org"):
        # org 范围：OPC 根下文档，按 name 归一下前缀（去非字母数字、大小写不敏感）发现
        name = uri[len("opc://org"):].lstrip("/")
        root = _find_root()
        if not name:
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

    raise ValueError(f"不支持的 URI 方案：{uri}")


# ---------------------------------------------------------------------------
# 链接器自检（check-links）：全文扫描所有 opc:// 引用
# ---------------------------------------------------------------------------

_REF_RE = re.compile(r'opc://[A-Za-z0-9_:<>\-/][^\s"`\'\)\]\}>]*')


def scan_refs(root):
    """遍历 root，收集所有文件里的 opc:// 引用 -> {uri: [(file, line), ...]}。"""
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
                with open(fp, encoding="utf-8") as f:
                    for i, line in enumerate(f, 1):
                        for m in _REF_RE.finditer(line):
                            uri = m.group(0)
                            if "<" in uri or ">" in uri:   # 文档示例占位，跳过
                                continue
                            if "..." in uri:                # 省略号示例（opc://company:C001/...），跳过
                                continue
                            refs.setdefault(uri, []).append((fp, i))
            except (UnicodeDecodeError, OSError):
                pass
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
        try:
            txt = open(md, encoding="utf-8").read()
        except OSError:
            issues.append(f"{entry}/company.md 不可读")
            continue
        m = re.search(r'公司\s*ID\s*[:：]\s*(\S+)', txt)
        if not m:
            issues.append(f"{entry}/company.md 缺「公司 ID」声明，无法被发现")
            continue
        cid = m.group(1).strip()
        if known_cids and cid not in known_cids:
            issues.append(
                f"{entry}/company.md 声明公司 ID={cid}，但 opc.toml 无 [company.{cid}] 段")
    return issues


def check_links(cid="C001", root=None):
    """链接器自检：① manifest 定义的 key 必须物理存在；② 全文 opc:// 引用必须可解析；③ 结构审计（锚点）。"""
    root = root or _find_root()
    issues = []

    # ① manifest 自身定义的 key 物理存在性（即便暂时无人引用）
    try:
        cfg = load_company(cid)
        for key in ["workbench", "tasks_data", "roster",
                    "affairs", "page_templates", "skills"]:
            try:
                p = cfg._abs(key)
            except KeyError:
                issues.append(f"未定义符号：opc://company:{cid}/{key}")
                continue
            if not os.path.exists(p):
                issues.append(f"失效引用：opc://company:{cid}/{key} -> {p}（不存在）")
    except Exception as e:
        issues.append(f"加载公司 {cid} 失败：{e}")

    # ② 全文扫描所有 opc:// 引用，逐个解析
    refs = scan_refs(root)
    for uri in sorted(refs):
        try:
            resolve(uri)
        except Exception as e:
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
    """
    if sys.platform.startswith("win"):
        # mklink 是 cmd 内建命令，必须经 cmd /c；路径加引号以兼容空格/中文
        cmd = f'mklink /J "{link}" "{target}"'
        subprocess.run(cmd, shell=True, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        os.symlink(target, link, target_is_directory=True)


def _remove_link(link):
    """安全删除链接本身（不碰目标）。兼容 symlink / junction（含断链）。
    companies/ 是受管锚命名空间，内部链接由本函数独占重建，安全。
    """
    for fn in (
        lambda: os.unlink(link),
        lambda: os.rmdir(link),
        lambda: subprocess.run(
            ["cmd", "/c", "rmdir", link], shell=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False),
    ):
        try:
            fn()
            return
        except OSError:
            continue
        except Exception:
            continue


def _link_resolves_to(link, target):
    """link 是否已指向 target（断链/不存在返回 False）。"""
    try:
        return os.path.realpath(link) == os.path.realpath(target)
    except OSError:
        return False


def sync_links(root=None):
    """重新同步所有公司的稳定锚 companies/<cid> -> 真实目录。

    发现逻辑（不依赖手动输入）：
      - 先试 opc.toml 的 home（已是 companies/<cid> 或真实存在的目录）；
      - home 失效/不存在（如真实目录被改名）→ 按 company.md 的「公司 ID」扫描发现真实位置。
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
        home_rel = companies[cid].get("home")
        target = None
        if home_rel:
            cand = os.path.join(root, home_rel)
            if os.path.isdir(cand) and not _link_resolves_to(cand, os.path.join(link_root, cid)):
                target = cand
        if target is None:
            target = _discover_company_home(cid, root)
        if target is None:
            err.append(f"{cid}: 未发现真实目录（home 失效且无 company.md ID 匹配）")
            continue

        link = os.path.join(link_root, cid)
        if _link_resolves_to(link, target):
            ok.append(f"{cid}: 已指向 {target}（无需改动）")
            continue
        _remove_link(link)          # 断链/错指都安全移除（companies/ 受管）
        _create_link(link, target)
        ok.append(f"{cid}: 重指向 -> {target}")
    return ok, err


def _read_file(p):
    """读取文本文件，失败返回空串（用于钩子/配置探测）。"""
    try:
        with open(p, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return ""


def doctor(root=None):
    """系统初始化自检（init gate）：检查「系统正常跑」的前置条件。

    返回 (errors, warnings)。用于 agent 开工前门禁——全绿才进入业务；
    不绿按 README「系统初始化」章节补齐（建锚 / 装钩子 / 修失效引用）。
    退出码：有 error 则 1（阻断），仅 warning 则 0（放行）。
    """
    root = root or _find_root()
    if root is None:
        return ["未找到 opc.toml（OPC 根）——先在 OPC 仓库根目录运行"], []
    errors, warns = [], []

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
            errors.append(f"稳定锚缺失：companies/{cid} 不存在 → 跑 `python opc_resolver.py --sync-links`")
        else:
            real = os.path.realpath(link)
            if not os.path.isdir(real):
                errors.append(f"稳定锚失效：companies/{cid} 未指向有效目录 → 跑 `python opc_resolver.py --sync-links`")
            else:
                warns.append(f"稳定锚 companies/{cid} -> {real} ✓")

    # 3. pre-commit 门禁（开发期便利，warn 不阻断运行时）
    hook = os.path.join(root, ".git", "hooks", "pre-commit")
    if os.path.isfile(hook) and "opc_resolver" in _read_file(hook):
        warns.append("pre-commit 门禁已装 ✓")
    else:
        warns.append("pre-commit 门禁未装（提交前不拦截失效引用）→ `cp scripts/pre-commit .git/hooks/`")

    # 4. 命名空间全文扫描（核心，失效即阻断）
    iss = check_links()
    if iss:
        errors.append(f"命名空间存在 {len(iss)} 处失效引用 → 跑 `python opc_resolver.py --check` 查看并修")
    else:
        warns.append("命名空间全文扫描自洽 ✓")

    return errors, warns


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="OPC 命名空间解析 / 链接器自检")
    ap.add_argument("--check", action="store_true", help="校验命名空间路径自洽（含全文扫描）")
    ap.add_argument("--sync-links", action="store_true",
                    help="同步稳定锚：重指向 companies/<cid> 到真实目录（零参数，靠 company.md ID 发现）")
    ap.add_argument("--company", default="C001", help="公司 id")
    ap.add_argument("--resolve", help="解析单个 opc:// URI 并打印绝对路径")
    ap.add_argument("--doctor", action="store_true",
                    help="系统初始化自检（init gate）：检查 Python 版本/稳定锚/pre-commit/命名空间，全绿才开工")
    a = ap.parse_args()

    if a.resolve:
        print(resolve(a.resolve))
    elif a.sync_links:
        ok, err = sync_links()
        for line in ok:
            print("[ok]", line)
        for line in err:
            print("[ERR]", line)
        if err:
            sys.exit(1)
        print("[done] 稳定锚同步完成")
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
