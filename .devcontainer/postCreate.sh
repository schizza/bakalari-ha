#!/usr/bin/env bash
set -euo pipefail

echo "🔧 Installing dev dependencies…"

python -m pip install --upgrade pip

pip install -e .
pip install \
  ruff \
  pre-commit \
  pytest \
  pytest-asyncio \
  pytest-homeassistant-custom-component \
  homeassistant==2025.1.4 \
  async-bakalari-api==0.3.6

# Pre-commit hooks (pre-commit + pre-push)
pre-commit install -t pre-commit -t pre-push || true

echo "✅ Done. Useful commands:"
echo " - ruff check ."
echo " - pytest -q"
echo " - make ci
echo " - act push -j tests"
