"""Private path policy and fail-closed push guard; no network writes."""
import fnmatch
import os
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import urlsplit
PRIVATE_SEGMENTS = {"private", "私密", "个人", "memory", "workspace", "_AI工作区", ".workbuddy", ".zcode", ".claude", ".codex", ".agents", ".opc-sync", ".opc-data"}
def private_path(path, patterns=(), entity_ids=()):
    # Versioned synthetic regression; no user data.
    if path.replace(chr(92), "/").strip("/") == "_AI工作区/回归测试/test_runtime.py":
        return False
    parts = path.replace("\\", "/").strip("/").split("/")
    if any(p.casefold() in {segment.casefold() for segment in PRIVATE_SEGMENTS} for p in parts):
        return True
    if any(any(p == eid or p.startswith(eid + "-") for p in parts) for eid in entity_ids):
        return True
    normalized = "/".join(parts)
    for rule in patterns:
        rule = rule.replace(chr(92), "/").strip("/")
        if fnmatch.fnmatchcase(normalized, rule):
            return True
        if not any(char in rule for char in "*?[") and normalized.startswith(rule + "/"):
            return True
    return False
def policy(root):
    import opc_resolver
    root = Path(root)
    patterns = [s.strip() for s in (root / ".opc-private-paths.txt").read_text(encoding="utf-8").splitlines() if s.strip() and not s.lstrip().startswith("#")]
    return patterns, [key.split("/")[-1] for key in opc_resolver.private_entities(str(root))]
def normalize_remote(value):
    value = value.strip().rstrip("/")
    if "://" in value:
        u = urlsplit(value)
        value = (u.hostname or "").lower() + "/" + u.path.lstrip("/")
    elif re.match(r"^[^/]+@[^:]+:", value):
        host, path = value.split(":", 1)
        value = host.split("@")[-1].lower() + "/" + path
    else:
        value = os.path.normcase(os.path.abspath(os.path.expanduser(value)))
    return value[:-4] if value.endswith(".git") else value
def _git(root, *args):
    p = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=10)
    return p.stdout.strip() if p.returncode == 0 else ""
def push_allowed(remote, url, public_name, public_urls, private_name="", private_url=""):
    if not public_name or not public_urls:
        return False
    urls = {normalize_remote(u) for u in public_urls if u}
    if remote == public_name or normalize_remote(url) in urls:
        return False
    return bool(private_name and remote == private_name and private_url and normalize_remote(url) == normalize_remote(private_url))
def guard(root, remote, url):
    public_name = _git(root, "config", "--get", "opc.publicRemote") or "origin"
    public_urls = _git(root, "remote", "get-url", "--push", "--all", public_name).splitlines()
    fetch_url = _git(root, "remote", "get-url", public_name)
    if fetch_url:
        public_urls.append(fetch_url)
    private_name = _git(root, "config", "--get", "opc.privateRemote")
    private_url = _git(root, "remote", "get-url", "--push", private_name) if private_name else ""
    if push_allowed(remote, url, public_name, public_urls, private_name, private_url):
        return 0
    print("⛔ 工作仓库拒绝公开或未经登记的推送。公开发布使用 scripts/opc-publish；私有备份需显式登记 opc.privateRemote。", file=sys.stderr)
    return 1
if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--guard":
        raise SystemExit(guard(Path(__file__).resolve().parent, sys.argv[2], sys.argv[3]))
    raise SystemExit("usage: opc_privacy.py --guard REMOTE URL")
