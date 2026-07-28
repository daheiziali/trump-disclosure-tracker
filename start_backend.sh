#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/backend"
python3 review_server.py
