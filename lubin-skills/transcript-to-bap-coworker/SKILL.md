---
name: transcript-to-bap-coworker
description: |
  Meta-skill that turns a sales / discovery / kickoff call transcript into one
  or several deployed and tested Bap (Heybap) coworkers, with all assets:
  agent prompt, SKILL.md, render scripts, `/app/output.html` template with
  interactive postMessage buttons, custom MCP server(s) when needed,
  workspace wiring, and a closed-loop test pass. Chains
  `parse-transcript-to-agent-spec`, `build-mcp-for-bap`, `build-agents-for-bap`,
  and `bap-coworker-test-loop` into a single pipeline. Use when a transcript
  arrives and the goal is "walk out of the call with the agents already live".
---

# Transcript to deployed Bap coworker, end to end

The aspiration: a call ends, the transcript hits Grain, and within a few minutes the proposed coworkers are running on Bap, tested against the success criteria the prospect actually stated. This skill is the orchestrator that makes that real. It does not do the work itself; it chains the four other skills in this folder in the right order, surfaces the unavoidable human checkpoints, and produces a single report at the end.

It is the top of the dependency chain. Nothing else in `lubin-skills/` calls it.

## When to invoke

- A transcript is dropped in chat with intent to "monte les agents", "agentifie ce call", "fais tourner le pipeline complet".
- A Grain URL is shared with "voici, sors-moi les coworkers".
- A `.txt` / `.md` transcript file is attached without other instructions and a `parse-transcript-to-agent-spec` JSON is desired downstream.
- The `agent-builder` coworker on Bap fires (if you set up the scheduled poll: `mcp__bap__coworker_update` with `schedule: { type: "interval", intervalMinutes: 30 }` and a prompt that calls this skill on each new Grain transcript).

Do not invoke when:

- The user asked only for parsing the transcript (no deployment). Use [parse-transcript-to-agent-spec](../parse-transcript-to-agent-spec/SKILL.md) directly.
- The user wants to update an existing coworker, not build a new one. Update path goes through [bap-coworker-test-loop](../bap-coworker-test-loop/SKILL.md) directly.
- The transcript covers a single read-only workflow ("summarise X") with no repeatable structure. A skill suffices, no coworker needed.

## Pipeline overview

```
                +-----------------------------+
   transcript ->|  parse-transcript-to-agent  |-- agentSpec.json (1..N agents)
                +-----------------------------+
                              |
                              v
                +-----------------------------+
                |  rank + filter (confidence >= 0.5,
                |   maxAgents from options)   |
                +-----------------------------+
                              |
                              v
                +-----------------------------+
                |  per-agent loop:            |
                |                             |
                |  1. resolve tools           |
                |     - native_integration    |
                |     - existing_workspace_mcp|
                |     - sandbox_cli           |
                |     - custom_mcp_to_build --|-->  invoke build-mcp-for-bap
                |                             |     HUMAN STOP: paste URL in Bap UI
                |                             |
                |  2. generate skill folder   |
                |     SKILL.md + render.py    |
                |     + /app/output.html      |
                |                             |
                |  3. skill_add               |--> mcp__bap__skill_add
                |                             |
                |  4. coworker_create         |--> mcp__bap__coworker_create
                |                             |
                |  5. test loop               |--> bap-coworker-test-loop
                +-----------------------------+
                              |
                              v
                +-----------------------------+
                |  consolidated report:       |
                |  - @username per agent      |
                |  - status (live / handoff)  |
                |  - test artefacts links     |
                |  - human checkpoints open   |
                +-----------------------------+
```

## Input contract

```json
{
  "transcript": "<text or path or Grain URL>",
  "context": { /* same as parse-transcript-to-agent-spec.context */ },
  "options": {
    "maxAgents": 3,
    "minConfidence": 0.5,
    "dryRun": false,
    "skillFolderRoot": "/tmp/agent-builds",
    "handoffChannel": "#agents-builds",
    "testEnvPath": "./test_env.yaml",
    "newMcpProjectVercelTeam": "the-agentic-company"
  }
}
```

`dryRun: true` produces all assets locally (skill folder, MCP scaffold, coworker config JSON) without calling any `mcp__bap__*` tool. Use to review before deploying.

`maxAgents` caps how many agents are actually built this run. Lower-ranked agents past the cap are emitted in the report as `notBuilt` with their spec, so a human can revisit later.

## Step 1. Parse the transcript

```
spec = invoke parse-transcript-to-agent-spec
  transcript: input.transcript
  context: input.context
  options: { maxAgents: input.options.maxAgents, language: "fr" }
```

Persist `spec` to `${skillFolderRoot}/<callId>/agent-spec.json` where `<callId>` is a stable hash of the transcript + call date. The downstream steps and the final report reference this file.

Validate before continuing:

- `spec.validationErrors` is empty.
- At least one agent has `confidence >= minConfidence`.
- Otherwise: emit handoff with the spec + ambiguities, stop.

Sort `spec.agents` by `rank` ascending, drop anything below `minConfidence`, truncate at `maxAgents`.

## Step 2. Resolve tools per agent

For each `agent` in the surviving list, build a `toolPlan`:

```
toolPlan = {
  nativeIntegrations: [],          // -> integrations[] on coworker_create
  existingWorkspaceMcps: [],       // -> workspaceMcpServerIds[]
  sandboxClis: [],                 // documented in prompt, no wiring
  customMcpsToBuild: [],           // invoke build-mcp-for-bap, HUMAN STOP
}
```

For each item in `agent.neededTools`:

| kind | Action |
|------|--------|
| `native_integration` | Append to `nativeIntegrations`. Verify the integration name matches the Bap canonical list (slack, gmail, notion, linear, airtable, outlook, google-calendar, google-drive, salesforce, hubspot). Otherwise downgrade to `sandboxCli` or `customMcp`. |
| `existing_workspace_mcp` | Resolve the MCP server ID via `mcp__bap__coworker_list` of a known reference coworker, or ask human. Store id. |
| `sandbox_cli` | No wiring; the agent prompt will reference the CLI per rule #16 of `build-agents-for-bap`. |
| `custom_mcp_to_build` | Trigger [build-mcp-for-bap](../build-mcp-for-bap/SKILL.md), see Step 2b. |

### Step 2b. Build custom MCP when needed

When `customMcpsToBuild` is non-empty, for each entry:

1. Scaffold a Vercel + Next.js project per `build-mcp-for-bap`. Project name: `${tool.name}-mcp`, generic enough to be reused.
2. Implement the tools listed in `tool.endpoints[]` (the spec must include enough detail; if not, push to `ambiguities` and stop).
3. `vercel deploy --prod --yes` and capture the alias URL.
4. `vercel project protection disable --sso`.
5. Smoke-test the OAuth chain with the curl snippet in `build-mcp-for-bap`.

Then emit a **HUMAN STOP** because there is no programmatic API to bind a workspace MCP to Bap today:

```
[human action required]
A new MCP has been deployed:
  Name : grain-transcript-mcp
  URL  : https://grain-transcript-mcp.vercel.app/api/mcp
  Tools: fetch_transcript, list_recent_meetings

Open Bap -> Workspace settings -> MCP servers -> Add new -> paste the URL above
Click "Connect OAuth". Status must flip to Connected.

When done, paste the workspaceMcpServerId here (or accept the auto-detect prompt).
```

Auto-detect heuristic: once the human acks, the orchestrator calls `mcp__bap__coworker_list`, picks the most recently created coworker with this MCP wired (a reference seed coworker can be created for this purpose), and reads the id. Caching the result avoids repeating the human step for the next agents in the batch.

Persist the id to `${skillFolderRoot}/<callId>/mcps.json` so the test loop can wire later coworkers without re-asking.

## Step 3. Generate the skill folder per agent

Each agent gets a skill folder under `${skillFolderRoot}/<callId>/<agent.slug>/`:

```
${agent.slug}/
├── SKILL.md
├── data_schema.json          (only if the agent emits structured output)
├── render.py                 (only if rule #1 applies: large artefact)
└── output_template.html      (only if /app/output.html is part of outputs)
```

### SKILL.md generation

Frontmatter:

```yaml
---
name: ${agent.slug}
description: |
  ${agent.description}
  Use when ${derived from agent.triggers + agent.inputs}.
---
```

Body, in this order:

1. **One-paragraph intro.** Restate `agent.goal`, name the prospect (from `spec.callMeta.prospect`).
2. **Inputs.** From `agent.inputs[]` and `agent.requiresUserInput` / `agent.userInputPrompt`.
3. **Steps.** Numbered list from `agent.steps[]`, each step naming the tool (namespaced where needed per rule #6).
4. **Output contract.** From `agent.outputs[]`, with the exact format. Mention `/app/output.html` if applicable (rule #15).
5. **Validation signals.** From `agent.stopHumanCheckpoints[]` and any pause points. Include rule-#19 sentinel: explicitly list which user phrases trigger phase transitions, and the `[MODE TEST]` bypass.
6. **Tool fallbacks.** For each native integration that has a sandbox CLI fallback (Gmail, Outlook, Slack), document the CLI per rule #16.
7. **Failure modes the agent should self-recover from.** A short list (timeouts, missing inputs, rate limits).

If the agent emits `/app/output.html`, generate `output_template.html` with the deterministic skeleton:

```html
<!doctype html>
<html lang="fr">
<head><meta charset="utf-8"><title>${agent.agentName}</title></head>
<body>
  <script id="data" type="application/json">__DATA_JSON__</script>
  <main id="root">Chargement...</main>
  <script>
    const ORIGINAL_HTML = document.documentElement.outerHTML;  // rule #4
    const raw = document.getElementById('data').textContent;
    const data = JSON.parse(raw);
    render(data);
    // Action buttons -> postMessage
    document.querySelectorAll('[data-action]').forEach(btn => {
      btn.addEventListener('click', () => {
        const prompt = btn.getAttribute('data-prompt');
        btn.disabled = true;
        parent.postMessage({ type: "bap:agentic-app-prompt", version: 1, prompt }, "*");
        setTimeout(() => { btn.disabled = false; }, 3000);
      });
      window.addEventListener('message', e => {
        if (e.data?.type === "bap:agentic-app-prompt-result" && e.data.status === "sent") {
          btn.textContent = btn.textContent + " envoye";
        }
      });
    });
    function render(data) { /* generated per agent.outputs schema */ }
  </script>
</body>
</html>
```

The buttons in the rendered DOM use `data-action="<id>"` and `data-prompt="<instruction to send back to chat>"`. The list of buttons comes from `agent.outputs[*].interactions[]` (if the spec contains it) or is left empty.

If rule #1 applies (any output >5 KB structured content), bundle a `render.py`:

```python
#!/usr/bin/env python3
"""Deterministic renderer for ${agent.agentName}.
Reads /tmp/data.json, writes /app/output.html.
"""
import json, pathlib, html, re

ROOT = pathlib.Path(__file__).parent
TPL = (ROOT / "output_template.html").read_text(encoding="utf-8")

def main():
    data = json.loads(pathlib.Path("/tmp/data.json").read_text(encoding="utf-8"))
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")   # rule #2
    out = TPL.replace("__DATA_JSON__", blob)
    pathlib.Path("/app/output.html").write_text(out, encoding="utf-8")
    print(f"output.html written ({len(out)} bytes)")

if __name__ == "__main__":
    main()
```

The generated SKILL.md instructs the agent to discover and run it per rule #10:

```
find /app/.opencode/skills -name render.py -path "*${agent.slug}*" -exec python {} \;
```

## Step 4. Upload the skill

```
mcp__bap__skill_add({
  files: [
    { path: "${agent.slug}/SKILL.md",            contentBase64: base64(SKILL.md) },
    { path: "${agent.slug}/render.py",           contentBase64: base64(render.py), mimeType: "text/x-python" },
    { path: "${agent.slug}/output_template.html",contentBase64: base64(template),  mimeType: "text/html" }
  ]
})
```

`mcp__bap__coworker_uploadDocument` is for documents attached to a coworker, not for skill bundles; use `skill_add` here. Templates above 2 KB are tolerated by `skill_add` (the 2 KB ceiling in rule #18 is for the per-coworker document path, not the skill bundle).

Verify the skill loaded by listing it indirectly: create a minimal smoke `chat_run` that asks the system to list available skills, and check the slug is present. If absent, the upload silently failed; abort the agent build and surface.

## Step 5. Create the coworker — two-call pattern

**The MCP `coworker_create` tool has a narrow signature.** It accepts only: `name`, `prompt`, `model`, `authSource`, `trigger`, `integrations`, `autoApprove`, `folder`, `files`. It does **NOT** accept `username`, `skillSlugs`, `requiresUserInput`, `userInputPrompt`, `workspaceMcpServerIds`, `schedule`, `toolAccessMode`, `customIntegrations`, or `description`.

So a fully wired coworker always takes **two calls**: a minimal `coworker_create` followed by a `coworker_update` that adds everything else. Skip the update and the coworker is shipped with no skill wired, no start message, no MCP IDs, no schedule — silent half-broken state.

### 5a. Minimal create

```
const created = await mcp__bap__coworker_create({
  name: agent.agentName,
  prompt: assemblePrompt(agent),                         // see below
  model: agent.model || "openai/gpt-5.5",                // rule #8 default
  authSource: agent.authSource || "shared",
  trigger: agent.triggers[0].type || "manual",
  autoApprove: false,                                    // safe default; test loop will flip if needed
  integrations: toolPlan.nativeIntegrations.map(t => t.name)
})
const coworkerId = created.coworker.id                   // UUID, used as `reference` in update
```

`assemblePrompt(agent)` builds the prompt around 5 blocks: role, mission, tool inventory with namespaced names (rule #6), step-by-step procedure with validation signals (rule #19), output contract referencing the skill, and a "what to do if blocked" section.

### 5b. Update — wire everything the create cannot set

```
await mcp__bap__coworker_update({
  reference: coworkerId,                                 // or the returned @username once 5b sets one
  username: agent.slug,                                  // hyphenated, unique per workspace
  description: agent.description,                        // human-readable one-liner
  skillSlugs: [agent.slug],
  workspaceMcpServerIds: [
    ...toolPlan.existingWorkspaceMcps,
    ...toolPlan.customMcpsToBuild.map(m => m.workspaceMcpServerId)
  ],
  requiresUserInput: agent.requiresUserInput,
  userInputPrompt: agent.triggers.find(t => t.type === "manual")?.userInputPrompt,
  toolAccessMode: "selected",                            // restrict to listed integrations; less LLM confusion
  schedule: agent.triggers.find(t => t.type === "scheduled")?.spec || null
})
```

Run 5a and 5b for **every** coworker — do not batch creates and only update the last one. Each coworker needs its own update, or the skill, start message, and MCP IDs are missing.

### 5c. Sanity check the wiring

Before moving on, call `coworker_get(@${agent.slug})` and confirm:

- `allowedSkillSlugs` contains `agent.slug`
- `requiresUserInput` is `true` and `userInputPrompt` is non-empty (if the agent expects input)
- `allowedIntegrations` matches the toolPlan
- `allowedWorkspaceMcpServerIds` is non-empty if the agent needs a workspace MCP

A `get` that misses any of these means the update silently dropped a field — usually a typo in the field name. Fix and re-update before testing.

Persist the coworker reference (the returned `@username`) to `${skillFolderRoot}/<callId>/coworkers.json`.

## Step 6. Run the test loop — never skip this

**Non-negotiable.** A coworker is not "live" until at least one `[MODE TEST]` run has produced the expected behaviour. The `[MODE TEST]` sentinel exists precisely to make this step workspace-safe: writes to Salesforce / Gmail / Notion are bypassed, the agent logs the payload it *would* have sent. There is no "I don't want to pollute the workspace" exception — that is the failure mode this contract removes.

Skipping this step has cost two real demos in the field: in both, the coworker shipped, the human-readable status said "live", and the first real run failed silently (skill not enabled, MCP tool name mismatch, schedule never fired). The fix is upstream: validate via a `[MODE TEST]` run *before* declaring the build done.

### 6a. Prerequisite — enable the freshly-uploaded skills

`mcp__bap__skill_add` returns `enabled: false` for new user skills. Disabled skills are *not* deployed into the sandbox under `/app/.claude/skills/`, so the coworker's `find /app/.opencode/skills -name SKILL.md | xargs grep -l '<slug>'` returns nothing, the agent gives up cleanly, and the run completes with no real work done. No error, no warning — just an agent that ran fast and produced nothing.

There is currently **no MCP tool to enable a skill programmatically**. This is a workspace UI step:

> HeyBap UI → Skills → find the freshly-uploaded skill by slug → toggle it on.

The orchestrator must surface this as a **HUMAN STOP** between Step 4 (`skill_add`) and Step 6 (test loop), the same way Step 2b stops for the MCP bind. Block until the human confirms; do not run the test loop against unenabled skills (it will pass with `(no output)` and you will think the agent works).

```
[human action required — skills uploaded but disabled]
Two skills are queued and need to be enabled in the workspace:
  - sales-call-wrap-up
  - sales-followup-drip

Open HeyBap → Skills → toggle each one on.
Reply "skills enabled" when done and I'll run the test loop.
```

When this MCP gap is closed (a `skill_update({enabled: true})` or `skill_enable({slug})` lands), drop the human stop and call it programmatically.

### 6b. Invoke the test loop

For each freshly enabled coworker:

```
result = invoke bap-coworker-test-loop
  coworkerReference: "@${agent.slug}"
  agentSpec: agent
  testEnv: loaded from input.options.testEnvPath
  options: {
    maxIterations: 5,
    perRunTimeoutSeconds: 300,
    handoffChannel: input.options.handoffChannel,
    stopOnFirstHumanCheckpoint: true
  }
```

Per agent: every `testPayloads[]` entry must be exercised, and every one must contain `[MODE TEST]` (parse-skill rule #5). The first payload validates the happy path; subsequent ones validate the degenerate inputs.

### 6c. Read the logs, do not trust the status

`coworker_run` returning `status: "completed"` only means the sandbox finished. It does **not** mean the agent did the right thing. Always pull `coworker_logs(runId)` and verify:

- The first `read` or `bash find` tool_use for the skill's SKILL.md actually returned content (not `(no output)` or `File not found`).
- The expected tool calls fired (Salesforce write attempt, Gmail send attempt, `render.py` execution, etc.) — even bypassed in `[MODE TEST]`, the agent should still *attempt* the tool path so you can confirm it picked the right tool name.
- The structured payload the agent logged matches the skill's data contract.
- `sandboxFiles` contains the artefacts the skill claims to produce (e.g. `/app/output.html` for panel coworkers).

If any of those fail, the run "completed" but the coworker is broken — do not mark `live`. Iterate via `coworker_update` (prompt / skillSlugs / userInputPrompt) and re-run.

### 6d. Interactive features — `[MODE TEST]` is not enough, real-receiver run is mandatory

A `[MODE TEST]` run validates that the agent can read the skill, extract the data, and produce the artefact (data.json, panel HTML, etc.). It does **not** validate the parts that only fire on real user interaction or real external writes:

- Panel buttons that postMessage back to the chat (rule #15). MODE TEST renders the panel, but it does not exercise the click → chat → agent reaction loop.
- Tool calls that the agent is told to *bypass* in MODE TEST (Salesforce write, Gmail send, Notion page create). MODE TEST verifies extraction; it does not verify that the tool name is correct, the integration is wired, the OAuth scope is right, the field mapping matches the target system.
- Multi-turn flows where the second turn depends on a real reply from the first turn.

For any coworker that has interactive features or real external writes, the test loop must include a **two-phase test**, both mandatory:

| Phase | Sentinel | Receiver / target | Validates |
|-------|----------|-------------------|-----------|
| 1. MODE TEST | `[MODE TEST]` | fake email / fake caseId / fake channel | extraction, render, panel exists, structured artefacts present |
| 2. Real-receiver | (no sentinel) | tester's own email / sandbox CRM org / `#test-bot` Slack channel | button click → chat injection, real tool fires, artefact reaches the target system |

Phase 2 always uses the **tester's own** receiver, never the prospect's. For email coworkers: `contactEmail = lubin@hyperstack.studio` (or whoever's running the test). For CRM coworkers: a sandbox org or a dedicated test case. For Slack coworkers: a `#test-*` channel the tester owns. Sending the prospect a "test" email is never acceptable.

The phase-2 run is gated on a human action when the panel requires a click (rule #15 buttons). The orchestrator surfaces this as a **HUMAN STOP** after phase 1:

```
[human action required — interactive E2E test]
Phase 1 (MODE TEST) passed for @sales-followup-drip. Panel rendered, payload extracted.
Phase 2 needs you to:
  1. Open the conversation: <link>
  2. Click "Send" in the panel
  3. Verify (a) a chat message starting with [SEND EMAIL EXACTLY AS BELOW] appears, (b) the email lands in your inbox

Reply "phase 2 ok" or paste the chat error you see, and I'll mark the coworker live or iterate.
```

When the agent supports an autonomous test path (auto-approve mode + a deterministic transcript that hits the same code paths), phase 2 can be automated by triggering a second `coworker_run` and watching the logs for the actual `salesforce_*` / `google_gmail_*` tool call to fire. The button-click loop, however, requires a human gesture — no way around it today.

### 6e. Branch on the result

- `status: "success"` and logs check out → mark `live` in the final report.
- `status: "handoff"` or logs reveal a silent failure → mark `needsReview`, append the diagnosis (which check failed in 6c).

The test loop already does sandbox cleanup; nothing else to do here.

## Step 7. Consolidated report

Emit one Markdown report to the human via the handoff channel and to disk at `${skillFolderRoot}/<callId>/report.md`:

```
# Build report - ${spec.callMeta.prospect} - ${spec.callMeta.callDateIso}

## Live coworkers (${live.length})
- **@${agent.slug}** - ${agent.description}
  test loop: 1 pass in 2 iterations
  last run: <link to run logs>
  triggers: ${agent.triggers}

## Needs review (${needsReview.length})
- **@${agent.slug}** - ${agent.description}
  test loop: handed off after 5 iterations
  failing criteria: ${failing}
  recommended action: ${diagnosis.recommendation}

## Built and waiting for human MCP bind (${humanBindWaiting.length})
- **mcp grain-transcript-mcp** - URL: https://grain-transcript-mcp.vercel.app/api/mcp
  paste into Bap workspace MCP settings, then run resume command

## Not built (below confidence threshold or maxAgents cap)
- **${candidate.agentName}** - confidence ${candidate.confidence} (${candidate.evidence[0].quote})

## Ambiguities surfaced by the parser
- ${ambiguity.topic} - needs decision: ${ambiguity.options.join(' / ')}
```

This is the artefact a human reviews. Everything in the pipeline is auditable from this report.

## Resume after human action

The pipeline can be re-invoked with `{ resumeCallId: "<callId>", action: "mcp-bound", workspaceMcpServerId: "<uuid>" }` to continue past a human bind without re-doing earlier steps. State is read from `${skillFolderRoot}/<callId>/`.

## Autonomous mode (`/loop` over Grain)

This skill is the natural target of an autonomous loop: pick up new call transcripts as they appear, run the full pipeline, drop the report. Two cadences are supported.

### Pattern A: `/loop <interval>` (fixed cadence)

```
/loop 30m invoke transcript-to-bap-coworker
  poll: { source: "grain", since: state.lastSeenIso, dedupAgainst: state.seen }
  context: { language: "fr" }
  options: { maxAgents: 3, testEnvPath: "./test_env.yaml" }
```

The wrapper runs every 30 minutes. Each tick:

1. Fetch new Grain transcripts since `state.lastSeenIso` (Grain public API + PAT bearer, see the operator's `grain-corpus-access` memory).
2. For each new transcript not in `state.seen`, invoke this skill with `transcript: <grain url or text>` and the inferred `context.prospect`.
3. Append the transcript id to `state.seen` and update `state.lastSeenIso` only after the skill returns (success or handoff). Failure during processing keeps the transcript in queue for the next tick.
4. Emit a heartbeat line into the configured Slack ops channel ("Tick at HH:MM, N scanned, M built").

State path: `${skillFolderRoot}/state/grain-poll.json`. Persisted between ticks. The wrapper must use file locking (e.g. `flock`) so two overlapping ticks do not double-build.

### Pattern B: `/goal <condition>` (self-paced, until done)

When you want to drain a backlog of transcripts collected ad hoc (e.g. the 50 last calls Baptiste mentioned in the daily sync):

```
/goal "all transcripts in /tmp/backlog-2026-06.tsv processed AND every emitted agent is either live or handoff"
  invoke transcript-to-bap-coworker on each transcript
  stop when goal met OR budget exhausted
```

The orchestrator self-paces: it picks the next transcript, runs the pipeline, marks done, loops until the goal condition evaluates true. No interval. The model decides when to stop based on the goal predicate, which is the natural pattern for batch backfills.

`/goal` requires a goal predicate that can be evaluated from the orchestrator's persisted state (`coworkers.json`, `report.md`, the input list). Avoid open-ended goals ("until the team is happy"); they never terminate.

### Coexistence

Both patterns can run in parallel safely if they share the `${skillFolderRoot}/state/` directory and use the same `seen` dedup. Pattern A handles the steady stream of new calls; pattern B is invoked manually when you want to backfill or stress-test the pipeline.

### What NOT to do

- Run `/loop 5m` or shorter. Grain rate-limits and the pipeline can take 3 to 30 min per transcript; tighter cadence just produces overlap.
- Run `/goal` without a measurable predicate. The model will either stop early or loop forever.
- Skip the heartbeat. Without it, autonomous mode is a black box; you have to be able to see the loop is alive.

## Failure modes and where they live

| Symptom | Where the bug is | Where to look |
|---------|------------------|----------------|
| Pipeline stops at step 1 with validation errors | Spec extraction misread the transcript | `parse-transcript-to-agent-spec` rules, possibly tune the context object |
| Pipeline stops at step 2b waiting for MCP bind | Bap has no API for this yet | Human paste, then resume |
| `skill_add` returned 200 but coworker can't find the skill | Slug collision or async indexing | Wait 5s, retry the smoke check before failing |
| `coworker_create` rejected `workspaceMcpServerIds` | The MCP id was wrong or the workspace MCP was disabled | `mcp__bap__coworker_get(@reference)` of a known coworker that uses it, copy the id |
| Test loop never succeeds, every iteration patches the model | Anti-pattern; structural fix needed | Read `bap-coworker-test-loop` anti-patterns, likely rule #1 |
| Coworker schedules trigger every 30 min and create duplicate work | Scheduled trigger created without dedup | The agent prompt must dedup against `coworker_runs` history or persist seen ids; surface to human if missing in spec |

## Anti-patterns

- Building every agent the parser proposed, ignoring confidence and rank. The parser produces a candidate list; the orchestrator filters.
- Skipping the test loop because "the prompt looks right". The whole point is to verify, not assert.
- Adding `autoApprove: true` at `coworker_create` time to avoid `awaiting_approval` during tests. That sticks for prod runs too. Let the test loop flip it temporarily; never set it on by default.
- Building the same custom MCP twice for two agents in the same batch. Resolve duplicates in step 2; one MCP per `tool.name`, shared across coworkers.
- Putting the call-specific prospect name in the skill slug. Slugs are workspace-global; use the workflow domain (`sales-call-debrief-writer`), not the prospect (`acme-debrief-writer`).
- Reporting `live` for a coworker that has `needsReview` items. The report distinguishes them deliberately so the human knows what to inspect.

## Report HeyBap bugs and feature gaps (mandatory, all steps)

The orchestrator is the only place in the pipeline that touches HeyBap at every level: spec extraction, MCP scaffolding and binding, skill upload, coworker creation, run / log / update, panel rendering, report persistence. You see the whole stack misbehave or fail to expose a needed capability. Surface every finding through [bap-finding-router](../bap-finding-router/SKILL.md). The router classifies (SIMPLE vs COMPLEX) and dispatches to `bap-bug-report` (opens a PR on `the-agentic-company/bap`, notifies `#technical-pr`) or `bap-feature-brainstorm` (posts a 3-options problem statement in `#brainstorming-produit`).

One finding equals one invocation. A one-line description is enough; the router and its downstream skills do the deep investigation themselves. Do not invoke the leaf skills directly; do not batch findings; do not wait until "the end of the pipeline"; do not silently route around. Baptiste asked explicitly for tight feedback in the 2026-06-18 daily sync, and the orchestrator is the most concentrated source of HeyBap signal that exists.

Triggers per step:

- **Step 1 (parse).** Whatever `parse-transcript-to-agent-spec` would otherwise surface as a platform gap (see its own section).
- **Step 2 (resolve tools).** A `neededTools[]` item should have been a native integration but you had to downgrade to `custom_mcp_to_build`. Name the missing integration as a feature request. `workspaceMcpServerIds` cannot be resolved because there is no listing API: feature request (also explicit in step 2b).
- **Step 2b (build custom MCP).** The HUMAN STOP on workspace MCP bind is the single biggest friction of the whole pipeline. File the feature request once per session: "programmatic workspace MCP server creation + bind (URL, auth, OAuth) without UI". Also file a feature request if `Connect OAuth` fails on a freshly deployed MCP that passes the curl smoke-test (workspace-side regression).
- **Step 3 (generate skill folder).** The HTML postMessage protocol (`bap:agentic-app-prompt`) has no schema introspection. There is no way to declaratively list "what actions a panel can send". Feature request. Also flag any panel-rendering bug observed during dry-run inspection.
- **Step 4 (`skill_add`).** Returns 200 but the skill is not immediately visible to coworkers (async indexing window not documented). Bug or doc gap. `skill_add` cannot replace an existing skill with the same slug without manual delete first: feature request.
- **Step 5 (`coworker_create`).** Rejects unknown `workspaceMcpServerIds` silently or with an opaque error: bug. No way to attach the `agentSpec` JSON as first-class coworker metadata (every run regenerates the test overlay from the on-disk spec file): feature request. `coworker_create` does not accept a `schedule` matching the spec's `triggers[].spec` shape one-to-one: surface the gap.
- **Step 6 (test loop).** Whatever `bap-coworker-test-loop` would otherwise surface (see its own section).
- **Step 7 (report).** The final report cannot be persisted as a HeyBap entity; it lands in Slack and on disk only. Feature request: a `coworker.buildReport` first-class object queryable from the UI.
- **Resume after human action.** No webhook from HeyBap to notify the orchestrator that the workspace MCP bind happened. Feature request.

If at any step you find yourself writing a comment like "TODO: HeyBap should support X" in code or in the report, that comment is the bug report. File it.

## See also

- [parse-transcript-to-agent-spec](../parse-transcript-to-agent-spec/SKILL.md): step 1 of this pipeline.
- [bap-coworker-test-loop](../bap-coworker-test-loop/SKILL.md): step 6 of this pipeline.
- [build-agents-for-bap](../build-agents-for-bap/SKILL.md): the rule set the generated coworker must follow. Cited inline throughout (rules #1, #2, #4, #6, #8, #10, #15, #16, #18, #19).
- [build-mcp-for-bap](../build-mcp-for-bap/SKILL.md): called in step 2b when a custom MCP is needed.
- [bap-finding-router](../bap-finding-router/SKILL.md): invoke at every step where the platform falls short (see the section above).
