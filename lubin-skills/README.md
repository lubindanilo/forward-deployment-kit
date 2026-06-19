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
| [`bap-finding-router`](bap-finding-router/SKILL.md) | Single entry point for every HeyBap finding observed during the pipeline. Classifies SIMPLE vs COMPLEX, dispatches to `bap-bug-report` (PR on `the-agentic-company/bap` + notification in `#technical-pr`) or `bap-feature-brainstorm` (3 options + decision question in `#brainstorming-produit`). The leaves live under `~/.claude/skills/`. |

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
       (PR + Slack)     (3 options + Slack)
        ~/.claude/        ~/.claude/
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

From Claude Code, with a transcript in `/tmp/grain-export.txt`:

```
invoke transcript-to-bap-coworker
  transcript: /tmp/grain-export.txt
  context: { prospect: "Concentrix", callType: "discovery" }
  options: { maxAgents: 3, testEnvPath: "./test_env.yaml" }
```

The orchestrator emits a Markdown report at the end listing live coworkers, items needing human review, and any MCP that needs manual UI binding (Bap currently has no programmatic API for that step).

## Reporting HeyBap bugs and feature gaps

Each pipeline skill (`parse-transcript-to-agent-spec`, `bap-coworker-test-loop`, `transcript-to-bap-coworker`) has a dedicated "Report HeyBap bugs and feature gaps" section that mandates invoking [`bap-finding-router`](bap-finding-router/SKILL.md) whenever a platform misbehaviour, missing API, or feature gap is observed. The router is the only entry point; the pipeline skills do not call the leaves directly.

Routing:

- **SIMPLE** (small diff, single surface, low design risk, operator confidence >= 0.8): the router dispatches to `bap-bug-report` (in `~/.claude/skills/bap-bug-report/`), which clones `the-agentic-company/bap`, implements the quick fix on a branch, opens a PR, and posts a short notification in `#technical-pr` with @Baptiste pinged.
- **COMPLEX** (multi-surface, data model touched, design choice with multiple defensible answers): the router dispatches to `bap-feature-brainstorm` (in `~/.claude/skills/bap-feature-brainstorm/`), which posts problem + 3 options + decision question in `#brainstorming-produit`. The team picks; the implementation then goes through `bap-bug-report` in a follow-up.

The router's classification grid is strict (lines changed, files touched, schema impact, breaking change, operator confidence). Findings that fail any criterion are COMPLEX by default; this keeps risky changes out of auto-merge territory and gives the team a chance to weigh in.

This keeps the feedback loop tight between forward-deployment work and the HeyBap roadmap. If you fork this kit and run it on your own workspace, swap the leaf skills for your own equivalents (the router contract is generic; the leaves are environment-specific).
