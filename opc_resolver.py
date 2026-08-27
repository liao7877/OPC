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


def check_links(cid="C001", root=None):
    """链接器自检：① manifest 定义的 key 必须物理存在；② 全文 opc:// 引用必须可解析。"""
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

    return issues


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="OPC 命名空间解析 / 链接器自检")
    ap.add_argument("--check", action="store_true", help="校验命名空间路径自洽（含全文扫描）")
    ap.add_argument("--company", default="C001", help="公司 id")
    ap.add_argument("--resolve", help="解析单个 opc:// URI 并打印绝对路径")
    a = ap.parse_args()

    if a.resolve:
        print(resolve(a.resolve))
    elif a.check:
        iss = check_links(a.company)
        if iss:
            print("链接器报错：")
            for i in iss:
                print("  -", i)
            sys.exit(1)
        print(f"[ok] 命名空间自洽：扫描全项目 opc:// 引用均无失效")
