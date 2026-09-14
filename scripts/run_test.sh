#!/usr/bin/env bash
# run_test.sh — Run lints and/or tests for this project.
#
# Usage:
#   bash scripts/run_test.sh          # run all (lint + test)
#   bash scripts/run_test.sh lint     # run lints only
#   bash scripts/run_test.sh test     # run tests only
#   bash scripts/run_test.sh all      # run all (lint + test)

set -e

info() { echo "[INFO] $*"; }

run_lints() {
    info "Running pre-commit hooks..."
    pre-commit run --all-files

    for f in scripts/lints/*.sh; do
        [[ -f "$f" ]] || continue
        info "Running $f..."
        bash "$f"
    done
}

run_tests() {
    info "Running Python tests..."
    uv run pytest
    info "Running shellcheck..."
    find . -name "*.sh" -not -path "./.git/*" -exec shellcheck {} +
}

case "${1:-all}" in
    lint)  run_lints ;;
    test)  run_tests ;;
    all)   run_lints; run_tests ;;
    *)     echo "Usage: bash scripts/run_test.sh [lint|test|all]"; exit 1 ;;
esac
