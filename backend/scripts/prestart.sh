#! /usr/bin/env bash

set -e
set -x

python scripts/prestart.py
alembic upgrade head
python scripts/init_data.py
