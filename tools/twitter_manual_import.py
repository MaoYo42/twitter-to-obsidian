from __future__ import annotations

import argparse
import re
from pathlib import Path

from common import URLS_FILE, append_urls_to_markdown


URL_RE = re.compile(r"https?://(?:www\.)?(?:x|twitter)\.com/[^/\s]+/status/\d+")


def extract_urls(text: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for url in URL_RE.findall(text):
        if url not in seen:
            seen.add(url)
            ordered.append(url)
    return ordered


def main() -> None:
    parser = argparse.ArgumentParser(description="从文本或文件中提取 X/Twitter URL 并写入收件箱")
    parser.add_argument("--file", help="从本地文本文件读取")
    parser.add_argument("--text", help="直接传入一段包含 URL 的文本")
    args = parser.parse_args()

    if args.file:
        text = Path(args.file).read_text(encoding="utf-8")
    elif args.text:
        text = args.text
    else:
        text = input("把包含 URL 的文本粘贴进来后回车：\n")

    urls = extract_urls(text)
    append_urls_to_markdown(urls, URLS_FILE)
    print(f"imported={len(urls)} inbox={URLS_FILE}")


if __name__ == "__main__":
    main()
