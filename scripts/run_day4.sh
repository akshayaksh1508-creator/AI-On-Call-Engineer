#!/usr/bin/env bash
set -euo pipefail
python -m day4.cli init
python -m unittest discover -s tests -v
python -m day4.cli benchmark
