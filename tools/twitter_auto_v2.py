#!/usr/bin/env python3
"""
Twitter 书签 → Obsidian 知识库 全自动 Pipeline v2 (opencli 版)
不再依赖 cookie 文件，通过 opencli 复用 Chrome 登录态

用法:
    python3 twitter_auto_v2.py           # 完整流程
    python3 twitter_auto_v2.py --dry-run  # 预览不执行
    python3 twitter_auto_v2.py --limit 50 # 自定义拉取数量
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

# Paths — 默认使用脚本所在目录的上级作为项目根目录
# 也可通过环境变量 TWITTER_OBSIDIAN_ROOT 自定义
TW_BASE = Path(os.environ.get("TWITTER_OBSIDIAN_ROOT", str(Path(__file__).resolve().parent.parent)))
INBOX = TW_BASE / "00_收件箱"
RAW = TW_BASE / "10_原始内容"
SORTED = TW_BASE / "30_已整理" / "Twitter"
ARCHIVE = TW_BASE / "40_已归档"
STATE_DIR = INBOX / "_state"
PROCESSED_IDS_FILE = STATE_DIR / "processed_tweet_ids.json"

TWEET_URL_RE = re.compile(r"https?://(?:www\.)?(?:x|twitter)\.com/([^/\s]+)/status/(\d+)")


def load_processed_ids() -> set:
    """加载已处理的推文 ID"""
    if PROCESSED_IDS_FILE.exists():
        data = json.loads(PROCESSED_IDS_FILE.read_text())
        if isinstance(data, list):
            return set(data)
        return set(data.get("ids", []))
    return set()


def save_processed_ids(ids: set):
    """保存已处理的推文 ID"""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    PROCESSED_IDS_FILE.write_text(json.dumps(sorted(ids), ensure_ascii=False, indent=2))


def stage_check_daemon() -> bool:
    """阶段0: 检查 opencli daemon + 插件连通性（自动唤醒）"""
    print("\n🔌 阶段0: 检查 opencli 连通性")
    
    for attempt in range(3):
        try:
            result = subprocess.run(
                ["opencli", "doctor"],
                capture_output=True, text=True, timeout=15
            )
            output = result.stdout
            if "Everything looks good" in output:
                print("  ✅ opencli daemon + Chrome 插件已连通")
                return True
            elif "Extension: not connected" in output:
                if attempt < 2:
                    print(f"  ⚠️  插件未连接，第 {attempt+1} 次重试（doctor 自动唤醒 daemon）...")
                    time.sleep(2)
                    continue
                print("  ❌ Chrome 插件未连接 — 请确保 Chrome 已打开且 OpenCLI 插件已启用")
                return False
            elif "Daemon" in output and "not" in output.lower():
                if attempt < 2:
                    print(f"  ⚠️  daemon 未运行，第 {attempt+1} 次重试...")
                    time.sleep(2)
                    continue
                return False
            else:
                print(f"  ⚠️  未知状态: {output[:100]}")
                return False
        except FileNotFoundError:
            print("  ❌ opencli 未安装")
            return False
        except subprocess.TimeoutExpired:
            print("  ❌ opencli doctor 超时")
            return False
    return False


def stage_fetch_bookmarks(limit: int = 100) -> list[dict]:
    """阶段1: 通过 opencli 拉取书签"""
    print(f"\n📡 阶段1: 拉取书签 (limit={limit})")
    try:
        result = subprocess.run(
            ["opencli", "twitter", "bookmarks", "--limit", str(limit), "-f", "json"],
            capture_output=True, text=True, timeout=60
        )
        if result.returncode != 0:
            print(f"  ❌ 拉取失败: {result.stderr[:200]}")
            return []
        
        data = json.loads(result.stdout)
        bookmarks = data if isinstance(data, list) else data.get("results", [])
        print(f"  📖 拉取到 {len(bookmarks)} 条书签")
        return bookmarks
    except json.JSONDecodeError as e:
        print(f"  ❌ JSON 解析失败: {e}")
        return []
    except subprocess.TimeoutExpired:
        print("  ❌ 拉取超时")
        return []


def stage_filter_new(bookmarks: list[dict]) -> list[dict]:
    """阶段2: 过滤出新书签"""
    print(f"\n🔍 阶段2: 过滤新书签")
    processed = load_processed_ids()
    
    new_bookmarks = []
    for bm in bookmarks:
        tweet_id = bm.get("id", "")
        url = bm.get("url", "")
        
        # 从 URL 提取 ID（备用）
        if not tweet_id and url:
            match = TWEET_URL_RE.search(url)
            if match:
                tweet_id = match.group(2)
        
        if tweet_id and tweet_id not in processed:
            bm["id"] = tweet_id
            new_bookmarks.append(bm)
    
    print(f"  已处理: {len(processed)}, 新发现: {len(new_bookmarks)}")
    return new_bookmarks


def stage_save_to_sorted(bookmarks: list[dict]) -> list[str]:
    """阶段3: 保存到 30_已整理/Twitter/
    
    文件名格式：{tweet_id}.md（纯 ID，知识卡片提炼时由 agent 重命名为中文标题）
    内容格式：结构化元数据 + 原文，方便后续 agent 提炼
    """
    print(f"\n📂 阶段3: 保存 {len(bookmarks)} 条到已整理")
    SORTED.mkdir(parents=True, exist_ok=True)
    
    saved_files = []
    for bm in bookmarks:
        tweet_id = bm.get("id", "unknown")
        author = bm.get("author", bm.get("name", "unknown"))
        text = bm.get("text", "")
        url = bm.get("url", "")
        likes = bm.get("likes", 0)
        created = bm.get("created_at", "")
        
        # 文件名：纯 tweet ID（避免污染知识库命名）
        filename = f"{tweet_id}.md"
        filepath = SORTED / filename
        
        # 内容格式：结构化，方便 agent 提炼
        content = f"""---
tweet_id: {tweet_id}
author: {author}
likes: {likes}
created_at: {created}
url: {url}
---

{text}
"""
        filepath.write_text(content, encoding="utf-8")
        saved_files.append(filename)
        print(f"  ✅ {author}: {text[:40]}...")
    
    return saved_files


def _refresh_cookie_via_opencli() -> dict | None:
    """通过 opencli daemon cookies API 获取新鲜 cookie（后台，不操控 UI）"""
    try:
        import urllib.request
        payload = json.dumps({
            "id": "cookie-refresh",
            "action": "cookies",
            "url": "https://x.com"
        }).encode()
        req = urllib.request.Request(
            "http://localhost:19825/command",
            data=payload, method="POST"
        )
        req.add_header("Content-Type", "application/json")
        req.add_header("X-OpenCLI", "1")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        cookies = data.get("data", [])
        cookie_dict = {c["name"]: c["value"] for c in cookies}
        ct0 = cookie_dict.get("ct0", "")
        auth = cookie_dict.get("auth_token", "")
        if ct0 and auth:
            cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
            bearer = "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
            # Also update env file
            env_file = Path.home() / ".x_cookie_env"
            with open(env_file, "w") as f:
                f.write(f"export X_COOKIE='{cookie_str}'\n")
                f.write(f"export X_CSRF_TOKEN='{ct0}'\n")
                f.write(f"export X_AUTH_BEARER='{bearer}'\n")
            return {
                "Authorization": f"Bearer {bearer}",
                "Cookie": cookie_str,
                "X-Csrf-Token": ct0,
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            }
    except Exception:
        pass
    return None


def _delete_bookmark_api(tweet_id: str, headers: dict) -> bool:
    """通过 GraphQL API 删除单条书签"""
    import urllib.request
    import urllib.error
    url = "https://x.com/i/api/graphql/Wlmlj2-xzyS1GN3a6cj-mQ/DeleteBookmark"
    payload = json.dumps({
        "variables": {"tweet_id": tweet_id},
        "queryId": "Wlmlj2-xzyS1GN3a6cj-mQ",
    }).encode()
    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            return data.get("data", {}).get("tweet_bookmark_delete") == "Done"
    except urllib.error.HTTPError as e:
        if e.code == 429:
            print(f"  ⏳ 429 限流，等待 30s...")
            time.sleep(30)
            return _delete_bookmark_api(tweet_id, headers)
        return False
    except Exception:
        return False


def stage_unbookmark(bookmarks: list[dict], delay: float = 0.5) -> tuple[int, int]:
    """阶段4: 通过 GraphQL API 后台清理线上书签（不操控浏览器前台）"""
    print(f"\n🗑️  阶段4: 清理 {len(bookmarks)} 条线上书签 (API 后台模式)")
    
    # 通过 opencli 获取新鲜 cookie
    headers = _refresh_cookie_via_opencli()
    if not headers:
        print("  ⚠️  无法通过 opencli 获取 cookie")
        print("  💡 跳过清理（不影响 pipeline 核心功能）")
        return 0, 0
    
    print("  🔑 Cookie 已通过 opencli 自动刷新")
    
    success = 0
    failed = 0
    for i, bm in enumerate(bookmarks, 1):
        tweet_id = bm.get("id", "")
        if not tweet_id:
            url = bm.get("url", "")
            match = TWEET_URL_RE.search(url)
            if match:
                tweet_id = match.group(2)
        
        if not tweet_id:
            failed += 1
            continue
        
        ok = _delete_bookmark_api(tweet_id, headers)
        if ok:
            success += 1
        else:
            failed += 1
        
        if i % 10 == 0 or i == len(bookmarks):
            print(f"  进度: {i}/{len(bookmarks)} (✅{success} ❌{failed})")
        
        if delay > 0 and i < len(bookmarks):
            time.sleep(delay)
    
    return success, failed


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Twitter 书签全自动 Pipeline v2 (opencli)")
    parser.add_argument("--dry-run", action="store_true", help="预览模式")
    parser.add_argument("--no-unbookmark", action="store_true", help="跳过清理书签")
    parser.add_argument("--limit", type=int, default=100, help="拉取书签数量上限")
    args = parser.parse_args()

    print("🦞 Twitter 书签 → Obsidian Pipeline v2 (opencli)")
    print(f"   时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    if args.dry_run:
        print("🔍 [DRY RUN 模式]")

    # 阶段0: 检查连通性
    if not stage_check_daemon():
        print("\n❌ opencli 未就绪，流程终止")
        print("   请确保: 1) Chrome 已打开  2) OpenCLI 插件已启用  3) 已登录 x.com")
        sys.exit(1)

    # 阶段1: 拉取书签
    bookmarks = stage_fetch_bookmarks(args.limit)
    if not bookmarks:
        print("\n✅ 没有书签，流程结束")
        return

    # 阶段2: 过滤新书签
    new_bookmarks = stage_filter_new(bookmarks)
    if not new_bookmarks:
        print("\n✅ 没有新书签")
        # 清理已处理的书签
        if not args.no_unbookmark and not args.dry_run:
            all_ids = {bm.get("id") for bm in bookmarks if bm.get("id")}
            processed = load_processed_ids()
            already_processed = [bm for bm in bookmarks if bm.get("id") in processed]
            if already_processed:
                stage_unbookmark(already_processed)
        return

    # 阶段3: 保存到已整理
    if not args.dry_run:
        saved = stage_save_to_sorted(new_bookmarks)
    else:
        saved = [f"[DRY] {bm.get('author')}: {bm.get('text','')[:40]}" for bm in new_bookmarks]
        for s in saved:
            print(f"  {s}")

    # 更新 processed IDs
    if not args.dry_run:
        processed = load_processed_ids()
        for bm in new_bookmarks:
            if bm.get("id"):
                processed.add(bm["id"])
        save_processed_ids(processed)

    # 阶段4: 清理线上书签
    unbookmark_ok, unbookmark_fail = 0, 0
    if not args.no_unbookmark and not args.dry_run:
        unbookmark_ok, unbookmark_fail = stage_unbookmark(bookmarks)

    # 汇总
    print("\n" + "=" * 50)
    print("📊 执行汇总")
    print(f"  拉取书签: {len(bookmarks)}")
    print(f"  新增入库: {len(new_bookmarks)}")
    print(f"  清理书签: ✅{unbookmark_ok} ❌{unbookmark_fail}")

    if saved:
        print(f"\n📝 新入库 {len(saved)} 篇:")
        for f in saved[:10]:
            print(f"  - {f[:80]}")
        if len(saved) > 10:
            print(f"  ... 还有 {len(saved)-10} 篇")

    # 写入运行日志
    result = {
        "version": "v2-opencli",
        "fetched": len(bookmarks),
        "new": len(new_bookmarks),
        "saved": len(saved),
        "unbookmark_ok": unbookmark_ok,
        "unbookmark_fail": unbookmark_fail,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    log_file = STATE_DIR / "auto_run_log.jsonl"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with open(log_file, "a") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
