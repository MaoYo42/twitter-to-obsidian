#!/usr/bin/env python3
"""从 Chrome Cookie DB 直接解密 x.com cookie（macOS Keychain + AES）
完全后台运行，不需要打开 x.com 标签页，不操控浏览器
"""
import sqlite3, subprocess, os, sys, shutil, tempfile
from pathlib import Path

try:
    from Crypto.Cipher import AES
    from Crypto.Protocol.KDF import PBKDF2
except ImportError:
    print("需要 pycryptodome: pip3 install pycryptodome")
    sys.exit(1)

COOKIE_DB = Path.home() / "Library/Application Support/Google/Chrome/Profile 1/Cookies"
ENV_FILE = Path.home() / ".x_cookie_env"
BEARER = "AAAAAAAAAAAAAAAAAAAAANRILgAAAAAAnNwIzUejRCOuH5E6I8xnZz4puTs%3D1Zv7ttfk8LF81IUq16cHjhLTvJu4FA33AGWWjCpTnA"


def get_chrome_key():
    result = subprocess.run(
        ["security", "find-generic-password", "-w", "-s", "Chrome Safe Storage", "-a", "Chrome"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"Keychain error: {result.stderr}")
    password = result.stdout.strip()
    return PBKDF2(password, b"saltysalt", dkLen=16, count=1003)


def decrypt_cookie(enc_value, key):
    if enc_value[:3] == b"v10":
        enc_value = enc_value[3:]
        cipher = AES.new(key, AES.MODE_CBC, b" " * 16)
        dec = cipher.decrypt(enc_value)
        pad = dec[-1] if isinstance(dec[-1], int) else ord(dec[-1])
        return dec[:-pad].decode("utf-8", errors="replace")
    return ""


def main():
    print("🔑 从 Chrome Cookie DB 解密 x.com cookie...")
    
    key = get_chrome_key()
    
    tmp = tempfile.mktemp(suffix=".db")
    shutil.copy2(COOKIE_DB, tmp)
    
    conn = sqlite3.connect(tmp)
    rows = conn.execute(
        "SELECT host_key, name, encrypted_value FROM cookies "
        "WHERE host_key LIKE '%.x.com%' OR host_key LIKE '%.twitter.com%'"
    ).fetchall()
    conn.close()
    os.unlink(tmp)
    
    cookies = {}
    for host, name, enc in rows:
        try:
            v = decrypt_cookie(enc, key)
            if v:
                cookies[name] = v
        except Exception:
            pass
    
    ct0 = cookies.get("ct0", "")
    auth = cookies.get("auth_token", "")
    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
    
    print(f"📝 解密到 {len(cookies)} 个 cookie")
    print(f"   ct0: {'✅' if ct0 else '❌'}")
    print(f"   auth_token: {'✅' if auth else '❌'}")
    
    if not ct0 or not auth:
        print("⚠️  缺少关键 cookie — 你可能没有在 Chrome 中登录 x.com")
        sys.exit(1)
    
    with open(ENV_FILE, "w") as f:
        f.write(f"export X_COOKIE='{cookie_str}'\n")
        f.write(f"export X_CSRF_TOKEN='{ct0}'\n")
        f.write(f"export X_AUTH_BEARER='{BEARER}'\n")
    
    print(f"✅ 写入 {ENV_FILE}")
    
    # 验证
    if "--test" in sys.argv:
        import urllib.request, json
        headers = {
            "Authorization": f"Bearer {BEARER}",
            "Cookie": cookie_str,
            "X-Csrf-Token": ct0,
            "User-Agent": "Mozilla/5.0",
        }
        req = urllib.request.Request(
            "https://x.com/i/api/1.1/account/settings.json",
            headers=headers
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                print(f"✅ Cookie 有效! @{data.get('screen_name', '?')}")
        except Exception as e:
            print(f"❌ Cookie 无效: {e}")


if __name__ == "__main__":
    main()
