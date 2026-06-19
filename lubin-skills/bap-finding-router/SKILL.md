---
name: bap-finding-router
description: |
  Single entry point for every HeyBap finding observed during forward
  deployment: bug, missing feature, friction, surprise. Classifies the
  finding on a strict simple-vs-complex grid and dispatches to one of
  two leaf skills: `bap-bug-report` (SIMPLE: investigates, implements
  the quick fix on a branch in `the-agentic-company/bap`, opens a PR,
  notifies `#technical-pr` with @Baptiste) or `bap-feature-brainstorm`
  (COMPLEX: investigates, frames the finding as problem + 3 options +
  decision question, posts to `#brainstorming-produit`). Use whenever
  `parse-transcript-to-agent-spec`, `bap-coworker-test-loop`,
  `transcript-to-bap-coworker`, or a human observes a HeyBap gap.
---

# Finding router for HeyBap

The pipeline skills (`parse-transcript-to-agent-spec`, `bap-coworker-test-loop`, `transcript-to-bap-coworker`) sit at the front line of HeyBap usage. They are designed to surface every platform gap or misbehaviour as a structured *finding*. This skill is the single gate every finding goes through. It classifies, decides where the finding lands, and invokes the right downstream skill autonomously.

No finding bypasses this router. No finding is silently logged in a TODO comment or in the orchestrator's final report only.

## When to invoke

- A pipeline step concludes "the root cause is in HeyBap, not in my prompt / skill" (`bap-coworker-test-loop` diagnose step returns `requiresHuman: true`).
- The parser flags an `ambiguities[]` entry whose real story is "the platform should let me do this".
- The orchestrator hits a HUMAN STOP that should not exist (workspace MCP bind, skill re-upload conflict, etc.).
- Inspecting a coworker output, a panel button, or a sandbox file, the operator notices a regression.
- A teammate says "this is broken in HeyBap" in chat and points at a specific surface.

Do not invoke for findings outside HeyBap: a bug in a third-party MCP, a Notion API change, a Slack rate limit. Those go to the relevant provider's channel.

## Input contract

```json
{
  "kind": "bug | feature",
  "title": "<one-line restatement, < 80 chars>",
  "oneLineDescription": "<what the operator observed, factual>",
  "context": {
    "pipelineStep": "parse | step2-resolve | step2b-mcp-bind | step3-generate | step4-skill_add | step5-coworker_create | step6-test-loop | step7-report | runtime | ui",
    "evidence": [
      { "kind": "code_ref", "value": "apps/web/src/components/prompt-bar.tsx:56" },
      { "kind": "run_id", "value": "run-abc123" },
      { "kind": "log_excerpt", "value": "<short quote from coworker_logs>" },
      { "kind": "screenshot_path", "value": "/tmp/screenshot-2026-06-18.png" }
    ],
    "transcriptOrCoworker": "<optional pointer: @coworker-username or transcript path>"
  },
  "operatorConfidence": 0.0
}
```

`operatorConfidence` is the calling skill's own estimate of "how sure am I this is a real HeyBap issue vs my own misuse". The router uses it in the classification.

## Classification grid (the only rule that matters)

A finding is **SIMPLE** if and only if EVERY criterion in the grid below is true. If even one is false, it is **COMPLEX**. When in doubt, classify as COMPLEX (failsafe).

| Criterion | Threshold for SIMPLE |
|-----------|----------------------|
| Lines changed by the proposed fix | < 50 |
| Files touched by the proposed fix | <= 2 |
| Migration of the DB or state model required | no |
| Breaking change to an exported API (orpc routers, MCP tools, db schema exports) | no |
| Touches `packages/db/src/schema/*` data model definitions | no |
| Touches sandbox runtime, auth, billing, multi-tenant boundary | no |
| Existing tests already cover the area (or one trivial test to add) | yes |
| Operator confidence in the fix | >= 0.8 |
| More than one defensible approach (genuine design choice) | no |
| Documented elsewhere as "do not touch without design discussion" | no |
| Bug only: live reproducible deterministically in <5 min | yes (bugs only) |
| Feature only: scope fits in a single PR description (<= 5 bullets) | yes (features only) |

## Investigation step (5 minutes, hard cap)

Before classifying, the router does a focused investigation:

1. Clone (or reuse) `the-agentic-company/bap` locally under `/tmp/bap-router-<timestamp>` (or pull an existing recent clone).
2. Grep for the evidence references provided (`file:line` if any).
3. Estimate: which files would the fix touch, how many lines, does it cross any of the failsafe boundaries above.
4. Form an operator-side opinion on the fix path (this is what gets passed downstream if it dispatches to `bap-codebase-fix`).

If the 5-minute cap is reached without a confident classification, default to COMPLEX. The router never burns more than 5 minutes per finding; deep investigation lives downstream (`bap-bug-report` or `bap-feature-brainstorm`).

## Dispatch matrix

After classification, two destinations:

| classification | downstream skill | output |
|----------------|------------------|--------|
| SIMPLE (bug or feature) | `bap-bug-report` | Branch + quick fix implemented + PR opened on `the-agentic-company/bap` + short notification in `#technical-pr` with @Baptiste pinged. Features whose fix exceeds ~50 lines land as draft PRs with a TODO checklist in the body (handled by `bap-bug-report` itself). |
| COMPLEX (feature OR structural bug) | `bap-feature-brainstorm` | Investigation + problem statement + 3 defensible options + decision question, posted to `#brainstorming-produit`. No PR opened. Implementation goes through `bap-bug-report` in a follow-up once the team picks an option. |

The router does not implement the fix itself. It only classifies and forwards. The downstream skill owns the rest of the loop (investigation depth, PR, Slack, dedup of its own kind).

## Dedup before dispatch

Two checks, in order. The downstream skills also dedup at their own layer, but doing a fast check at the router avoids wasting investigation budget on a duplicate.

1. **Slack dedup**: search the target channel for the last 60 days using distinctive tokens from the finding (file paths, symbol names, unique noun phrases). For SIMPLE, search `#technical-pr` (channel id from config). For COMPLEX, search `#brainstorming-produit`. If a recent thread covers the same root cause, do not dispatch. Return `verdict: "already-reported"` + permalink.
2. **PR dedup** (SIMPLE only): `gh pr list --search "<distinctive token>" --state open --repo the-agentic-company/bap`. If an open PR addresses the same root cause, do not dispatch. Return `verdict: "already-reported"` + PR URL.

A duplicate is worse than no message. Never bypass the dedup checks.

## Confidence floor

If the **operatorConfidence** is below 0.6, the router refuses to dispatch and returns a `low-confidence` verdict to the caller with: "Reproduce the finding once more (different transcript, different coworker), confirm with a teammate, then re-invoke me." This prevents the pipeline from spamming Slack on transient flakes.

The threshold is 0.6, not 0.5: the cost of a duplicate or false-positive Slack ping is higher than the cost of one more reproduction by the operator.

## Output

The router returns a structured result to the calling skill:

```json
{
  "verdict": "dispatched | already-reported | low-confidence | config-missing",
  "classification": { "kind": "bug", "complexity": "simple" },
  "downstreamSkill": "bap-bug-report | bap-feature-brainstorm",
  "slackPermalink": "https://the-agentic-company.slack.com/archives/...",
  "prUrl": "https://github.com/the-agentic-company/bap/pull/123",
  "notes": "<1-line summary suitable for the orchestrator's final report>"
}
```

`prUrl` is set only when the downstream is `bap-bug-report` and the PR was opened. The orchestrator (`transcript-to-bap-coworker`) consolidates these results in its final report's "HeyBap findings" section.

## Invocation patterns

### From a pipeline skill (the default)

```
invoke bap-finding-router
  kind: "bug"
  title: "skill_add returned 200 but coworker can't see the skill for 6s"
  oneLineDescription: "After mcp__bap__skill_add succeeds, a chat_run query for available skills returns empty for several seconds before the skill becomes visible."
  context: {
    pipelineStep: "step4-skill_add",
    evidence: [
      { kind: "run_id", value: "run-abc" },
      { kind: "log_excerpt", value: "...availableSkills: []..." }
    ]
  }
  operatorConfidence: 0.85
```

### Direct from the human

If the human says "bug in HeyBap: when I click X, nothing happens", construct the input contract inline and invoke. The router still classifies and dispatches: it is the same gate.

### From `bap-bug-report` or `bap-feature-brainstorm` (not allowed)

The downstream skills must not invoke the router. The router is the entry; the downstream skills are leaves. If a downstream skill discovers a *second* finding during its investigation, it surfaces that to the caller (the router or the human), who can re-invoke the router on it.

## Anti-patterns

- Calling `bap-bug-report` or `bap-feature-brainstorm` directly from a pipeline skill instead of going through the router. The router enforces classification + dedup + correct destination; bypassing it loses those.
- Classifying a finding as SIMPLE because the operator *wants* it to be a quick fix. Apply the grid strictly. A 60-line change touching two surfaces is COMPLEX.
- Skipping the 5-minute investigation. Without it, the classification is a guess and the dispatch is unsafe.
- Dispatching when `operatorConfidence < 0.6`. Reproduce first.
- Letting the router run longer than 5 minutes. If the classification is still uncertain at that cap, default to COMPLEX and let `bap-feature-brainstorm` investigate at depth.
- Dispatching a structural bug to `bap-bug-report` because "it is a bug, that is the bug skill". Structural bugs that need design discussion go to `bap-feature-brainstorm` (which accepts COMPLEX bugs as well, see its frontmatter). Use the grid, not the kind.
- Re-routing once a downstream skill has already started. The router is the entry; downstream skills do not call back into it.

## Config and channel ids

The router reads `config.yaml` next to its SKILL.md (`lubin-skills/bap-finding-router/config.yaml` in the FDK clone) for:

```yaml
slack:
  technical_pr_channel_id: "C0BBTDDQ6AJ"          # #technical-pr, used by bap-bug-report
  brainstorm_channel_id: "REPLACE_WITH_CREATED_CHANNEL_ID"  # #brainstorming-produit
  baptiste_user_id: "U0A87JNV8QP"
slack_workspace: "The Agentic Company"
github_repo: "the-agentic-company/bap"
investigation_time_cap_minutes: 5
confidence_floor: 0.6
```

If `brainstorm_channel_id` is the placeholder, the router refuses to dispatch any COMPLEX finding and returns `verdict: "config-missing"`. Set the channel id once the Slack channel is created.

## See also

- [parse-transcript-to-agent-spec](../parse-transcript-to-agent-spec/SKILL.md): one of the upstream invokers.
- [bap-coworker-test-loop](../bap-coworker-test-loop/SKILL.md): the most prolific source of findings (every diagnose step is a potential finding).
- [transcript-to-bap-coworker](../transcript-to-bap-coworker/SKILL.md): the orchestrator that aggregates findings into the final report.
- `bap-bug-report`: dispatched for SIMPLE findings (bug or small feature). Lives in `~/.claude/skills/`. Opens a PR, posts in `#technical-pr`.
- `bap-feature-brainstorm`: dispatched for COMPLEX findings (feature or structural bug). Lives in `~/.claude/skills/`. Posts a 3-options brainstorm in `#brainstorming-produit`.
