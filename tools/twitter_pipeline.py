from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


TOOLS_DIR = Path(__file__).resolve().parent


def run_step(name: str, args: list[str]) -> int:
    command = [sys.executable, str(TOOLS_DIR / name), *args]
    completed = subprocess.run(command)
    return completed.returncode


def main() -> None:
    parser = argparse.ArgumentParser(description="运行 Twitter 自动化三阶段流程")
    parser.add_argument("--input-json", help="阶段一使用本地 JSON 作为输入")
    parser.add_argument("--snapshot", action="store_true", help="阶段一保存快照")
    parser.add_argument("--yes", action="store_true", help="跳过阶段二后的确认")
    parser.add_argument("--keep-inbox", action="store_true", help="阶段二结束后保留 Twitter-URLs.md")
    parser.add_argument("--skip-ingest", action="store_true", help="跳过阶段一，直接消费收件箱里的 URL")
    args = parser.parse_args()

    if not args.skip_ingest:
        ingest_args: list[str] = []
        if args.input_json:
            ingest_args.extend(["--input-json", args.input_json])
        if args.snapshot:
            ingest_args.append("--snapshot")

        if run_step("twitter_ingest.py", ingest_args) != 0:
            raise SystemExit(1)

    fetch_args = [] if args.keep_inbox else ["--clear-inbox"]
    if run_step("twitter_fetch.py", fetch_args) != 0:
        raise SystemExit(1)

    if not args.yes:
        reply = input("阶段二已完成，继续执行阶段三分流吗？[y/N] ").strip().lower()
        if reply not in {"y", "yes"}:
            print("已停止在阶段二。")
            return

    if run_step("twitter_route.py", []) != 0:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
