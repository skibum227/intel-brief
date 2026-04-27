#!/usr/bin/env python3
"""
Migrate legacy Intel Brief files from YYYY-MM-DD.md to YYYYMM/DD HH-MM.md format.

Legacy format:  <vault>/Intel Briefs/2024-03-15.md
New format:     <vault>/Intel Briefs/202403/15 09-00.md

The time is set to 09:00 since legacy files had no time component.
Dry-run by default — pass --execute to actually move files.

Usage:
    python migrate_briefs.py             # preview what would happen
    python migrate_briefs.py --execute   # actually move the files
"""
import argparse
import shutil
from pathlib import Path

from src.config import load_config, get_vault_path


def main():
    parser = argparse.ArgumentParser(description="Migrate legacy brief files")
    parser.add_argument("--execute", action="store_true", help="Actually move files (default is dry run)")
    args = parser.parse_args()

    config = load_config()
    vault_path = get_vault_path(config)
    output_folder = config.get("obsidian_output_folder", "Intel Briefs")
    output_dir = vault_path / output_folder

    if not output_dir.exists():
        print(f"Directory not found: {output_dir}")
        return

    legacy_files = sorted(output_dir.glob("????-??-??.md"))
    if not legacy_files:
        print("No legacy files found (YYYY-MM-DD.md). Nothing to migrate.")
        return

    print(f"Found {len(legacy_files)} legacy file(s){'' if args.execute else ' — DRY RUN (pass --execute to apply)'}:\n")

    for src in legacy_files:
        # Parse YYYY-MM-DD from stem
        try:
            from datetime import datetime
            dt = datetime.strptime(src.stem, "%Y-%m-%d")
        except ValueError:
            print(f"  SKIP  {src.name}  (unexpected filename format)")
            continue

        # New path: YYYYMM/DD 09-00.md
        new_dir = output_dir / dt.strftime("%Y%m")
        new_name = dt.strftime("%d 09-00") + ".md"
        dst = new_dir / new_name

        if dst.exists():
            print(f"  SKIP  {src.name}  →  {dst.relative_to(output_dir)}  (destination already exists)")
            continue

        print(f"  {'MOVE' if args.execute else 'WOULD MOVE'}  {src.name}  →  {dst.relative_to(output_dir)}")

        if args.execute:
            new_dir.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))

    if not args.execute:
        print("\nRun with --execute to apply these changes.")
    else:
        print("\nDone.")


if __name__ == "__main__":
    main()
