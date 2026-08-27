#!/usr/bin/env bash
# Publish mcp-benchmark-hygiene to PyPI + Official MCP Registry.
# USAGE: ./publish_to_registry.sh <pypi-api-token>
set -euo pipefail
TOKEN="${1:?Usage: $0 <pypi-api-token>}"
ROOT="$(cd "$(dirname "$0")" && pwd)"
export TWINE_USERNAME="__token__"
export TWINE_PASSWORD="$TOKEN"

echo "==> 1/3 Building package..."
cd "$ROOT"
rm -rf dist build *.egg-info
python3 -m build

echo "==> 2/3 Uploading sdist+wheel to PyPI..."
python3 -m twine upload dist/*

echo "==> 3/3 Done uploading. Registry publish requires mcp-publisher login (fresh JWT) + publish in ONE command."
echo "       mcp-publisher login github --token <PAT> && mcp-publisher publish server.json"
