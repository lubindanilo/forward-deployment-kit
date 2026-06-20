---
name: bap-capability-impact-analyzer
description: |
  Given a HeyBap capability gap (something the platform cannot do today,
  blocking one or more coworker builds), produce a structured impact
  analysis. Step 3 fans out 5 parallel subagents (Agent tool,
  general-purpose / Explore) over adjacency map, surface inventory,
  caller graph, test contract, and git history to find the **simplest
  viable shape**: which existing abstraction in `the-agentic-company/bap`
  the new capability can reuse, what files / surfaces would actually be
  touched, whether the change is additive or contract-modifying. Output:
  use cases unlocked (with evidence), effort estimate (t-shirt size +
  lines + surfaces + confidence), implementation sketch anchored on the
  adjacency it reuses (no new abstractions when an existing one fits),
  and a go / no-go recommendation with rationale. Consumable by
  `bap-feature-brainstorm` (which adds an "Impact" section to the Linear
  ticket it creates, with the 3 options grounded in the sketch's
  adjacency) or by the operator standalone when triaging an existing
  `BAP-<n>` feature ticket. Use when the orchestrator surfaces a gap
  (`parse-transcript-to-agent-spec` `ambiguities[]` or `notBuilt[]`
  blocked by HeyBap), when the router classifies a finding as COMPLEX
  feature, or when a teammate asks "is feature X worth building, what
  is the simplest way to ship it, and what else does it unlock?".
---

# Capability impact analyzer for HeyBap

The brainstorm skill and the post-deploy loop describe the *what* and *how* of a missing capability. They do not answer the question that comes before code: **is this worth building, and is it the right shape?** That decision needs adjacent data: how many other use cases does the same capability unblock, how big is the lift, are there nearby workarounds. This skill produces that data.

Without it, every feature ticket is decided on the immediate use case alone, and we either over-build (every gap = a feature) or under-build (no gap ever rises above "interesting").

## When to invoke

- `bap-feature-brainstorm` is about to draft the 3 options for a feature gap. Call this skill first; the output goes into the ticket's `## Impact si implémenté` section.
- `parse-transcript-to-agent-spec` emits an `ambiguities[].topic` or `notBuilt[]` item explicitly blocked by a HeyBap capability gap. The orchestrator can call this skill to enrich the consolidated report.
- The operator looks at an existing `BAP-<n>` feature ticket without quantified impact and wants a go / no-go basis. Invoke with `ticketRef: "BAP-<n>"`; the skill posts a Linear comment with the analysis.

Do not invoke when:

- The finding is a structural bug (not a missing capability). Use `bap-feature-brainstorm` directly; the 3 options approach is the right shape for bugs that need design.
- The capability is obviously trivial (raise a constant, add a missing toast). Use `bap-bug-report` directly.

## Input contract

```json
{
  "capability": "<one-line: e.g. 'programmatic workspace MCP server bind without UI'>",
  "context": "<2-3 lines: where the gap was observed, which step of the pipeline, which transcript / coworker>",
  "blockedUseCase": "<the concrete use case that hit the gap right now>",
  "ticketRef": "BAP-<n> (optional, present when the operator triages an existing ticket)",
  "options": {
    "transcriptCorpus": "<path to a folder or jsonl of past Grain transcripts; defaults to operator's Grain corpus (memory: grain-corpus-access)>",
    "coworkerBuildsRoot": "${skillFolderRoot}/state",
    "researchTimeCapMinutes": 10
  }
}
```

## Step 1 — scan past transcripts for the same gap

Search the operator's Grain transcript corpus for occurrences of the same pain. The corpus is accessible per the operator's `grain-corpus-access` memory (~620 transcripts via Grain public API + PAT bearer); on the local box it lives wherever the operator has cached it, typically `~/Code/transcripts/` or via the Grain API directly.

Build 3 to 5 distinctive search queries from `capability` and `context`:

- File paths / symbol names that appeared in the original finding.
- Noun phrases unique to the gap ("programmatic MCP bind", "scheduled trigger conditional", "panel button introspection").
- Verbs that hint at the missing API ("listAll", "createBound", "subscribe").

For each match, record: transcript id, speaker, timestamp, quoted line. Collapse near-duplicates (same speaker within 2 min of a prior quote on the same topic).

If the corpus is not accessible (no API key, no local cache), fall back to:

- Past coworker build state files under `${skillFolderRoot}/<callId>/agent-spec.json`. Look for `ambiguities[]` entries that match the capability pattern. Each such entry is a coworker build that was blocked by the same gap.
- Open Linear tickets in team `BAP` with label `Need More Shaping` matching the capability text.

## Step 2 — scan past coworker builds for blocked work

Each build under `${skillFolderRoot}/<callId>/` has an `agent-spec.json` (the parser output), a `coworkers.json` (built or notBuilt), and a `report.md`. Grep them for:

- `ambiguities[]` entries whose `topic` mentions the same capability area.
- `notBuilt[]` entries whose `evidence[*].quote` shares lexical overlap with the capability.
- `report.md` "Built and waiting for human MCP bind" lines (those are MCP-bind-gap-blocked).

Each hit becomes a `useCasesUnlocked[]` entry: the coworker that would have been built if the capability had existed, with a reference to the run that surfaced the block.

## Step 3 — deep codebase research for effort + reuse (mandatory, fan out)

The goal of this step is not just an effort number; it is to find the **simplest viable shape** for the capability, anchored in the existing codebase. Picking the first plausible implementation path is the failure mode this step prevents. The best implementation is almost always the one that reuses an existing abstraction; the worst is the one that invents a new pattern parallel to one that already exists.

Clone (or reuse) `the-agentic-company/bap` locally under `/tmp/bap-impact-<timestamp>` or pull a recent clone. Then run the angles below as **parallel subagents** (Agent tool, `general-purpose` or `Explore`, one per angle, in a single message). Each returns a structured report with `file:line` evidence.

### Mandatory angles (one subagent each, parallel)

1. **Adjacent implementation map.** Find 2 to 3 places in the repo where a *similar shape* already exists. Adjacent = same kind of work, different domain. A new "list workspace MCPs" tool is adjacent to "list coworkers" (already exists, follow that shape). A new schedule trigger is adjacent to the existing `coworker.trigger` orpc router. For each adjacency, give the `file:line` entry point and one sentence on what its contract is. The delta from adjacent-to-new is the size proxy.

2. **Surface inventory.** Walk every surface the capability would touch end-to-end: orpc router, server service, db schema, sandbox glue, MCP tool registration, frontend (chat + coworker output, both, when applicable), settings UI, tests. For each: existing files in the area, whether the change is "extend existing file" or "new file required" (the former is always cheaper), and the contract that surface owes to its callers.

3. **Dependency + caller graph.** What already calls into the surfaces from angle 2? Will the change extend those callers' contract or merely add a new entry point? An additive change (new tool, new route) is cheaper than a contract change (new column, new required arg). If the change is contract-modifying, list every caller that would need updating.

4. **Test contract in the area.** List every test under `apps/*/test/`, `packages/*/test/`, `__tests__/`, matching `*.spec.*` / `*.test.*` that touches the area. For each: what behaviour it locks in. A capability that fits within the existing test contract is cheaper than one that requires new test scaffolding.

5. **History lens.** `git log --oneline -20 -- <area>` and `git blame` on the closest adjacent implementation. Why is the code shaped the way it is? If a deliberate prior design choice exists (a `do-not-touch` comment, a related PR description, a TODO that was explicitly deferred), respect it or flag the conflict.

Run angles 1-5 **concurrently** (5 subagent invocations in a single Agent message). Wait for all returns before synthesising.

### Synthesise (after subagents return)

Produce, in this order:

- **Simplest viable shape**: one paragraph. Reuse the adjacent implementation from angle 1 verbatim if you can; if not, justify the deviation. Identify whether the change is *extend an existing file* (cheap) or *new file* (more expensive).
- **Boundaries crossed**: from angle 2, count files / surfaces touched.
- **Caller impact**: from angle 3, list whether the change is additive (no caller churn) or contract-modifying (caller updates required).
- **Test coverage**: from angle 4, list which existing tests cover the area; flag gaps.
- **History constraints**: from angle 5, list any prior design choice the new capability must respect.

### Output

```json
{
  "linesChanged": 180,
  "filesTouched": 4,
  "surfacesAffected": ["orpc router (coworker_workspace_mcp_*)", "settings UI", "MCP tool registration", "db schema migration"],
  "tShirtSize": "M",                 // S < 100, M 100-300, L 300-800, XL > 800
  "confidence": "medium",
  "unknowns": ["whether the existing OAuth flow can be reused or needs a new dance"],
  "adjacencyReused": "packages/core/src/server/services/sandbox-file-service.ts:42 (similar shape)",
  "callerImpact": "additive (no existing caller needs updating)",
  "testCoverage": "packages/core/test/coworker.test.ts:118-205 covers the adjacent area; new tool needs ~30 lines of test, no scaffolding",
  "historyConstraints": "none; OAuth dance was deliberately limited to UI per Baptiste commit 9f3a2c1"
}
```

Cap research time at `options.researchTimeCapMinutes` (10 by default). If at the cap the estimate is still uncertain, return `tShirtSize: "L"` with `confidence: "low"` and a list of unknowns. Do not bluff a number that the angles did not support.

## Step 4 — sketch how it would be implemented (anti-complexification)

One short paragraph, three to five lines, file-anchored, **derived from the Step 3 angle 1 adjacency**. Not a PR diff; an implementation outline that the brainstorm skill can use as substrate for its three options.

**Rules** (apply to every sketch):

- Reuse before inventing. If angle 1 found an adjacent implementation, the sketch must model on it (and name the file:line entry point); justify any deviation in one sentence.
- Extend before creating. If angle 2 found an existing file that can host the change, the sketch must put the change there; do not propose a new file when an existing one fits.
- Additive before contract-modifying. If angle 3 says additive is possible, the sketch must take the additive path; only propose a contract change if angle 3 rules out additive.
- No new abstraction (service, hook, type, schema) unless angle 1 returned "no adjacency"; in that case, say so explicitly in the sketch.
- No defensive code for cases the caller graph (angle 3) rules out.
- Smallest surface that resolves the gap. If a one-line lift solves it, the sketch is one line; do not invent surfaces to make the change feel substantive.

Example sketch (good):

```
Add an orpc router `coworker.workspace_mcp.create({ url, oauthConfig })` modelled
on the existing `coworker.create` router at apps/web/src/server/router/coworker.ts:54.
Reuse the OAuth handler from packages/core/src/server/services/workspace-mcp-oauth.ts:18
(already used by the Settings UI; no new dance needed). Persist the new
`bindMethod: "ui" | "api"` column via a single-column migration on the existing
`workspace_mcp` table (packages/db/src/schema/workspace_mcp.ts:12). Settings UI calls
the same router; additive only, no contract change for human users. Adjacency: the
"list coworkers" router is the same shape (file:line confirmed in Step 3 angle 1).
```

Example sketch (bad — what to avoid):

```
Introduce a new MCPBindOrchestrator service layered above the existing OAuth flow
with a pluggable dispatch strategy and a new event bus to coordinate between the UI
and the API path. Add a new MCP introspection protocol so meta-coworkers can negotiate
the bind asynchronously.
```

(Bad because: invents two new abstractions (orchestrator + event bus), proposes a new protocol when an additive router would do, no adjacency reused.)

Stay agnostic on the *which* of the brainstorm's three options. The brainstorm picks; this sketch is the substrate, not the answer.

## Step 5 — list adjacent use cases unlocked

Beyond the use case that surfaced the gap, what *new* things become possible once the capability exists. Two to five entries, each with:

- One-line use case.
- Whether it has been requested before (point at a transcript id, a Linear ticket, or a past coworker build).
- Whether a workaround exists today (so the team can weigh "feature vs accepting the workaround").

This is the highest-signal section for the go / no-go decision.

## Step 6 — recommendation with rationale

Single block:

```json
{
  "verdict": "implement | wait | defer | won't fix",
  "rationale": "<2-3 lines: weighted score of use cases unlocked vs effort vs risk>",
  "alternatives": [
    { "name": "workaround in operator's playbook", "where": "manual UI step in <screen>" },
    { "name": "feature flag on adjacent surface", "where": "feature already exists for chat, extend to coworker output" }
  ]
}
```

Verdict rubric:

- **implement**: t-shirt S/M AND >= 2 unlocked use cases (one of which has a real customer-facing impact), no defensible workaround.
- **wait**: t-shirt L/XL, even if many unlocked use cases. Bundle with a larger initiative.
- **defer**: t-shirt S/M but only one unlocked use case AND a documented workaround. Cost > value today.
- **won't fix**: the capability would conflict with a deliberate design choice already made on this surface.

When in doubt, recommend `wait` and ask the team to override.

## Step 7 — emit the structured payload

Full return value, returned to the caller (and posted as a Linear comment when `ticketRef` is set):

```json
{
  "capability": "...",
  "useCasesUnlocked": [
    { "useCase": "...", "evidence": "transcript <id> at <ts> | BAP-<n> | coworker-build <callId>", "alreadyBuiltAs": "@coworker-x or null", "workaroundToday": "null or one-line" }
  ],
  "effortEstimate": {
    "linesChanged": 180, "filesTouched": 4, "surfacesAffected": ["..."],
    "tShirtSize": "M", "confidence": "medium", "unknowns": ["..."]
  },
  "implementationSketch": "<paragraph from Step 4>",
  "adjacentImpact": [
    { "what": "<one-line>", "reuses": "<the shared component / route / hook>" }
  ],
  "recommendation": {
    "verdict": "implement | wait | defer | won't fix",
    "rationale": "...",
    "alternatives": [ { "name": "...", "where": "..." } ]
  },
  "ticketRef": "BAP-<n> (when set on input)",
  "commentUrl": "<linear comment permalink, when a comment was posted>"
}
```

## Step 8 — Linear comment (when `ticketRef` is set)

If the caller passed a `ticketRef`, post a Linear comment on that ticket. Body template:

```markdown
## Impact si implémenté (analyse `bap-capability-impact-analyzer`)

**Use cases débloqués (N)**
- <use case 1> — évidence : <ref> — workaround actuel : <ou null>
- <use case 2> …

**Effort estimé** : <T-shirt> (~<lines> lignes, surfaces : <surfaces>) — confiance <low/medium/high>
**Inconnues** : <list ou "aucune">

**Esquisse d'implémentation**
<paragraphe de Step 4>

**Recommandation** : `<verdict>`
<rationale>
Alternatives : <list ou "aucune">
```

Use `mcp__linear__save_comment({ issueId: "<ticket uuid>", body: "..." })`. Resolve the ticket uuid by calling `mcp__linear__get_issue({ id: "BAP-<n>" })` first; the comment endpoint needs the uuid, not the identifier.

Capture the returned comment permalink in the output's `commentUrl`.

## Integration with `bap-feature-brainstorm`

The brainstorm skill calls this skill at the start of Step 4 (writing the ticket body), receives the payload, and inserts an "Impact si implémenté" block before the "3 options envisagées" block. The brainstorm still owns the title, the three options, and the decision question; this skill only adds substrate.

Wiring (read by the brainstorm at runtime, no change needed today other than the brainstorm calling this skill — see `bap-feature-brainstorm` Step 4 for the placement):

```
analysis = invoke bap-capability-impact-analyzer
  capability: <from finding title>
  context: <from finding context>
  blockedUseCase: <from the use case that surfaced the gap>
  options: { researchTimeCapMinutes: 10 }
```

If the analyzer returns `recommendation.verdict == "won't fix"`, the brainstorm skill can still create the ticket but should add a header "Recommandation analyzer : won't fix" so the team sees the dissent.

## Standalone invocation

```
invoke bap-capability-impact-analyzer
  capability: "programmatic workspace MCP server bind without UI"
  context: "Hit during transcript-to-bap-coworker step 2b on the Concentrix call (2026-06-19). HUMAN STOP fired waiting for the operator to paste the URL in Bap UI."
  blockedUseCase: "Auto-bind a grain-transcript-mcp deployed by the same orchestrator pipeline"
  ticketRef: "BAP-42"
```

Returns the payload AND posts a Linear comment on BAP-42.

## Anti-patterns

- Running this skill on every finding. It is for *capability gaps* (something the platform cannot do today), not for bugs. Bugs go to `bap-bug-report` directly.
- Burning more than `researchTimeCapMinutes` on the effort estimate. The t-shirt size is enough; the brainstorm and the actual PR will refine.
- Counting the use case that surfaced the gap *and* using it as one of the "unlocked" use cases. The original use case is the trigger, not part of the unlocked list.
- Listing strawman adjacent use cases. Each entry must have a concrete evidence reference (transcript id, ticket, build). Speculation dilutes the signal.
- Returning `verdict: "implement"` when the t-shirt is XL and a workaround exists. The rubric is explicit; do not override it because the use case is exciting.
- Posting the Linear comment when `ticketRef` is not set. The comment is opt-in via the input; otherwise the caller decides where to surface the payload.
- Skipping the Step 3 parallel angles and producing a t-shirt size from a single grep pass. Without the adjacency map (angle 1) the sketch will invent abstractions that already exist in the codebase.
- Proposing a new file / new abstraction in Step 4 when an existing one fits (angles 1 and 2 must rule it out first). The brainstorm options can revisit; the sketch must default to the simplest viable shape.
- Returning `verdict: "implement"` while the sketch invents a parallel pattern to an existing one. Reusing the adjacency from angle 1 is mandatory before that verdict.

## Config

`lubin-skills/bap-capability-impact-analyzer/config.yaml`:

```yaml
linear:
  team_id: "5ff3b86a-a1a5-4241-ac5c-e65a143f16e3"
  team_key: "BAP"
github_repo: "the-agentic-company/bap"
research_time_cap_minutes: 10
corpus:
  transcripts_root: null                 # set to the local Grain cache if present; null = use Grain API per grain-corpus-access memory
  coworker_builds_root: "/tmp/agent-builds"
  state_dir_pattern: "${callId}/agent-spec.json"
```

## See also

- [bap-finding-router](../bap-finding-router/SKILL.md): triggers this skill via the brainstorm path for COMPLEX feature gaps.
- [bap-feature-brainstorm](../../.claude/skills/bap-feature-brainstorm/SKILL.md): the primary consumer. Adds the analyzer's payload as an "Impact si implémenté" section in the Linear ticket it creates.
- [parse-transcript-to-agent-spec](../parse-transcript-to-agent-spec/SKILL.md): emits the `ambiguities[]` / `notBuilt[]` items this skill scans across past builds.
- Grain corpus access: operator memory `grain-corpus-access` — ~620 transcripts via Grain public API (PAT Bearer).
