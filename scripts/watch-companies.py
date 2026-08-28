#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""watch-companies.py —— OPC 公司稳定锚监听守护（可选 / 未来启用）

监听 OPC 根下 rename/move/create/delete 事件 -> 防抖 2s -> 调 opc_resolver.py --sync-links。
本脚本只是「触发器外壳」，不含任何「公司在哪」的发现逻辑；发现/重指全部复用 resolver（DIP）。
依赖：pip install watchdog

架构位置（回答「加监听进程是否只需跑脚本」）：
  watcher 监听行为 -> 调 link 脚本（= opc_resolver --sync-links）。业务智能只有一份。
"""
import os
import sys
import time
import subprocess
import threading


def main():
    try:
        from watchdog.observers import Observer
        from watchdog.events import FileSystemEventHandler
    except ImportError:
        sys.exit("缺少依赖 watchdog，请先：pip install watchdog")

    here = os.path.dirname(os.path.abspath(__file__))   # scripts/
    root = os.path.dirname(here)                          # OPC 根
    resolver = os.path.join(root, "opc_resolver.py")
    py = sys.executable
    anchor_dir = os.path.join(root, "companies")

    _timer = None

    def trigger():
        try:
            subprocess.run([py, resolver, "--sync-links"], check=False)
        except Exception as e:  # noqa: BLE001
            print("[watch] sync 失败:", e)

    def schedule():
        global _timer
        if _timer:
            _timer.cancel()
        _timer = threading.Timer(2.0, trigger)
        _timer.start()

    class _H(FileSystemEventHandler):
        def on_any_event(self, event):
            # 只关心 OPC 根一层的事件（公司目录被 rename/move/create/delete 才影响锚）。
            # 非递归监听：公司内部文件写入（worklog 等）与锚无关，不触发 sync；
            # .git 与 companies/ 自身的回写抖动也跳过，避免循环。
            if ".git" in event.src_path or event.src_path.startswith(anchor_dir):
                return
            schedule()

    observer = Observer()
    observer.schedule(_H(), root, recursive=False)
    observer.start()
    print(f"[watch] 监听 {root} 一层（目录 rename/move 触发锚同步；Ctrl+C 退出）")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
