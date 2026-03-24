from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from common import CONFIG_EXAMPLE_FILE, CONFIG_FILE, ROOT, URLS_FILE, ensure_base_layout, load_config


def main() -> None:
    parser = argparse.ArgumentParser(description="检查 Twitter 自动化目录是否准备就绪")
    parser.parse_args()

    ensure_base_layout()
    config = load_config()
    python_ok = sys.version_info >= (3, 11)
    print(f"root={ROOT}")
    print(f"python={'ok' if python_ok else 'warn'} {sys.version.split()[0]}")
    print(f"config={'present' if CONFIG_FILE.exists() else 'missing'} {CONFIG_FILE}")
    print(f"config_example=present {CONFIG_EXAMPLE_FILE}")
    print(f"inbox=present {URLS_FILE}")
    print(f"curl={'present' if shutil.which('curl') else 'missing'}")
    request_url = config.get('bookmark_fetch', 'request_url', default='')
    print(f"bookmark_request={'configured' if request_url and 'REPLACE_ME' not in str(request_url) else 'placeholder'}")


if __name__ == "__main__":
    main()
