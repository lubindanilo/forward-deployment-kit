---
name: parse-transcript-to-agent-spec
description: |
  Read a sales / discovery / kickoff call transcript and emit a strict JSON spec
  describing the Bap (Heybap) coworker(s) implied by the conversation: goal,
  triggers, inputs, steps, outputs, needed tools, success criteria, test
  payloads, and human-in-the-loop checkpoints. The downstream skills
  `transcript-to-bap-coworker` and `bap-coworker-test-loop` consume this JSON
  to build, deploy and validate the coworker on Bap. Use when a transcript
  (Grain export, raw text, audio that has already been transcribed) needs to
  be turned into one or several deployable agents.
---

# Parse a call transcript into a Bap agent spec

Half the work of shipping a coworker is reading a 45-minute call carefully enough to extract what it should actually do. This skill turns that reading pass into a deterministic JSON document that every downstream automation can rely on. No prose, no "I think", just a schema.

The output is the contract for [transcript-to-bap-coworker](../transcript-to-bap-coworker/SKILL.md) and [bap-coworker-test-loop](../bap-coworker-test-loop/SKILL.md). Get this wrong and the rest of the pipeline silently produces a useless agent.

## When to invoke

Trigger keywords / patterns:

- "voici le transcript de mon call avec X, qu'est-ce qu'on en sort"
- "regarde ce que veut le prospect, monte le coworker"
- "parse le transcript Grain de [...] et propose les agents"
- A Grain URL (`https://grain.com/share/.../...`) or a `.txt` / `.md` attachment that looks like a multi-speaker transcript
- A meeting note dropped with "agentifie ça"

If the user gives you a transcript without instructions, default to invoking this skill before doing anything else. The JSON output is cheap and makes every later decision concrete.

## Input contract

```json
{
  "transcript": "<raw text or Grain export, speaker labels OK>",
  "context": {
    "prospect": "Concentrix",
    "icp": "BPO 200k+ agents, sales ops",
    "callType": "discovery | kickoff | follow-up | technical | demo",
    "ownerInternal": "Lubin",
    "callDateIso": "2026-06-18",
    "priorAgents": []
  },
  "options": {
    "maxAgents": 5,
    "language": "fr"
  }
}
```

`context` is optional but raises quality. If absent, infer from the transcript itself: prospect name from speaker references, callType from intent markers ("on commence", "vous avez vu la démo", "après les retours de la dernière fois").

`maxAgents` caps the number of agents proposed. The transcript almost always contains 2 to 6 candidate processes; ranking them prevents diluting the loop.

## Output schema

Return one document with `agents[]` (array). Each agent is the unit consumed downstream.

```json
{
  "schemaVersion": "1.0",
  "callMeta": {
    "prospect": "Concentrix",
    "callType": "discovery",
    "callDateIso": "2026-06-18",
    "transcriptSummary": "1 paragraph, max 600 chars",
    "ownerInternal": "Lubin"
  },
  "agents": [
    {
      "rank": 1,
      "agentName": "Sales call debrief writer",
      "slug": "sales-call-debrief-writer",
      "description": "After every prospect call, drop a structured debrief in the Slack #ventes channel and a Notion page linked to the deal.",
      "goal": "Turn a Grain transcript into a Slack debrief plus a Notion page in under 5 minutes.",
      "triggers": [
        { "type": "manual", "userInputPrompt": "Colle le lien Grain et le nom du prospect." },
        { "type": "scheduled", "spec": { "type": "interval", "intervalMinutes": 30 }, "note": "Poll Grain for new transcripts." }
      ],
      "inputs": [
        { "name": "grainUrl", "type": "string", "required": true, "source": "userInput" },
        { "name": "prospectName", "type": "string", "required": false, "source": "userInput" }
      ],
      "steps": [
        { "id": 1, "what": "Fetch transcript text from Grain using PAT", "tool": "grain.fetch_transcript" },
        { "id": 2, "what": "Extract SPICED signals + 3 follow-up actions", "tool": "agent.reasoning" },
        { "id": 3, "what": "Post the debrief to Slack #ventes", "tool": "slack.send_message" },
        { "id": 4, "what": "Create a Notion page under the deals database", "tool": "notion.create_page" }
      ],
      "outputs": [
        {
          "kind": "slack_message",
          "channel": "#ventes",
          "format": "headline + 5 bullets + Notion link",
          "successCriteriaRef": ["debrief_has_5_bullets", "debrief_links_to_notion"]
        },
        {
          "kind": "notion_page",
          "database": "Deals",
          "format": "structured page with SPICED fields filled",
          "successCriteriaRef": ["notion_spiced_filled", "notion_page_linked_to_deal"]
        }
      ],
      "neededTools": [
        { "name": "grain", "kind": "custom_mcp_to_build", "rationale": "No native Grain integration in Bap; PAT-based API exists." },
        { "name": "slack", "kind": "native_integration", "scopes": ["chat:write"] },
        { "name": "notion", "kind": "native_integration", "scopes": ["pages:write"] }
      ],
      "successCriteria": [
        { "id": "debrief_has_5_bullets", "check": "slack_message.body contains >= 5 bullet lines starting with '- '" },
        { "id": "debrief_links_to_notion", "check": "slack_message.body contains a notion.so URL" },
        { "id": "notion_spiced_filled", "check": "notion_page.properties.SPICED is not empty" },
        { "id": "notion_page_linked_to_deal", "check": "notion_page.parent.database_id == 'Deals'" }
      ],
      "testPayloads": [
        {
          "name": "happy_path",
          "userInput": "[MODE TEST] https://grain.com/share/fake-test-call-001 Acme Corp",
          "expectedOutcomes": ["debrief_has_5_bullets", "debrief_links_to_notion", "notion_spiced_filled"]
        },
        {
          "name": "no_prospect_name",
          "userInput": "[MODE TEST] https://grain.com/share/fake-test-call-002",
          "expectedOutcomes": ["debrief_has_5_bullets", "debrief_links_to_notion"]
        }
      ],
      "stopHumanCheckpoints": [
        { "step": "after_step_3_before_step_4", "reason": "First production run: visually verify the Slack message format before persisting in Notion." }
      ],
      "model": "openai/gpt-5.5",
      "authSource": "shared",
      "requiresUserInput": true,
      "estimatedRunDurationSeconds": 90,
      "confidence": 0.84,
      "evidence": [
        { "quote": "il faut absolument qu'après chaque call on ait un truc qui tombe dans Slack et dans Notion", "speaker": "Lubin", "timestampApprox": "12:34" },
        { "quote": "SPICED on l'utilise pour qualifier, donc le debrief doit le remplir", "speaker": "Lubin", "timestampApprox": "18:02" }
      ]
    }
  ],
  "ambiguities": [
    { "topic": "Grain webhook vs polling", "needHumanDecision": true, "options": ["Polling every 30 min", "Build a Grain webhook receiver"] }
  ],
  "discardedCandidates": [
    {
      "agentName": "Auto-generate full CRM",
      "reason": "Out of scope: the prospect wanted a Salesforce clone, no clear repeatable workflow. Same anti-pattern as Concentrix Jean-Marc."
    }
  ]
}
```

Every field is required unless the schema marks it optional. Empty arrays are explicit (`[]`), never omitted.

## Extraction rules

The model decides what becomes an agent and what doesn't. The rules below are non-negotiable; they exist because real transcripts are noisy.

### 1. An agent is a repeatable workflow, not a one-off task

Markers of a real agent:

- "à chaque fois que", "tous les matins", "dès qu'on reçoit"
- "ce qu'on fait là c'est qu'on copie-colle X dans Y, ça prend 20 min, on aimerait que ce soit auto"
- "le mec passe 1h par jour à"

Markers of a one-off that should be discarded (or sent to `discardedCandidates`):

- "il faudrait qu'on construise une plateforme entière de"
- "un Salesforce custom"
- "tout le système de comptabilité de la boîte"

Anti-pattern from the field: the Concentrix Jean-Marc case (vibe-coded CRM with 50 pages, not an agent). When the transcript describes building an app rather than automating a workflow, the answer is `discardedCandidates`, not a 200-step agent.

### 2. Steps come from "comment vous faites aujourd'hui"

The transcript usually contains both the wish ("on aimerait que...") and the manual process ("aujourd'hui ce qu'on fait c'est..."). The manual process *is* the steps array. Extract it literally, then map each step to a tool.

If the manual process is missing, ask the user via `ambiguities` rather than inventing steps.

### 3. Classify each tool into one of 4 kinds

| Kind | When to use | Downstream consequence |
|------|-------------|------------------------|
| `native_integration` | Slack, Gmail, Notion, Linear, Airtable, Outlook, Google Calendar, Google Drive, Salesforce, HubSpot | Wire via `integrations: [...]` on `coworker_create` |
| `existing_workspace_mcp` | The workspace already has an MCP server for this tool, named in the transcript or known from context | Wire via `workspaceMcpServerIds: [<id>]` |
| `custom_mcp_to_build` | The tool has an HTTP API but no Bap integration (Grain, internal CRM, vibe-coded service) | Triggers `build-mcp-for-bap` in the orchestrator |
| `sandbox_cli` | The action can be done via a CLI shipped in the Bap sandbox (`google-gmail`, `slack-cli`, ffmpeg, curl) | No wiring needed, document the command in the agent prompt |

Default to `native_integration` when unsure and the tool name matches a known Bap integration. The orchestrator will catch mistakes during the test loop.

### 4. successCriteria must be machine-checkable

Each criterion gets a unique `id` and a `check` written as an assertion the test loop can evaluate against the run output. Vague criteria like "the debrief should be good" are rejected.

Examples that work:

- `"slack_message.body contains >= 5 bullet lines starting with '- '"`
- `"notion_page.properties.SPICED is not empty"`
- `"output.html contains <button id='send_email'>"`
- `"coworker_logs.events contains a tool_use for 'slack.send_message'"`

Examples that don't:

- `"the agent should be helpful"`
- `"good quality output"`
- `"as expected"`

If a criterion can't be made machine-checkable, push it into `stopHumanCheckpoints` and accept that the test loop will pause for human eyes.

### 5. testPayloads always include `[MODE TEST]`

Per rule #19 of [build-agents-for-bap](../build-agents-for-bap/SKILL.md), multi-step coworkers stall without a test sentinel. Every `testPayloads[].userInput` must contain the literal `[MODE TEST]` marker, which the generated coworker prompt is required to honour by running all phases back-to-back without pausing.

Provide 1 happy path + 1 degenerate input (missing required field, short input, edge case). Three payloads max; more is diminishing returns for the test loop budget.

### 6. stopHumanCheckpoints declare the unavoidable human bind

Two cases always produce a checkpoint:

- The agent calls `build-mcp-for-bap` and a freshly deployed MCP needs to be pasted into Bap's workspace MCP settings (no programmatic API for this yet).
- The agent sends an irreversible external action (email to a real address, Slack post in a real channel, payment, signed PDF). The test loop will pause before that step and wait for human go.

Mark them explicitly so [bap-coworker-test-loop](../bap-coworker-test-loop/SKILL.md) and the human harness know where to gate.

### 7. Confidence is honest, not optimistic

`confidence` is a float in [0.0, 1.0]. Below 0.6 means "the transcript doesn't really support this agent, but it's the closest signal I have". The orchestrator skips agents below 0.5 by default. Set it based on:

- How explicit the user was about wanting this workflow automated (+ 0.3 if directly stated)
- How clearly the steps were described (+ 0.2 if step-by-step described in manual process)
- How many of the needed tools are already wired (+ 0.1 per known integration)
- Penalty for ambiguity in success criteria (- 0.2 if half are non-checkable)

### 8. Quote your evidence

Every agent must come with at least one `evidence` entry: a quote from the transcript (verbatim) + the speaker + an approximate timestamp. This is what lets a human inspector decide "yes this is what they asked for" in seconds.

If the transcript is non-timestamped, leave `timestampApprox` as an empty string and use the position in the transcript ("first third" / "near the end").

### 9. Platform fit — what Bap is and is not designed for

Before emitting an agent, sanity-check that the workflow matches what Bap (Heybap) was built for. Bap is a coworker platform: each coworker runs scheduled or human-triggered turns, reads structured inputs, calls wired tools, and produces structured outputs. It is not general-purpose AI infrastructure, and it is not a hosting platform for arbitrary products. Mismatched asks should go to `discardedCandidates` with a one-line note, not become low-confidence agents.

**Bap is strong at, build the agent:**

- **Structured, repeatable workflows.** Inputs and outputs can be enumerated up front (a transcript → a CRM update; a calendar event → a prep brief; a ticket → a categorised reply draft). One run = one well-defined turn.
- **Wrap-up / post-event automation.** "Event happened, now do the N things a human used to do" — call ended, ticket created, doc signed, email received. The event is the trigger, the manual steps are the agent.
- **Read-heavy CRM / docs / messaging chores.** Pull from one or two sources, transform, write to one or two destinations. Native integrations cover Slack, Gmail, Outlook, Notion, Linear, Airtable, Salesforce, HubSpot, Dynamics, LinkedIn, Google Calendar/Docs/Sheets/Drive, GitHub. Anything in this list is effectively free.
- **Human-in-the-loop validation panels.** Generate a draft (email, ticket, summary, devis), surface it in the agentic-app panel (`/app/output.html`) with Send/Edit/Cancel buttons, the human decides in a click, the agent acts on the decision. This is the dominant production pattern; lean toward it whenever the agent's output is "a message to a human" rather than "a row in a system".
- **Async background work measured in seconds to minutes.** Transcription, doc parsing, image generation, multi-step batch jobs taking 1–10 min per run.
- **Scheduled batch jobs.** Daily digests, weekly pipelines, hourly polling of a source — `schedule: {type: daily|weekly|interval...}` is first-class.

**Bap is not designed for (push to `discardedCandidates` with reason):**

- **Live, low-latency interaction loops.** Live transcription during a call, live "next-best-action" prompts whispering to an advisor while the customer is still on the phone, real-time co-pilots reacting under one second. Bap is turn-based async; sub-second response loops belong on a different stack (browser SDK, telephony platform, dedicated streaming AI service).
- **Voice-to-voice or telephony-driven workflows.** Autonomous outbound calling, IVR replacement, in-call voice agents that take the call themselves. No native telephony, no voice synthesis loop, no PSTN integration. Refer the prospect to a voice-AI vendor (Vapi, Retell, ElevenLabs Conversational AI directly) and have Bap pick up post-call from the transcript instead. When a transcript surfaces this need, the right output is a wrap-up agent (always feasible) plus an `ambiguities[]` entry pointing at the voice platform of record.
- **Hosted dashboards and BI surfaces.** Real-time charts with manager logins, drill-downs, embedded report viewers. Bap can compose a daily digest and post it to Slack, write metrics to a Notion page, or produce an HTML snapshot, but it does not host a BI product. Looker, Metabase, Tableau, the client's existing BI is where dashboards live.
- **Full-product replacements.** "Build us a custom CRM / a Salesforce clone / our internal ticketing tool / our pricing engine". Bap automates *inside* existing tools; it does not replace them. The Concentrix Jean-Marc case is the canonical anti-pattern: a transcript asked for a 50-page custom CRM, the correct output was `discardedCandidates`, not a 200-step agent.
- **Anything that needs an SDK in the client's own app.** Browser extensions, mobile-app embeds, in-product chat widgets. Bap is server-side; the client's app does not call Bap, Bap calls the client's APIs.
- **High-frequency or per-keystroke automations.** Anything firing more than ~1×/minute per workflow strains the orchestration model. Batch them or move them downstream.
- **Unstructured "creative writing" loops with no contract.** "Be my brainstorming partner" / "help me think" / "iterate freely with me until I'm happy". A coworker needs a defined output and a defined success criterion. Open-ended chat without a contract = use the chat UI, not a coworker.

**Heuristic, one sentence.** If the workflow is *"an event happens, here are the structured steps a human used to do, run them and write to system X"*, build it. If it's *"a person needs help in real time"* or *"we want a tool we don't have today"*, refer the prospect elsewhere or scope it down to a Bap-shaped sub-workflow first.

**Telephony-adjacent (recurring case).** Sales/support call workflows on Bap should look like: *post-call transcript arrives → coworker reads, summarises, updates CRM, drafts follow-up*. They should not look like: *coworker takes the call*. Multi-channel follow-up campaigns are Bap-shaped only when the channels have native integrations (email/Gmail/Outlook = yes); WhatsApp/SMS need a custom MCP build + human bind in the workspace UI and should be scoped explicitly (see `transcript-to-bap-coworker` step 2b human stop).

**Multi-agent decomposition.** If the prospect's wish list contains a wide net ("auto summary + CRM update + insights + follow-up + voice triage + dashboard"), do not emit one super-agent. Decompose:

- Group items that share trigger + input + destination into one coworker (a "wrap-up" coworker that summarises, extracts insights, and writes them all to the same Salesforce case is *one* workflow).
- Separate items that have a different trigger or a different human in the loop (a "follow-up email drip with human validation" is a different coworker from the wrap-up — different trigger, different operator, different UX).
- Discard items that fail this platform-fit check.

Document the decomposition logic in `transcriptSummary` so the human inspector sees why N became M.

## Invocation patterns

### Direct, from Claude Code

```
@parse-transcript-to-agent-spec
transcript: "<paste or path:/tmp/grain-export.txt>"
context: { prospect: "Concentrix", callType: "discovery" }
```

The skill writes the JSON to `/tmp/agent-spec-<timestamp>.json` (or stdout if the caller wants inline). Always write to disk too: the downstream skills want a stable path.

### From the `transcript-to-bap-coworker` orchestrator

The orchestrator calls this skill as step 1, validates the output against the JSON schema, and only proceeds to step 2 (MCP decision) if at least one agent has `confidence >= 0.5`. Lower-confidence agents are surfaced to the human but not auto-built.

### From a coworker on Bap (advanced)

You can install this skill on Bap via `mcp__bap__skill_add` and let a meta-coworker (`@agent-builder`) invoke it. In that setup, the coworker's `prompt` instructs it to call the skill, then chain to `transcript-to-bap-coworker`. This is the path that closes the "finish a call, walk out with the agents" loop discussed in the J13 daily sync.

## Validation

After producing the JSON, run two checks before returning:

1. **Schema check.** Required fields present on every agent, types correct, `successCriteria[].check` non-empty strings, `testPayloads[].userInput` contains `[MODE TEST]`.
2. **Self-consistency.** Every `successCriteria[].id` referenced in `outputs[].successCriteriaRef` exists. Every `testPayloads[].expectedOutcomes` references existing `successCriteria` ids. Every `steps[].tool` is declared in `neededTools[]`.

On failure, return a `validationErrors` array at the top level and refuse to emit `agents[]`. The orchestrator treats a non-empty `validationErrors` as a hard stop.

## Fallbacks when info is missing

The transcript will not have everything. Default behaviour:

| Missing | Fallback |
|---------|----------|
| `triggers` | `[{ type: "manual", userInputPrompt: "..." }]` with the prompt inferred from `inputs` |
| `model` | `openai/gpt-5.5` (per rule #8 of `build-agents-for-bap`) |
| `authSource` | `shared` |
| `requiresUserInput` | `true` if `inputs[].source` includes `userInput`, else `false` |
| `estimatedRunDurationSeconds` | 60 if all-native tools, 180 if any MCP call, 300 if transcription / image generation involved |
| `confidence` | Start at 0.5, adjust per rule 7 |

If `goal` or `steps[]` can't be derived at all, do not emit the agent. Push it to `ambiguities[]` with `needHumanDecision: true` and the exact question to ask.

## Anti-patterns

- Emitting an agent for every wish in the transcript. The transcript usually contains aspirations the user does not actually want automated yet. Filter to repeatable, owned-by-someone workflows.
- Inventing `steps[]` the user did not describe. If the manual process is missing, say so in `ambiguities`.
- Writing prose in `description` or `goal`. One sentence, action verb, measurable result.
- Skipping `evidence` quotes. Without them, the human inspector cannot verify and the orchestrator cannot defend the choice.
- Putting `[MODE TEST]` only in some payloads. All testPayloads must include it; the test loop relies on this contract.
- Marking an agent `confidence: 0.9` because it sounds nice. Confidence is based on how *explicit* the transcript was, not how plausible the agent feels.
- Forcing a voice-triage / live-copilot / BI-dashboard ask into a low-confidence agent because "we can try". Rule #9 — these belong in `discardedCandidates` with a one-line platform-fit reason and (optionally) an `ambiguities[]` entry pointing at the right downstream platform.
- Emitting one super-agent for "summary + CRM + insights + follow-up + dashboard". Decompose per rule #9: group items that share trigger + input + destination, separate items that have a different trigger or different human in the loop, discard items that fail platform fit.

## Report HeyBap bugs and feature gaps

This skill reads transcripts in a way that surfaces what the platform *cannot* do today. Every time you encounter a HeyBap capability gap or a misbehaviour, invoke [bap-finding-router](../bap-finding-router/SKILL.md). The router classifies the finding (SIMPLE vs COMPLEX) and dispatches to the right leaf: `bap-bug-report` for SIMPLE (opens a PR on `the-agentic-company/bap` and creates a Linear ticket in team `Bap` at status `In Review` linked to the PR) or `bap-feature-brainstorm` for COMPLEX (creates a Linear ticket in team `Bap` at status `Triage` with label `Need More Shaping` containing the 3-options problem statement). Linear's own integrations notify the team; no direct Slack post. One finding equals one invocation. Do not invoke `bap-bug-report` or `bap-feature-brainstorm` directly from this skill; the router is the only entry point.

Specific triggers from this skill:

- The transcript describes a workflow that needs a capability HeyBap does not expose yet (Grain webhook trigger, conditional schedule, sub-coworker spawning, sandbox-native test mode, first-class agentSpec storage). Feature request.
- A `neededTools[]` item gets classified `existing_workspace_mcp` but there is no public listing API to verify it, so you must ask the human. Feature request.
- A `neededTools[]` item that should be a native integration (Grain, Notion sub-DB routing, Linear cycle sync) is downgraded to `custom_mcp_to_build` because the integration is missing. Feature request, name the integration.
- The parser would benefit from a HeyBap-side schema for the agent spec (store the JSON on the coworker as metadata, version it, regenerate from transcript) so the orchestrator does not maintain its own `${skillFolderRoot}/<callId>/agent-spec.json`. Feature request.
- Any time the transcript references a HeyBap action you remember being broken (skill upload race, `awaiting_user_input` regression, panel not refreshing, etc.). Bug.

Do not silently downgrade into `ambiguities[]` or `discardedCandidates[]` when the real story is "the platform should let me do this". The two arrays are for legitimate scope decisions; platform gaps go through `bap-finding-router`.

## See also

- [transcript-to-bap-coworker](../transcript-to-bap-coworker/SKILL.md): the orchestrator that consumes this JSON and produces a deployed coworker.
- [bap-coworker-test-loop](../bap-coworker-test-loop/SKILL.md): the test harness that reads `successCriteria` and `testPayloads` to validate the coworker post-deploy.
- [build-agents-for-bap](../build-agents-for-bap/SKILL.md): rules the generated coworker must follow at build time. Rules #6, #8, #12, #19 are referenced directly in the schema above.
- [build-mcp-for-bap](../build-mcp-for-bap/SKILL.md): triggered when `neededTools[].kind == "custom_mcp_to_build"`.
- [bap-finding-router](../bap-finding-router/SKILL.md): single entry point for every HeyBap finding observed during parsing (see the section above).
