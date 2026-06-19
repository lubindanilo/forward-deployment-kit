#!/usr/bin/env bash
# build-from-transcript.sh
#
# Manual trigger, autonomous from there. Pass a transcript (file path, Grain URL,
# or inline text). The script invokes `claude -p` from the FDK repo root, which
# picks up .claude/settings.json (pre-approved tools) and runs the full pipeline:
# parse -> resolve tools -> build MCPs if needed -> skill_add -> coworker_create
# + update -> bap-coworker-test-loop -> emit a report.
#
# Every HeyBap gap observed during the run is routed through bap-finding-router,
# which dispatches to bap-bug-report (SIMPLE) or bap-feature-brainstorm (COMPLEX).
# After a merge on the-agentic-company/bap, run bap-post-deploy-verify on the PR
# (separately or via a /loop wrapper) to close the loop.

set -euo pipefail

usage() {
  cat <<USAGE >&2
Usage: $(basename "$0") <transcript> [prospect] [callType] [maxAgents]

  <transcript>   Path to a file, a Grain URL, or "-" to read from stdin.
  [prospect]     Optional prospect name (improves the agentSpec).
  [callType]     discovery | kickoff | follow-up | technical | demo (default: discovery)
  [maxAgents]    Cap agents built (default: 3)

Examples:
  $(basename "$0") /tmp/grain-export.txt "Concentrix" discovery
  $(basename "$0") "https://grain.com/share/abc" "Eden Red"
  $(basename "$0") - "Acme" < /tmp/transcript.txt
USAGE
  exit 1
}

[[ $# -lt 1 ]] && usage

TRANSCRIPT_INPUT="$1"
PROSPECT="${2:-}"
CALL_TYPE="${3:-discovery}"
MAX_AGENTS="${4:-3}"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUN_TS="$(date +%Y%m%d-%H%M%S)"
LOG_DIR="$REPO_ROOT/.run-logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/build-${RUN_TS}.log"

command -v claude >/dev/null 2>&1 || {
  echo "claude CLI not found in PATH. Install Claude Code or fix \$PATH." >&2
  exit 2
}

# Auto-launch the live dashboard so the operator can watch pipeline state,
# parallel agents, generated outputs and Linear tickets in real time.
# Idempotent: skips if a monitor is already serving on port 7777.
# Disable with FDK_SKIP_DASHBOARD=1.
if [[ "${FDK_SKIP_DASHBOARD:-0}" != "1" ]] && [[ -x "$REPO_ROOT/scripts/dashboard.sh" ]]; then
  "$REPO_ROOT/scripts/dashboard.sh" || true
fi

# Resolve the transcript input to a stable reference string for the prompt
if [[ "$TRANSCRIPT_INPUT" == "-" ]]; then
  TMP_TRANSCRIPT="$(mktemp /tmp/transcript-${RUN_TS}-XXXXXX.txt)"
  cat - > "$TMP_TRANSCRIPT"
  TRANSCRIPT_REF="path: $TMP_TRANSCRIPT"
elif [[ -f "$TRANSCRIPT_INPUT" ]]; then
  TRANSCRIPT_REF="path: $TRANSCRIPT_INPUT"
elif [[ "$TRANSCRIPT_INPUT" =~ ^https?:// ]]; then
  TRANSCRIPT_REF="url: $TRANSCRIPT_INPUT"
else
  TMP_TRANSCRIPT="$(mktemp /tmp/transcript-${RUN_TS}-XXXXXX.txt)"
  printf '%s\n' "$TRANSCRIPT_INPUT" > "$TMP_TRANSCRIPT"
  TRANSCRIPT_REF="path: $TMP_TRANSCRIPT"
fi

CONTEXT_JSON=$(jq -n \
  --arg prospect "$PROSPECT" \
  --arg callType "$CALL_TYPE" \
  '{prospect: $prospect, callType: $callType} | with_entries(select(.value != ""))')

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting FDK pipeline" | tee -a "$LOG"
echo "  Transcript : $TRANSCRIPT_REF"                       | tee -a "$LOG"
echo "  Context    : $CONTEXT_JSON"                         | tee -a "$LOG"
echo "  Max agents : $MAX_AGENTS"                           | tee -a "$LOG"
echo "  Log file   : $LOG"                                  | tee -a "$LOG"
echo ""                                                      | tee -a "$LOG"

PROMPT=$(cat <<EOF
You are running the FDK autonomous pipeline. The user manually triggered this with a transcript; you are autonomous from now until the report.

Invoke the skill \`transcript-to-bap-coworker\` with:
  transcript: $TRANSCRIPT_REF
  context: $CONTEXT_JSON
  options: { maxAgents: $MAX_AGENTS, testEnvPath: "$REPO_ROOT/test_env.yaml", skillFolderRoot: "/tmp/agent-builds", handoffChannel: "#agents-builds" }

Run the full pipeline end-to-end without asking for confirmation:
1. parse-transcript-to-agent-spec
2. resolve tools, build custom MCPs if needed. When a HUMAN STOP for workspace MCP bind is reached, document it in the report and continue with the next agent (do not block the whole pipeline).
3. generate skill folders (SKILL.md + render.py + output.html template as needed)
4. mcp__bap__skill_add
5. mcp__bap__coworker_create + coworker_update (two-call pattern)
6. bap-coworker-test-loop on each coworker with stopOnFirstHumanCheckpoint=false. Panel E2E phase-2 tests get queued as HUMAN STOPs in the report.
7. Emit the final consolidated Markdown report to /tmp/agent-builds/<callId>/report.md

For every HeyBap gap observed during the run, invoke \`bap-finding-router\` exactly once per finding. Do not invoke \`bap-bug-report\` or \`bap-feature-brainstorm\` directly; the router classifies and dispatches.

Do not stop to ask for permission on any tool call. The .claude/settings.json in this repo pre-approves every tool the pipeline needs.

Output at the end, in this exact shape:
1. The final report path.
2. The list of @username coworkers that landed live.
3. The list of agents that need a human stop (with the stop reason).
4. The list of PRs opened on the-agentic-company/bap during this run.
5. The list of Linear tickets created during this run (one block per ticket: BAP-<n>, URL, state In Review for SIMPLE or Triage for COMPLEX, label set, assignee). For COMPLEX feature gaps, mention that the brainstorm ticket carries an Impact section produced by bap-capability-impact-analyzer (use cases unlocked, t-shirt size, verdict).
EOF
)

cd "$REPO_ROOT"

claude -p "$PROMPT" \
  --add-dir "$REPO_ROOT" \
  --add-dir /tmp \
  2>&1 | tee -a "$LOG"

EXIT=${PIPESTATUS[0]}

echo ""                                            | tee -a "$LOG"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Done (exit $EXIT). Full log: $LOG" | tee -a "$LOG"

exit "$EXIT"
