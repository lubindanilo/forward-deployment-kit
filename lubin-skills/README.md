# lubin-skills

Field-tested skills contributed by [Lubin Danilo](https://github.com/lubindanilo) for shipping coworkers + MCPs on Bap (Heybap). Each skill captures gotchas learned from production deployments (BATIMGIE energy audits, Galien pharmacy pre-visits, `hyperstack-transcribe` MCP) that aren't documented elsewhere.

## Contents

| Skill | One-liner |
|-------|-----------|
| [`build-mcp-for-bap`](build-mcp-for-bap/SKILL.md) | Reference pattern (not a pipeline stage) for scaffolding a custom HTTP MCP server (Next.js + Vercel) that satisfies Bap's OAuth 2.0 auto-approve dance. Read by the orchestrator when a tool is needed and no existing MCP fits. |
| [`build-agents-for-bap`](build-agents-for-bap/SKILL.md) | Reference rule set (24 proven coworker rules, not a pipeline stage): skill design, MCP wiring, auth modes, sandbox layout, debugging via `coworker_logs`. Read by the orchestrator before generating SKILL.md / render.py / agent prompt. The agent-side counterpart of `build-mcp-for-bap`. |
| [`build-mini-apps-for-bap`](build-mini-apps-for-bap/SKILL.md) | Reference pattern (not a pipeline stage) for INTERACTIVE mini-apps inside coworkers: pair a thin Bap skill (renders `/app/output.html` once) with an EXTERNAL backend (Vercel / Fly / Cloudflare) for live state, SSE, multi-user collaboration, long-running jobs. Reference build: `vault/projects/heybap-live-copilot/`. Read by the orchestrator before scaffolding when the parser sets `miniApp.needed = true`. |
| [`phase-1`](phase-1/SKILL.md) | Provider-agnostic Phase 1 entrypoint. Uses the active runtime: Codex runs the transcript-to-coworker pipeline directly from the FDK contracts; Claude uses the guarded wrapper adapter. Replaces provider-specific Phase 1 skills. |
| [`phase-2`](phase-2/SKILL.md) | Provider-agnostic Phase 2 entrypoint. Uses the active runtime: Codex runs the classification/clarification flow directly; Claude uses the guarded wrapper adapter. Replaces provider-specific Phase 2 skills. |
| [`parse-transcript-to-agent-spec`](parse-transcript-to-agent-spec/SKILL.md) | Read a sales / discovery transcript and emit a strict JSON spec describing the coworker(s) the conversation implies (goal, steps, tools, success criteria, test payloads). |
| [`bap-coworker-test-loop`](bap-coworker-test-loop/SKILL.md) | Run + observe + patch loop: `coworker_run` -> `coworker_logs` -> eval -> `coworker_update` until the coworker passes every success criterion. Supports sandbox-redirect and act-then-cleanup strategies per integration. |
| [`transcript-to-bap-coworker`](transcript-to-bap-coworker/SKILL.md) | Meta-skill that chains the four above into one pipeline: transcript -> spec -> custom MCP(s) if needed -> skill bundle -> coworker -> tested. The "finish the call, walk out with the agents live" loop. Also posts two status updates to the client's Slack channel via `bap-client-notify` (planned + validated). |
| [`bap-client-notify`](bap-client-notify/SKILL.md) | Client-facing Slack notifier wired into the orchestrator. Two phases: `planned` (post after the parser + tool resolver, lists the coworkers about to be built and their integrations) and `validated` (post after the test loop, lists the coworkers in production with their HeyBap URLs). Auto-resolves the prospect's channel via `slack_search_channels`; creates a public `client-<slug>` channel when none exists (Slack MCP cannot auto-invite, so Baptiste / Louis get a "invite manually" reminder in the consolidated report). Idempotent on `(callId, phase)`. |
| [`feature-bug-complexity-classification`](feature-bug-complexity-classification/SKILL.md) | Single entry point for every HeyBap finding (manual via `./go.sh bug`/`feature` or auto from a pipeline step). It first applies a clarification gate for small localized ambiguities where one operator answer would choose the SIMPLE path. Then pass 1 classifies SIMPLE vs COMPLEX, and pass 2 (COMPLEX only) splits SCOPED vs FUZZY. Dispatch: `needs-clarification` asks one question and stops; SIMPLE routes to `bap-bug-report` (PR on `the-agentic-company/bap` + Linear ticket at `In Review`, assignee Lubin); COMPLEX-SCOPED routes to `bap-feature-brainstorm` (Linear ticket at `Triage` with label `Need More Shaping`, assignee Baptiste); COMPLEX-FUZZY routes to `bap-direction-shaping` (Slack `#feature-brainstorming` post, NO Linear ticket until the team picks a direction). |
| [`bap-prior-art-scout`](bap-prior-art-scout/SKILL.md) | Before generating a new coworker / skill / MCP / panel, scan the operator's prior work for similar artefacts. 5 parallel angles: workspace coworkers (`mcp__bap__coworker_list`), past local builds (`~/HeyBap Pipeline/runs/`), vault projects (`~/Personal Agents/vault/projects/`), FDK skills, personal skills. Returns ranked matches with `reuseRecipe` and a `primaryReuse` recommendation that downstream skills bake into generation (copy + swap data binding, never structural rewrite). |
| [`bap-platform-feasibility-check`](bap-platform-feasibility-check/SKILL.md) | For every external third-party platform the new coworker would interact with (Leboncoin, Se Loger, LinkedIn, Indeed, Welcome to the Jungle, Vinted, Booking, PAP, Bien Ici, Pipedrive, ...), run 5 parallel web-research angles (official API + tier, ToS posture, community MCPs / SDKs, browser-automation feasibility, known incidents) to verify the integration is actually achievable. Returns a verdict per platform (`feasible-via-api` / `feasible-via-mcp` / `feasible-via-browser` / `legally-risky` / `infeasible`) + recommended strategy + alternatives. Stops the pipeline from burning hours on an MCP whose target platform will block it on day one. |
| [`bap-bug-report`](bap-bug-report/SKILL.md) | SIMPLE leaf. Clones the bap repo, reproduces the bug live (Chrome MCP for UI), creates a Linear ticket in team `Bap` to get an identifier (`BAP-<n>`), implements the quick fix on a branch named `fix/bap-<n>-slug`, opens a PR titled `BAP-<n> <Area>: …`, then transitions the Linear ticket to `In Review` and attaches the PR. Embeds a `FINDING_CONTEXT` JSON block in the Linear ticket description for downstream verification. |
| [`bap-direction-shaping`](bap-direction-shaping/SKILL.md) | COMPLEX-FUZZY leaf. Used when a finding is too unclear or product-direction-impacting to ticket directly (surface unknown, cross-cutting, multiple plausible products, or product-fit unclear). Produces a structured problem statement (problem + why fuzzy + possible surfaces + 3-5 open questions + origin) and posts it in Slack `#feature-brainstorming` for team discussion. No Linear ticket is created here; once the team converges on a direction, the operator re-files via the gate with the new context and it lands in Linear through the standard SIMPLE or COMPLEX-SCOPED path. |
| [`bap-post-deploy-verify`](bap-post-deploy-verify/SKILL.md) | Closes the loop after a PR is merged + deployed. Three modes: A (re-run coworker, default), B (Chrome MCP visual repro), C (headless Playwright spec generated per finding and committed for permanent regression). Verdict on Pass: comments the Linear ticket and transitions it to `Live` (completed-type status). On Fail: opens a new Linear ticket via `feature-bug-complexity-classification` labelled `Regression` and linked to the original via `relatedTo`. |
| [`bap-ticket-implementer`](bap-ticket-implementer/SKILL.md) | Autonomous loop that drains Linear tickets assigned to Lubin with label `agent-autonomous`. Reads description + comments + linked PR, runs the same 5-subagent deep-research pass as `bap-bug-report` (to confirm the fix is still applicable today), implements ≤ 120 lines on a branch, opens or updates the PR, comments the ticket with the SHA, and posts a one-liner in Slack `#pr-lubin`. Refuses on ambiguous / large / stale tickets. `/loop 30m`. |
| [`bap-favorite-coworker-watchdog`](bap-favorite-coworker-watchdog/SKILL.md) | Continuous watchdog over the operator's PRODUCTION coworkers (those marked favorite via `mcp__bap__coworker_setFavorite`). On each tick, lists favorites, pulls recent runs + logs, applies 5 anomaly checks (terminal failure, silent output drift, missing tool_use vs contract, drastic slowdown, missed schedule). Coworker-side anomalies → Slack `#agents-production`. Platform-side → Linear via `feature-bug-complexity-classification`. `/loop 60m`, escalates to @lubin on 3rd consecutive same-anomaly tick. |

## How they relate

```
  Reference patterns (READ by the orchestrator before scaffolding,
  NOT pipeline stages — they're playbooks the orchestrator consults
  to scaffold correctly):

       build-mcp-for-bap        (HTTP MCP playbook, OAuth 2.0 auto-approve)
       build-agents-for-bap     (24 proven coworker rules)
       build-mini-apps-for-bap  (panel + external backend pattern,
                                 read when miniApp.needed = true)


  Pipeline (stages, chained):

              transcript-to-bap-coworker  (orchestrator)
                      |
                      v
              parse-transcript-to-agent-spec
                      |
                      v
              bap-prior-art-scout  (5 subagents parallel: workspace
              coworkers + past builds + vault projects + FDK + personal
              skills, returns reuse anchors)
                      |
                      v
              bap-platform-feasibility-check  (5 subagents web parallel:
              API + ToS + community MCPs + browser automation + known
              incidents. HUMAN STOP on legally-risky / infeasible)
                      |
                      v
              orchestrator scaffolds (SKILL.md + render.py + /app/output.html)
              by APPLYING the 3 reference patterns above, then runs
              skill_add + coworker_create + coworker_update
                      |
                      v
              bap-coworker-test-loop  (run -> log -> eval -> update, up to 5x)
                      |
                      v
              bap-client-notify  (planned + validated)
              two Slack posts to the prospect's channel:
              after tool resolution (what we will build + which integrations)
              after test loop pass (live coworkers + heybap URLs)
              auto-search channel, auto-create #client-<slug> if missing
                      |
                      v
              @coworker live on Bap  (+ report + outputs)


  ==== HeyBap-side feedback (any step above may emit a finding) ====
                      |
                      v
              feature-bug-complexity-classification  (clarify, classify, dispatch)
                      |
              +-------+--------+----------------+
              |                |                |
              v                v                v
       bap-bug-report   bap-feature-     bap-direction-shaping
       (SIMPLE)         brainstorm       (COMPLEX-FUZZY)
       Linear BAP-<n>   (COMPLEX-        Slack #feature-brainstorming
        at In Review,    SCOPED)         post: problem + open
        assignee Lubin,  Linear BAP-<n>  questions + origin.
        + PR opened      at Triage,      NO Linear ticket.
        + FINDING_CONTEXT Need More       Off-ramp until team
        bug OR feature   Shaping label,  converges on direction.
                         Impact + 3      Then re-file via gate.
                         options in body
                         (Impact step
                          quantifies
                          demand: scans
                          Grain corpus +
                          past builds),
                         assignee Baptiste
              |
              v
       bap-ticket-implementer  (/loop 30m, autonomous)
       drains SIMPLE Linear tickets with label `agent-autonomous`:
       reads ticket, 5-subagent research pass, implements <= 120 lines,
       opens / updates PR, comments ticket, posts in Slack #pr-lubin
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
     ticket to    feature-bug-complexity-classification,
     Live)        Regression label,
                  relatedTo original)


  Continuous side-loop (parallel to everything else):

       bap-favorite-coworker-watchdog  (/loop 60m)
       lists @coworkers marked favorite (= in prod),
       5 anomaly checks on recent runs/logs,
       coworker-side issues -> Slack #agents-production,
       platform-side issues -> Linear via
       feature-bug-complexity-classification.
       3rd consecutive same-anomaly tick: @lubin mention.
```

- **Reference patterns** (read before scaffolding, NOT pipeline stages): `build-mcp-for-bap` (HTTP MCP playbook), `build-agents-for-bap` (24 coworker rules), `build-mini-apps-for-bap` (interactive panel + external backend pattern). The orchestrator consults these like docs to scaffold correctly.
- **Pipeline stages**: `parse-transcript-to-agent-spec` (input -> structured spec), `bap-prior-art-scout` (reuse anchors), `bap-platform-feasibility-check` (external platform feasibility), `bap-coworker-test-loop` (deployed -> validated), `transcript-to-bap-coworker` (chains the stages and applies the patterns), `feature-bug-complexity-classification` (HeyBap-side feedback gate).
- **Autonomous loops**: `bap-ticket-implementer` (`/loop 30m`, drains tagged Linear tickets), `bap-favorite-coworker-watchdog` (`/loop 60m`, monitors production coworkers).

The three reference patterns describe HOW to build a coworker correctly (MCP scaffolding, 24 rules, mini-app shape); the pipeline stages automate the path from a raw call transcript or operator brief to a tested live coworker by applying those patterns; the complexity-classification gate closes the feedback loop on the HeyBap platform itself; the autonomous loops run in parallel to drain the backlog and catch production drift before clients notice.

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

Or a free-form **operator brief** (first-person spec, no need for a real call):

```bash
echo "Je veux un coworker qui parse mes leads CSV chaque matin et écrit le récap dans Notion" \
  | FDK_INPUT_MODE=brief scripts/build-from-transcript.sh - "" brief
```

The wrapper invokes `claude -p` from the FDK root, hands the input to `transcript-to-bap-coworker`, and the orchestrator runs the full chain autonomously. The parser auto-detects whether the input is a transcript (multi-speaker dialogue, Grain URL) or a brief (first-person operator voice without speaker labels). Force the mode with `FDK_INPUT_MODE=transcript|brief|auto` (default auto). Logs land in `.run-logs/build-<timestamp>.log`.

### Live dashboard (auto-launched)

The wrapper auto-starts a local monitor on `http://localhost:7777` and opens it in the default browser. The dashboard shows, in real time:

- **Pipeline runs** (per `callId`): prospect, current step state (parse / resolve-tools / mcps / skills-upload / coworkers / report), agent fleet with status badges (live / testing / planned / handoff), ambiguity counters.
- **Generated outputs**: thumbnails of every `/app/output.html` template the pipeline emitted, embedded as sandboxed iframes (one card per coworker).
- **Linear tickets** in team `Bap` with label `Dogfooding`, color-coded by state (Triage / In Review / Live / Regression). Requires `LINEAR_API_KEY` in env; without it the panel shows a disabled notice and the rest of the dashboard still works.
- **Run logs**: a tail of the most recent `.run-logs/build-*.log` color-coded by level.

Skip the dashboard with `FDK_SKIP_DASHBOARD=1`. Run it standalone with `scripts/dashboard.sh`; stop it with `kill $(cat .run-logs/monitor.pid)`. The monitor is Python 3 stdlib only (no pip install needed).

What "autonomous after" means concretely:

- No permission prompt for any of the tools needed (`mcp__bap__*`, `mcp__Claude_in_Chrome__*`, Slack MCP, Notion MCP, Linear MCP, `gh`, `git`, `npx playwright`, `vercel`, `curl`, `jq`, etc.). The `.claude/settings.json` allowlist is shared with the team, `.claude/settings.local.json` is gitignored for personal overrides.
- HUMAN STOPs (workspace MCP bind, panel E2E click) are *documented* in the final report instead of blocking the run. `stopOnFirstHumanCheckpoint` is false in this mode.
- HeyBap findings observed during the run route through `feature-bug-complexity-classification` automatically.

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

Each pipeline skill (`parse-transcript-to-agent-spec`, `bap-coworker-test-loop`, `transcript-to-bap-coworker`) has a dedicated "Report HeyBap bugs and feature gaps" section that mandates invoking [`feature-bug-complexity-classification`](feature-bug-complexity-classification/SKILL.md) whenever a platform misbehaviour, missing API, or feature gap is observed. The router is the only entry point; the pipeline skills do not call the leaves directly.

Routing:

- **NEEDS-CLARIFICATION** (localized surface, likely small diff, but one operator-intent answer is needed to choose the path): the router asks one concise question and stops before Linear, Slack, PR, or artifact work. The operator re-runs Phase 2 with the clarified one-liner.
- **SIMPLE** (small diff, single surface, low design risk, operator confidence >= 0.8): the router dispatches to `bap-bug-report` (in `lubin-skills/bap-bug-report/`), which creates a Linear ticket in team `Bap` to claim a `BAP-<n>` identifier, clones `the-agentic-company/bap`, implements the quick fix on a branch named `fix/bap-<n>-slug`, opens a PR titled `BAP-<n> <Area>: …`, then transitions the Linear ticket to `In Review` with the PR attached. Linear's GitHub integration auto-links the branch + PR via the identifier; Linear's Slack / email notifications cover the team.
- **COMPLEX-SCOPED** (multi-surface OR design choice with multiple defensible answers, BUT the surface is known and the change is genuinely ticketable): the router dispatches to `bap-feature-brainstorm` (in `~/.claude/skills/bap-feature-brainstorm/`), which creates a Linear ticket in team `Bap` at status `Triage` with labels `Need More Shaping` + (`Bug` or `Feature`) + `Dogfooding`, containing the problem + 3 options + decision question. Assignee Baptiste (CTO drives the design choice). **Terminal in this dispatch**: no PR is opened, no tests are written, no `bap-post-deploy-verify` runs. The pipeline stops at the Linear ticket. Once Baptiste decides, a follow-up SIMPLE ticket is opened (manually or via a re-file through the gate) and goes through `bap-bug-report` for the actual implementation, linked back to the brainstorm ticket via `relatedTo`.
- **COMPLEX-FUZZY** (surface unknown, cross-cutting >2 major surfaces, multiple plausible products with no obvious winner, or product-fit unclear — at least TWO criteria triggered): the router dispatches to `bap-direction-shaping` (in `lubin-skills/bap-direction-shaping/`), which posts a structured problem statement in Slack `#feature-brainstorming` (problem + why fuzzy + possible surfaces + 3-5 open questions + origin). **No Linear ticket is created at this stage**. The team discusses; once they converge on a direction, someone re-files the finding via the gate with the added context and it lands in Linear through the SIMPLE or COMPLEX-SCOPED path.

The router's classification grid is strict (lines changed, files touched, schema impact, breaking change, operator confidence), but it first checks whether a small localized ambiguity can be resolved by one operator answer. Findings that still fail any SIMPLE criterion after that gate are COMPLEX by default; from there a second pass decides SCOPED vs FUZZY. Single-criterion fuzziness falls back to SCOPED (better to over-ticket than under-discuss); two or more fuzziness criteria triggers FUZZY.

This keeps the feedback loop tight between forward-deployment work and the HeyBap roadmap. If you fork this kit and run it on your own workspace, swap the leaf skills for your own equivalents (the router contract is generic; the leaves are environment-specific).

## Closing the loop after merge

Once a PR opened by `bap-bug-report` is merged and deployed, [`bap-post-deploy-verify`](bap-post-deploy-verify/SKILL.md) goes back into HeyBap (or the bap code paths) and confirms the original finding is gone in prod. Three modes:

- **Mode A** (default): re-runs the affected coworker via `mcp__bap__coworker_run`, diffs the new logs against the original run that surfaced the finding. Cheap, deterministic, suitable for the 80% of findings that touch coworker behaviour or backend code.
- **Mode B**: drives heybap.com with the Claude-in-Chrome MCP, reproduces the finding scenario, captures before/after screenshots. Used when the finding lives in the UI.
- **Mode C**: generates and runs a headless Playwright spec under [`bap-post-deploy-verify/playwright-tests/`](bap-post-deploy-verify/playwright-tests/). One spec per finding, committed for permanent CI regression. Reuses the QA visual pattern from the operator's `li-seo` project.

On `verified`, the verifier comments the PR, labels it `post-deploy-verified`, and marks the finding closed. On `regression`, it opens a new finding (`regression after merge of #PR`) back through `feature-bug-complexity-classification`. The loop is closed.

## Autonomous mode (`/loop` and `/goal`)

Three skills carry autonomous-mode sections:

- [`transcript-to-bap-coworker`](transcript-to-bap-coworker/SKILL.md) supports `/loop 30m` for steady Grain polling and `/goal "<predicate>"` for batch backfills.
- [`feature-bug-complexity-classification`](feature-bug-complexity-classification/SKILL.md) supports `/loop 60m` to drain a findings queue (`~/.claude/skills/feature-bug-complexity-classification/queue.jsonl`) that upstream skills append to.
- [`bap-coworker-test-loop`](bap-coworker-test-loop/SKILL.md) supports `/goal` wrapping for re-entering the loop after an upstream change (typically a `bap-post-deploy-verify` Mode A pass).

A future meta-coworker `@agent-builder` scheduled on HeyBap is the natural host for these loops. See each skill's "Autonomous mode" section for the exact patterns and predicates.
