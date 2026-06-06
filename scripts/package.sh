#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/dist"
mkdir -p "$OUT"
cd "$ROOT/.."
zip -r "$OUT/lbh-systematic.zip" "$(basename "$ROOT")" \
  -x "*/__pycache__/*" "*/.pytest_cache/*" "*.pyc" "*/.lbh/*" "*/dist/*" "*/build/*" "*/.git/*"
echo "$OUT/lbh-systematic.zip"
