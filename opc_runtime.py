"""Choose a supported interpreter before importing Python 3.11-only modules."""
import os
import shutil
import subprocess
import sys

def configure_output():
    """CLI output is UTF-8 even when Windows pipes default to an ANSI codepage."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

def supported_python():
    candidates = []
    if os.environ.get("OPC_PYTHON"):
        candidates.append([os.environ["OPC_PYTHON"]])
    candidates.append([sys.executable])
    for name in ("python3", "python", "python3.14", "python3.13", "python3.12", "python3.11"):
        path = shutil.which(name)
        if path:
            candidates.append([path])
    if sys.platform.startswith("win") and shutil.which("py"):
        candidates.append([shutil.which("py"), "-3"])
    seen = set()
    for command in candidates:
        if tuple(command) in seen:
            continue
        seen.add(tuple(command))
        try:
            result = subprocess.run(command + ["-c", "import sys; print(sys.executable); sys.exit(sys.version_info < (3,11))"], capture_output=True, text=True, timeout=5)
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip().splitlines()[-1]
        except (OSError, subprocess.TimeoutExpired):
            continue
    raise RuntimeError("OPC 需要 Python >= 3.11；请安装后设置 OPC_PYTHON 为解释器路径。")

def ensure_supported():
    if sys.version_info >= (3, 11):
        return
    try:
        executable = supported_python()
    except RuntimeError as exc:
        raise SystemExit(str(exc))
    os.execv(executable, [executable] + sys.argv)

if __name__ == "__main__":
    configure_output()
    print(supported_python())
