#!/usr/bin/env python3
"""
Twitter 书签 → Obsidian 知识库 全自动 Pipeline
每晚自动执行: cookie刷新 → ingest → fetch → route → unbookmark → 汇报

用法:
    python3 twitter_auto.py           # 完整流程
    python3 twitter_auto.py --dry-run  # 预览不执行
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

# Add tools dir to path
TOOLS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS_DIR))

from common import load_config, build_bookmark_headers, load_processed_ids
from twitter_unbookmark import fetch_bookmark_ids, delete_bookmark

# Paths
TW_BASE = Path(os.environ.get("TWITTER_OBSIDIAN_ROOT", str(Path(__file__).resolve().parent.parent)))
INBOX = TW_BASE / "00_收件箱"
RAW = TW_BASE / "10_原始内容"
SORTED = TW_BASE / "30_已整理" / "Twitter"
ARCHIVE = TW_BASE / "40_已归档"
COOKIE_ENV_FILE = Path.home() / ".x_cookie_env"


def stage_refresh_cookie():
    """阶段0: 从浏览器自动刷新 cookie"""
    print("\n🍪 阶段0: Cookie 刷新")
    try:
        from twitter_refresh_cookie import find_x_tab, extract_cookies, build_cookie_string, validate_cookie, write_env_file
        
        ws_url = find_x_tab()
        if not ws_url:
            print("  ⚠️  未找到 x.com 标签页，使用现有 cookie")
            return _load_existing_cookie()
        
        cookie_dict = extract_cookies(ws_url)
        if not cookie_dict:
            print("  ⚠️  提取 cookie 失败，使用现有 cookie")
            return _load_existing_cookie()
        
        cookie_str = build_cookie_string(cookie_dict)
        ct0 = cookie_dict.get("ct0", "")
        
        if validate_cookie(cookie_str, ct0):
            write_env_file(cookie_str, ct0)
            # 注入当前进程环境变量
            os.environ["X_COOKIE"] = cookie_str
            os.environ["X_CSRF_TOKEN"] = ct0
            print(f"  ✅ 提取并验证 {len(cookie_dict)} 个 cookie")
            return True
        else:
            print("  ⚠️  新 cookie 验证失败，使用现有 cookie")
            return _load_existing_cookie()
    except Exception as e:
        print(f"  ⚠️  Cookie 刷新异常: {e}，使用现有 cookie")
        return _load_existing_cookie()


def _load_existing_cookie() -> bool:
    """从 ~/.x_cookie_env 加载已有 cookie 到环境变量"""
    if not COOKIE_ENV_FILE.exists():
        print("  ❌ 无可用 cookie 文件")
        return False
    
    content = COOKIE_ENV_FILE.read_text()
    for line in content.splitlines():
        if line.startswith("export ") and "=" in line:
            # export X_COOKIE='...'
            var_part = line[7:]  # strip "export "
            key, _, val = var_part.partition("=")
            val = val.strip("'\"")
            os.environ[key] = val
    
    print("  📂 已加载现有 cookie")
    return True


def stage_ingest(max_pages=10):
    """阶段1: 拉取新书签"""
    print("\n📡 阶段1: Ingest — 拉取新书签")
    import subprocess
    result = subprocess.run(
        [sys.executable, str(TOOLS_DIR / "twitter_ingest.py"), "--max-pages", str(max_pages)],
        capture_output=True, text=True, cwd=str(TW_BASE),
        env={**os.environ}
    )
    output = result.stdout.strip()
    print(f"  {output}")
    
    # 解析结果
    parts = {}
    for part in output.split():
        if "=" in part:
            k, v = part.split("=", 1)
            parts[k] = v
    
    discovered = int(parts.get("discovered", 0))
    appended = int(parts.get("appended", 0))
    return discovered, appended

def stage_fetch(retries=2):
    """阶段2: 抓取推文正文"""
    print("\n📥 阶段2: Fetch — 抓取推文正文")
    import subprocess
    result = subprocess.run(
        [sys.executable, str(TOOLS_DIR / "twitter_fetch.py"), "--retries", str(retries)],
        capture_output=True, text=True, cwd=str(TW_BASE),
        env={**os.environ},
        timeout=300
    )
    output = result.stdout.strip()
    print(f"  {output}")
    
    success = 0
    failure = 0
    for line in output.split("\n"):
        if line.startswith("success="):
            parts = line.split()
            for p in parts:
                if p.startswith("success="):
                    success = int(p.split("=")[1])
                elif p.startswith("failure="):
                    failure = int(p.split("=")[1])
    return success, failure

def stage_route():
    """阶段3: 分流到已整理"""
    print("\n📂 阶段3: Route — 分流到已整理")
    import subprocess
    result = subprocess.run(
        [sys.executable, str(TOOLS_DIR / "twitter_route.py")],
        capture_output=True, text=True, cwd=str(TW_BASE),
        env={**os.environ}
    )
    output = result.stdout.strip()
    print(f"  {output}")
    
    routed = 0
    for line in output.split("\n"):
        if line.startswith("routed="):
            routed = int(line.split("=")[1])
    return routed

def stage_unbookmark(delay=0.5):
    """阶段4: 清理线上书签 (从 API 拉取实际书签 ID，不依赖本地 processed_ids)"""
    print("\n🗑️  阶段4: Unbookmark — 清理线上书签")
    config = load_config()
    headers = build_bookmark_headers(config)
    
    # 始终从 API 拉取当前实际书签，避免用过时的 processed_ids
    ids = fetch_bookmark_ids(headers, max_pages=10)
    if not ids:
        print("  无书签需要清理")
        return 0, 0
    
    print(f"  找到 {len(ids)} 条书签")
    success = 0
    failed = 0
    for i, tid in enumerate(ids, 1):
        ok = delete_bookmark(tid, headers)
        if ok:
            success += 1
        else:
            failed += 1
        if i % 10 == 0 or i == len(ids):
            print(f"  进度: {i}/{len(ids)} (✅{success} ❌{failed})")
        if delay > 0 and i < len(ids):
            time.sleep(delay)
    
    return success, failed

def get_new_files():
    """获取 30_已整理 中的新文件"""
    if not SORTED.exists():
        return []
    return [f.name for f in SORTED.glob("TW-*.md")]

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Twitter 书签全自动 Pipeline")
    parser.add_argument("--dry-run", action="store_true", help="预览模式")
    parser.add_argument("--no-unbookmark", action="store_true", help="跳过清理书签")
    parser.add_argument("--max-pages", type=int, default=10, help="Ingest 最大页数")
    args = parser.parse_args()

    print("🦞 Twitter 书签 → Obsidian 全自动 Pipeline")
    print(f"   时间: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 50)

    if args.dry_run:
        print("🔍 [DRY RUN 模式]")
    
    # 阶段0: Cookie 刷新
    cookie_ok = stage_refresh_cookie()
    if not cookie_ok:
        print("\n❌ 无法获取有效 cookie，流程终止")
        print("   请在 OpenClaw 浏览器中打开 x.com 并登录")
        return
    
    # 阶段1: Ingest
    discovered, appended = stage_ingest(args.max_pages)
    
    if appended == 0:
        print("\n✅ 没有新书签，流程结束")
        # 仍然清理线上书签（可能有手动收藏的）
        if not args.no_unbookmark and not args.dry_run:
            stage_unbookmark()
        return
    
    # 阶段2: Fetch
    fetch_ok, fetch_fail = stage_fetch()
    
    # 阶段3: Route
    routed = stage_route()
    
    # 获取新文件列表
    new_files = get_new_files()
    
    # 阶段4: Unbookmark
    unbookmark_ok, unbookmark_fail = 0, 0
    if not args.no_unbookmark and not args.dry_run:
        unbookmark_ok, unbookmark_fail = stage_unbookmark()
    
    # 汇总
    print("\n" + "=" * 50)
    print("📊 执行汇总")
    print(f"  发现书签: {discovered} (新增 {appended})")
    print(f"  抓取成功: {fetch_ok}, 失败: {fetch_fail}")
    print(f"  分流入库: {routed}")
    print(f"  清理书签: ✅{unbookmark_ok} ❌{unbookmark_fail}")
    
    if new_files:
        print(f"\n📝 新入库 {len(new_files)} 篇:")
        for f in new_files:
            title = f.replace('.md','')
            title = title.split('-Title-')[-1].replace('-', ' ')[:80] if '-Title-' in title else title[:80]
            print(f"  - {title}")
    
    # 输出 JSON 格式供 cron 解析
    result = {
        "discovered": discovered,
        "appended": appended,
        "fetched": fetch_ok,
        "fetch_failed": fetch_fail,
        "routed": routed,
        "unbookmark_ok": unbookmark_ok,
        "unbookmark_fail": unbookmark_fail,
        "new_files": new_files,
    }
    
    # 写入运行日志
    log_file = TW_BASE / "00_收件箱" / "_state" / "auto_run_log.jsonl"
    log_file.parent.mkdir(parents=True, exist_ok=True)
    with open(log_file, "a") as f:
        f.write(json.dumps({**result, "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S")}, ensure_ascii=False) + "\n")

if __name__ == "__main__":
    main()
