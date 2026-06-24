#!/usr/bin/env bash
# submit-finding.sh
#
# Manual operator-direct entry to Phase 2 of the HeyBap forward-deployment
# pipeline. Use when Lubin notices a bug or wants a feature while using HeyBap
# day-to-day and doesn't want to wait for the pipeline to surface it.
#
# Invokes `claude -p` from the FDK repo root, which picks up
# .claude/settings.json (pre-approved tools) and routes the finding through
# `feature-bug-complexity-classification`. That skill runs the 5-minute
# investigation, the dedup, the classification grid, and dispatches to
# `bap-bug-report` (SIMPLE) or `bap-feature-brainstorm` (COMPLEX) which
# creates the Linear ticket and (for SIMPLE) opens the PR.
#
# Usage:
#   submit-finding.sh bug "Sandbox cache miss: coworker_run is 8s instead of 800ms"
#   submit-finding.sh feature "Add coworker_pin to keep favorites visible across pagination"

set -euo pipefail

usage() {
  cat <<USAGE >&2
Usage: $(basename "$0") <bug|feature> "<one-line description>"

  Routes a manual operator-direct finding through feature-bug-complexity-classification.

Examples:
  $(basename "$0") bug "Re-run button blocks 4s before firing, no feedback"
  $(basename "$0") feature "coworker_pin keeps favorites visible across pagination"
USAGE
  exit 1
}

[[ $# -lt 2 ]] && usage

KIND="$1"
shift
ONE_LINER="$*"

if [[ "$KIND" != "bug" && "$KIND" != "feature" ]]; then
  echo "First arg must be 'bug' or 'feature' (got: $KIND)" >&2
  usage
fi

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_TS="$(date +%Y%m%d-%H%M%S)"
LOG_DIR="${HEYBAP_LOGS_ROOT:-$REPO_ROOT/.run-logs}"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/finding-${RUN_TS}.log"

command -v claude >/dev/null 2>&1 || {
  echo "claude CLI not found in PATH. Install Claude Code or fix \$PATH." >&2
  exit 2
}

PIPELINE_STEP="runtime"
[[ "$KIND" == "feature" ]] && PIPELINE_STEP="ui"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Submitting $KIND finding" | tee -a "$LOG"
echo "  Description : $ONE_LINER"                              | tee -a "$LOG"
echo "  Log file    : $LOG"                                    | tee -a "$LOG"
echo ""                                                        | tee -a "$LOG"

# Escape any embedded quotes for safe inclusion in the prompt JSON example.
ESCAPED_ONE_LINER="$(printf '%s' "$ONE_LINER" | sed 's/"/\\"/g')"

PROMPT=$(cat <<EOF
You are running the manual operator-direct entry to the HeyBap forward-deployment pipeline. The operator (Lubin) just observed a $KIND in HeyBap and wants it routed through Phase 2. You are autonomous from now until the verdict.

The operator's one-line description:

  $ONE_LINER

Invoke the \`feature-bug-complexity-classification\` skill with this input:

\`\`\`json
{
  "kind": "$KIND",
  "title": "<derive from the one-liner, < 80 chars, focus on the affected surface>",
  "oneLineDescription": "$ESCAPED_ONE_LINER",
  "context": {
    "pipelineStep": "$PIPELINE_STEP",
    "evidence": [],
    "transcriptOrCoworker": "manual-trigger:operator"
  },
  "operatorConfidence": 0.85
}
\`\`\`

Run the gate's full flow without asking for confirmation:
1. Linear dedup search (team Bap, last 60 days, several distinctive tokens from the one-liner).
2. 5-minute investigation in a clone of \`the-agentic-company/bap\` to localize the surface and estimate fix size.
3. Clarification gate: if the surface is localized, the likely fix is small, and the only blocker is operator intent (for example exact UI placement or label wording), return \`needs-clarification\` with one concise question instead of dispatching as COMPLEX-SCOPED.
4. Classification on the 12-criterion grid (SIMPLE vs COMPLEX), after the clarification gate. Default to COMPLEX only when the clarification gate does not apply.
5. Dispatch:
   - SIMPLE → \`bap-bug-report\` runs its own 5-subagent deep research, opens the PR, and creates the Linear ticket at status In Review (label Bug or Feature + Dogfooding, assignee Lubin).
   - COMPLEX → \`bap-feature-brainstorm\` produces problem + 3 options + decision question, creates the Linear ticket at status Triage (label Need More Shaping + Bug or Feature + Dogfooding, assignee Baptiste). For capability gaps, Step 3b inside the brainstorm quantifies impact (Grain corpus + past builds + use cases unlocked + verdict) and the ticket carries an Impact section.

Do not stop to ask for permission on any tool call. The .claude/settings.json in this repo pre-approves every tool the gate needs.

Output at the end, in this exact shape:
1. The verdict: dispatched | needs-clarification | already-reported | low-confidence | config-missing.
2. The classification (kind + complexity).
3. The downstream skill invoked.
4. The clarification question if the verdict is needs-clarification.
5. The Linear ticket identifier and URL (e.g. BAP-127, https://linear.app/heybap/issue/BAP-127).
6. The PR URL if a PR was opened.
7. A one-sentence summary suitable for the dashboard.
EOF
)

cd "$REPO_ROOT"

claude -p "$PROMPT" \
  --add-dir "$REPO_ROOT" \
  --add-dir /tmp \
  2>&1 | tee -a "$LOG"

EXIT=${PIPESTATUS[0]}

echo ""                                                              | tee -a "$LOG"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Done (exit $EXIT). Log: $LOG"   | tee -a "$LOG"

exit "$EXIT"
