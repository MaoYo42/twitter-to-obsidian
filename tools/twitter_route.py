from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

from common import MANIFEST_FILE, RAW_DIR, ROOT, SORTED_DIR, load_config, log_run, read_json, safe_slug, write_json


def dedup_by_tweet_id(files: list[Path]) -> list[Path]:
    """When multiple files exist for the same tweet_id, keep the largest (best content)."""
    from collections import defaultdict
    groups: defaultdict[str, list[Path]] = defaultdict(list)
    ungrouped: list[Path] = []
    for path in files:
        m = re.search(r"TW-(\d+)-", path.name)
        if m:
            groups[m.group(1)].append(path)
        else:
            ungrouped.append(path)

    result: list[Path] = list(ungrouped)
    for tweet_id, paths in groups.items():
        if len(paths) == 1:
            result.append(paths[0])
        else:
            # Keep the largest file (most content), remove the rest
            paths.sort(key=lambda p: p.stat().st_size, reverse=True)
            result.append(paths[0])
            for loser in paths[1:]:
                loser.unlink(missing_ok=True)
    return sorted(result)


def discover_markdown_files(directory: Path) -> list[Path]:
    raw = sorted(path for path in directory.glob("*.md") if path.is_file())
    return dedup_by_tweet_id(raw)


def choose_target(filename: str, routing: dict) -> Path:
    for rule in routing.get("rules", []):
        prefix = str(rule.get("prefix", "")).strip()
        target = str(rule.get("target", "")).strip()
        if prefix and filename.startswith(prefix) and target:
            return (ROOT / target).resolve()
    default_target = str(routing.get("default_target", "30_已整理/未分类")).strip()
    return (ROOT / default_target).resolve()


def update_index(directory: Path) -> None:
    files = sorted(path for path in directory.glob("*.md") if path.name != "_index.md")
    lines = [f"# {directory.name} 索引\n", "\n"]
    for file in files:
        lines.append(f"- [[{file.stem}]]\n")
    (directory / "_index.md").write_text("".join(lines), encoding="utf-8")


def route_notes(dry_run: bool = False) -> tuple[int, list[dict]]:
    config = load_config().data
    routing = config.get("routing", {})
    manifest = read_json(MANIFEST_FILE, default=[])
    moved: list[dict] = []

    for source in discover_markdown_files(RAW_DIR):
        target_dir = choose_target(source.name, routing)
        target_dir.mkdir(parents=True, exist_ok=True)
        target = target_dir / source.name

        if dry_run:
            moved.append({"source": str(source), "target": str(target), "moved": False})
            continue

        shutil.move(str(source), str(target))
        moved.append({"source": str(source), "target": str(target), "moved": True})
        manifest.append({"source": str(source), "target": str(target)})
        log_run("route", source=str(source), target=str(target))

    if not dry_run:
        write_json(MANIFEST_FILE, manifest)
        touched_dirs = {str(Path(item["target"]).parent) for item in moved if item["moved"]}
        for directory in sorted(touched_dirs):
            update_index(Path(directory))

    return len(moved), moved


def main() -> None:
    parser = argparse.ArgumentParser(description="按文件前缀分流原始笔记并更新索引")
    parser.add_argument("--dry-run", action="store_true", help="仅显示将要移动的文件")
    args = parser.parse_args()

    count, moved = route_notes(dry_run=args.dry_run)
    print(f"routed={count}")
    for item in moved:
        print(f"{item['source']} -> {item['target']}")


if __name__ == "__main__":
    main()
