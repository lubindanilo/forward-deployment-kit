---
name: bap-coworker-test-loop
description: |
  Close the loop on a freshly created Bap (Heybap) coworker: run it with test
  payloads, observe the run via `coworker_logs`, evaluate the output against
  machine-checkable success criteria, and `coworker_update` the prompt /
  skills / integrations until the run conforms or the iteration cap is hit.
  Supports two test strategies per integration: `sandbox-redirect` (route
  actions to test accounts / channels / DBs) and `act-then-cleanup`
  (let the agent act, then delete the artefacts it produced). Use after
  `coworker_create` and before declaring a coworker ready for production.
---

# Close the loop on a Bap coworker

Creating a coworker is the easy half. Knowing it actually does what the spec said takes a real run, real observation, and usually two or three rounds of prompt / skill tweaks. This skill turns that into a deterministic loop driven by the agent spec produced by [parse-transcript-to-agent-spec](../parse-transcript-to-agent-spec/SKILL.md).

The loop has one job: get the coworker from "created" to "passes every successCriterion on every testPayload, without polluting production state."

This skill complements [build-agents-for-bap](../build-agents-for-bap/SKILL.md) (which tells you how to build a coworker well) and [transcript-to-bap-coworker](../transcript-to-bap-coworker/SKILL.md) (which calls this skill as its final step).

## When to invoke

- Right after `mcp__bap__coworker_create` on a new coworker that has at least one `testPayload` and one `successCriterion` (both come from the agent spec).
- After a `coworker_update` that changed prompt or wiring, to confirm the change actually improved the output.
- Before handing a coworker to a customer or to a teammate. "Works on the demo" is not "works in the loop".

Do NOT invoke on:

- A coworker that has no `successCriteria` (the loop has nothing to check against; either add criteria or accept the risk and skip).
- A read-only single-step coworker where the only output is a chat message and there is no machine-checkable success ("summarise this URL" type). Manual eyeballing is fine.
- A coworker whose `testPayloads` cannot be made safe (irreversible action with no sandbox and no cleanup path: payments, signed contracts, production alerts to large channels). Surface to human with the `stopHumanCheckpoint` mechanism instead.

## Input contract

```json
{
  "coworkerReference": "@sales-call-debrief-writer",
  "agentSpec": { /* the JSON emitted by parse-transcript-to-agent-spec for one agent */ },
  "testEnv": { /* loaded from test_env.yaml or passed inline, see below */ },
  "options": {
    "maxIterations": 5,
    "perRunTimeoutSeconds": 300,
    "evalBudgetSeconds": 30,
    "handoffChannel": "#agents-builds",
    "stopOnFirstHumanCheckpoint": true
  }
}
```

`agentSpec` is the same shape produced by `parse-transcript-to-agent-spec`, scoped to one agent. The loop reads `successCriteria`, `testPayloads`, `outputs`, and `stopHumanCheckpoints` directly.

`maxIterations` defaults to 5. Past that, the loop hands off rather than burning more tokens.

## `test_env.yaml` schema

Lives at the root of the FDK repo (or path passed via `testEnv` inline). Maps every integration the coworker may touch to its test mode. The orchestrator reads this once and substitutes values in the test payload + the temporary test prompt.

```yaml
# test_env.yaml
default_strategy: sandbox-redirect

integrations:
  notion:
    strategy: sandbox-redirect
    sandboxDatabaseId: "11111111-2222-3333-4444-555555555555"   # "Test Deals" DB
    note: "All page.create calls during tests land in this DB; archived after eval."

  linear:
    strategy: sandbox-redirect
    sandboxTeamKey: "TEST"
    note: "Issues created in TEST team. Auto-cancelled after eval."

  slack:
    strategy: sandbox-redirect
    sandboxChannel: "#test-coworkers"
    note: "Never post in #ventes / #general during tests. Channel is private."

  gmail:
    strategy: sandbox-redirect
    sandboxAlias: "lubin+test@hyperstack.studio"
    sandboxAccountLabel: "lubin-test"
    note: "Mails sent to the +alias; trash purged after eval."

  airtable:
    strategy: act-then-cleanup
    note: "API supports delete; cleanup via record id captured in coworker_logs."

  outlook:
    strategy: sandbox-redirect
    sandboxAlias: "outlook-test@hyperstack.studio"

  http_custom_mcp:
    strategy: act-then-cleanup
    fallback: skip
    note: "Per-MCP. If no delete endpoint, skip the test and require humanCheckpoint."

# Per-coworker overrides
overrides:
  "@payment-collector":
    integrations:
      stripe:
        strategy: sandbox-redirect
        sandboxApiKey: "sk_test_..."

# Cleanup behaviour
cleanup:
  archiveInsteadOfDelete: true     # Notion archive vs hard delete
  retentionMinutes: 60             # keep test artefacts for an hour for postmortem
  cleanupOnFailure: false          # leave artefacts in place when a run errors, for debugging
```

If an integration the coworker needs is not declared in `test_env.yaml`, the loop refuses to start and emits a config error. No silent prod actions.

## The loop algorithm

```
function testLoop(coworkerReference, agentSpec, testEnv, options):
    iteration = 0
    history = []

    while iteration < options.maxIterations:
        iteration += 1
        injectTestPromptOverlay(coworkerReference, testEnv, agentSpec)  // step A

        for payload in agentSpec.testPayloads:                          // step B
            run = mcp__bap__coworker_run(reference=coworkerReference, userInput=payload.userInput)
            terminal = pollUntilTerminal(run.id, options.perRunTimeoutSeconds)
            logs = mcp__bap__coworker_logs(runId=run.id)

            evaluations = evaluate(logs, payload.expectedOutcomes, agentSpec.successCriteria)
            cleanup(logs, testEnv, options)                              // step C

            history.append({iteration, payload, terminal, evaluations})

            if any criterion fails AND payload.required:
                break                                                    // step D, abort this iteration
        else:
            return success(history)                                      // step E

        diagnosis = diagnose(history[-len(agentSpec.testPayloads):], logs)   // step F
        if diagnosis.requiresHuman:
            return handoff(history, diagnosis, options.handoffChannel)
        mcp__bap__coworker_update(reference=coworkerReference, **diagnosis.patch)   // step G

    return handoff(history, "iteration_cap_reached", options.handoffChannel)
```

Each step in detail below.

### Step A. Inject test prompt overlay

Before each iteration of the loop, the coworker's prompt is *temporarily augmented* with a block describing the test mode:

```
--- TEST MODE (automatic, do not surface to chat) ---
You are running in test mode. Honour these substitutions:
- Notion: use database 11111111-2222-3333-4444-555555555555 ("Test Deals").
- Slack: post in #test-coworkers only.
- Gmail: send to lubin+test@hyperstack.studio (account label "lubin-test"). Use the google-gmail CLI per rule #16 of build-agents-for-bap.
- Linear: create in team TEST.

When the userInput contains [MODE TEST], run all phases back-to-back without pausing.

Do not call any tool whose target cannot be redirected via the rules above. If you must, stop and explain.
--- END TEST MODE ---
```

This block is applied via `mcp__bap__coworker_update(reference, prompt=originalPrompt + overlay)` and removed at the end of the loop (or on handoff). Capture the original prompt before applying so the cleanup restores it.

The overlay is generated from the `test_env.yaml` for the integrations actually declared in `agentSpec.neededTools`. Do not inject substitutions for tools the coworker does not use.

### Step B. Run a test payload

`mcp__bap__coworker_run(reference, userInput=payload.userInput)` returns a run id. Polling pattern, since runs are async (rule #7 of `build-agents-for-bap`):

```ts
async function pollUntilTerminal(runId: string, timeoutSeconds: number) {
  const terminal = new Set(["completed", "error", "cancelled"]);
  const interactive = new Set(["needs_user_input", "awaiting_approval", "awaiting_auth", "paused"]);
  const start = Date.now();
  while ((Date.now() - start) / 1000 < timeoutSeconds) {
    const log = await mcp__bap__coworker_logs({ runId });
    if (terminal.has(log.run.status)) return log;
    if (interactive.has(log.run.status)) {
      // Test mode does not provide interactive input. If the coworker stalls here,
      // it means [MODE TEST] was ignored. Surface as a diagnostic.
      return { ...log, _stalledInteractive: true };
    }
    await sleep(2000);
  }
  return { _timedOut: true, runId };
}
```

If the run errors with the rule-#9 infra-flake message ("The runtime ended in a non-terminal state and could not be recovered. Retry the task to continue."), retry once with the exact same payload before counting it as a failure. The other error message ("The runtime stopped making progress.") indicates the agent itself stalled. Do not retry as-is, count as a failure and diagnose.

### Step C. Cleanup per integration

After each run, walk `coworker_logs.events` and collect tool calls that mutated external state. Apply the cleanup strategy from `test_env.yaml`:

| Integration | act-then-cleanup logic |
|-------------|------------------------|
| Notion | Each `notion.create_page` event has a `page.id` in its tool_result. `mcp__notion-update-page(pageId, archived=true)` (or hard delete if `archiveInsteadOfDelete: false`). |
| Linear | Each `issue.create` event yields `issue.id`. `mcp__linear__save_issue(id, state="cancelled")` then delete via direct API if available. |
| Airtable | Each `create_records_for_table` yields record ids. `mcp__airtable__delete_records_for_table(tableId, recordIds)`. |
| Slack | Each `chat.postMessage` yields `ts` (message timestamp). Use Slack API delete (no MCP tool for that today; record into handoff if unsupported). |
| Gmail | Each `messages.send` yields a `messageId`. Trash via Gmail API or `google-gmail --account <label> trash --message-id <id>`. |
| Custom MCP | Best-effort: invoke the matching `*_delete` or `*_undo` tool if exposed by the MCP. Otherwise list the artefact in the handoff and rely on `sandbox-redirect` next time. |

When `strategy: sandbox-redirect`, cleanup is optional. Artefacts in the sandbox channel / DB are expected; only purge if `retentionMinutes` is exceeded.

Cleanup runs even when the run errored, unless `cleanupOnFailure: false`. The default is to keep failed-run artefacts in place for postmortem.

### Step D. Per-iteration abort

A `testPayload` may be marked `required: true`. If a required payload fails its criteria, abort the rest of the payloads for this iteration and go straight to diagnose / patch. This shortens the loop when the first failure is obvious.

If no payloads are required, run all of them every iteration: a coworker that passes the happy path but fails the degenerate input still needs work.

### Step E. Success exit

The loop returns success only when **all** `testPayloads` pass **all** their `expectedOutcomes` in the same iteration. Partial passes across iterations do not count; the coworker must be stable in one shot.

Return value:

```json
{
  "status": "success",
  "coworkerReference": "@sales-call-debrief-writer",
  "iterations": 2,
  "finalRunIds": ["run-abc", "run-def"],
  "history": [ /* full log of each iteration */ ],
  "testArtefacts": [ /* what was created and what was cleaned up */ ],
  "finalPromptDiff": "<unified diff of original prompt vs current>"
}
```

### Step F. Diagnose

The diagnose step inspects the failure pattern and proposes a patch. Patterns and their patches:

| Failure pattern | Diagnostic | Patch |
|-----------------|------------|-------|
| `coworker_logs.events` has no tool_use for a required tool | Agent skipped a step. Likely cause: prompt does not enforce step order. | Add explicit step list to the prompt: "Do step 1, then 2, then 3. Do not skip." |
| Tool was called with wrong target (e.g. wrong Notion DB) | Test overlay not honoured. | Strengthen the overlay wording; move it to the top of the prompt. |
| Tool not visible in `_init` message: "Some selected tools are unavailable" | Missing `workspaceMcpServerIds` or `allowedSkillSlugs`. Rule #5. | Patch `workspaceMcpServerIds` / `allowedSkillSlugs` based on `agentSpec.neededTools`. |
| Run stalled in `awaiting_approval` despite [MODE TEST] | `autoApprove: false`. | Patch `autoApprove: true` for tests only. |
| Run stalled in `awaiting_auth` | `authSource` mismatched with model (rule #8). | Patch `authSource` per the rule-8 matrix. |
| "Runtime stopped making progress" | Skill asks the LLM to emit too much. Rule #1. | Surface to human, the fix is structural (bundle a script). Do not auto-patch. |
| `output.html` missing | Skill that should produce it did not run; usually missing skill slug. | Patch `allowedSkillSlugs`. |
| `successCriteria` text says X but `output.html` is fine visually | Criterion is over-specific. | Surface to human, ask to refine criterion. Do not silently relax. |

A patch that touches anything other than `prompt`, `skillSlugs`, `workspaceMcpServerIds`, `autoApprove`, `authSource`, `integrations`, `requiresUserInput`, `userInputPrompt` is rejected and surfaced. Structural changes (the skill itself) need human review and a re-deploy.

### Step G. Patch + iterate

`mcp__bap__coworker_update(reference, ...patch)` and loop. Persist the diff between iterations: the handoff message must show the user every patch applied.

### Handoff

Triggered when:

- Iteration cap reached without success.
- A diagnose step returned `requiresHuman: true`.
- A `stopHumanCheckpoint` was hit and `stopOnFirstHumanCheckpoint: true`.

Format of the Slack ping in `options.handoffChannel`:

```
[handoff] coworker @sales-call-debrief-writer (5/5 iterations, no pass)

Last run: https://heybap.com/runs/<runId>
Failing criteria:
  - debrief_has_5_bullets : got 3 bullets
  - notion_spiced_filled  : SPICED field is empty

Patches applied this loop:
  iter 1 -> tightened step order in prompt
  iter 2 -> added autoApprove=true
  iter 3 -> swapped model to openai/gpt-5.5 (was gpt-5.4)
  iter 4 -> added @debrief-writer skill slug
  iter 5 -> no patch produced (diagnose returned requiresHuman)

Diagnosis: model produces a partial debrief on long transcripts. Looks like rule #1: the skill asks the agent to generate the whole markdown body. Recommend bundling a render.py.

Full transcript: /tmp/test-loop-<timestamp>.json
```

## Eval methodology

The evaluator runs in process, in under `options.evalBudgetSeconds` (default 30). It is *not* an LLM call by default. Each `successCriteria[].check` is parsed and executed against a structured view of the run:

```json
{
  "run": { "id": "...", "status": "completed", "errorMessage": null, "events": [...] },
  "tool_calls": [
    { "name": "slack.send_message", "args": {...}, "result": {...}, "atIso": "..." }
  ],
  "sandbox_files": [
    { "path": "/app/output.html", "fileId": "...", "size": 12345, "content": "<truncated>" }
  ],
  "documents_created": [],
  "messages": [ /* assistant + user messages on the conversation */ ]
}
```

Supported check forms:

- `<dotted.path> contains "<substring>"`, e.g. `tool_calls.slack.send_message.args.text contains "Acme"`
- `<dotted.path> matches /<regex>/` (Python re syntax)
- `<dotted.path> exists` / `<dotted.path> is not empty`
- `tool_calls.<name>.count >= <int>`
- `output.html contains "<substring>"`
- `events contains tool_use for "<tool>"` (sugar over `tool_calls.<tool>.count >= 1`)

For LLM-judged criteria (rare, only when human says explicitly "ask a model"), wrap in `LLM_JUDGE("<question>", <expected>)` and the evaluator runs a short `mcp__bap__chat_run` to score. Cap to one LLM judge call per iteration to control cost.

If a criterion uses syntax the evaluator does not understand, fail closed: mark the criterion `unparseable`, surface to human. Do not silently pass.

## Cleanup strategies by integration (default table)

| Integration | Strategy | Cleanup operation | Caveat |
|-------------|----------|-------------------|--------|
| Slack | sandbox-redirect | None during test. Purge `#test-coworkers` weekly. | Posting cannot be undone without admin scope. |
| Gmail | sandbox-redirect | Move `+test` aliased mails to trash after eval. | Recipient is yourself. |
| Notion | sandbox-redirect | Archive pages in "Test Deals" DB after `retentionMinutes`. | Hard delete needs API call; archive is cheap. |
| Linear | sandbox-redirect | Cancel issues in `TEST` team after `retentionMinutes`. | Cancelled issues stay visible; delete via direct API only. |
| Airtable | act-then-cleanup | Delete records by id. | Linked-record cleanup may cascade; verify. |
| Outlook | sandbox-redirect | Trash via Graph API. | Same as Gmail. |
| Google Drive | sandbox-redirect (folder `_tests/`) | Move to trash. | Trash retention 30d. |
| Salesforce | sandbox-redirect | Delete by id. | Use sandbox org if available, never prod. |
| Stripe | sandbox-redirect (test mode keys) | None; test mode is isolated. | Never run with live keys. |
| HTTP custom MCP | act-then-cleanup with fallback | Invoke `*_delete` tool if present. | Often missing; mark as `humanCheckpoint`. |

## Diagnostics patterns (cheat sheet)

```
errorMessage: "The runtime ended in a non-terminal state..." 
   -> infra flake, retry once with same payload.

errorMessage: "The runtime stopped making progress."
   -> structural, surface to human. Refactor toward rule #1.

run.status == "needs_user_input" mid-test
   -> [MODE TEST] not honoured. Strengthen prompt overlay.

run.status == "awaiting_approval" mid-test
   -> autoApprove off. Patch to true for test runs.

run.status == "awaiting_auth"
   -> rule #8 mismatch. Patch authSource per the matrix.

tool_calls.<tool>.count == 0
   -> Tool was needed but never called. Check workspaceMcpServerIds + namespacing (rule #6).

output.html size == 0 or absent
   -> Skill that writes it did not run. Check allowedSkillSlugs and rule #15.

assistant.messages.last contains "Je ne peux pas..."
   -> Coworker refused. Inspect why; often missing input or wrong instruction phrasing.
```

## When NOT to use this skill

- Coworker has no `testPayloads` and no `successCriteria`. The loop has nothing to do. Add criteria to the spec first.
- Coworker is read-only and the only success is a chat answer. Manual eyeballing is enough.
- The agent spec confidence is below 0.5 across all agents. Surface the spec to a human instead of brute-forcing tests.
- The cleanup strategy for at least one needed integration is `skip` and there is no sandbox-redirect available. Refuse to run; humans must intervene.

## Anti-patterns

- Running the test loop without first injecting the test overlay. The coworker will hit prod Slack / prod Notion. The loop refuses to start when no overlay was set; if you bypass this check manually, you are about to break things.
- Auto-patching the `model` field on every iteration. Model bumps are last resort; most fixes are prompt or skill wiring. Patch model only when diagnose explicitly says `model_mismatch_for_authSource` or `model_too_weak_for_long_prompt`.
- Treating `awaiting_user_input` as a failure. It is a signal that [MODE TEST] was ignored. Fix the overlay, do not patch around the symptom.
- Cleaning up before evaluation. Eval needs the artefacts to inspect. Always evaluate first, then cleanup.
- Counting a `needs_user_input` test as success because the run did not error. Success requires a terminal `completed` plus passing eval.
- Hardcoding the iteration cap to a large number to "give the loop more chances". After 5 iterations without progress, the answer is human review, not more tokens.

## Report HeyBap bugs and feature gaps

The test loop is the most concentrated source of HeyBap-side signal in the pipeline. Every iteration that *patches around* a platform misbehaviour is a finding you should report. Invoke [bap-finding-router](../bap-finding-router/SKILL.md). The router classifies the finding (SIMPLE vs COMPLEX) and dispatches to `bap-bug-report` (opens a PR on `the-agentic-company/bap`, notifies `#technical-pr`) or `bap-feature-brainstorm` (posts a 3-options problem statement in `#brainstorming-produit`). One finding equals one invocation. Do not invoke the leaf skills directly.

Specific triggers from this skill:

- The diagnose step returns `requiresHuman: true` because the patch space (`prompt`, `skillSlugs`, `workspaceMcpServerIds`, `autoApprove`, `authSource`, `integrations`, `requiresUserInput`, `userInputPrompt`) cannot fix the failure. The root cause sits in HeyBap. Bug or feature, depending.
- A run errored with `The runtime stopped making progress.` and the underlying skill follows rule #1 (no large artefact generation, bundled script in place). Bug.
- `coworker_logs.events` is missing a `tool_use` for a tool the agent demonstrably called (visible in the side-effect: Notion page created, but no `notion.create_page` event). Bug.
- `run.status == "completed"` but `sandboxFiles` is empty even though the skill wrote `/app/output.html`. Bug.
- `awaiting_auth` fires without a clear reason, on a coworker whose `authSource` and `model` are aligned with the rule-#8 matrix. Bug.
- `act-then-cleanup` is the right strategy for an integration but the matching MCP exposes no delete or undo endpoint (Slack message delete needing admin scope, a custom MCP without an `_delete` tool). Feature request, name the integration.
- Test runs are indistinguishable from prod runs in the HeyBap UI because `coworker_runs` cannot be filtered by tag or by the `[MODE TEST]` marker. Feature request: first-class test mode (tagged runs, auto-cleanup hook, sandbox env routing native to the platform).
- `coworker_update` accepted a patch but the new prompt did not propagate to the next run (cache invalidation gap). Bug.
- The diagnose patterns table grows with a new failure mode that has no recommended patch. Feature request: HeyBap-side observability for this pattern.

Do not retry quietly. Surface every structural finding.

## See also

- [parse-transcript-to-agent-spec](../parse-transcript-to-agent-spec/SKILL.md): produces the `agentSpec` this skill consumes.
- [transcript-to-bap-coworker](../transcript-to-bap-coworker/SKILL.md): the orchestrator that calls this skill at the end.
- [build-agents-for-bap](../build-agents-for-bap/SKILL.md): rules referenced throughout (#1, #5, #6, #7, #8, #9, #11, #15, #16, #19).
- [build-mcp-for-bap](../build-mcp-for-bap/SKILL.md): when the diagnose step says "the MCP itself is the bug", fix lives there.
- [bap-finding-router](../bap-finding-router/SKILL.md): invoke whenever a diagnose step concludes the root cause is in HeyBap (see the section above).
