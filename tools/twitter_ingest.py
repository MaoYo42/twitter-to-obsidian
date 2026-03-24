from __future__ import annotations

import argparse
import json
import re
import urllib.parse
from pathlib import Path
from typing import Any

from common import (
    PROCESSED_IDS_FILE,
    URLS_FILE,
    build_bookmark_headers,
    append_urls_to_markdown,
    load_config,
    load_processed_ids,
    log_run,
    normalize_tweet_url,
    request_json,
    save_processed_ids,
    tweet_id_from_url,
    write_json,
)


TWEET_URL_RE = re.compile(r"https?://(?:www\.)?(?:x|twitter)\.com/[^/\s]+/status/\d+")


def walk_json(node: Any) -> list[Any]:
    items = [node]
    if isinstance(node, dict):
        for value in node.values():
            items.extend(walk_json(value))
    elif isinstance(node, list):
        for value in node:
            items.extend(walk_json(value))
    return items


def extract_candidate_urls(data: dict[str, Any]) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()

    for node in walk_json(data):
        if isinstance(node, str):
            for match in TWEET_URL_RE.findall(node):
                if match not in seen:
                    seen.add(match)
                    found.append(match)
        elif isinstance(node, dict):
            expanded = node.get("expanded_url")
            if isinstance(expanded, str) and TWEET_URL_RE.match(expanded) and expanded not in seen:
                seen.add(expanded)
                found.append(expanded)

            rest_id = node.get("rest_id")
            screen_name = (
                node.get("core", {})
                .get("user_results", {})
                .get("result", {})
                .get("legacy", {})
                .get("screen_name")
            )
            if rest_id and screen_name:
                url = f"https://x.com/{screen_name}/status/{rest_id}"
                if url not in seen:
                    seen.add(url)
                    found.append(url)
    return found


def extract_bottom_cursor(data: dict[str, Any]) -> str | None:
    """Extract the 'Bottom' pagination cursor from the bookmarks API response."""
    try:
        entries = data["data"]["bookmark_timeline_v2"]["timeline"]["instructions"][0]["entries"]
        for entry in entries:
            content = entry.get("content", {})
            if content.get("cursorType") == "Bottom":
                return content.get("value")
    except (KeyError, IndexError, TypeError):
        pass
    return None


def build_paginated_url(base_url: str, cursor: str) -> str:
    """Insert a cursor into the bookmarks API URL for pagination."""
    parsed = urllib.parse.urlparse(base_url)
    params = urllib.parse.parse_qs(parsed.query)

    # Decode, inject cursor, re-encode the variables JSON
    variables = json.loads(params["variables"][0])
    variables["cursor"] = cursor
    params["variables"] = [json.dumps(variables, separators=(",", ":"))]

    new_query = urllib.parse.urlencode(params, doseq=True, quote_via=urllib.parse.quote)
    return urllib.parse.urlunparse(parsed._replace(query=new_query))


def fetch_bookmarks_page(request_url: str, headers: dict[str, str], timeout: int) -> dict[str, Any]:
    """Fetch a single page of bookmarks."""
    return request_json(request_url, headers=headers, timeout=timeout)


def load_all_bookmarks(args: argparse.Namespace, max_pages: int = 5) -> tuple[list[dict[str, Any]], int]:
    """Fetch all bookmark pages up to max_pages, returning (all_page_data, page_count)."""
    config = load_config()

    if args.input_json:
        data = json.loads(Path(args.input_json).read_text(encoding="utf-8"))
        return [data], 1

    request_url = config.get("bookmark_fetch", "request_url")
    if not request_url or "REPLACE_ME" in str(request_url):
        raise SystemExit(
            "bookmark_fetch.request_url 尚未配置。请复制 config.example.json 为 config.json 并填入真实请求地址。"
        )

    headers = build_bookmark_headers(config)
    timeout = int(config.get("fetch", "timeout_seconds", default=20))

    all_pages: list[dict[str, Any]] = []
    current_url = str(request_url)

    for page in range(max_pages):
        data = fetch_bookmarks_page(current_url, headers, timeout)
        all_pages.append(data)

        # Check for next page
        bottom_cursor = extract_bottom_cursor(data)
        if not bottom_cursor:
            break  # No more pages

        # Check if this page had any tweet entries (not just cursors)
        try:
            entries = data["data"]["bookmark_timeline_v2"]["timeline"]["instructions"][0]["entries"]
            tweet_entries = [e for e in entries if not e.get("content", {}).get("cursorType")]
            if len(tweet_entries) == 0:
                break  # Empty page, stop
        except (KeyError, IndexError, TypeError):
            break

        current_url = build_paginated_url(str(request_url), bottom_cursor)

    return all_pages, len(all_pages)


def main() -> None:
    parser = argparse.ArgumentParser(description="增量拉取 X/Twitter 书签 URL 到收件箱")
    parser.add_argument("--input-json", help="从本地 JSON 文件读取书签响应，便于离线调试")
    parser.add_argument("--snapshot", action="store_true", help="保存本次抓取快照")
    parser.add_argument("--max-pages", type=int, default=5, help="最大分页拉取数（默认 5 页，每页 20 条）")
    args = parser.parse_args()

    config = load_config()
    processed = load_processed_ids()

    # Fetch all pages
    all_pages, page_count = load_all_bookmarks(args, max_pages=args.max_pages)

    # Extract URLs from all pages
    all_urls: list[str] = []
    seen_urls: set[str] = set()
    for data in all_pages:
        for url in extract_candidate_urls(data):
            if url not in seen_urls:
                seen_urls.add(url)
                all_urls.append(url)

    new_urls: list[str] = []
    new_ids: set[str] = set()
    for url in all_urls:
        url = normalize_tweet_url(url)
        tweet_id = tweet_id_from_url(url)
        if tweet_id not in processed:
            new_urls.append(url)
            new_ids.add(tweet_id)

    append_urls_to_markdown(new_urls, URLS_FILE)
    processed.update(new_ids)
    save_processed_ids(processed)

    if args.snapshot:
        snapshot_file = Path(config.get("bookmark_fetch", "snapshot_file", default="00_收件箱/_state/latest_bookmarks.json"))
        snapshot_path = (Path(__file__).resolve().parent.parent / snapshot_file).resolve()
        # Save the first page as snapshot (or merge all pages)
        write_json(snapshot_path, all_pages[0] if len(all_pages) == 1 else {"pages": all_pages})

    log_run(
        "ingest",
        source=str(args.input_json or "network"),
        pages=page_count,
        discovered=len(all_urls),
        appended=len(new_urls),
        processed_file=str(PROCESSED_IDS_FILE),
    )

    print(f"pages={page_count} discovered={len(all_urls)} appended={len(new_urls)} inbox={URLS_FILE}")


if __name__ == "__main__":
    main()
