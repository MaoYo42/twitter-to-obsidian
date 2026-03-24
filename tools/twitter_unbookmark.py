#!/usr/bin/env python3
"""批量清理 X/Twitter 收藏 — 使用 GraphQL DeleteBookmark API

用法:
    python3 twitter_unbookmark.py              # 清理所有已处理的收藏
    python3 twitter_unbookmark.py --dry-run     # 预览，不实际删除
    python3 twitter_unbookmark.py --limit 50    # 只清理前 50 条
    python3 twitter_unbookmark.py --all         # 拉取全部书签并清空

依赖: 需要环境变量 X_COOKIE, X_CSRF_TOKEN, X_AUTH_BEARER
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
from pathlib import Path

# Add tools dir to path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import load_config, build_bookmark_headers, load_processed_ids

DELETE_BOOKMARK_HASH = "Wlmlj2-xzyS1GN3a6cj-mQ"
BOOKMARKS_HASH = "J1HURtBCLHqE2c7wKvFznA"


def delete_bookmark(tweet_id: str, headers: dict, max_retries: int = 3) -> bool:
    """Remove a single bookmark via GraphQL mutation, with 429 backoff."""
    import urllib.request
    import urllib.error

    url = f"https://x.com/i/api/graphql/{DELETE_BOOKMARK_HASH}/DeleteBookmark"
    payload = json.dumps({
        "variables": {"tweet_id": tweet_id},
        "queryId": DELETE_BOOKMARK_HASH,
    }).encode()

    for attempt in range(max_retries):
        req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
        req.add_header("Content-Type", "application/json")

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                return data.get("data", {}).get("tweet_bookmark_delete") == "Done"
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait = (attempt + 1) * 30  # 30s, 60s, 90s
                print(f"  ⏳ 429 限流，等待 {wait}s 后重试 ({attempt + 1}/{max_retries})...")
                time.sleep(wait)
                continue
            print(f"  ❌ Error removing {tweet_id}: {e}")
            return False
        except Exception as e:
            print(f"  ❌ Error removing {tweet_id}: {e}")
            return False

    print(f"  ❌ {tweet_id}: 超过最大重试次数")
    return False


def fetch_bookmark_ids(headers: dict, max_pages: int = 50) -> list[str]:
    """Fetch all bookmarked tweet IDs from the API."""
    import urllib.request

    config = load_config()
    base_url = str(config.get("bookmark_fetch", "request_url"))
    tweet_ids = []
    current_url = base_url

    for page in range(max_pages):
        req = urllib.request.Request(current_url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read())
        except Exception as e:
            print(f"  ❌ Error fetching page {page + 1}: {e}")
            break

        instructions = data.get("data", {}).get("bookmark_timeline_v2", {}).get("timeline", {}).get("instructions", [])
        if not instructions:
            break
        entries = instructions[0].get("entries", [])
        
        bottom_cursor = None
        page_ids = []
        for entry in entries:
            content = entry.get("content", {})
            if content.get("cursorType") == "Bottom":
                bottom_cursor = content.get("value")
                continue
            if content.get("cursorType"):
                continue
            # Extract tweet ID from entry
            entry_id = entry.get("entryId", "")
            if entry_id.startswith("tweet-"):
                page_ids.append(entry_id.replace("tweet-", ""))

        tweet_ids.extend(page_ids)
        print(f"  📖 Page {page + 1}: found {len(page_ids)} bookmarks (total: {len(tweet_ids)})")

        if not bottom_cursor or len(page_ids) == 0:
            break

        # Build next page URL
        parsed = urllib.parse.urlparse(base_url)
        params = urllib.parse.parse_qs(parsed.query)
        variables = json.loads(params["variables"][0])
        variables["cursor"] = bottom_cursor
        params["variables"] = [json.dumps(variables, separators=(",", ":"))]
        new_query = urllib.parse.urlencode(params, doseq=True, quote_via=urllib.parse.quote)
        current_url = urllib.parse.urlunparse(parsed._replace(query=new_query))

    return tweet_ids


def main():
    parser = argparse.ArgumentParser(description="批量清理 X/Twitter 收藏")
    parser.add_argument("--dry-run", action="store_true", help="只预览，不实际删除")
    parser.add_argument("--limit", type=int, default=0, help="限制删除数量 (0=全部)")
    parser.add_argument("--all", action="store_true", help="拉取全部书签并清空（不依赖 processed_ids）")
    parser.add_argument("--delay", type=float, default=0.5, help="每次删除间隔秒数 (防限流)")
    args = parser.parse_args()

    config = load_config()
    headers = build_bookmark_headers(config)

    if args.all:
        print("📡 正在拉取全部书签...")
        tweet_ids = fetch_bookmark_ids(headers, max_pages=50)
    else:
        print("📋 从 processed_ids 加载已提取的书签...")
        tweet_ids = sorted(load_processed_ids())

    if args.limit > 0:
        tweet_ids = tweet_ids[:args.limit]

    print(f"\n📊 待清理: {len(tweet_ids)} 条收藏")

    if args.dry_run:
        print("🔍 [DRY RUN] 以下收藏将被删除:")
        for tid in tweet_ids[:20]:
            print(f"  - {tid}")
        if len(tweet_ids) > 20:
            print(f"  ... 还有 {len(tweet_ids) - 20} 条")
        return

    # Confirm
    print(f"\n⚠️  即将删除 {len(tweet_ids)} 条 X 收藏，此操作不可逆！")
    print(f"   延迟: {args.delay}s/条, 预计耗时: {len(tweet_ids) * args.delay / 60:.1f} 分钟")
    
    success = 0
    failed = 0
    for i, tweet_id in enumerate(tweet_ids, 1):
        ok = delete_bookmark(tweet_id, headers)
        if ok:
            success += 1
        else:
            failed += 1

        if i % 50 == 0 or i == len(tweet_ids):
            print(f"  进度: {i}/{len(tweet_ids)} (✅{success} ❌{failed})")

        if args.delay > 0 and i < len(tweet_ids):
            time.sleep(args.delay)

    print(f"\n🏁 完成! 成功: {success}, 失败: {failed}")


if __name__ == "__main__":
    main()
