#!/usr/bin/env bash
# Run the CI checks locally in Linux containers (stand-in while GitHub Actions minutes are unavailable).
#   tools/ci_local.sh            # Python 3.11 and 3.13
#   tools/ci_local.sh 3.12       # chosen versions
# Needs Docker. By default it tests a clean export of HEAD (`git archive`), as a fresh clone would see it, so files
# that are present locally but not committed cannot hide failures (red-team A5 / C2). --working-tree tests the
# working tree instead. Nothing is written back.
set -euo pipefail
cd "$(dirname "$0")/.."
SRC="$PWD"
if [ "${1:-}" = "--working-tree" ]; then
  shift
else
  SRC="$(mktemp -d)/export"
  mkdir -p "$SRC"
  git archive HEAD | tar -x -C "$SRC"
  echo "testing a clean export of $(git rev-parse --short HEAD)"
fi
versions=("${@:-3.11 3.13}")
for v in ${versions[@]}; do
  echo "== Python $v (Linux)"
  docker run --rm -v "$SRC":/src:ro "python:$v-slim" sh -c '
    set -e
    apt-get -qq update >/dev/null 2>&1 && apt-get -qq install -y git >/dev/null 2>&1
    cp -r /src /w && cd /w && rm -rf .venv
    pip install -q --root-user-action=ignore -e ".[dev]" >/dev/null 2>&1
    python -m pytest -q
    python tools/lint_language.py
    python tools/measure_footprint.py --check
    python tools/regenerate_schemas.py --check
    steward check --final --summary --repo examples/toy-expression-benchmark'
done
