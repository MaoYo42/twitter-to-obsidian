from __future__ import annotations

import argparse
import json
import re
import urllib.error
from pathlib import Path
from typing import Any

from common import (
    FAILED_DIR,
    RAW_DIR,
    SORTED_DIR,
    TEMPLATE_DIR,
    URLS_FILE,
    clear_urls_markdown,
    fill_command_template,
    first_non_empty,
    jina_proxy_url,
    load_config,
    log_run,
    read_urls_from_markdown,
    request_text,
    safe_slug,
    shell_json,
    tweet_id_from_url,
)


def extract_title_from_content(content: str, fallback: str) -> str:
    for line in content.splitlines():
        stripped = line.strip("# ").strip()
        if stripped:
            return stripped[:80]
    return fallback


def naive_html_to_text(html: str) -> str:
    text = re.sub(r"(?is)<script.*?>.*?</script>", "", html)
    text = re.sub(r"(?is)<style.*?>.*?</style>", "", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def structured_fetch(url: str, config: dict[str, Any], timeout: int) -> dict[str, Any]:
    command = config.get("fetch", {}).get("structured_fetch", {}).get("command", [])
    enabled = bool(config.get("fetch", {}).get("structured_fetch", {}).get("enabled"))
    if not enabled or not command:
        raise RuntimeError("structured_fetch_disabled")
    payload = shell_json(fill_command_template(command, url), timeout=timeout)
    return {
        "source": "structured",
        "title": first_non_empty(payload.get("title"), payload.get("author"), tweet_id_from_url(url)),
        "content": first_non_empty(payload.get("text"), payload.get("content"), json.dumps(payload, ensure_ascii=False)),
        "author": first_non_empty(payload.get("author"), payload.get("screen_name"), "unknown"),
        "created_at": first_non_empty(payload.get("created_at")),
        "context": first_non_empty(
            payload.get("quote_text"),
            "\n\n".join(payload.get("thread", [])) if isinstance(payload.get("thread"), list) else "",
        ),
        "raw": payload,
    }


def jina_fetch(url: str, timeout: int) -> dict[str, Any]:
    content = request_text(jina_proxy_url(url), headers={"user-agent": "Mozilla/5.0"}, timeout=timeout)
    title = extract_title_from_content(content, fallback=tweet_id_from_url(url))
    return {
        "source": "jina",
        "title": title,
        "content": content.strip(),
        "author": "unknown",
        "created_at": "",
        "context": "",
        "raw": {"jina_url": jina_proxy_url(url)},
    }


def raw_fetch(url: str, timeout: int) -> dict[str, Any]:
    html = request_text(url, headers={"user-agent": "Mozilla/5.0"}, timeout=timeout)
    text = naive_html_to_text(html)
    title = extract_title_from_content(text, fallback=tweet_id_from_url(url))
    return {
        "source": "raw_html",
        "title": title,
        "content": text,
        "author": "unknown",
        "created_at": "",
        "context": "",
        "raw": {"html_length": len(html)},
    }


def fetch_with_fallbacks(url: str, config: dict[str, Any]) -> tuple[dict[str, Any] | None, list[str]]:
    timeout = int(config.get("fetch", {}).get("timeout_seconds", 20))
    attempts: list[str] = []

    try:
        result = structured_fetch(url, config, timeout)
        attempts.append("structured:ok")
        return result, attempts
    except Exception as exc:
        attempts.append(f"structured:fail:{type(exc).__name__}")

    if config.get("fetch", {}).get("jina_enabled", True):
        try:
            result = jina_fetch(url, timeout)
            attempts.append("jina:ok")
            return result, attempts
        except Exception as exc:
            attempts.append(f"jina:fail:{type(exc).__name__}")

    if config.get("fetch", {}).get("raw_html_enabled", True):
        try:
            result = raw_fetch(url, timeout)
            attempts.append("raw_html:ok")
            return result, attempts
        except Exception as exc:
            attempts.append(f"raw_html:fail:{type(exc).__name__}")

    return None, attempts


def render_note(template: str, values: dict[str, str]) -> str:
    content = template
    for key, value in values.items():
        content = content.replace(f"{{{{{key}}}}}", value)
    return content


def write_failure_note(url: str, attempts: list[str]) -> Path:
    tweet_id = tweet_id_from_url(url)
    path = FAILED_DIR / f"UDF-{tweet_id}.md"
    body = (
        f"# UDF {tweet_id}\n\n"
        f"- URL: {url}\n"
        f"- Status: UDF\n"
        f"- Attempts: {', '.join(attempts)}\n"
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def is_low_quality_content(content: str) -> bool:
    """Detect login walls, error pages, and empty content."""
    if len(content.strip()) < 100:
        return True
    # Pure error pages
    if "520: Web server is returning an unknown error" in content:
        return True
    if "Target URL returned error" in content:
        return True
    # Login wall with NO actual tweet content:
    # X pages always have boilerplate, so check if there's real content BEYOND it
    boilerplate_markers = [
        "Don't miss what's happening",
        "People on X are the first to know",
        "this page doesn't exist",
    ]
    # Strip out boilerplate to see what's left
    stripped = content
    for marker in boilerplate_markers:
        stripped = stripped.replace(marker, "")
    # Remove common X UI elements
    import re
    stripped = re.sub(r"\[Log in\].*?\[Sign up\]", "", stripped, flags=re.DOTALL)
    stripped = re.sub(r"Trending.*$", "", stripped, flags=re.DOTALL)
    stripped = re.sub(r"New to X\?.*$", "", stripped, flags=re.DOTALL)
    stripped = re.sub(r"\s+", " ", stripped).strip()
    # If after stripping boilerplate less than 80 chars remain, it's a login wall
    if len(stripped) < 80:
        return True
    return False


def existing_note_for_tweet(tweet_id: str, directory: Path) -> Path | None:
    """Check if a note for this tweet_id already exists in a directory."""
    prefix = f"TW-{tweet_id}-"
    for path in directory.glob(f"{prefix}*.md"):
        return path
    return None


def write_note(url: str, payload: dict[str, Any], config: dict[str, Any]) -> Path:
    tweet_id = tweet_id_from_url(url)
    prefix = str(config.get("default_note_prefix", "TW"))
    title_seed = first_non_empty(payload.get("title"), tweet_id)
    slug = safe_slug(title_seed)
    filename = f"{prefix}-{tweet_id}-{slug}.md"
    path = RAW_DIR / filename

    # Dedup: remove any existing note for the same tweet_id in RAW and SORTED dirs
    for check_dir in [RAW_DIR, SORTED_DIR]:
        for subdir in [check_dir] + [d for d in check_dir.iterdir() if d.is_dir()]:
            existing = existing_note_for_tweet(tweet_id, subdir)
            if existing and existing != path:
                existing.unlink(missing_ok=True)

    template_path = TEMPLATE_DIR / "tweet-note-template.md"
    template = template_path.read_text(encoding="utf-8")
    title = first_non_empty(payload.get("title"), tweet_id)
    body = render_note(
        template,
        {
            "title": f"{prefix} {title}",
            "url": url,
            "tweet_id": tweet_id,
            "author": first_non_empty(payload.get("author"), "unknown"),
            "created_at": first_non_empty(payload.get("created_at"), ""),
            "source": first_non_empty(payload.get("source"), "unknown"),
            "status": "fetched",
            "content": first_non_empty(payload.get("content"), ""),
            "context": first_non_empty(payload.get("context"), ""),
            "forward_links": f"[[{filename[:-3]}]]",
            "back_links": "",
        },
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description="消费收件箱 URL 并生成原始推文笔记")
    parser.add_argument("--clear-inbox", action="store_true", help="处理结束后清空 Twitter-URLs.md")
    parser.add_argument("--url", action="append", default=[], help="直接处理指定 URL，可重复使用")
    parser.add_argument("--retries", type=int, default=2, help="每条 URL 最大重试次数")
    args = parser.parse_args()

    config = load_config().data
    urls = args.url or read_urls_from_markdown(URLS_FILE)
    if not urls:
        print("no urls to process")
        return

    successes = 0
    failures = 0
    low_quality = 0
    for url in urls:
        payload = None
        attempts: list[str] = []
        for attempt in range(1 + args.retries):
            payload, attempts = fetch_with_fallbacks(url, config)
            if payload is None:
                continue
            # Quality gate: reject login walls and error pages
            content = first_non_empty(payload.get("content"), "")
            if is_low_quality_content(content):
                payload = None  # Treat as failure, will retry
                attempts.append(f"quality_gate:fail:attempt{attempt+1}")
                continue
            break  # Good content, stop retrying

        if payload is None:
            failure_path = write_failure_note(url, attempts)
            failures += 1
            log_run("fetch_failure", url=url, attempts=attempts, file=str(failure_path))
            continue

        note_path = write_note(url, payload, config)
        successes += 1
        log_run("fetch_success", url=url, attempts=attempts, file=str(note_path))

    if args.clear_inbox:
        clear_urls_markdown(URLS_FILE)

    print(f"success={successes} failure={failures}")


if __name__ == "__main__":
    main()
