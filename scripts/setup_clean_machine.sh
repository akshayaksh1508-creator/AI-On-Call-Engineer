#!/usr/bin/env bash
# NightShift One-Command Clean Machine Setup & Demo Verification (Day 10 Task A4)
# Usage: bash scripts/setup_clean_machine.sh [--verify-only]
set -euo pipefail

START_TS=$(date +%s)
VERIFY_ONLY="${1:-}"

echo "==> [NightShift Setup] Checking prerequisites (python3, git)..."
PYTHON_BIN="${PYTHON:-python3}"
command -v "$PYTHON_BIN" >/dev/null 2>&1 || PYTHON_BIN="python"
command -v "$PYTHON_BIN" >/dev/null 2>&1 || { echo "ERROR: Python 3 is required."; exit 1; }
command -v git >/dev/null 2>&1 || { echo "ERROR: git is required."; exit 1; }

if [ ! -f ".env" ] && [ -f ".env.example" ]; then
  echo "==> Creating .env from .env.example..."
  cp .env.example .env
fi

if [ "$VERIFY_ONLY" != "--verify-only" ]; then
  echo "==> Installing Python dependencies..."
  "$PYTHON_BIN" -m pip install -r requirements.txt -r requirements-dev.txt
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    echo "==> Running make up..."
    make up
  else
    echo "==> Docker daemon not active; skipping container startup and running local mode."
  fi
fi

echo "==> Validating CODEOWNERS and running end-to-end demo..."
"$PYTHON_BIN" run.py check-owners
"$PYTHON_BIN" run.py demo --fault fault_001_bad_deploy

END_TS=$(date +%s)
ELAPSED=$((END_TS - START_TS))
echo "==> [NightShift Setup] Completed in ${ELAPSED}s (limit: 900s / 15 minutes)."
if [ "$ELAPSED" -ge 900 ]; then
  echo "ERROR: Setup + demo exceeded 15-minute SLA!"
  exit 1
fi
