"""Build and verify a sanitized publication clone; upload requires --push."""
import opc_runtime
opc_runtime.ensure_supported()
import argparse
import inspect
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import opc_privacy


def run(cwd, *args, timeout=300):
    p = subprocess.run(list(args), cwd=cwd, capture_output=True, timeout=timeout)
    if p.returncode:
        raise RuntimeError(f'{args[0]} failed ({p.returncode}): ' + (p.stdout + p.stderr).decode('utf-8', 'replace')[-5000:])
    return p.stdout


def filename_callback(patterns, entity_ids):
    return ('import fnmatch\nPRIVATE_SEGMENTS = ' + repr(opc_privacy.PRIVATE_SEGMENTS) + '\n'
            + inspect.getsource(opc_privacy.private_path)
            + '\nreturn None if private_path(filename.decode("utf-8", "surrogateescape"), '
            + repr(patterns) + ', ' + repr(entity_ids) + ') else filename\n')


def verify_history(build, patterns, entity_ids):
    commits = run(build, 'git', 'rev-list', '--all').decode().splitlines()
    if not commits:
        raise RuntimeError('Publication has no commits')
    checked = set()
    for commit in commits:
        tree = run(build, 'git', 'rev-parse', commit + '^{tree}').strip()
        if tree in checked:
            continue
        checked.add(tree)
        paths = run(build, 'git', 'ls-tree', '-rz', '--name-only', commit).split(b'\0')
        if any(p and opc_privacy.private_path(p.decode('utf-8', 'surrogateescape'), patterns, entity_ids) for p in paths):
            raise RuntimeError(f'Private paths remain in publication commit {commit}')
    return {'commits_checked': len(commits), 'trees_checked': len(checked), 'private_paths': 0}


def build_release(root, parent=None, overlay=False):
    root = Path(root).resolve()
    patterns, entity_ids = opc_privacy.policy(root)
    run(root, sys.executable, '-m', 'git_filter_repo', '--version')
    parent = Path(parent or root / '_AI工作区' / '发布构建')
    parent.mkdir(parents=True, exist_ok=True)
    build = Path(tempfile.mkdtemp(prefix='release-', dir=parent))
    run(root, 'git', 'clone', '--no-local', '--single-branch', '--no-tags', '--branch', 'main', str(root), str(build))
    run(build, sys.executable, '-m', 'git_filter_repo', '--force',
        '--filename-callback', filename_callback(patterns, entity_ids),
        '--message-callback', 'return b"OPC public revision\\n"',
        '--name-callback', 'return b"OPC contributors"',
        '--email-callback', 'return b"opc@users.noreply.github.com"')
    result = verify_history(build, patterns, entity_ids)
    if overlay:
        for directory, dirs, names in os.walk(root):
            rel = Path(directory).relative_to(root)
            dirs[:] = [d for d in dirs if d not in {'.git', '__pycache__', 'companies', '.claude', '.agents', '.codex', 'node_modules'}
                       and not (Path(directory) / d).is_symlink()
                       and ((rel / d).as_posix() in {"_AI工作区", "_AI工作区/回归测试"} or not opc_privacy.private_path((rel / d).as_posix(), patterns, entity_ids))]
            for name in names:
                src, target = Path(directory) / name, rel / name
                if src.is_symlink() or opc_privacy.private_path(target.as_posix(), patterns, entity_ids):
                    continue
                dst = build / target
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
    run(build, sys.executable, 'opc_resolver.py', '--ensure-links')
    run(build, sys.executable, 'opc_resolver.py', '--check')
    result.update(build=str(build), working_preview=overlay, pushed=False)
    return result


def public_target(root):
    remote = opc_privacy._git(root, "config", "--get", "opc.publicRemote") or "origin"
    urls = opc_privacy._git(root, "remote", "get-url", "--push", "--all", remote).splitlines()
    if len(urls) != 1 or not urls[0]:
        raise RuntimeError("Exactly one configured public push URL is required")
    url = urls[0]
    refs = run(root, "git", "ls-remote", url, "refs/heads/main").decode().splitlines()
    expected = refs[0].split()[0] if refs else ""
    return url, expected


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--push', action='store_true')
    parser.add_argument('--preview-working', action='store_true', help='offline preview of uncommitted fixes; never upload')
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    if args.push and args.preview_working:
        parser.error('--push cannot be combined with --preview-working')
    if args.push:
        if run(root, 'git', 'status', '--porcelain', '--untracked-files=normal').strip():
            raise RuntimeError('Commit reviewed source changes before publishing')
        if run(root, 'git', 'branch', '--show-current').strip() != b'main':
            raise RuntimeError('Publication must run from committed main')
    target = public_target(root) if args.push else None
    result = build_release(root, overlay=args.preview_working)
    if args.push:
        url, expected = target
        run(result['build'], 'git', 'push', '--force-with-lease=refs/heads/main:' + expected,
            url, 'HEAD:refs/heads/main')
        published = run(result['build'], 'git', 'rev-parse', 'HEAD').decode().strip()
        remote_refs = run(result['build'], 'git', 'ls-remote', url, 'refs/heads/main').decode().split()
        if not remote_refs or remote_refs[0] != published:
            raise RuntimeError('Remote revision verification failed after publication')
        result['published_commit'] = published
        result['previous_public_commit'] = expected
        result['pushed'] = True
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    opc_runtime.configure_output()
    try:
        main()
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(f'Publication stopped: {exc}', file=sys.stderr)
        raise SystemExit(1)
