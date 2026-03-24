#!/usr/bin/env python3
"""从 OpenClaw 内建浏览器 (CDP) 自动提取 X/Twitter cookie

通过 Chrome DevTools Protocol 连接已登录的 x.com 标签页，
提取完整 cookie（含 httpOnly），写入环境变量文件供 pipeline 使用。

用法:
    python3 twitter_refresh_cookie.py              # 提取并写入 cookie 文件
    python3 twitter_refresh_cookie.py --check      # 仅检查 cookie 是否有效
    python3 twitter_refresh_cookie.py --env-file   # 显示 cookie 文件路径

依赖: websocket-client (pip3 install websocket-client)

原理:
  1. 连接 CDP 端口 (默认 18800)
  2. 找到 x.com 标签页
  3. 用 Network.getCookies 拿完整 cookie（含 httpOnly）
  4. 写入 ~/.x_cookie_env 供 pipeline source
  5. 可选：验证 cookie 有效性（试拉一次书签 API）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
import urllib.error
from pathlib import Path

CDP_PORT = int(os.environ.get("CDP_PORT", "18800"))
CDP_BASE = f"http://127.0.0.1:{CDP_PORT}"
COOKIE_ENV_FILE = Path.home() / ".x_cookie_env"

# 公共 bearer token (X 前端共用，不是秘密)
DEFAULT_BEARER = (
    "Bearer AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs"
    "%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"
)


def find_x_tab() -> str | None:
    """找到 x.com 标签页的 WebSocket URL"""
    try:
        data = urllib.request.urlopen(f"{CDP_BASE}/json", timeout=5).read()
        targets = json.loads(data)
    except Exception as e:
        print(f"❌ 无法连接 CDP ({CDP_BASE}): {e}", file=sys.stderr)
        return None

    for t in targets:
        url = t.get("url", "")
        if ("x.com" in url or "twitter.com" in url) and t.get("type") == "page":
            return t.get("webSocketDebuggerUrl")

    return None


def extract_cookies(ws_url: str) -> dict[str, str] | None:
    """通过 CDP WebSocket 提取 x.com 的所有 cookie"""
    try:
        import websocket
    except ImportError:
        print("❌ 需要安装 websocket-client: pip3 install --break-system-packages websocket-client",
              file=sys.stderr)
        return None

    try:
        ws = websocket.create_connection(ws_url, timeout=10, suppress_origin=True)
    except Exception as e:
        print(f"❌ WebSocket 连接失败: {e}", file=sys.stderr)
        return None

    ws.send(json.dumps({
        "id": 1,
        "method": "Network.getCookies",
        "params": {"urls": [
            "https://x.com",
            "https://api.x.com",
            "https://x.com/i/api",
        ]}
    }))

    result = json.loads(ws.recv())
    ws.close()

    cookies = result.get("result", {}).get("cookies", [])
    if not cookies:
        print("❌ 未获取到 cookie — x.com 可能未登录", file=sys.stderr)
        return None

    cookie_dict = {}
    for c in cookies:
        cookie_dict[c["name"]] = c["value"]

    # 必须有 auth_token 和 ct0
    if "auth_token" not in cookie_dict or "ct0" not in cookie_dict:
        print("❌ cookie 中缺少 auth_token 或 ct0 — 可能未登录", file=sys.stderr)
        return None

    return cookie_dict


def build_cookie_string(cookie_dict: dict[str, str]) -> str:
    """构建完整 cookie 字符串"""
    return "; ".join(f"{k}={v}" for k, v in cookie_dict.items())


def validate_cookie(cookie_str: str, ct0: str) -> bool:
    """验证 cookie 是否有效（试拉一次书签 API）"""
    import urllib.parse
    
    url = "https://x.com/i/api/graphql/J1HURtBCLHqE2c7wKvFznA/Bookmarks?" + urllib.parse.urlencode({
        "variables": json.dumps({"count": 1}),
        "features": json.dumps({
            "graphql_timeline_v2_bookmark_timeline": True,
            "rweb_tipjar_consumption_enabled": True,
            "responsive_web_graphql_exclude_directive_enabled": True,
            "verified_phone_label_enabled": False,
            "creator_subscriptions_tweet_preview_api_enabled": True,
            "responsive_web_graphql_timeline_navigation_enabled": True,
            "responsive_web_graphql_skip_user_profile_image_extensions_enabled": False,
            "communities_web_enable_tweet_community_results_fetch": True,
            "c9s_tweet_anatomy_moderator_badge_enabled": True,
            "articles_preview_enabled": True,
            "responsive_web_edit_tweet_api_enabled": True,
            "tweetypie_unmention_optimization_enabled": True,
            "responsive_web_text_conversations_enabled": False,
            "responsive_web_twitter_article_tweet_consumption_enabled": True,
            "responsive_web_media_download_video_enabled": False,
            "longform_notetweets_inline_media_enabled": True,
            "responsive_web_enhance_cards_enabled": False,
            "longform_notetweets_rich_text_read_enabled": True,
            "freedom_of_speech_not_reach_fetch_enabled": True,
            "standardized_nudges_misinfo": True,
            "tweet_with_visibility_results_prefer_gql_limited_actions_policy_enabled": True,
            "rweb_video_timestamps_enabled": True,
            "longform_notetweets_consumption_enabled": True,
            "tweet_awards_web_tipping_enabled": False,
            "view_counts_everywhere_api_enabled": True,
        })
    })

    headers = {
        "cookie": cookie_str,
        "x-csrf-token": ct0,
        "authorization": DEFAULT_BEARER,
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    }

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read())
            # 只要不报错就算成功
            return "data" in data
    except urllib.error.HTTPError as e:
        print(f"❌ 验证失败: HTTP {e.code}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"❌ 验证失败: {e}", file=sys.stderr)
        return False


def write_env_file(cookie_str: str, ct0: str, bearer: str = DEFAULT_BEARER):
    """写入 cookie 环境变量文件，可被 source 加载"""
    # 转义单引号
    cookie_esc = cookie_str.replace("'", "'\"'\"'")
    ct0_esc = ct0.replace("'", "'\"'\"'")
    bearer_esc = bearer.replace("'", "'\"'\"'")

    content = f"""# Auto-generated by twitter_refresh_cookie.py
# Last updated: {__import__('time').strftime('%Y-%m-%d %H:%M:%S')}
# Source this file before running Twitter pipeline scripts
export X_COOKIE='{cookie_esc}'
export X_CSRF_TOKEN='{ct0_esc}'
export X_AUTH_BEARER='{bearer_esc}'
"""
    COOKIE_ENV_FILE.write_text(content)
    os.chmod(COOKIE_ENV_FILE, 0o600)  # 仅本人可读
    print(f"✅ Cookie 写入 {COOKIE_ENV_FILE}")


def main():
    parser = argparse.ArgumentParser(description="从浏览器自动提取 X/Twitter cookie")
    parser.add_argument("--check", action="store_true", help="仅检查当前 cookie 是否有效")
    parser.add_argument("--env-file", action="store_true", help="显示 cookie 文件路径")
    parser.add_argument("--no-validate", action="store_true", help="跳过验证")
    parser.add_argument("--cdp-port", type=int, default=CDP_PORT, help="CDP 端口")
    args = parser.parse_args()

    if args.env_file:
        print(str(COOKIE_ENV_FILE))
        return

    if args.check:
        # 从现有文件检查
        if not COOKIE_ENV_FILE.exists():
            print(f"❌ {COOKIE_ENV_FILE} 不存在")
            sys.exit(1)
        # 快速读取并验证
        content = COOKIE_ENV_FILE.read_text()
        cookie_str = ct0 = ""
        for line in content.splitlines():
            if line.startswith("export X_COOKIE="):
                cookie_str = line.split("='", 1)[1].rstrip("'")
            elif line.startswith("export X_CSRF_TOKEN="):
                ct0 = line.split("='", 1)[1].rstrip("'")
        if validate_cookie(cookie_str, ct0):
            print("✅ Cookie 有效")
        else:
            print("❌ Cookie 无效或已过期")
            sys.exit(1)
        return

    cdp_port = args.cdp_port
    cdp_base = f"http://127.0.0.1:{cdp_port}"

    # Step 1: 找 x.com 标签页
    # Override module-level CDP_BASE for find_x_tab
    import twitter_refresh_cookie as _self
    _self.CDP_BASE = cdp_base
    ws_url = find_x_tab()
    if not ws_url:
        print("❌ 未找到 x.com 标签页 — 请确保 OpenClaw 浏览器中已打开并登录 x.com")
        sys.exit(1)
    print("🔍 找到 x.com 标签页")

    # Step 2: 提取 cookie
    cookie_dict = extract_cookies(ws_url)
    if not cookie_dict:
        sys.exit(1)
    
    cookie_str = build_cookie_string(cookie_dict)
    ct0 = cookie_dict.get("ct0", "")
    print(f"🍪 提取到 {len(cookie_dict)} 个 cookie (含 httpOnly)")

    # Step 3: 验证
    if not args.no_validate:
        if validate_cookie(cookie_str, ct0):
            print("✅ Cookie 验证通过")
        else:
            print("⚠️  Cookie 验证失败，仍然写入（可能是临时网络问题）")

    # Step 4: 写入文件
    write_env_file(cookie_str, ct0)
    
    print(f"\n使用方法: source {COOKIE_ENV_FILE} && python3 twitter_auto.py")


if __name__ == "__main__":
    main()
