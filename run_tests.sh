#!/usr/bin/env bash
# Pre-commit gate. Run this before committing or running the brief in prod.
#   1) compile every .py file in the repo (catches SyntaxError fast)
#   2) run pytest
#
# Exit non-zero if anything fails.

set -euo pipefail

cd "$(dirname "$0")"

echo "── 1/2: compiling all .py sources ──"
python -m compileall -q src run.py search.py migrate_briefs.py

echo "── 2/2: pytest ──"
python -m pytest -q

echo
echo "OK — all checks passed."
