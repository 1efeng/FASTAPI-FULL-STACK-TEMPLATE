#!/usr/bin/env bash

set -e
set -x

FASTAPI_ENV=development coverage run -m pytest "${@:-tests/}"
coverage report
coverage html --title "${1:-coverage}"
