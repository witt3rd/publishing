#!/usr/bin/env bash
# CI time budget report: per-job wall time of a ci workflow run against ci/budget.txt.
# usage: tools/ci-budget.sh [run-id]    (default: latest successful ci run on main; needs gh)
# Prints a table, exits 1 if any job is over its budget (use as a report; the workflow runs it non-blocking).
set -euo pipefail
cd "$(dirname "$0")/.."
budget=ci/budget.txt
run=${1:-$(gh run list --workflow ci.yml --branch main --status success --limit 1 --json databaseId -q '.[0].databaseId')}
repo=${GITHUB_REPOSITORY:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}
gh api "repos/$repo/actions/runs/$run/jobs?per_page=100" --jq \
  '.jobs[] | select(.conclusion=="success") | [.name, ((.completed_at|fromdateiso8601) - (.started_at|fromdateiso8601))] | @tsv' |
python3 - "$budget" "$run" <<'PY'
import sys
budget_file, run = sys.argv[1:]
budgets = {}
for line in open(budget_file):
    line = line.split("#")[0].strip()
    if line:
        sec, name = line.split(None, 1)
        budgets[name.strip()] = int(sec)
rows = [l.rstrip("\n").split("\t") for l in sys.stdin if l.strip()]
over = 0
print(f"CI time budget, run {run}")
print(f"{'job':70} {'secs':>6} {'budget':>7}")
for name, secs in sorted(rows, key=lambda r: -int(r[1])):
    secs = int(secs)
    b = budgets.get(name)
    flag = ""
    if b is None:
        flag = "  (no budget: add it to ci/budget.txt)"
    elif secs > b:
        flag, over = "  OVER", over + 1
    print(f"{name[:70]:70} {secs:>6} {b if b else '-':>7}{flag}")
print(f"total job-seconds: {sum(int(r[1]) for r in rows)}; over budget: {over}")
sys.exit(1 if over else 0)
PY
