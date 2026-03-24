from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent.parent
INBOX_DIR = ROOT / "00_收件箱"
STATE_DIR = INBOX_DIR / "_state"
RAW_DIR = ROOT / "10_原始内容"
FAILED_DIR = ROOT / "20_处理失败"
SORTED_DIR = ROOT / "30_已整理"
TEMPLATE_DIR = ROOT / "templates"
URLS_FILE = INBOX_DIR / "Twitter-URLs.md"
PROCESSED_IDS_FILE = STATE_DIR / "processed_ids.json"
RUN_LOG_FILE = STATE_DIR / "run_log.jsonl"
MANIFEST_FILE = STATE_DIR / "notes_manifest.json"
CONFIG_FILE = ROOT / "config.json"
CONFIG_EXAMPLE_FILE = ROOT / "config.example.json"


@dataclass
class Config:
    data: dict[str, Any]

    def get(self, *keys: str, default: Any = None) -> Any:
        current: Any = self.data
        for key in keys:
            if not isinstance(current, dict) or key not in current:
                return default
            current = current[key]
        return current


def ensure_base_layout() -> None:
    for path in (INBOX_DIR, STATE_DIR, RAW_DIR, FAILED_DIR, SORTED_DIR, TEMPLATE_DIR):
        path.mkdir(parents=True, exist_ok=True)
    if not URLS_FILE.exists():
        URLS_FILE.write_text("# Twitter URLs\n\n", encoding="utf-8")
    if not PROCESSED_IDS_FILE.exists():
        write_json(PROCESSED_IDS_FILE, [])
    if not MANIFEST_FILE.exists():
        write_json(MANIFEST_FILE, [])


def load_config() -> Config:
    ensure_base_layout()
    path = CONFIG_FILE if CONFIG_FILE.exists() else CONFIG_EXAMPLE_FILE
    return Config(read_json(path, default={}))


def read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def append_jsonl(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(data, ensure_ascii=False) + "\n")


def load_processed_ids() -> set[str]:
    items = read_json(PROCESSED_IDS_FILE, default=[])
    return {str(item) for item in items if str(item).strip()}


def save_processed_ids(processed_ids: set[str]) -> None:
    write_json(PROCESSED_IDS_FILE, sorted(processed_ids))


def read_urls_from_markdown(path: Path = URLS_FILE) -> list[str]:
    if not path.exists():
        return []
    content = path.read_text(encoding="utf-8")
    urls = re.findall(r"https?://[^\s)\]]+", content)
    seen: set[str] = set()
    ordered: list[str] = []
    for url in urls:
        if url not in seen:
            seen.add(url)
            ordered.append(url)
    return ordered


def append_urls_to_markdown(urls: list[str], path: Path = URLS_FILE) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = read_urls_from_markdown(path)
    known = set(existing)
    lines: list[str] = []
    if not path.exists():
        lines.append("# Twitter URLs\n")
    for url in urls:
        if url not in known:
            lines.append(f"- {url}\n")
            known.add(url)
    if lines:
        with path.open("a", encoding="utf-8") as handle:
            if path.stat().st_size > 0 and not path.read_text(encoding="utf-8").endswith("\n"):
                handle.write("\n")
            handle.writelines(lines)


def clear_urls_markdown(path: Path = URLS_FILE) -> None:
    path.write_text("# Twitter URLs\n\n", encoding="utf-8")


def iso_now() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def safe_slug(value: str, max_length: int = 80) -> str:
    value = re.sub(r"\s+", "-", value.strip())
    value = re.sub(r"[^\w\-\u4e00-\u9fff]+", "-", value, flags=re.UNICODE)
    value = re.sub(r"-{2,}", "-", value).strip("-_")
    return value[:max_length] or "untitled"


def request_text(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: int = 20,
) -> str:
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="replace")


def request_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    timeout: int = 20,
) -> dict[str, Any]:
    return json.loads(request_text(url, headers=headers, timeout=timeout))


def shell_json(command: list[str], timeout: int = 30) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return json.loads(completed.stdout)


def shell_text(command: list[str], timeout: int = 30) -> str:
    completed = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return completed.stdout


def fill_command_template(parts: list[str], url: str) -> list[str]:
    return [part.replace("{url}", url) for part in parts]


def env_or_empty(name: str | None) -> str:
    if not name:
        return ""
    return os.environ.get(name, "").strip()


def build_bookmark_headers(config: Config) -> dict[str, str]:
    headers: dict[str, str] = {}
    for key, value in (config.get("bookmark_fetch", "headers", default={}) or {}).items():
        headers[str(key)] = str(value)

    cookie = env_or_empty(config.get("bookmark_fetch", "cookie_env"))
    csrf = env_or_empty(config.get("bookmark_fetch", "csrf_token_env"))
    bearer = env_or_empty(config.get("bookmark_fetch", "authorization_env"))

    if cookie:
        headers["cookie"] = cookie
    if csrf:
        headers["x-csrf-token"] = csrf
    if bearer:
        headers["authorization"] = bearer
    return headers


def log_run(event: str, **payload: Any) -> None:
    append_jsonl(
        RUN_LOG_FILE,
        {
            "time": iso_now(),
            "event": event,
            **payload,
        },
    )


def fail(message: str, exit_code: int = 1) -> None:
    print(message, file=sys.stderr)
    raise SystemExit(exit_code)


def ensure_parent(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def relative_to_root(path: Path) -> str:
    return str(path.resolve().relative_to(ROOT.resolve()))


def jina_proxy_url(url: str) -> str:
    """Prepend Jina reader prefix, preserving the original scheme."""
    if url.startswith("https://") or url.startswith("http://"):
        return "https://r.jina.ai/" + url
    return "https://r.jina.ai/https://" + url


def tweet_id_from_url(url: str) -> str:
    match = re.search(r"/status/(\d+)", url)
    return match.group(1) if match else safe_slug(url, max_length=32)


def normalize_tweet_url(url: str) -> str:
    """Normalize twitter.com → x.com and strip query/fragment."""
    url = re.sub(r"https?://(?:www\.)?twitter\.com/", "https://x.com/", url)
    url = re.sub(r"https?://(?:www\.)?x\.com/", "https://x.com/", url)
    url = url.split("?")[0].split("#")[0]
    # Strip trailing /photo/N, /video/N suffixes to get canonical tweet URL
    url = re.sub(r"/(?:photo|video)/\d+$", "", url)
    return url


def first_non_empty(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""

