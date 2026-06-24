---
name: feature-bug-complexity-classification
description: |
  Single entry point for every HeyBap finding, whether the operator
  signals it manually (ad-hoc bug/feature noticed during day-to-day usage)
  or a pipeline step auto-detects it (parser, prior-art scout, feasibility
  check, test loop, orchestrator). Classifies the finding on a strict
  grid that produces four outcomes: NEEDS-CLARIFICATION, SIMPLE,
  COMPLEX-SCOPED, or COMPLEX-FUZZY. Dispatches to one of three leaf skills:
  `bap-bug-report` (SIMPLE: implements the quick fix on a branch in
  `the-agentic-company/bap`, opens a PR, creates a Linear ticket at status
  `In Review` linked to the PR, assignee Lubin); `bap-feature-brainstorm`
  (COMPLEX-SCOPED: investigates, frames the finding as problem + 3 options
  + decision question, creates a Linear ticket at status `Triage` with
  label `Need More Shaping`, assignee Baptiste); or `bap-direction-shaping`
  (COMPLEX-FUZZY: posts a structured problem statement in Slack
  `#feature-brainstorming` for team discussion, NO Linear ticket created
  until the team converges on a direction). Linear sends notifications on
  create / update on its own; the router itself never posts to Slack.
  Use whenever `parse-transcript-to-agent-spec`, `bap-coworker-test-loop`,
  `transcript-to-bap-coworker`, or the operator observes a HeyBap gap.
---

# Feature and bug complexity classification gate for HeyBap

Two distinct entry points feed this single gate:

1. **Manual (operator-direct)**. Lubin notices a bug or wants a feature while using HeyBap day-to-day. He fires `./go.sh bug "..."` / `./go.sh feature "..."` from the HeyBap Pipeline workspace, or types "bug in heybap: ..." in Claude Code. This is the most common path in practice.
2. **Auto (pipeline)**. The forward-deployment pipeline skills (`parse-transcript-to-agent-spec`, `bap-prior-art-scout`, `bap-platform-feasibility-check`, `bap-coworker-test-loop`, `transcript-to-bap-coworker`) surface every platform gap or misbehaviour they hit as a structured *finding*, and forward it here.

Both paths land on the same grid, the same confidence floor, and the same
clarification gate. The router classifies, decides where the finding lands, and
invokes the right downstream skill autonomously unless the finding needs one
operator answer before safe classification.

Every finding becomes a Linear ticket in the `Bap` team. Linear's own notifications (Slack integration, email, in-app) replace the previous direct Slack posts; create / update events on the ticket are already broadcast to the team. The router never posts to Slack itself.

No finding bypasses this router. No finding is silently logged in a TODO comment or in the orchestrator's final report only.

## When to invoke

### Manual triggers (operator-direct)

- Lubin is using HeyBap and notices something that does not work or could be better. From the shell: `./go.sh bug "<one-liner>"` or `./go.sh feature "<one-liner>"`. From Claude Code chat: `bug in heybap: <one-liner>` or `feature for heybap: <one-liner>`. Both forms construct the input contract and invoke this skill.
- Inspecting a coworker output, a panel button, or a sandbox file, the operator notices a regression. Same wrappers.
- A teammate says "this is broken in HeyBap" in chat and points at a specific surface. The operator forwards the description through `./go.sh bug "..."`.

### Auto triggers (pipeline)

- A pipeline step concludes "the root cause is in HeyBap, not in my prompt / skill" (`bap-coworker-test-loop` diagnose step returns `requiresHuman: true`).
- The parser flags an `ambiguities[]` entry whose real story is "the platform should let me do this".
- The orchestrator hits a HUMAN STOP that should not exist (workspace MCP bind, skill re-upload conflict, etc.).
- `bap-favorite-coworker-watchdog` detects a platform-side anomaly on a production coworker (sandbox crash, runtime stopped making progress, MCP returning 5xx).
- `bap-post-deploy-verify` finds a regression after merge.

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

## Clarification gate — before SIMPLE vs COMPLEX

Before applying the SIMPLE/COMPLEX grid, check whether the only thing preventing
a likely SIMPLE implementation is operator intent. If so, do not spend the
finding as COMPLEX-SCOPED. Return `verdict: "needs-clarification"` with one
concise question and stop before downstream dispatch.

Use this gate when ALL of these are true:

| Criterion | Required for NEEDS-CLARIFICATION |
|-----------|-----------------------------------|
| Surface localized | The 5-minute investigation found a likely file/component/system boundary |
| Small technical blast radius | The plausible fix still looks like < 50 changed lines and <= 3 files |
| No safety boundary | No DB/schema, auth, billing, sandbox runtime, multi-tenant, or exported API boundary |
| Ambiguity is operator intent | The uncertainty is placement, copy, exact trigger, or another product preference the operator can answer directly |
| Answer chooses one path | A single answer would make one SIMPLE implementation clearly preferable |
| No broader product debate | The question is not whether HeyBap should solve the problem at all |

Good examples:

- "Move the Back button to the left panel" but investigation finds several
  plausible small placements. Ask: "Should the Back button be an icon in the
  top-left of the conversation panel, next to the existing copy control, and be
  removed from the settings header?"
- "Rename this CTA" when two labels would both be reasonable and the component
  is localized. Ask which label to use.

Do NOT use this gate when the answer would still leave a structural design
choice, cross-surface rewrite, or unclear product direction. Those remain
COMPLEX-SCOPED or COMPLEX-FUZZY.

Manual interactive callers should ask the question directly. Headless wrappers
should return the question in the output contract so the operator can re-run
Phase 2 with the clarified one-liner.

## Classification grid — pass 1 (SIMPLE vs COMPLEX)

A finding is **SIMPLE** if and only if EVERY criterion in the grid below is true. If even one is false, it is **COMPLEX**. When in doubt, classify as COMPLEX (failsafe).

| Criterion | Threshold for SIMPLE |
|-----------|----------------------|
| Lines changed by the proposed fix | < 50 |
| Files touched by the proposed fix | <= 3 |
| Migration of the DB or state model required | no |
| Breaking change to an exported API (orpc routers, MCP tools, db schema exports) | no |
| Touches `packages/db/src/schema/*` data model definitions | no |
| Touches sandbox runtime, auth, billing, multi-tenant boundary | no |
| Existing tests already cover the area (or one trivial test to add) | yes |
| Operator confidence in the fix | >= 0.8 |
| More than one defensible approach after the clarification gate | no |
| Documented elsewhere as "do not touch without design discussion" | no |
| Bug only: live reproducible deterministically in <5 min | yes (bugs only) |
| Feature only: scope fits in a single PR description (<= 5 bullets) | yes (features only) |

## Classification grid — pass 2 (COMPLEX sub-split: SCOPED vs FUZZY)

If the finding is COMPLEX, a second pass decides whether it is **COMPLEX-SCOPED** (known surface, design call needed, ticketable now) or **COMPLEX-FUZZY** (too unclear to ticket, needs Slack discussion first).

The finding is **COMPLEX-FUZZY** if AT LEAST TWO of the following hold. With exactly one criterion true, default to **COMPLEX-SCOPED** (better to over-ticket than under-discuss).

| Fuzziness criterion | Triggered when |
|---------------------|---------------|
| Surface unknown | No file:line or system boundary identified during the 5-min investigation |
| Cross-cutting | Implementation would touch > 2 major surfaces (sandbox runtime, schema, MCP layer, panel UI, billing, multi-tenant) |
| Multiple plausible products | More than one defensible "shape" could come out of the idea, no obvious winner |
| Product-fit unclear | Genuinely undecided whether HeyBap should solve this at all (vs document as out of scope, vs redirect to a third-party) |
| Confidence band | `operatorConfidence` is in `[0.6, 0.75)` (strong enough to discuss, not strong enough to ticket) |

Record the set of triggered criteria as `fuzzyReasons[]` and pass them downstream so the Slack post can anchor its "Why this is fuzzy" line on the actual signals.

If COMPLEX with zero fuzziness criteria → COMPLEX-SCOPED.

## Investigation step (5 minutes, hard cap)

Before classifying, the router does a focused investigation:

1. Clone (or reuse) `the-agentic-company/bap` locally under `/tmp/bap-router-<timestamp>` (or pull an existing recent clone).
2. Grep for the evidence references provided (`file:line` if any).
3. Estimate: which files would the fix touch, how many lines, does it cross any of the failsafe boundaries above.
4. Form an operator-side opinion on the fix path (this is what gets passed downstream).
5. Note the fuzziness signals from pass 2: did the investigation localize a surface? How many surfaces would the fix touch? Is operatorConfidence in the fuzzy band? These feed the SCOPED/FUZZY sub-split.

If the 5-minute cap is reached without a confident classification, first check
the clarification gate. If one operator answer would make the likely small fix
obvious, return `needs-clarification`; otherwise default to COMPLEX. If COMPLEX
with two or more fuzziness criteria → FUZZY. The router never burns more than 5
minutes per finding; deep investigation lives downstream (`bap-bug-report`,
`bap-feature-brainstorm`, or `bap-direction-shaping`).

## Dispatch matrix

After classification, three destinations:

| classification | downstream skill | output |
|----------------|------------------|--------|
| SIMPLE (bug or feature) | `bap-bug-report` | Branch + quick fix implemented + PR opened on `the-agentic-company/bap` + Linear ticket created in team `Bap` at status `In Review`, labels `Bug` or `Feature` + `Dogfooding`, assignee **Lubin** (operator owns the PR), PR URL attached. Features whose fix exceeds ~50 lines land as draft PRs with a TODO checklist in the ticket body (handled by `bap-bug-report` itself). |
| COMPLEX-SCOPED (surface known, design call required) | `bap-feature-brainstorm` | Investigation + problem statement + 3 defensible options + decision question, posted as a Linear ticket in team `Bap` at status `Triage`, labels `Need More Shaping` + (`Bug` or `Feature`) + `Dogfooding`, assignee **Baptiste** (CTO drives the design choice). For capability-gap findings, the brainstorm skill's own Step 3b quantifies impact (Grain corpus scan + past builds scan + use cases unlocked + verdict) so the ticket carries an Impact section. **Terminal here**: no PR is opened, no tests, no code, no `bap-post-deploy-verify`. The dispatch ends at the Linear ticket. Implementation comes later, via a follow-up SIMPLE ticket that re-enters the gate once the team has picked an option (the brainstorm ticket is transitioned to `In Progress` and the new SIMPLE ticket links back via `relatedTo`). |
| COMPLEX-FUZZY (direction unclear, no obvious surface, big changes) | `bap-direction-shaping` | Structured problem statement (problem + why fuzzy + possible surfaces + open questions + origin) posted in Slack `#feature-brainstorming` via the Slack MCP. **NO Linear ticket created** at this stage. If the team converges on a direction, the finding gets re-filed via the gate with the new context and lands as SIMPLE or COMPLEX-SCOPED on the next pass. |

`NEEDS-CLARIFICATION` is not dispatched. It returns one operator question and
the likely SIMPLE path that would be taken if the answer confirms it.

The router does not create the ticket (or Slack post) itself. It only classifies and forwards. The downstream skill owns the rest of the loop (investigation depth, PR, Linear ticket creation, Slack post).

Dedup intentionally removed: in practice the operator's volume is low and a duplicate Linear ticket is fast to spot and cancel manually. The cost of every Phase 2 invocation paying the dedup latency is higher than the cost of the occasional duplicate.

## Confidence floor

If the **operatorConfidence** is below 0.6, the router refuses to dispatch and returns a `low-confidence` verdict to the caller with: "Reproduce the finding once more (different transcript, different coworker), confirm with a teammate, then re-invoke me." This prevents the pipeline from spamming Linear on transient flakes.

The threshold is 0.6, not 0.5: the cost of a duplicate or false-positive Linear ticket is higher than the cost of one more reproduction by the operator.

## Output

The router returns a structured result to the calling skill:

```json
{
  "verdict": "dispatched | needs-clarification | low-confidence | config-missing",
  "classification": {
    "kind": "bug",
    "complexity": "needs-clarification | simple | complex-scoped | complex-fuzzy",
    "fuzzyReasons": ["surface-unknown", "cross-cutting"]
  },
  "downstreamSkill": "bap-bug-report | bap-feature-brainstorm | bap-direction-shaping",
  "clarificationQuestion": "<one concise operator question when verdict is needs-clarification>",
  "likelySimplePath": "<the small implementation path that would be taken after confirmation>",
  "linearTicketIdentifier": "BAP-123",
  "linearTicketUrl": "https://linear.app/heybap/issue/BAP-123",
  "prUrl": "https://github.com/the-agentic-company/bap/pull/456",
  "slackThreadUrl": "https://the-agentic-company.slack.com/archives/CXXX/p1750000000",
  "notes": "<1-line summary suitable for the orchestrator's final report>"
}
```

- `prUrl` is set only when downstream is `bap-bug-report` and the PR was opened.
- `linearTicketIdentifier` / `linearTicketUrl` are set for `bap-bug-report` (SIMPLE) and `bap-feature-brainstorm` (COMPLEX-SCOPED). They are **absent** for `bap-direction-shaping` (COMPLEX-FUZZY) since no Linear ticket is created at that stage.
- `slackThreadUrl` is set only for `bap-direction-shaping` (COMPLEX-FUZZY).
- `clarificationQuestion` and `likelySimplePath` are set only for `needs-clarification`; no downstream skill, ticket, Slack post, or PR is created in that verdict.
- `fuzzyReasons` is populated only when complexity is `complex-fuzzy`; empty otherwise.

The orchestrator (`transcript-to-bap-coworker`) consolidates these results in its final report's "HeyBap findings" section, splitting them into "Tickets opened" and "Direction discussions opened".

## Invocation patterns

### From a pipeline skill (the default)

```
invoke feature-bug-complexity-classification
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

### Manual trigger (operator-direct, most common path)

Two ergonomic wrappers, same gate behind both.

**From the HeyBap Pipeline shell**:

```
./go.sh bug "Re-run button blocks 4s before firing, no feedback"
./go.sh feature "Add coworker_pin to keep favorites visible across pagination"
```

`go.sh` is a thin wrapper that invokes `claude -p` headless with the input contract pre-built:

```json
{
  "kind": "bug",                                  // or "feature"
  "title": "<derived from the one-liner, < 80 chars>",
  "oneLineDescription": "<the quoted string>",
  "context": {
    "pipelineStep": "runtime",                    // "ui" for feature by default
    "evidence": []                                // operator can amend interactively
  },
  "operatorConfidence": 0.85
}
```

`operatorConfidence` defaults to 0.85 (the operator is the most reliable source). The router still runs the 5-minute investigation to localize the surface, and downstream the leaf skill runs its 5-subagent deep research before opening the PR; the thin input contract does NOT shortcut that work.

**From Claude Code chat**:

The operator types a short message like `bug in heybap: coworker_run is super slow after redeploy` or `feature: coworker_pin to keep favorites at the top`. Claude constructs the same input contract inline and invokes this skill. No wrapper script needed.

**Same gate, same rules**. Manual triggers go through the SAME classification grid and the SAME confidence floor (0.6). The only difference is that `context.evidence` is usually thin (just the description) and the 5-minute investigation has to localize the surface from scratch instead of taking a `file:line` reference.

### From `bap-bug-report`, `bap-feature-brainstorm`, or `bap-direction-shaping` (not allowed)

The downstream skills must not invoke the router. The router is the entry; the downstream skills are leaves. If a downstream skill discovers a *second* finding during its investigation, it surfaces that to the caller (the router or the human), who can re-invoke the router on it.

When a `bap-direction-shaping` Slack thread converges on a direction, the operator (or a teammate) re-files the finding via the gate with the added context (`./go.sh bug "..."` or `./go.sh feature "..."` with the new clarity). The gate then classifies it as SIMPLE or COMPLEX-SCOPED and the standard Linear path takes over. The Slack thread URL is included in the new ticket's body for traceability.

## Invocation from a scheduled meta-coworker (`/loop`)

The router is the entry point for *findings*, not for transcripts. A scheduled meta-coworker (`@agent-builder` running every 30 minutes on HeyBap) can invoke the router for any unprocessed finding that other pipelines surfaced:

```
/loop 60m drain the findings queue
  for each unprocessed entry in ${findingsQueue}:
    invoke feature-bug-complexity-classification with the entry
    mark processed regardless of verdict (dispatched / config-missing / low-confidence)
```

`${findingsQueue}` is a local file (`~/.claude/skills/feature-bug-complexity-classification/queue.jsonl`) that upstream skills append to instead of invoking the router synchronously. This lets high-volume pipelines drain at the router's own cadence rather than blocking each runner on a synchronous dispatch.

## Anti-patterns

- Calling `bap-bug-report`, `bap-feature-brainstorm`, or `bap-direction-shaping` directly from a pipeline skill instead of going through the router. The router enforces classification + correct destination; bypassing it loses those.
- Classifying a finding as SIMPLE because the operator *wants* it to be a quick fix. Apply the grid strictly. A 60-line change touching two surfaces is COMPLEX.
- Skipping the 5-minute investigation. Without it, the classification is a guess and the dispatch is unsafe.
- Dispatching when `operatorConfidence < 0.6`. Reproduce first.
- Letting the router run longer than 5 minutes. If the classification is still uncertain at that cap, default to COMPLEX (and to COMPLEX-FUZZY if at least two fuzziness criteria triggered).
- Turning a small operator-intent ambiguity into COMPLEX-SCOPED when the clarification gate applies. Ask one concise question first; do not create a shaping ticket just to choose between two tiny UI placements or labels.
- Dispatching a structural bug to `bap-bug-report` because "it is a bug, that is the bug skill". Structural bugs that need design discussion go to `bap-feature-brainstorm` (SCOPED) or `bap-direction-shaping` (FUZZY). Use the grid, not the kind.
- **Classifying as FUZZY on a single criterion**. Default to COMPLEX-SCOPED unless at least TWO fuzziness criteria triggered. A premature FUZZY classification dumps a half-shaped problem into Slack and slows the team down.
- **Classifying as SCOPED when no surface is identified after 5 min**. Without a surface, `bap-feature-brainstorm` cannot frame 3 defensible options. Dispatch FUZZY so the team helps narrow the surface in Slack before any Linear ticket.
- Re-routing once a downstream skill has already started. The router is the entry; downstream skills do not call back into it.
- Posting to Slack on SCOPED findings, or creating a Linear ticket on FUZZY findings. The two destinations are mutually exclusive at the dispatch layer.

## Config and ids

The router reads `config.yaml` next to its SKILL.md (`lubin-skills/feature-bug-complexity-classification/config.yaml` in the FDK clone) for:

```yaml
linear:
  team_id: "5ff3b86a-a1a5-4241-ac5c-e65a143f16e3"      # team Bap, key BAP
  team_key: "BAP"
  default_project_id: null                             # optional, e.g. a "Roadmap" project id
  baptiste_user_id: "b05ce629-639d-4861-8de0-c2ba17ce84a6"
  # louis_user_id intentionally omitted — Louis Adam must never be tagged by this workflow
  lubin_user_id: "8fc555af-50cd-4093-9878-92f6f08e6d96"
  default_assignee_user_id: "8fc555af-50cd-4093-9878-92f6f08e6d96"   # Lubin for SIMPLE; brainstorm overrides to Baptiste for COMPLEX
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
```

`bap-bug-report` and `bap-feature-brainstorm` read the same ids (they each have their own `config.yaml` that duplicates the values for portability). When updating any of the Linear ids, update all three configs at once. The router is the canonical source.

If `team_id` is missing or set to the placeholder, the router refuses to dispatch and returns `verdict: "config-missing"`.

## See also

- [parse-transcript-to-agent-spec](../parse-transcript-to-agent-spec/SKILL.md): one of the upstream invokers.
- [bap-coworker-test-loop](../bap-coworker-test-loop/SKILL.md): the most prolific source of findings (every diagnose step is a potential finding).
- [transcript-to-bap-coworker](../transcript-to-bap-coworker/SKILL.md): the orchestrator that aggregates findings into the final report.
- [bap-direction-shaping](../bap-direction-shaping/SKILL.md): dispatched for COMPLEX-FUZZY findings. Posts a structured problem statement in Slack `#feature-brainstorming` for team discussion. No Linear ticket created at that stage.
- `bap-bug-report`: dispatched for SIMPLE findings (bug or small feature). Creates the Linear ticket at status `In Review` AND opens the PR. Lives in `lubin-skills/bap-bug-report/`.
- `bap-feature-brainstorm`: dispatched for COMPLEX-SCOPED findings (feature or structural bug with a known surface). Creates the Linear ticket at status `Triage` with label `Need More Shaping`, assignee Baptiste. Lives in `~/.claude/skills/bap-feature-brainstorm/`.
- `bap-post-deploy-verify`: transitions the Linear ticket to `Live` after a verified post-deploy run, or opens a new Linear ticket labeled `Regression` (linked via `relatedTo`) if the finding came back. Only runs against tickets from `bap-bug-report` / `bap-feature-brainstorm`; FUZZY findings never reach it (no ticket exists).
