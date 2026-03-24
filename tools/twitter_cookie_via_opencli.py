#!/usr/bin/env python3
"""
通过 opencli daemon API 获取 x.com cookie（后台，不操控浏览器 UI）

用法:
    python3 twitter_cookie_via_opencli.py          # 获取并写入 ~/.x_cookie_env
    python3 twitter_cookie_via_opencli.py --test    # 测试 cookie 是否有效
"""
import json
import os
import sys
import urllib.request
import uuid
from pathlib import Path

DAEMON_URL = "http://localhost:19825/command"
ENV_FILE = Path.home() / ".x_cookie_env"
BEARER = "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"


def get_cookies_from_opencli(url: str = "https://x.com") -> list[dict]:
    """通过 opencli daemon 获取指定 URL 的 cookie"""
    payload = json.dumps({
        "id": str(uuid.uuid4()),
        "type": "cookies",
        "url": url,
    }).encode()
    
    req = urllib.request.Request(DAEMON_URL, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-OpenCLI", "1")
    
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read())
    
    return data.get("data", [])


def refresh_cookie() -> dict:
    """获取完整 cookie 并写入环境文件"""
    # 尝试多个域名
    all_cookies = {}
    for url in ["https://x.com", "https://twitter.com", "https://api.x.com"]:
        try:
            cookies = get_cookies_from_opencli(url)
            for c in cookies:
                all_cookies[c["name"]] = c["value"]
        except Exception:
            pass
    
    if not all_cookies:
        print("❌ 无法从 opencli 获取 cookie")
        print("   请确保: Chrome 已打开 + OpenCLI 插件已启用 + 已登录 x.com")
        return {}
    
    ct0 = all_cookies.get("ct0", "")
    auth = all_cookies.get("auth_token", "")
    
    cookie_str = "; ".join(f"{k}={v}" for k, v in all_cookies.items())
    
    print(f"📝 获取到 {len(all_cookies)} 个 cookie 字段")
    print(f"   ct0: {'✅' if ct0 else '❌'}")
    print(f"   auth_token: {'✅' if auth else '❌'}")
    
    if not ct0 or not auth:
        print("⚠️  缺少关键 cookie（ct0 或 auth_token）")
        print("   你可能没有在 Chrome 中登录 x.com")
        return {}
    
    # 写入环境文件
    with open(ENV_FILE, "w") as f:
        f.write(f"export X_COOKIE='{cookie_str}'\n")
        f.write(f"export X_CSRF_TOKEN='{ct0}'\n")
        f.write(f"export X_AUTH_BEARER='{BEARER}'\n")
    
    print(f"✅ Cookie 已写入 {ENV_FILE}")
    
    return {
        "cookie": cookie_str,
        "csrf": ct0,
        "bearer": BEARER,
    }


def test_cookie() -> bool:
    """测试当前 cookie 是否有效"""
    # 加载环境文件
    if not ENV_FILE.exists():
        print("❌ Cookie 环境文件不存在，先运行不带 --test 来获取")
        return False
    
    env = {}
    for line in ENV_FILE.read_text().splitlines():
        if line.startswith("export "):
            parts = line[7:].split("=", 1)
            if len(parts) == 2:
                env[parts[0]] = parts[1].strip("'\"")
    
    cookie = env.get("X_COOKIE", "")
    csrf = env.get("X_CSRF_TOKEN", "")
    bearer = env.get("X_AUTH_BEARER", BEARER)
    
    headers = {
        "Authorization": f"Bearer {bearer}",
        "Cookie": cookie,
        "X-Csrf-Token": csrf,
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    }
    
    # Test with a simple API call
    test_url = "https://x.com/i/api/1.1/account/settings.json"
    req = urllib.request.Request(test_url, headers=headers)
    
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
            screen_name = data.get("screen_name", "unknown")
            print(f"✅ Cookie 有效！登录账号: @{screen_name}")
            return True
    except urllib.error.HTTPError as e:
        print(f"❌ Cookie 无效 (HTTP {e.code})")
        return False


def main():
    if "--test" in sys.argv:
        test_cookie()
    else:
        result = refresh_cookie()
        if result and "--test" not in sys.argv:
            print("\n🧪 测试 cookie 有效性...")
            test_cookie()


if __name__ == "__main__":
    main()
