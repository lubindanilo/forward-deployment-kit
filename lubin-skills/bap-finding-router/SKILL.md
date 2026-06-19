---
name: bap-finding-router
description: |
  Single entry point for every HeyBap finding observed during forward
  deployment: bug, missing feature, friction, surprise. Classifies the
  finding on a strict simple-vs-complex grid and dispatches to one of
  two leaf skills: `bap-bug-report` (SIMPLE: investigates, implements
  the quick fix on a branch in `the-agentic-company/bap`, opens a PR,
  creates a Linear ticket in team `Bap` at status `In Review` linked to
  the PR) or `bap-feature-brainstorm` (COMPLEX: investigates, frames the
  finding as problem + 3 options + decision question, creates a Linear
  ticket in team `Bap` at status `Triage` with label `Need More Shaping`).
  Linear sends notifications on create / update on its own; no Slack post.
  Use whenever `parse-transcript-to-agent-spec`, `bap-coworker-test-loop`,
  `transcript-to-bap-coworker`, or a human observes a HeyBap gap.
---

# Finding router for HeyBap

The pipeline skills (`parse-transcript-to-agent-spec`, `bap-coworker-test-loop`, `transcript-to-bap-coworker`) sit at the front line of HeyBap usage. They are designed to surface every platform gap or misbehaviour as a structured *finding*. This skill is the single gate every finding goes through. It classifies, decides where the finding lands, and invokes the right downstream skill autonomously.

Every finding becomes a Linear ticket in the `Bap` team. Linear's own notifications (Slack integration, email, in-app) replace the previous direct Slack posts; create / update events on the ticket are already broadcast to the team. The router never posts to Slack itself.

No finding bypasses this router. No finding is silently logged in a TODO comment or in the orchestrator's final report only.

## When to invoke

- A pipeline step concludes "the root cause is in HeyBap, not in my prompt / skill" (`bap-coworker-test-loop` diagnose step returns `requiresHuman: true`).
- The parser flags an `ambiguities[]` entry whose real story is "the platform should let me do this".
- The orchestrator hits a HUMAN STOP that should not exist (workspace MCP bind, skill re-upload conflict, etc.).
- Inspecting a coworker output, a panel button, or a sandbox file, the operator notices a regression.
- A teammate says "this is broken in HeyBap" in chat and points at a specific surface.

Do not invoke for findings outside HeyBap: a bug in a third-party MCP, a Notion API change, a Slack rate limit. Those go to the relevant provider's tracker.

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
4. Form an operator-side opinion on the fix path (this is what gets passed downstream).

If the 5-minute cap is reached without a confident classification, default to COMPLEX. The router never burns more than 5 minutes per finding; deep investigation lives downstream (`bap-bug-report` or `bap-feature-brainstorm`).

## Dispatch matrix

After classification, two destinations:

| classification | downstream skill | output |
|----------------|------------------|--------|
| SIMPLE (bug or feature) | `bap-bug-report` | Branch + quick fix implemented + PR opened on `the-agentic-company/bap` + Linear ticket created in team `Bap` at status `In Review`, labels `Bug` or `Feature` + `Dogfooding`, assignee Baptiste, PR URL attached. Features whose fix exceeds ~50 lines land as draft PRs with a TODO checklist in the ticket body (handled by `bap-bug-report` itself). |
| COMPLEX (feature OR structural bug) | `bap-feature-brainstorm` | Investigation + problem statement + 3 defensible options + decision question, posted as a Linear ticket in team `Bap` at status `Triage`, labels `Need More Shaping` + (`Bug` or `Feature`) + `Dogfooding`, assignee Baptiste. No PR opened. Implementation goes through `bap-bug-report` in a follow-up once the team picks an option (the brainstorm ticket then gets transitioned to `In Progress` and a new SIMPLE ticket is opened with `relatedTo` set to it). |

The router does not create the ticket itself. It only classifies and forwards. The downstream skill owns the rest of the loop (investigation depth, PR, Linear ticket creation, dedup of its own kind).

## Dedup before dispatch

Two checks, in order. The downstream skills also dedup at their own layer, but doing a fast check at the router avoids wasting investigation budget on a duplicate.

1. **Linear dedup**: search team `Bap` for the last `dedup_window_days` days (60 by default) using distinctive tokens from the finding (file paths, symbol names, unique noun phrases).

   ```
   mcp__linear__list_issues({
     team: "BAP",
     query: "<distinctive token>",
     createdAt: "-P60D",
     limit: 50,
     includeArchived: false
   })
   ```

   Run 2 or 3 queries with different distinctive tokens (one with the file path, one with the symptom noun phrase). If a recent ticket covers the same root cause and is not in status `Canceled` or `Duplicate`, do not dispatch. Return `verdict: "already-reported"` + Linear ticket identifier (e.g. `BAP-123`) + URL.

2. **PR dedup** (SIMPLE only, second layer): `gh pr list --search "<distinctive token>" --state open --repo the-agentic-company/bap`. If an open PR addresses the same root cause but no Linear ticket points at it yet, dispatch SIMPLE anyway so the ticket is created; `bap-bug-report` will detect the existing PR in its own dedup pass and attach to it instead of opening a second one.

A duplicate is worse than no ticket. Never bypass the dedup checks.

## Confidence floor

If the **operatorConfidence** is below 0.6, the router refuses to dispatch and returns a `low-confidence` verdict to the caller with: "Reproduce the finding once more (different transcript, different coworker), confirm with a teammate, then re-invoke me." This prevents the pipeline from spamming Linear on transient flakes.

The threshold is 0.6, not 0.5: the cost of a duplicate or false-positive Linear ticket is higher than the cost of one more reproduction by the operator.

## Output

The router returns a structured result to the calling skill:

```json
{
  "verdict": "dispatched | already-reported | low-confidence | config-missing",
  "classification": { "kind": "bug", "complexity": "simple" },
  "downstreamSkill": "bap-bug-report | bap-feature-brainstorm",
  "linearTicketIdentifier": "BAP-123",
  "linearTicketUrl": "https://linear.app/heybap/issue/BAP-123",
  "prUrl": "https://github.com/the-agentic-company/bap/pull/456",
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

## Invocation from a scheduled meta-coworker (`/loop`)

The router is the entry point for *findings*, not for transcripts. A scheduled meta-coworker (`@agent-builder` running every 30 minutes on HeyBap) can invoke the router for any unprocessed finding that other pipelines surfaced:

```
/loop 60m drain the findings queue
  for each unprocessed entry in ${findingsQueue}:
    invoke bap-finding-router with the entry
    mark processed regardless of verdict (already-reported / dispatched / config-missing / low-confidence)
```

`${findingsQueue}` is a local file (`~/.claude/skills/bap-finding-router/queue.jsonl`) that upstream skills append to instead of invoking the router synchronously. This is the right pattern for high-volume pipelines where 5 runners observe the same bug: they append to the queue, the router drains at its own cadence, dedup catches duplicates once.

The queue file becomes the in-flight dedup registry mentioned in the roadmap (axis #6 of the lubin-skills-map). One file replaces both.

## Anti-patterns

- Calling `bap-bug-report` or `bap-feature-brainstorm` directly from a pipeline skill instead of going through the router. The router enforces classification + dedup + correct destination; bypassing it loses those.
- Classifying a finding as SIMPLE because the operator *wants* it to be a quick fix. Apply the grid strictly. A 60-line change touching two surfaces is COMPLEX.
- Skipping the 5-minute investigation. Without it, the classification is a guess and the dispatch is unsafe.
- Dispatching when `operatorConfidence < 0.6`. Reproduce first.
- Letting the router run longer than 5 minutes. If the classification is still uncertain at that cap, default to COMPLEX and let `bap-feature-brainstorm` investigate at depth.
- Dispatching a structural bug to `bap-bug-report` because "it is a bug, that is the bug skill". Structural bugs that need design discussion go to `bap-feature-brainstorm` (which accepts COMPLEX bugs as well, see its frontmatter). Use the grid, not the kind.
- Re-routing once a downstream skill has already started. The router is the entry; downstream skills do not call back into it.
- Posting to Slack instead of creating a Linear ticket. Linear is the canonical surface; Slack notifications are derived from Linear's own integrations.

## Config and ids

The router reads `config.yaml` next to its SKILL.md (`lubin-skills/bap-finding-router/config.yaml` in the FDK clone) for:

```yaml
linear:
  team_id: "5ff3b86a-a1a5-4241-ac5c-e65a143f16e3"      # team Bap, key BAP
  team_key: "BAP"
  default_project_id: null                             # optional, e.g. a "Roadmap" project id
  baptiste_user_id: "b05ce629-639d-4861-8de0-c2ba17ce84a6"
  louis_user_id: "90938296-0e91-4439-9c53-b939cd975d20"
  lubin_user_id: "8fc555af-50cd-4093-9878-92f6f08e6d96"
  default_assignee_user_id: "b05ce629-639d-4861-8de0-c2ba17ce84a6"
  labels:
    bug: "..."
    feature: "..."
    regression: "..."
    need_more_shaping: "..."
    dogfooding: "..."
    ui_ux: "..."
  statuses:
    triage: "..."
    in_review: "..."
    live: "..."
github_repo: "the-agentic-company/bap"
investigation_time_cap_minutes: 5
confidence_floor: 0.6
dedup_window_days: 60
```

`bap-bug-report` and `bap-feature-brainstorm` read the same ids (they each have their own `config.yaml` that duplicates the values for portability). When updating any of the Linear ids, update all three configs at once. The router is the canonical source.

If `team_id` is missing or set to the placeholder, the router refuses to dispatch and returns `verdict: "config-missing"`.

## See also

- [parse-transcript-to-agent-spec](../parse-transcript-to-agent-spec/SKILL.md): one of the upstream invokers.
- [bap-coworker-test-loop](../bap-coworker-test-loop/SKILL.md): the most prolific source of findings (every diagnose step is a potential finding).
- [transcript-to-bap-coworker](../transcript-to-bap-coworker/SKILL.md): the orchestrator that aggregates findings into the final report.
- `bap-bug-report`: dispatched for SIMPLE findings (bug or small feature). Creates the Linear ticket at status `In Review` AND opens the PR. Lives in `lubin-skills/bap-bug-report/`.
- `bap-feature-brainstorm`: dispatched for COMPLEX findings (feature or structural bug). Creates the Linear ticket at status `Triage` with label `Need More Shaping`. Lives in `~/.claude/skills/bap-feature-brainstorm/`.
- `bap-post-deploy-verify`: transitions the Linear ticket to `Live` after a verified post-deploy run, or opens a new Linear ticket labeled `Regression` (linked via `relatedTo`) if the finding came back.
