# lubin-skills

Field-tested skills contributed by [Lubin Danilo](https://github.com/lubindanilo) for shipping coworkers + MCPs on Bap (Heybap). Each skill captures gotchas learned from production deployments (BATIMGIE energy audits, Galien pharmacy pre-visits, `hyperstack-transcribe` MCP) that aren't documented elsewhere.

## Contents

| Skill | One-liner |
|-------|-----------|
| [`build-mcp-for-bap`](build-mcp-for-bap/SKILL.md) | Scaffold a custom HTTP MCP server (Next.js + Vercel) that satisfies Bap's OAuth 2.0 auto-approve dance. |
| [`build-agents-for-bap`](build-agents-for-bap/SKILL.md) | Ship reliable coworkers: skill design, MCP wiring, auth modes, sandbox layout, debugging via `coworker_logs`. The agent-side counterpart of `build-mcp-for-bap`. |
| [`parse-transcript-to-agent-spec`](parse-transcript-to-agent-spec/SKILL.md) | Read a sales / discovery transcript and emit a strict JSON spec describing the coworker(s) the conversation implies (goal, steps, tools, success criteria, test payloads). |
| [`bap-coworker-test-loop`](bap-coworker-test-loop/SKILL.md) | Run + observe + patch loop: `coworker_run` -> `coworker_logs` -> eval -> `coworker_update` until the coworker passes every success criterion. Supports sandbox-redirect and act-then-cleanup strategies per integration. |
| [`transcript-to-bap-coworker`](transcript-to-bap-coworker/SKILL.md) | Meta-skill that chains the four above into one pipeline: transcript -> spec -> custom MCP(s) if needed -> skill bundle -> coworker -> tested. The "finish the call, walk out with the agents live" loop. |
| [`bap-finding-router`](bap-finding-router/SKILL.md) | Single entry point for every HeyBap finding observed during the pipeline. Classifies SIMPLE vs COMPLEX, dispatches to `bap-bug-report` (PR on `the-agentic-company/bap` + Linear ticket in team `Bap` at status `In Review`) or `bap-feature-brainstorm` (Linear ticket at status `Triage` with label `Need More Shaping` carrying problem + 3 options + decision question). Linear's own integrations notify the team; no direct Slack post. |
| [`bap-bug-report`](bap-bug-report/SKILL.md) | SIMPLE leaf. Clones the bap repo, reproduces the bug live (Chrome MCP for UI), creates a Linear ticket in team `Bap` to get an identifier (`BAP-<n>`), implements the quick fix on a branch named `fix/bap-<n>-slug`, opens a PR titled `BAP-<n> <Area>: …`, then transitions the Linear ticket to `In Review` and attaches the PR. Embeds a `FINDING_CONTEXT` JSON block in the Linear ticket description for downstream verification. |
| [`bap-post-deploy-verify`](bap-post-deploy-verify/SKILL.md) | Closes the loop after a PR is merged + deployed. Three modes: A (re-run coworker, default), B (Chrome MCP visual repro), C (headless Playwright spec generated per finding and committed for permanent regression). Verdict on Pass: comments the Linear ticket and transitions it to `Live` (completed-type status). On Fail: opens a new Linear ticket via `bap-finding-router` labelled `Regression` and linked to the original via `relatedTo`. |

## How they relate

```
                   transcript-to-bap-coworker  (orchestrator)
                              |
              +---------------+----------------+
              |               |                |
              v               v                v
       parse-transcript    build-mcp        build-agents
        -to-agent-spec     -for-bap         -for-bap (reference)
              |               |                |
              +-------+-------+----------------+
                      |
                      v
              bap-coworker-test-loop
                      |
              every step may emit a finding
                      |
                      v
              bap-finding-router  (classify, dispatch)
                      |
              +-------+--------+
              |                |
              v                v
       bap-bug-report   bap-feature-brainstorm
       (Linear BAP-<n>  (Linear BAP-<n>
        at In Review     at Triage with
        + PR opened      Need More Shaping
        + FINDING_CONTEXT label, 3 options
        in ticket body)  in body)
              |
              v (after merge + deploy)
       bap-post-deploy-verify
       Mode A: re-run coworker
       Mode B: Chrome MCP visual
       Mode C: Playwright headless
              |
        +-----+------+
        v            v
    verified     regression
    (transition  (new finding ->
     ticket to    bap-finding-router,
     Live)        Regression label,
                  relatedTo original)
```

- **Tool-layer** skills: `build-mcp-for-bap` (HTTP MCP), `build-agents-for-bap` (coworker rules).
- **Pipeline** skills: `parse-transcript-to-agent-spec` (input -> structured spec), `bap-coworker-test-loop` (deployed -> validated), `transcript-to-bap-coworker` (chains everything), `bap-finding-router` (HeyBap-side feedback).

The two tool-layer skills cover the full development loop on their own; the pipeline skills automate the path from a raw call transcript to a tested live coworker, and the finding router closes the feedback loop on the HeyBap platform itself.

## How to use these in your own setup

These skills are designed to be installed in Bap as user skills via the `skill_add` MCP tool, or copied into `.agents/skills/` of an FDK fork. They reference each other (`../<other-skill>/SKILL.md`) so keep them side by side.

The pipeline skills assume:

- The `mcp__bap__*` tools are available in your runtime (Claude Code with the `bap` MCP enabled, or a meta-coworker on Bap with the skills installed and a chained prompt).
- A `test_env.yaml` is present at the FDK root (see [`test_env.example.yaml`](test_env.example.yaml)) so the test loop knows which Notion DB / Slack channel / Gmail alias to redirect to.
- For custom-MCP cases (`build-mcp-for-bap`), Vercel CLI is logged in to the org and `vercel link` will work.

## Running the full pipeline

### Manual trigger, autonomous after (one-line)

The FDK repo ships a wrapper script and a pre-approved `.claude/settings.json` so the pipeline can run end-to-end without permission prompts:

```bash
scripts/build-from-transcript.sh /tmp/grain-export.txt "Concentrix" discovery
```

Or with a Grain URL directly:

```bash
scripts/build-from-transcript.sh "https://grain.com/share/abc-123" "Eden Red"
```

Or piping inline text:

```bash
scripts/build-from-transcript.sh - "Acme" < /tmp/transcript.txt
```

The wrapper invokes `claude -p` from the FDK root, hands the transcript to `transcript-to-bap-coworker`, and the orchestrator runs the full chain autonomously. Logs land in `.run-logs/build-<timestamp>.log`.

What "autonomous after" means concretely:

- No permission prompt for any of the tools needed (`mcp__bap__*`, `mcp__Claude_in_Chrome__*`, Slack MCP, Notion MCP, Linear MCP, `gh`, `git`, `npx playwright`, `vercel`, `curl`, `jq`, etc.). The `.claude/settings.json` allowlist is shared with the team, `.claude/settings.local.json` is gitignored for personal overrides.
- HUMAN STOPs (workspace MCP bind, panel E2E click) are *documented* in the final report instead of blocking the run. `stopOnFirstHumanCheckpoint` is false in this mode.
- HeyBap findings observed during the run route through `bap-finding-router` automatically.

### Direct invocation (without the wrapper)

```
invoke transcript-to-bap-coworker
  transcript: /tmp/grain-export.txt
  context: { prospect: "Concentrix", callType: "discovery" }
  options: { maxAgents: 3, testEnvPath: "./test_env.yaml" }
```

Useful from inside a Claude Code session when you want to interact with the run as it progresses.

### Prerequisites for the autonomous run

- `claude` CLI on `$PATH` with a valid auth (`claude setup-token` or interactive login).
- `gh` CLI authenticated on the `the-agentic-company` org (`gh auth status`).
- `mcp__bap__*` MCP server enabled. The `.claude/settings.local.json` typically lists `bap-prod` (and optionally `bap-staging`, `bap-local`).
- Slack, Notion and Linear MCPs available in the workspace (already standard in Lubin's setup).
- A `test_env.yaml` at the repo root with sandbox routing (see `lubin-skills/test_env.example.yaml`).
- For Mode C of `bap-post-deploy-verify`: `npm install` inside `lubin-skills/bap-post-deploy-verify/` and a one-shot `npm run auth:bootstrap` for the HeyBap Playwright session.

The orchestrator emits a Markdown report at the end listing live coworkers, items needing human review, MCPs awaiting manual bind, and findings dispatched. The report path is logged as the last line.

## Reporting HeyBap bugs and feature gaps

Each pipeline skill (`parse-transcript-to-agent-spec`, `bap-coworker-test-loop`, `transcript-to-bap-coworker`) has a dedicated "Report HeyBap bugs and feature gaps" section that mandates invoking [`bap-finding-router`](bap-finding-router/SKILL.md) whenever a platform misbehaviour, missing API, or feature gap is observed. The router is the only entry point; the pipeline skills do not call the leaves directly.

Routing:

- **SIMPLE** (small diff, single surface, low design risk, operator confidence >= 0.8): the router dispatches to `bap-bug-report` (in `lubin-skills/bap-bug-report/`), which creates a Linear ticket in team `Bap` to claim a `BAP-<n>` identifier, clones `the-agentic-company/bap`, implements the quick fix on a branch named `fix/bap-<n>-slug`, opens a PR titled `BAP-<n> <Area>: …`, then transitions the Linear ticket to `In Review` with the PR attached. Linear's GitHub integration auto-links the branch + PR via the identifier; Linear's Slack / email notifications cover the team.
- **COMPLEX** (multi-surface, data model touched, design choice with multiple defensible answers): the router dispatches to `bap-feature-brainstorm` (in `~/.claude/skills/bap-feature-brainstorm/`), which creates a Linear ticket in team `Bap` at status `Triage` with labels `Need More Shaping` + (`Bug` or `Feature`) + `Dogfooding`, containing the problem + 3 options + decision question. The team picks on the ticket; the implementation then goes through `bap-bug-report` in a follow-up that opens its own ticket linked back to the brainstorm via `relatedTo`.

The router's classification grid is strict (lines changed, files touched, schema impact, breaking change, operator confidence). Findings that fail any criterion are COMPLEX by default; this keeps risky changes out of auto-merge territory and gives the team a chance to weigh in.

This keeps the feedback loop tight between forward-deployment work and the HeyBap roadmap. If you fork this kit and run it on your own workspace, swap the leaf skills for your own equivalents (the router contract is generic; the leaves are environment-specific).

## Closing the loop after merge

Once a PR opened by `bap-bug-report` is merged and deployed, [`bap-post-deploy-verify`](bap-post-deploy-verify/SKILL.md) goes back into HeyBap (or the bap code paths) and confirms the original finding is gone in prod. Three modes:

- **Mode A** (default): re-runs the affected coworker via `mcp__bap__coworker_run`, diffs the new logs against the original run that surfaced the finding. Cheap, deterministic, suitable for the 80% of findings that touch coworker behaviour or backend code.
- **Mode B**: drives heybap.com with the Claude-in-Chrome MCP, reproduces the finding scenario, captures before/after screenshots. Used when the finding lives in the UI.
- **Mode C**: generates and runs a headless Playwright spec under [`bap-post-deploy-verify/playwright-tests/`](bap-post-deploy-verify/playwright-tests/). One spec per finding, committed for permanent CI regression. Reuses the QA visual pattern from the operator's `li-seo` project.

On `verified`, the verifier comments the PR, labels it `post-deploy-verified`, and marks the finding closed. On `regression`, it opens a new finding (`regression after merge of #PR`) back through `bap-finding-router`. The loop is closed.

## Autonomous mode (`/loop` and `/goal`)

Three skills carry autonomous-mode sections:

- [`transcript-to-bap-coworker`](transcript-to-bap-coworker/SKILL.md) supports `/loop 30m` for steady Grain polling and `/goal "<predicate>"` for batch backfills.
- [`bap-finding-router`](bap-finding-router/SKILL.md) supports `/loop 60m` to drain a findings queue (`~/.claude/skills/bap-finding-router/queue.jsonl`) that upstream skills append to.
- [`bap-coworker-test-loop`](bap-coworker-test-loop/SKILL.md) supports `/goal` wrapping for re-entering the loop after an upstream change (typically a `bap-post-deploy-verify` Mode A pass).

A future meta-coworker `@agent-builder` scheduled on HeyBap is the natural host for these loops. See each skill's "Autonomous mode" section for the exact patterns and predicates.
