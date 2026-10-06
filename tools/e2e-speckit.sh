#!/usr/bin/env bash
# End-to-end check against a real Spec Kit install (used by CI; runnable locally):
#   1. builds the archives and serves dist/ on localhost
#   2. specify init, then installs archiGuard, its preset and scopeGuard from archives
#   3. configure: archiGuard's and scopeGuard's hooks off (inline), the edit guard wired
#   4. the rendered skills reference real paths and wrap the core commands
#   5. the example feature through plan A/B (scope gate on the real scopeGuard engine), tasks B,
#      sign-off, implement A/B, and the edit guard through Spec Kit's events dispatcher
#
# Usage: tools/e2e-speckit.sh <scopeguard.zip URL or path>     (needs `specify` on PATH, git, python3)
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCOPEGUARD_ZIP="${1:?usage: e2e-speckit.sh <scopeguard.zip URL or path>}"
PORT="${E2E_PORT:-8765}"
WORK="$(mktemp -d)"
trap 'kill "${SERVER:-}" 2>/dev/null || true; rm -rf "$WORK"' EXIT
PY="$(command -v python3 || command -v python)"

fail() { echo "E2E FAIL: $*" >&2; exit 1; }
expect() {  # expect <exit code> <command...>
    local want="$1"; shift
    set +e; "$@" > "$WORK/out.txt" 2>&1; local got=$?; set -e
    if [[ "$got" != "$want" ]]; then cat "$WORK/out.txt"; fail "expected exit $want, got $got: $*"; fi
}
contains() { grep -qF -- "$1" "$WORK/out.txt" || { cat "$WORK/out.txt"; fail "output lacks: $1"; }; }

"$PY" "$REPO/tools/build.py" >/dev/null
mkdir -p "$WORK/www"
cp "$REPO"/dist/archiguard.zip "$REPO"/dist/archiguard-preset.zip "$WORK/www/"
if [[ -f "$SCOPEGUARD_ZIP" ]]; then cp "$SCOPEGUARD_ZIP" "$WORK/www/scopeguard.zip"; else curl -fsSL -o "$WORK/www/scopeguard.zip" "$SCOPEGUARD_ZIP"; fi
(cd "$WORK/www" && exec "$PY" -m http.server "$PORT" --bind 127.0.0.1 >/dev/null 2>&1) &
SERVER=$!
sleep 2
BASE="http://127.0.0.1:$PORT"

echo "== specify $(specify version 2>/dev/null | grep -o 'CLI Version *[0-9.]*' | grep -o '[0-9.]*$' || echo '?')"
cd "$WORK"
specify init lab --integration claude --script sh --ignore-agent-tools --non-interactive >/dev/null
cd lab
git init -q && git config user.email e2e@example.com && git config user.name e2e && git config commit.gpgsign false
printf 'y\ny\n' | specify extension add archiguard --from "$BASE/archiguard.zip" >/dev/null
specify preset add --from "$BASE/archiguard-preset.zip" >/dev/null
printf 'y\ny\n' | specify extension add scopeguard --from "$BASE/scopeguard.zip" >/dev/null
A=(bash .specify/extensions/archiguard/scripts/bash/archiguard.sh)

echo "== configure"
expect 0 "${A[@]}" configure
contains "integration   : inline"
contains "speckit.archiguard.plangate        off"
contains "speckit.scopeguard.plan            off"
contains "edit guard    : wired into .claude/settings.json"
"$PY" - <<'PY'
import re
text = open(".specify/extensions.yml").read()
for block in text.split("- extension: ")[1:]:
    if block.startswith(("archiguard", "scopeguard")):
        assert re.search(r"enabled:\s*false", block), "hook still enabled:\n" + block
PY

echo "== rendered skills"
grep -q "archiGuard (A): entry gates" .claude/skills/speckit-plan/SKILL.md || fail "plan wrap missing"
grep -q "archiGuard (B)" .claude/skills/speckit-implement/SKILL.md || fail "implement wrap missing"
grep -q "analyze-report.md" .claude/skills/speckit-analyze/SKILL.md || fail "analyze wrap missing"
if grep -rq "extensions/archiguard/gates" .claude; then fail "feature gate paths were rewritten into the extension"; fi
while read -r p; do
    [[ -e "$p" ]] || fail "rendered path does not exist: $p"
done < <(grep -rhoE "\.specify/extensions/archiguard/[A-Za-z0-9_./-]+" .claude | sort -u)
grep -q "speckit.archiguard.editguard pre_tool_use" .claude/settings.json || fail "edit guard not wired"

echo "== the example feature"
E="$REPO/examples/orders"
cp -r "$E/src" "$E/pom.xml" .
mkdir -p specs && cp -r "$E/specs/001-place-order" specs/ && rm -rf specs/001-place-order/gates
cp -r "$E/.specify/standards" .specify/
mkdir -p .specify/archiguard && cp "$E/.specify/archiguard/ledger.jsonl" .specify/archiguard/
CFG=.specify/extensions/archiguard/archiguard-config.yml
sed -i.bak -e 's|^  rulebook: null |  rulebook: acme-standards@v2026.10.1 |' -e 's|^  profile: null |  profile: java-service |' \
    -e 's|^  pin: null |  pin: "1.4.0" |' "$CFG" && rm -f "$CFG.bak"
expect 0 "${A[@]}" resolve
git add -A && git commit -qm "base" && git branch -M main && git checkout -qb 001-place-order

expect 0 "${A[@]}" run plan a --via inline
contains "SCOPE CONTRACT"
contains "| ARCH-201 |"
contains "1 user stories, 6 requirements"
expect 1 "${A[@]}" run plan b --via inline
contains "[plan] BR-002"
contains "[A3.3] ARCH-201"
PLAN=specs/001-place-order/plan.md
"$PY" - "$PLAN" <<'PY'
import sys
p = sys.argv[1]
s = open(p).read()
s = s.replace("<!-- ARCH-201 (layering) is missing on purpose: the A3.3 check-plan finds it. -->",
              "| ARCH-201 | Layers depend downwards only (api -> application -> domain) | satisfied | Project Structure | |")
s = s.replace("<!-- BR-002 (request the payment) is missing on purpose: the scope gate finds it when it is plugged in. -->",
              "| BR-002 | Request the payment of the order total | covered | Integration Points (payments) | |")
open(p, "w").write(s)
PY
expect 0 "${A[@]}" run plan b --via inline
contains "PASS after 1 repair iteration(s)"
expect 0 "${A[@]}" run plan b --via hook
contains "skipped"
expect 0 "${A[@]}" run tasks b --via inline

echo "== sign-off and implement"
expect 1 "${A[@]}" signoff --by "Lead architect"
contains "A3.6"
contains "uncommitted changes"
git add -A && git commit -qm "T000 UC-001 design"
printf '## Specification Analysis Report\n\n| ID | Category | Severity | Location(s) | Summary | Recommendation |\n|----|----|----|----|----|----|\n| A1 | Terminology | LOW | plan.md | x | y |\n\n- Critical Issues Count: 0\n' \
    > specs/001-place-order/gates/analyze-report.md
git add -A && git commit -qm "T000 UC-001 analyze report"
expect 0 "${A[@]}" signoff --by "Lead architect"
git add -A && git commit -qm "T000 UC-001 design signed"
expect 0 "${A[@]}" run implement a --via inline
expect 1 "${A[@]}" run implement b --via inline
contains "ARCH-201"
contains "ARCH-301"

echo "== edit guard through Spec Kit's events dispatcher"
export CLAUDE_PROJECT_DIR="$PWD"
payload() { printf '{"hook_event_name":"%s","tool_name":"Edit","cwd":"%s","tool_input":{"file_path":"%s/%s"}}' "$1" "$PWD" "$PWD" "$2"; }
set +e
payload PreToolUse specs/001-place-order/plan.md | "$PY" .specify/events.py speckit.archiguard.editguard pre_tool_use 20 2> "$WORK/out.txt"; code=$?
set -e
[[ $code == 2 ]] || fail "edit guard did not block the signed plan (exit $code)"
contains "read-only during Implement"
set +e
payload PostToolUse src/main/java/com/acme/orders/api/OrderController.java | "$PY" .specify/events.py speckit.archiguard.editguard post_tool_use 60 2> "$WORK/out.txt"; code=$?
set -e
[[ $code == 2 ]] || fail "edit guard did not report ARCH-301 (exit $code)"
contains "ARCH-301"
set +e
printf '{"hook_event_name":"PreToolUse","tool_name":"Bash","cwd":"%s","tool_input":{"command":"bash .specify/extensions/archiguard/scripts/bash/archiguard.sh ledger add --id ADR-0999 --type adr --title x --owner agent"}}' "$PWD" \
    | "$PY" .specify/events.py speckit.archiguard.editguard pre_tool_use 20 2> "$WORK/out.txt"; code=$?
set -e
[[ $code == 2 ]] || fail "edit guard did not block 'archiguard ledger add' for the agent (exit $code)"
contains "decision of a person"
grep -q '"matcher": "Edit|Write|MultiEdit|NotebookEdit|Bash|PowerShell"' .claude/settings.json || fail "shell matcher not wired"

echo "== workflow"
specify workflow add "$REPO/workflows/archiguard-sdd/workflow.yml" >/dev/null || fail "workflow rejected"

echo "E2E PASS"
