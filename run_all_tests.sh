#!/usr/bin/env bash
# Полный прогон тестов agent + server через локальные venv (без глобального pip).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"

ensure_venv() {
  local dir="$1"
  local req_file="$2"
  shift 2
  local extra_pip=("$@")
  local need_install=0

  cd "$dir"
  if [ ! -d .venv ]; then
    python3 -m venv .venv
    need_install=1
  fi
  # shellcheck disable=SC1091
  source .venv/bin/activate
  if [ "$need_install" -eq 1 ] || ! python -c "import pytest" >/dev/null 2>&1; then
    python -m pip install -q --upgrade pip
    python -m pip install -q -r "$req_file"
    if [ "${#extra_pip[@]}" -gt 0 ]; then
      python -m pip install -q "${extra_pip[@]}"
    fi
  fi
}

echo "=== Agent tests ==="
ensure_venv "$ROOT/agent" requirements-test.txt
python -m pytest tests/ -q --tb=line

echo ""
echo "=== Server tests ==="
ensure_venv "$ROOT/server" requirements-test.txt
python -m pytest tests/ -q --tb=line

echo ""
echo "All test suites passed."
