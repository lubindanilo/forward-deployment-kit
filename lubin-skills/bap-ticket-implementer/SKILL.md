---
name: bap-ticket-implementer
description: |
  Autonomous loop that picks up Linear tickets in team `Bap` assigned to
  Lubin and explicitly opted-in (label `agent-autonomous`), reads the
  description + comments + linked PR, implements the work on the
  `the-agentic-company/bap` repo using the same deep-research 5-subagent
  pattern as `bap-bug-report` (symptom → cause walk, callers, adjacency,
  tests, history), commits the result, opens or updates the PR, then
  posts a structured notification in Slack `#dev` with the original
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

`bap-bug-report` creates tickets with a proposed fix; this skill closes the gap when nobody picks them up. It pulls assigned tickets with the explicit opt-in label `agent-autonomous`, implements the work, commits, opens / updates the PR, comments the ticket, and posts a `#dev` message with the original problem + fix summary + a Baptiste ping so the review request lands where Baptiste actually looks for them.

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
- description has a `## Fix proposé` section OR a `## Acceptance criteria` section OR an implementation sketch from `bap-capability-impact-analyzer`
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

Implement the fix. Run any test from Step 4 angle 4 that touches the change site. If a test breaks unexpectedly, **stop** — do not edit the test. Post a Linear comment "Test broke unexpectedly: <test:file:line>. Implementation rolled back, escalating to operator". No commit.

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

If the ticket was at `Triage`, transition it to `In Review` (PR opened):

```
mcp__linear__save_issue({ id: "BAP-<n>", state: "<config.linear.statuses.in_review>" })
```

If it was already at `In Review`, no transition.

## Step 8 — Slack `#dev` notification (problem + fix + ping Baptiste for review)

Post a structured message in `#dev` summarising what just shipped and ask Baptiste to review.

Resolve identifiers:

- channel id from `config.yaml` (`slack.dev_channel_id`); fall back to `slack_search_channels({ query: "dev" })` if the placeholder is still in place.
- reviewer id from `config.yaml` (`slack.review_user_id`); fall back to `slack_search_users({ query: "Baptiste" })` if missing.

Body template (Slack mrkdwn):

```
:robot_face: *BAP-<n>* <ticket title> — implemented autonomously

*Problem.* <one or two sentences restating the symptom in plain language — pull from the ticket's "Problem" / "Symptôme" section, do not paste raw>

*Fix.* <one or two sentences naming the file(s) touched, the reuse anchor, and the diff size — e.g. "Reused `LoadingState`. +36 / -5 across 3 files.">

PR <URL> · commit `<sha-short>` · <lines> lines · <files-touched> files
Screenshots: <attachment.url #1> · <attachment.url #2>    ← only if the ticket already has image attachments OR Step 4's research pass captured a new repro; one URL per screenshot
<@<reviewer-id>> ready for your review. Post-deploy verification will run after merge.
```

Send via `mcp__aa816864-db59-4de1-a375-68c8cccbfe71__slack_send_message` (channel_id from config).

Screenshot rule: list every image attachment already on the Linear ticket (read `issue.attachments` from Step 3's `get_issue` call, filter on `contentType` starting with `image/`). If Step 4's deep research captured a fresh repro screenshot via Chrome MCP, upload it to the ticket first (`prepare_attachment_upload` + `create_attachment_from_upload`) and include the new URL too. Drop the whole `Screenshots:` line when there are zero images — do not write "Screenshots: none".

One message per PR. The `<@U…>` reviewer ping is required — it is the whole point of the post. On a re-implementation (loop tick later updating the same PR), reply in the thread of the original message rather than posting a new top-level message; the thread reply does NOT need to re-ping Baptiste.

## Step 9 — return to caller / log

Structured return:

```json
{
  "verdict": "implemented | escalated | stale-ticket | not-eligible | dry-run",
  "ticketRef": "BAP-<n>",
  "prUrl": "...",
  "commitSha": "...",
  "slackPermalink": "...",
  "linesChanged": 42,
  "filesChanged": 2,
  "researchAdaptation": "<one sentence or null>",
  "diagnosticNotes": "<one sentence if verdict != implemented>"
}
```

When called from `/loop`, append the return value to a JSONL log at `~/HeyBap Pipeline/logs/ticket-implementer.jsonl` for audit and the dashboard's Skills tab.

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
- Re-implementing a ticket whose PR is already open and CI-green. Check the existing PR first; if it solves the ticket, comment and stop, do not duplicate.
- Forgetting the FINDING_CONTEXT downstream contract. `bap-post-deploy-verify` reads it from the Linear ticket; if it is missing, fail eligibility instead of generating one (would lose the original signal).

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
  dev_channel_id: "C0AH3JU73E0"   # #dev — set once via slack_search_channels({ query: "dev" })
  review_user_id: "U0A87JNV8QP"   # Baptiste — set once via slack_search_users({ query: "Baptiste" })
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

If `dev_channel_id` or `review_user_id` is missing / a placeholder, the skill resolves it at runtime (via `slack_search_channels({ query: "dev" })` and `slack_search_users({ query: "Baptiste" })`) and caches the result in memory for the rest of the session.

## See also

- [bap-bug-report](../bap-bug-report/SKILL.md): creates the tickets this skill drains. Same 5-subagent research pattern.
- [bap-post-deploy-verify](../bap-post-deploy-verify/SKILL.md): closes the loop after this skill's PRs merge.
- [feature-bug-complexity-classification](../feature-bug-complexity-classification/SKILL.md): upstream gate. This skill only acts on tickets the gate already classified as SIMPLE.
- `bap-favorite-coworker-watchdog`: parallel autonomous loop that watches production coworkers and surfaces anomalies to `#agents-production`.
