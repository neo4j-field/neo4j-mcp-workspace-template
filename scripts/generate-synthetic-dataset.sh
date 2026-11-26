#!/usr/bin/env bash
set -euo pipefail
workspace_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$workspace_dir"
exec uv run --no-project --python 3.12 \
  --with reportlab==4.4.9 --with python-docx==1.2.0 \
  --with Pillow==13.0.0 --with PyYAML==6.0.3 \
  python -m tests.synthetic.generate "$@"
