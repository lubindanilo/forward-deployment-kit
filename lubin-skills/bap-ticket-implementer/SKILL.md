---
name: bap-ticket-implementer
description: |
  Autonomous loop that picks up Linear tickets in team `Bap` assigned to
  Lubin and explicitly opted-in (label `agent-autonomous`), reads the
  description + comments + linked PR, implements the work on the
  `the-agentic-company/bap` repo using the same deep-research 5-subagent
  pattern as `bap-bug-report` (symptom → cause walk, callers, adjacency,
  tests, history), commits the result, opens or updates the PR, then
  posts a structured notification in Slack `#pr-lubin` with the original
  problem, the fix applied, the PR + commit, and an `@Baptiste` ping
  for review. The ticket gets a Linear comment with the SHA, and (if the
  ticket was at `Triage`) is transitioned to `In Review`. Designed to
  drain low-friction items off the queue overnight; refuses to act on
  tickets that lack acceptance criteria, have unresolved comments, or
  whose proposed fix exceeds ~120 lines. Use as a scheduled `/loop`
  (every 30 min or every 2 h) or invoke directly with a single
  `ticketRef: "BAP-<n>"`.
---

# Autonomous Linear ticket implementer

`bap-bug-report` creates tickets with a proposed fix; this skill closes the gap when nobody picks them up. It pulls assigned tickets with the explicit opt-in label `agent-autonomous`, implements the work, commits, opens / updates the PR, comments the ticket, and posts a `#pr-lubin` message with the original problem + fix summary + a Baptiste ping so the review request lands where Baptiste actually looks for them.

Designed for the calm cases: a small fix, the proposed solution is already written on the ticket, the operator is asleep / in a meeting / off, and the queue can drain on its own. **Refuses** to touch anything ambiguous, large, or controversial.

## When to invoke

- Scheduled `/loop 30m` or `/loop 2h` on the operator's laptop or in a Bap meta-coworker.
- Direct invocation with `ticketRef: "BAP-<n>"` to act on one specific ticket.

Do not invoke for:

- Tickets without the `agent-autonomous` label (opt-in required; default is "operator implements").
- Tickets in any state other than `Triage` or `In Progress` or `In Review` with the label.
- Tickets whose comments include explicit `wait`, `blocked`, `@lubin please review first`, or an unresolved question.
- Tickets whose proposed fix exceeds ~120 lines (escalate to operator instead of attempting).

## Input contract

```json
{
  "ticketRef": "BAP-<n> (optional; when set, act on this ticket only)",
  "options": {
    "cadenceMinutes": 30,
    "maxLinesPerCommit": 120,
    "confidenceFloor": 0.7,
    "branchPrefix": "fix/bap-",
    "dryRun": false
  }
}
```

`dryRun: true` performs steps 1 to 5 (read + research + implement on a local branch) without pushing the branch or commenting the ticket.

## Step 1 — pick the next eligible ticket(s)

When called without `ticketRef`, query Linear:

```
mcp__linear__list_issues({
  team: "BAP",
  assignee: "lubin",
  label: "agent-autonomous",
  state: "Triage" or "In Progress" or "In Review",
  limit: 25,
  orderBy: "updatedAt"
})
```

For each candidate, apply the eligibility filter (see Step 2). Process the first eligible ticket; subsequent tickets land in the next loop tick.

When called with `ticketRef`, fetch only that ticket and proceed with the same filter.

## Step 2 — eligibility filter (hard gate)

The ticket must satisfy all of:

- `state in { "Triage", "In Progress", "In Review" }`
- `assignee.displayName == "lubin"`
- has label `agent-autonomous`
- last comment is not one of: "wait", "blocked", "ne pas toucher", "@lubin please review first", or any comment newer than 24 h from a different user that ends with a question mark
- description has a `## Fix proposé` section OR a `## Acceptance criteria` section OR an implementation sketch (from `bap-feature-brainstorm`'s Impact step, when the ticket came out of the SCOPED branch and an option was picked)
- FINDING_CONTEXT block present (so the verifier can close the loop later)

If any condition fails, post a Linear comment explaining which condition failed (single sentence), skip the ticket, and log.

## Step 3 — read everything

Fetch the full ticket context:

```
issue   = mcp__linear__get_issue({ id: "<ticketRef>", includeRelations: true })
comments = mcp__linear__list_comments({ issueId: issue.id })
```

If the ticket has a linked PR (Linear's GitHub integration), fetch its current diff + CI status:

```
gh pr view <num> --repo the-agentic-company/bap --json title,body,headRefName,statusCheckRollup,reviewDecision,mergeable
gh pr diff <num> --repo the-agentic-company/bap
```

Extract:

- the proposed fix from the description (file:line refs are mandatory; if missing, fail eligibility)
- acceptance criteria / success criteria (what the result must do)
- alternatives already considered (do not re-litigate them)
- FINDING_CONTEXT JSON (for downstream verify)
- any operator refinements in comments (newest first wins)

## Step 4 — deep codebase research (5 parallel subagents, same pattern as `bap-bug-report`)

Even when the ticket describes the fix, do the research pass: the ticket may be stale, the code may have moved, callers may have changed. Skipping this is the failure mode this skill exists to prevent.

Invoke 5 subagents in parallel (Agent tool, `general-purpose` or `Explore`, single message):

1. **Symptom → root cause walk** anchored on the ticket's description, file:line chain confirmed today.
2. **Caller graph** of the change site — verify no caller broke since the ticket was written.
3. **Adjacent implementations** — confirm the ticket's proposed pattern is still the right reuse anchor.
4. **Test contract** in the area — list every test that locks in the current behaviour.
5. **History lens** — git log + git blame, surface any commit landed AFTER the ticket was written that touches the area (could obsolete the fix).

Synthesise: is the ticket still implementable as written? Three outcomes:

- **Yes, exact**: proceed to Step 5.
- **Yes, with small adaptation**: note the adaptation in a `## Adaptation` Linear comment, then proceed.
- **No, stale**: post a Linear comment listing the conflicts (file moved, behaviour already shipped in another commit, contract change), do not implement, set ticket label `needs-refresh`. Done.

## Step 5 — implement on a branch (smallest viable diff)

Same constraints as `bap-bug-report` Step 7:

- Smallest possible diff, one or two files.
- Cap: `options.maxLinesPerCommit` (120 by default). If exceeded, halt and post a Linear comment "Implementation exceeds <cap> lines — escalating to operator". No commit.
- No new abstraction, no refactor, no while-I-am-here cleanup, no defensive code for impossible cases.
- No comments in the code explaining the bug.
- No em-dashes anywhere.

```bash
ls -d /tmp/bap-* 2>/dev/null || gh repo clone the-agentic-company/bap /tmp/bap-impl-$(date +%s)
cd /tmp/bap-*
git fetch origin && git checkout main && git pull
git checkout -b <branchPrefix><n>-<short-slug>      # e.g. fix/bap-127-skill-add-race
```

Implement the fix. Then run the full local test suite for the touched packages before staging:

- if the change touches `apps/web/`: `cd apps/web && bun run test:integration`.
- if the change touches `packages/core/`: `cd packages/core && bun run test:unit`.
- if both: `bun run test:ci` from the repo root.
- always run `cd apps/web && bun run typecheck` and `bun run lint` on the touched files.

If a test breaks unexpectedly, **stop** — do not edit the test. Post a Linear comment "Test broke unexpectedly: <test:file:line>. Implementation rolled back, escalating to operator". No commit. Same rule for typecheck or lint failures: fix the cause, do not bypass.

Commit:

```
<Area>: <verb> <object> (BAP-<n>)

Implemented autonomously by bap-ticket-implementer based on ticket description.
Adaptation, if any, noted in Linear comment timestamp <iso>.
File:line refs: <list>
```

## Step 6 — push + open or update PR

If a PR already exists for this ticket (linked via Linear's GitHub integration):

```bash
git push origin <branch>
gh pr edit <num> --repo the-agentic-company/bap --add-label autonomous-implementation
gh pr review <num> --comment --body "Updated by bap-ticket-implementer at <iso>. Diff: <gh diff link>"
```

If no PR exists yet:

```bash
git push -u origin <branch>
gh pr create \
  --repo the-agentic-company/bap \
  --base main \
  --title "BAP-<n> <Area>: <verb> <object>" \
  --body "Closes BAP-<n>. Implemented autonomously by bap-ticket-implementer. Linear ticket carries full context, FINDING_CONTEXT, and acceptance criteria." \
  --label autonomous-implementation
```

Capture the PR URL.

## Step 6.5 — verify the fix end-to-end on localhost (Chrome MCP, mandatory for UI changes)

Same contract as `bap-bug-report` Step 7.5. The autonomous loop does NOT post `Fixed, to review` unless the verification passed (or was explicitly skipped with a reason).

### A. Read the symptom assertion from the Linear ticket

`bap-bug-report` records `evidence.symptomAssertion` inside the FINDING_CONTEXT JSON block on every ticket it opens. Pull it:

```
issue = mcp__linear__get_issue({ id: "BAP-<n>" })
# parse the FINDING_CONTEXT block in issue.description; field: evidence.symptomAssertion
```

If the FINDING_CONTEXT is missing or has no `symptomAssertion`, set `verifyResult = { passed: false, skipped: true, reason: "no-symptom-assertion-on-ticket" }` and jump to subsection D. The autonomous loop never invents an assertion.

### B. Branch swap on the operator's main checkout

```bash
MAIN="<config.local_dev.bap_main_checkout>"
BRANCH="<fix branch from Step 6>"
PREV_BRANCH=$(git -C "$MAIN" rev-parse --abbrev-ref HEAD)
DIRTY=$(git -C "$MAIN" status --porcelain)
if [ -n "$DIRTY" ]; then
  git -C "$MAIN" stash push --include-untracked --message "bap-ticket-implementer-verify-BAP-<n>"
  STASHED=1
fi
git -C "$MAIN" fetch origin "$BRANCH"
git -C "$MAIN" switch "$BRANCH"
sleep <config.local_dev.hmr_wait_seconds>
```

On any swap failure → `verifyResult = { passed: false, skipped: true, reason: "branch-swap-failed: <err>" }` and jump to subsection D.

### C. Reproduce + assert + screenshot via Chrome MCP

```
mcp__Claude_in_Chrome__navigate({ url: "<config.local_dev.dev_server_url>/<bug-path-from-FINDING_CONTEXT>" })
# Replay any interaction (form_input, computer) needed to surface the symptom.
mcp__Claude_in_Chrome__screenshot({ })   # save to ~/HeyBap Pipeline/artifacts/BAP-<n>/after.png
afterText = mcp__Claude_in_Chrome__get_page_text({ })
console   = mcp__Claude_in_Chrome__read_console_messages({ })
network   = mcp__Claude_in_Chrome__read_network_requests({ })
```

Evaluate `symptomAssertion` against the captured state. The check is plain code (string match, regex, DOM probe via `find` / `inspect`), not an LLM judgment. Record:

```json
{
  "verifyResult": {
    "passed": true | false,
    "skipped": false,
    "assertion": "<verbatim from FINDING_CONTEXT.evidence.symptomAssertion>",
    "observed": "<one sentence: what Chrome actually showed>",
    "afterScreenshot": "~/HeyBap Pipeline/artifacts/BAP-<n>/after.png",
    "consoleClean": true | false,
    "networkClean": true | false
  }
}
```

### D. Restore the operator's working tree (always)

```bash
git -C "$MAIN" switch "$PREV_BRANCH"
if [ "${STASHED:-0}" = "1" ]; then git -C "$MAIN" stash pop; fi
```

Run subsection D inside a trap / finally so a thrown error in B / C never leaves the operator's checkout on the fix branch.

### E. Upload the AFTER screenshot to Linear

For both PASS and FAILED outcomes (skip only when there is no screenshot, e.g. backend-only fix):

```
upload  = mcp__linear__prepare_attachment_upload({ issue: "BAP-<n>", filename: "after.png", contentType: "image/png", size: <bytes> })
# PUT bytes to upload.uploadRequest.url with the signed headers
mcp__linear__create_attachment_from_upload({ issue: "BAP-<n>", assetUrl: upload.assetUrl, title: "After fix" })
```

Record the returned `attachment.url` for Step 8 (Slack post) to cite.

### F. Fallbacks (autonomous loop is often AFK)

- Chrome MCP unreachable → Playwright fallback (headless chromium against `localhost:3000` with `storage-state.json`). Same swap + sleep + assertion logic.
- Localhost down → `verifyResult.skipped = true, reason = "localhost-down"`.
- Backend-only ticket → verify via `curl` or `mcp__bap-local__chat_run` / `coworker_run`, assert on response shape; `verifyResult.skipped = false`.

If `verifyResult.passed === false && !verifyResult.skipped`: Step 7 keeps the ticket on `In Progress` (NOT `In Review`), keeps assignee Lubin (NOT Baptiste), and Step 8 uses the FAILED template pinging Lubin.

## Step 7 — Linear comment + state transition

Post a comment on the ticket with the commit SHA + PR URL + research summary:

```
Implemented autonomously at <iso>.

Commit: <sha> (BAP-<n> <Area>: <verb> <object>)
PR: <URL>
Lines: <n>
Tests touched: <count>

Adaptation vs ticket description (if any): <one paragraph from Step 4>
Research summary: 5 subagents agreed on the root cause as described; adjacency reused from <file:line>.

`bap-post-deploy-verify` will pick this up after merge + deploy.
```

Use `mcp__linear__save_comment({ issueId: <uuid>, body: ... })`.

Then transition status and reassign. **Conditional on `verifyResult` from Step 6.5.**

Pass case (`verifyResult.passed === true` OR `verifyResult.skipped === true`):

```
mcp__linear__save_issue({
  id: "BAP-<n>",
  state: "<config.linear.statuses.in_review>",      // idempotent: no-op if already In Review
  assignee: "<config.linear.reviewer_user_id>"      // Baptiste; PR is in his court now
})
```

Fail case (`verifyResult.passed === false && !verifyResult.skipped`):

```
mcp__linear__save_issue({
  id: "BAP-<n>",
  state: "<config.linear.statuses.in_progress>",    // stays on Lubin's queue, NOT reassigned
})
mcp__linear__save_comment({
  issue: "BAP-<n>",
  body: "Vérif Chrome MCP KO sur la branche du fix.\nAssertion : <verifyResult.assertion>\nObservé : <verifyResult.observed>\nPR laissée en draft, à reprendre."
})
```

`bap-post-deploy-verify` transitions PASS / SKIPPED tickets from `In Review` to `Live` after Baptiste's merge + the prod deploy. The FAIL case never gets there until Lubin re-implements.

## Step 8 — Slack `#pr-lubin` notification (problem + fix + ping Baptiste for review)

**This step is MANDATORY**. Without the Slack post, Baptiste doesn't learn the PR exists; the autonomous loop is NOT done at "PR opened + Linear updated" — it is done at "Slack #pr-lubin post permalink captured".

Resolve identifiers:

- channel id from `config.yaml` (`slack.pr_channel_id` = `C0BCH5L6PQS` = `#pr-lubin`); fall back to `slack_search_channels({ query: "pr-lubin" })` only if the placeholder is still in place.
- reviewer id from `config.yaml` (`slack.review_user_id` = `U0A87JNV8QP` = Baptiste); fall back to `slack_search_users({ query: "Baptiste" })` only if missing.

The body template is **conditional on `verifyResult` from Step 6.5**. Three variants (same shape as `bap-bug-report` Step 10).

### Variant 1 — PASS (verifyResult.passed === true)

```
Fixed, to review <@<reviewer-id>> <PR URL>
_<PR title without the BAP-<n> prefix>_
<problème en 1-2 phrases, langue produit, tiré du ticket>
<fix en 1-2 phrases avec file:line touché>. Ticket : BAP-<n>.
Verified : ✅ <verifyResult.assertion>. <verifyResult.observed>
Screenshots : <BEFORE Linear asset URL> · <AFTER Linear asset URL>
```

### Variant 2 — SKIPPED (verifyResult.skipped === true)

```
Fixed, to review <@<reviewer-id>> <PR URL>
_<PR title without the BAP-<n> prefix>_
<problème en 1-2 phrases, langue produit, tiré du ticket>
<fix en 1-2 phrases avec file:line touché>. Ticket : BAP-<n>.
Verified : skipped (<verifyResult.reason>). À retester avant merge.
```

### Variant 3 — FAILED (verifyResult.passed === false && !skipped)

Pings the operator (Lubin), NOT Baptiste — the fix is broken, Lubin re-investigates.

```
Vérif KO, à reprendre <@<operator-id>> <PR URL>
_<PR title without the BAP-<n> prefix>_
<problème en 1-2 phrases, langue produit, tiré du ticket>
<tentative en 1-2 phrases avec file:line touché>. Ticket : BAP-<n>.
Verified : ❌ <verifyResult.assertion>. <verifyResult.observed>. PR laissée en draft.
Screenshots : <BEFORE Linear asset URL> · <AFTER Linear asset URL>
```

`<operator-id>` = `config.slack.operator_user_id` (Lubin, `U0AT7378GSX`).

Mandatory call sequence:

```
result = mcp__aa816864-db59-4de1-a375-68c8cccbfe71__slack_send_message({
  channel_id: "<config.slack.pr_channel_id>",
  text: "<composed body above>"
})
if result.ok != true OR result.permalink is null:
  # retry once (transient API errors are common)
  result = mcp__aa816864-db59-4de1-a375-68c8cccbfe71__slack_send_message({ channel_id, text })
if result.ok != true OR result.permalink is null:
  # do NOT pretend success; surface the error in Step 9's verdict
  slackPostFailed = true
  slackPostError  = result.error or "no permalink returned"
else:
  slackPermalink = result.permalink
```

Constraints:

- Exactly one message per PR (top-level, no thread reply). On a re-implementation tick that updates an existing PR, detect the prior message via `slack_search_public({ query: "<PR URL>", limit: 5 })`; if found, reply in its thread WITHOUT re-pinging Baptiste; if not found, post a fresh top-level message.
- Line 1 prefix is the action label. PASS = `Fixed, to review` (ping Baptiste). SKIPPED = also `Fixed, to review` (still Baptiste's queue, just unverified). FAILED = `Vérif KO, à reprendre` (ping Lubin, NOT Baptiste).
- The PR URL on line 1 is the actionable link. The italic PR title on line 2 reinforces "PR is open, just review the diff."
- No `Linear:` link line. The ticket reference at the end (`Ticket : BAP-<n>`) is enough.
- Both descriptive sentences (problem + fix) carry `file:line` references for the bridge between the PR diff and the symptom.
- The `Verified:` line is **mandatory** in every variant.
- The `Screenshots:` line is **mandatory whenever the Linear ticket has BEFORE / AFTER attachments** (PASS and FAILED variants). Cite the Linear asset URLs (Slack auto-unfurls them inline).

## Step 8.5 — watch CI, fix red until green

Required for every PR opened or updated by this skill. The autonomous loop owns the green-up; never leave a red PR open for Baptiste to deal with.

1. **Watch CI.** Poll `gh pr checks <num>` until every check completes. The Bap CI runs oxlint, typecheck (`tsgo`), Fallow audit (CRAP / dead-code / dupes), gitleaks, react-doctor, and `bun run test:ci` (vitest unit + integration).

2. **If any check is red: fix it, do not abandon.** Read the failure log with `gh run view <id> --log-failed`, identify the root cause, fix in code on the SAME branch (do not close + reopen), commit, push, and watch again. Loop until green. Common gates and their fixes:
   - Fallow CRAP score at or above threshold → extract a small helper to drop cyclomatic.
   - oxlint `curly` → braces around `if` bodies.
   - typecheck error → match the existing signature.
   - vitest failure → the implementation is wrong; do NOT edit the test, return to Step 4 and pick a different angle.

   Never bypass with `--admin`, `--no-verify`, or by commenting-out the gate. If after 3 fix iterations the failure is genuinely architectural (e.g. requires a much larger refactor than the 120-line cap), halt the loop, post a Linear comment "CI failure not resolvable within the ticket's scope — escalating to operator", and exit. The PR stays open for Baptiste to look at.

3. **When CI is green, stop here.** The operator (Lubin) no longer has merge rights on `the-agentic-company/bap`; **only Baptiste merges**. The skill's contract ends at "PR opened or updated, CI green, Slack #pr-lubin pinged Baptiste at Step 8." Do NOT call `gh pr merge`. Do NOT trigger any deploy workflow. Baptiste reviews and squash-merges from GitHub when he is ready.

4. **Post-merge cleanup is owned by `bap-post-deploy-verify`**, not by this skill. Once Baptiste merges and the deploy lands, the verifier reads the FINDING_CONTEXT off the Linear ticket and confirms the fix in prod.

## Step 9 — return to caller / log

Structured return:

```json
{
  "verdict": "implemented | escalated | stale-ticket | not-eligible | dry-run",
  "ticketRef": "BAP-<n>",
  "prUrl": "...",
  "commitSha": "...",
  "slackPermalink": "...",         // null when slackPostFailed is true
  "slackPostFailed": false,        // true when Step 8's retry also failed; never silently null both
  "slackPostError": null,          // error message when slackPostFailed; null otherwise
  "linesChanged": 42,
  "filesChanged": 2,
  "researchAdaptation": "<one sentence or null>",
  "diagnosticNotes": "<one sentence if verdict != implemented>"
}
```

When called from `/loop`, append the return value to a JSONL log at `~/HeyBap Pipeline/logs/ticket-implementer.jsonl` for audit and the dashboard's Skills tab. The dashboard surfaces `slackPostFailed: true` as a red badge on the run row so the operator reposts manually.

## Autonomous mode (`/loop`)

```
/loop 30m drain agent-autonomous tickets assigned to Lubin
  invoke bap-ticket-implementer with no ticketRef
  on each return, write the verdict to ~/HeyBap Pipeline/logs/ticket-implementer.jsonl
  stop iterating when no eligible ticket is found OR after 5 implementations per tick
```

The cap of 5 implementations per tick prevents a runaway loop from carpet-bombing PRs if the eligibility filter is misconfigured.

## Anti-patterns

- Implementing without the `agent-autonomous` label. The label is the operator's explicit opt-in for autonomous action; never widen the filter.
- Skipping the deep-research pass because the ticket already describes the fix. The codebase may have moved; the research pass is the safety net.
- Editing a failing test to make it pass. A broken test means the fix is wrong; escalate to operator instead.
- Implementing when the last comment is a question or a `wait` / `blocked` marker. The operator is doing something with this ticket; do not race.
- Carpet-bombing PRs in a single tick. Cap of 5 implementations per `/loop` invocation is hard.
- Posting to Slack without including the PR URL + commit SHA + line counts. The notification IS the proof of work; minus those refs it is noise.
- Posting to Slack without the original problem + fix summary or without the Baptiste ping. The review request never starts; the activity-feed-only format is no longer the team norm.
- Forgetting the `Screenshots:` line when the ticket has image attachments. Slack auto-unfurls Linear asset URLs, so citing them gives Baptiste the repro evidence inline instead of forcing a Linear roundtrip.
- Posting the PASS template (`Fixed, to review`) when `verifyResult.passed === false`. The fix did not fix; use the FAILED template pinging Lubin instead.
- Skipping Step 6.5's Chrome MCP verification when localhost is reachable and the ticket has a UI surface. The verification is the contract, not optional.
- Leaving the operator's main checkout on the fix branch after Step 6.5. Subsection D must always run, even on a thrown error.
- Re-implementing a ticket whose PR is already open and CI-green. Check the existing PR first; if it solves the ticket, comment and stop, do not duplicate.
- Forgetting the FINDING_CONTEXT downstream contract. `bap-post-deploy-verify` reads it from the Linear ticket; if it is missing, fail eligibility instead of generating one (would lose the original signal).
- Calling `gh pr merge` from this skill. Lubin no longer has merge rights on `the-agentic-company/bap`; Baptiste is the only person who merges. The autonomous loop stops at "CI green + Slack #pr-lubin pinged."
- Triggering any deploy workflow (`release-main.yml`, `prod-release.yml`). Deploys are owned by Baptiste post-merge.

## Config

`lubin-skills/bap-ticket-implementer/config.yaml`:

```yaml
linear:
  team_key: "BAP"
  assignee_username: "lubin"
  trigger_label: "agent-autonomous"
  refresh_label: "needs-refresh"
  in_review_status: "423d89b9-126c-4db1-aa27-05b25baafd20"
slack:
  workspace: "The Agentic Company"
  pr_channel_id: "C0BCH5L6PQS"      # #pr-lubin — set once via slack_search_channels({ query: "pr-lubin" })
  review_user_id: "U0A87JNV8QP"     # Baptiste — pinged on Step 8 PASS / SKIPPED variants
  operator_user_id: "U0AT7378GSX"   # Lubin — pinged on Step 8 FAILED variant when verify KO
local_dev:
  bap_main_checkout: "/Users/lubin.danilo/bap/bap"   # operator's checkout serving the dev server; Step 6.5 swaps branches here
  dev_server_url: "http://localhost:3000"            # probe target + Chrome MCP navigate target
  hmr_wait_seconds: 5                                # post-swap delay for Next.js HMR to recompile
github:
  repo: "the-agentic-company/bap"
  branch_prefix: "fix/bap-"
  pr_label: "autonomous-implementation"
limits:
  cadence_minutes: 30
  max_lines_per_commit: 120
  max_implementations_per_tick: 5
  confidence_floor: 0.7
log_path: "~/HeyBap Pipeline/logs/ticket-implementer.jsonl"
```

If `pr_channel_id` or `review_user_id` is missing / a placeholder, the skill resolves it at runtime (via `slack_search_channels({ query: "pr-lubin" })` and `slack_search_users({ query: "Baptiste" })`) and caches the result in memory for the rest of the session.

## See also

- [bap-bug-report](../bap-bug-report/SKILL.md): creates the tickets this skill drains. Same 5-subagent research pattern.
- [bap-post-deploy-verify](../bap-post-deploy-verify/SKILL.md): closes the loop after this skill's PRs merge.
- [feature-bug-complexity-classification](../feature-bug-complexity-classification/SKILL.md): upstream gate. This skill only acts on tickets the gate already classified as SIMPLE.
- `bap-favorite-coworker-watchdog`: parallel autonomous loop that watches production coworkers and surfaces anomalies to `#agents-production`.
