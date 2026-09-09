#! /usr/bin/env bash
set -e
set -x

python scripts/prestart.py
bash scripts/test.sh "$@"
