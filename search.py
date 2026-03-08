#!/usr/bin/env python3
"""
Search across all Intel Brief markdown files.

Usage:
    python search.py "query"
    python search.py "query" --limit 20
"""
import argparse
import re
import sys
from datetime import datetime
from pathlib import Path

import yaml


def _highlight(text: str, query: str) -> str:
    return re.sub(f"({re.escape(query)})", r"[\1]", text, flags=re.IGNORECASE)


def main():
    parser = argparse.ArgumentParser(description="Search Intel Brief history")
    parser.add_argument("query", nargs="+", help="Search terms")
    parser.add_argument("--limit", type=int, default=15, help="Max results (default 15)")
    args = parser.parse_args()

    query = " ".join(args.query)
    config = yaml.safe_load(open(Path(__file__).parent / "config.yaml"))
    vault_path = Path(config["obsidian_vault_path"]).expanduser()
    output_folder = config.get("obsidian_output_folder", "Intel Briefs")
    output_dir = vault_path / output_folder

    if not output_dir.exists():
        print(f"  No brief directory found at: {output_dir}")
        sys.exit(1)

    results = []
    pattern = re.compile(re.escape(query), re.IGNORECASE)

    for path in sorted(output_dir.glob("*/*.md"), reverse=True):
        try:
            dt = datetime.strptime(f"{path.parent.name}/{path.stem}", "%Y%m/%d %H-%M")
            date_label = dt.strftime("%a %b %-d, %Y  %-I:%M %p")
        except ValueError:
            date_label = path.stem

        text = path.read_text(encoding="utf-8")
        lines = text.splitlines()
        matches = []
        for i, line in enumerate(lines):
            if pattern.search(line):
                # 1 line of context above/below, stripped
                ctx_start = max(0, i - 1)
                ctx_end = min(len(lines), i + 2)
                snippet = "\n    ".join(
                    _highlight(l, query) for l in lines[ctx_start:ctx_end] if l.strip()
                )
                matches.append(snippet)

        if matches:
            # Obsidian URI for linking
            rel = path.relative_to(vault_path)
            vault_name = vault_path.name
            obsidian_uri = f"obsidian://open?vault={vault_name}&file={str(rel.with_suffix(''))}"
            results.append((date_label, matches[:3], obsidian_uri))

    if not results:
        print(f"\n  No results for '{query}'\n")
        return

    total = sum(len(m) for _, m, _ in results)
    print(f"\n  {total} match(es) across {len(results)} brief(s) for '{query}'\n")
    print("  " + "─" * 60)

    for date_label, matches, uri in results[: args.limit]:
        print(f"\n  📄 {date_label}")
        for snippet in matches:
            print(f"    {snippet}")
        print(f"  🔗 {uri}")

    print()


if __name__ == "__main__":
    main()
