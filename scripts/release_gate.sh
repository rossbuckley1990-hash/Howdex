#!/usr/bin/env bash
set -euo pipefail

export HOWDEX_EMBEDDER=hash
export PYTHONUNBUFFERED=1

echo "== Howdex release gate =="

echo
echo "1. Checking for obvious secrets/runtime files..."
if find . \
  -path "./.git" -prune -o \
  -path "./.venv" -prune -o \
  \( -name ".env" -o -name ".env.*" -o -name "*.pem" -o -name "*.key" -o -name "*.db" -o -name "*.sqlite" -o -name "*.sqlite3" \) \
  -print | grep -q .; then
  echo "❌ Secret/runtime-like files found:"
  find . \
    -path "./.git" -prune -o \
    -path "./.venv" -prune -o \
    \( -name ".env" -o -name ".env.*" -o -name "*.pem" -o -name "*.key" -o -name "*.db" -o -name "*.sqlite" -o -name "*.sqlite3" \) \
    -print
  exit 1
fi
echo "✅ No obvious secret/runtime files found"

echo
echo "2. Running full tests..."
python -m pytest -q

echo
echo "3. Running healthcheck..."
howdex health

echo
echo "4. Running SWE-repeat benchmark..."
howdex eval swe-repeat

echo
echo "5. Regenerating benchmark report..."
python benchmarks/report.py

echo
echo "6. Building package..."
python -m pip install --quiet build
python -m build

echo
echo "✅ RELEASE GATE PASSED"
