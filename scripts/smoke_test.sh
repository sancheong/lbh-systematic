#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEMO="${TMPDIR:-/tmp}/lbh-demo-$$"
LBH="python -m lbh.cli"

python "$ROOT/scripts/create_demo_repo.py" "$DEMO"
cd "$DEMO"
PYTHONPATH="$ROOT/src" $LBH init
PYTHONPATH="$ROOT/src" $LBH index
PYTHONPATH="$ROOT/src" $LBH search "결제 후 알림" --limit 10
PYTHONPATH="$ROOT/src" $LBH ask "결제 완료 후 이메일 알림이 안 가는 문제를 확인해줘"
SESSION="$(find .lbh/sessions -mindepth 1 -maxdepth 1 -type d | sort | tail -n 1)"
printf '[READ: src/payments/checkout.py#1-80]\n' > /tmp/lbh-read-response.md
PYTHONPATH="$ROOT/src" $LBH respond /tmp/lbh-read-response.md --session "$SESSION"
PYTHONPATH="$ROOT/src" $LBH status --session "$SESSION"

echo "smoke test ok: $DEMO"
