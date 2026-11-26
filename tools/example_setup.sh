#!/usr/bin/env bash
# Regenerate every generated file of the worked example (red-team A5): data, values, displays and their lock, and,
# when LaTeX is installed, the paper and the talk (byte-stable builds). The README and CI use this one command.
#   tools/example_setup.sh
set -euo pipefail
cd "$(dirname "$0")/../examples/toy-expression-benchmark"
python make_data.py
steward paper values --write
python analysis/make_displays.py table
python analysis/make_displays.py figure
steward paper displays --record
if command -v latexmk >/dev/null; then
  export SOURCE_DATE_EPOCH=1768435200 FORCE_SOURCE_DATE=1
  (cd paper && latexmk -pdf -interaction=nonstopmode main.tex >/dev/null)
  (cd talks/progress-update && latexmk -pdf -interaction=nonstopmode slides.tex >/dev/null)
else
  echo "latexmk not found: paper/main.pdf and talks/progress-update/slides.pdf are used as committed"
fi
steward check --final --summary
