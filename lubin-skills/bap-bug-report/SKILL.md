---
name: bap-bug-report
description: |
  Deeply analyse a bug or feature request in the Bap repo
  (the-agentic-company/bap). Investigation is **mandatory and exhaustive**:
  Step 3 fans out 5 parallel subagents (Agent tool, general-purpose / Explore)
  over symptom-to-root-cause walk, caller graph, adjacent implementations,
  test contract, and git history before any code is written. Step 4
  enumerates 2 to 3 grounded alternatives and picks the one that
  minimises new code (reuse existing abstractions, no new files,
  additive over contract-modifying). Then implements the smallest fix
  on a branch, opens a Pull Request, and creates a Linear ticket in
  team `Bap` (key BAP) at status `In Review`, labelled `Bug` (or
  `Feature`) + `Dogfooding`, assigned to the operator (Lubin), with the
  PR attached as a link. Then posts a structured message in Slack `#pr-lubin`
  with the original problem, the fix applied, and an `@Baptiste` ping
  asking for review. Use when the user
  describes a bug or feature gap in Bap / HeyBap (chat, coworker output,
  attachments, MCP, skills UI, run flow…) and wants the best-shaped fix
  proposed as a PR + a tracked Linear ticket without manual copy-paste.
  Triggers: "Bug: …", "Feature: …", "ouvre un ticket pour …",
  "open a PR for …", "audit the bug …".
  **Do not invoke directly.** This skill is a leaf of the Phase 2 dispatch.
  Route through `feature-bug-complexity-classification` (or the `/phase-2`
  slash command, or `scripts/submit-finding.sh`). Direct invocation skips
  the classification grid (SIMPLE vs COMPLEX-SCOPED vs COMPLEX-FUZZY),
  which silently produces wrong routing. The only exception is an
  explicit operator override.
---

# Bap bug / feature → PR + Linear ticket

Goal: the user gives a short one-line bug or feature description; you investigate the Bap codebase in depth; you **create a Linear ticket in team `Bap` first to obtain its identifier (e.g. `BAP-123`), then implement the fix on a branch in `the-agentic-company/bap`, open a Pull Request that references the ticket identifier in its title, and update the Linear ticket to status `In Review` with the PR attached as a link**.

The Linear ticket is the durable report. A follow-up `#pr-lubin` Slack message restates the problem, summarises the fix, and pings Baptiste so the review request lands in his Slack inbox (the surface he watches).

## Repo & context (always)

- GitHub: https://github.com/the-agentic-company/bap
- Owner: `the-agentic-company`.
- CTO: Baptiste. The user (Lubin) is Chief of Staff at Hyperstack/CmdClaw and uses Bap heavily as a power user.
- Linear team: **Bap** (key `BAP`), workspace `heybap` (https://linear.app/heybap).
- Codebase layout (monorepo):
  - `apps/web/` — Next.js frontend (chat, coworker UIs, prompt bar, attachments, settings).
  - `packages/core/` — server services (sandbox, file service, orpc routers like `generation.startGeneration`, `coworker.trigger`).
  - Two recurring UI surfaces matter and are often asymmetric:
    1. **Chat panel** (`apps/web/src/components/chat/…`).
    2. **Coworker run output** (`apps/web/src/routes/agents/-components/coworker-info-panels.tsx`) + the prototype variant `apps/web/src/routes/prototype/coworker/info/-components/coworker-info-prototype.tsx`.
  - MIME validation for skill / coworker documents: `apps/web/src/server/storage/validation.ts` (separate from chat attachments).
  - Sandbox file limit: `packages/core/src/server/services/sandbox-file-service.ts`.
- PR conventions on this repo (look at recent merged PRs to confirm):
  - Title format: `<Area>: <verb> <object>` (e.g. `Web: fix coworker builder chat scrolling`, `Sandbox: fix coworker APP_URL sync`, `Skills: enable imports by default`). With this skill the title is prefixed with the Linear identifier: `BAP-123 Web: fix coworker builder chat scrolling`.
  - Branch format: `fix/<slug>` for bugs, `feat/<slug>` for features, with the Linear identifier in the slug: `fix/bap-123-chat-scrolling`. Linear's GitHub integration auto-detects either form.
  - Default branch is `main`.

## Step 1 — get a fresh local clone

Check first whether a recent clone already exists:

```bash
ls -d /tmp/bap-* 2>/dev/null
```

If yes, `cd` in and `git fetch origin && git checkout main && git pull`. Otherwise:

```bash
gh repo clone the-agentic-company/bap /tmp/bap-bug-$(date +%s)
```

The local clone is mandatory: this skill writes a fix on a branch and pushes it.

## Step 2 — reproduce the bug live in Chrome (preferred) or Playwright (fallback)

For any UI / UX / layout / interaction / visual bug, **reproduce the issue live and capture a "before" screenshot before concluding**. Static code reading alone misses half the picture (overflow, z-index, layout collapse, hover states, transition glitches, race conditions on load).

**Primary path — Chrome MCP (Claude in Chrome extension).** The operator (Lubin) keeps a Chrome browser signed in on `http://localhost:3000` against his own dev server running out of `<config.local_dev.bap_main_checkout>` (`/Users/lubin.danilo/bap/bap` by default). The skill drives that browser directly — no auth fixture needed, no headless context. This is the path to use whenever the dev stack is up and the Chrome MCP server is reachable.

Pre-conditions:

1. `curl -sf -o /dev/null -w "%{http_code}" <config.local_dev.dev_server_url>` returns `200`. If not, ask the operator to start the dev stack (`docker compose -f docker/compose/dev.yml up -d` + `bun run dev` from `<config.local_dev.bap_main_checkout>`) and re-poll. If still down after the prompt, fall back to Playwright (next subsection).
2. Operator's main checkout is on a branch where the bug reproduces (usually `main`). Probe with `git -C <config.local_dev.bap_main_checkout> rev-parse --abbrev-ref HEAD`. If the current branch is not `main` and the bug requires `main`, ask before any switch — never mutate the operator's working tree at this step.

Chrome MCP repro flow:

```
mcp__Claude_in_Chrome__navigate({ url: "<config.local_dev.dev_server_url>/<bug-path>" })
mcp__Claude_in_Chrome__screenshot({ })  // wide shot of the broken surface
# Save the returned image bytes (base64 in the tool result) to ~/HeyBap Pipeline/artifacts/BAP-<n>/before.png
mcp__Claude_in_Chrome__read_console_messages({ })    // silent JS errors
mcp__Claude_in_Chrome__read_network_requests({ })    // 4xx / 5xx / unexpected payloads
mcp__Claude_in_Chrome__get_page_text({ })            // anchor the symptom in plain text (a missing toast, a wrong redirect target, etc.)
```

When the bug requires interaction (click, type, drag) to surface, drive it via `mcp__Claude_in_Chrome__computer` / `mcp__Claude_in_Chrome__form_input` BEFORE the screenshot. The screenshot must show the bug, not just the page on which it would happen.

Record three artefacts:

- `evidence.symptomAssertion` — one sentence describing what to LOOK FOR to know the bug is present (e.g. "the workspace switch lands on `/` instead of `/agents`", "the dropzone shows a red error toast 'fichier trop volumineux'", "the chat input's send button stays disabled"). Step 7.5 will use this verbatim to assert the symptom is GONE after the fix.
- `evidence.symptomObserved` — what Chrome actually showed during this repro (URL, visible text, console line, network response). Confirms the assertion is grounded.
- `evidence.screenshots[]` with `{ kind: "before", path: "~/HeyBap Pipeline/artifacts/BAP-<n>/before.png" }`.

**Fallback path — Playwright (autonomous loop only).** When Chrome MCP is unavailable (operator AFK, extension disconnected, Phase 2 running headless via `claude -p` without a live browser), fall back to the Playwright snippet below. It uses headless chromium against the same `localhost:3000` and an auth fixture (`apps/web/tests/e2e/fixtures/*` or `storage-state.json`):

```ts
import { chromium } from "@playwright/test"
const url = "http://localhost:3000/agents/info/<slug>"
const out = "/Users/lubin.danilo/HeyBap Pipeline/artifacts/BAP-<n>/before.png"
const browser = await chromium.launch()
const ctx = await browser.newContext({ storageState: "storage-state.json" })
const page = await ctx.newPage()
page.on("console", m => console.log("console:", m.type(), m.text()))
page.on("requestfailed", r => console.log("requestfailed:", r.url(), r.failure()?.errorText))
await page.goto(url)
await page.waitForLoadState("networkidle")
await page.screenshot({ path: out, fullPage: true })
await browser.close()
```

Record `evidence.verifyMode: "chrome-mcp" | "playwright"` so Step 7.5 mirrors the same path.

Skip the live repro only for purely backend / non-visual bugs (schema migration, MCP server, log-only). Set `evidence.verifyMode = "skipped"` with a one-line justification in the Linear ticket; Step 7.5 then does API-level verification instead of UI verification.

The visual evidence refines the diagnosis. It does not replace the code-level root cause.

## Step 3 — deep codebase research (mandatory, fan out before fixing)

**Non-negotiable.** Picking the first plausible fix and shipping is the failure mode this step exists to prevent. The goal is to find the *best* way to fix the bug or build the feature, with the smallest blast radius and zero new regressions. The first idea is rarely the best one; the codebase usually contains an existing pattern that fits and reusing it beats inventing a new one.

Run this step in **parallel** via the Agent tool. Launch the angles below as separate subagents in a single message (one `general-purpose` or `Explore` agent per angle, briefed self-contained). Each subagent returns a structured report with `file:line` evidence for every claim. The skill aggregates the reports and only then proceeds to Step 4.

### Mandatory angles (each is one subagent)

1. **Symptom → root cause walk.** Start at the symptom (the file the user sees breaking, the failing log line, the missing toast). Trace **backwards** through the call graph until you reach a function whose return value or side effect *fully explains* the symptom. Stop at "this is the line that does it", not at "this looks suspicious". Output: an ordered chain of `file:line` references from symptom to root cause, each with one sentence on what it does.

2. **Caller graph of the change site.** Find every place that calls the function / reads the constant / depends on the behaviour you are about to change. Use `rg`, `ast-grep` if installed, or LSP if Bap is open in an editor. For each caller, note whether the proposed change would break its current contract. **A fix that updates one site and breaks three others is not a fix.**

3. **Adjacent implementations.** Find 2 to 3 places in the same repo where a *similar problem was already solved* (similar shape, different domain). Examples: another orpc router that solves the same validation pattern, another component that already wires the missing listener, another service that already handles the size limit you are about to lift. These are the templates. If none exists, say so explicitly; that is itself a signal that the change is novel.

4. **Test contract.** List every test file under `apps/*/test/`, `packages/*/test/`, `__tests__/`, or matching `*.spec.*` / `*.test.*` that touches the change site or one of its callers. For each, summarise in one line *what behaviour it locks in*. The fix must keep every existing test green; if a test must change, that is a signal of contract change and belongs in the PR body. If the area has zero test coverage, flag it.

5. **History lens (`git log` + `git blame`).** Why does the code look the way it does today? Run `git log --oneline -10 -- <change-site>` and `git blame <change-site>` on the offending line. If a recent commit introduced the symptom, name it. If the code was deliberately written this way (a known constraint, a TODO comment, a related PR description), respect that intent or call it out before overriding it.

Run angles 1-5 **concurrently** in a single Agent tool call message (5 subagent invocations in parallel). Wait for all to return before proceeding. If any angle returns "nothing found", do not silently skip; record it explicitly so Step 4 knows what evidence is missing.

### Synthesise (after subagents return)

Produce three things, in this order:

- **Root cause statement**: one paragraph, file:line anchored, derived from angle 1 + angle 5.
- **Constraints map**: what the fix MUST preserve (test contract, caller assumptions, deliberate prior design choices from angle 5). One bullet each.
- **Pattern match**: is there an existing adjacent implementation (angle 3) the fix can reuse? Name it. If yes, the fix is a *replication / extension*; if no, the fix is *novel* and you must justify why no existing pattern fits.

### Systematic coverage check (still required, in addition to the angles above)

1. Frontend filters / validation — `accept=`, MIME whitelists, size caps, silent `.filter(...)` drops, dropzone configs.
2. Client → server boundary — orpc routers, payload serialization (`dataUrl` base64 in JSON body is a known cost center).
3. Server services — sandbox limits, storage validation.
4. Surface asymmetry (chat vs coworker, prod vs prototype) — Bap's most common bug shape.
5. UX feedback — silent drops with no toast / error.
6. **DO NOT assume Vercel, S3, Cloudflare, etc.** Bap is **not** on Vercel. Frame body-limit / runtime claims as "any host body limit", not vendor-specific.

## Step 4 — design the fix, honestly (alternatives mandatory, simplest wins)

Before committing to a fix, **enumerate 2 to 3 alternative approaches** grounded in the research from Step 3. Each alternative must:

- Be technically possible given the constraints map.
- Touch a different surface or use a different abstraction (so the comparison is real, not cosmetic).
- Carry an honest trade-off line: what does it cost that the others do not (lines, surfaces touched, test churn, regression risk, performance, learning curve for the next person reading it).

Pick the alternative that **minimises new code while resolving the root cause**, preferring:

- Reusing an existing abstraction from Step 3 angle 3 over inventing a new one.
- Editing one site over editing two (when the constraints map allows).
- Lifting a constant or wiring a missing listener over restructuring a module.
- A change whose every caller (Step 3 angle 2) keeps the same contract over a change that requires updating callers.

**Anti-complexification rules** (apply to every fix, no exceptions):

- No new abstraction (function, hook, service, type) unless an existing one demonstrably cannot be reused.
- No new file unless the existing files cannot host the change.
- No defensive code for cases that cannot happen given the call graph (Step 3 angle 2). Trust the boundaries you traced.
- No comments explaining the bug in the code itself; the Linear ticket and PR body own that.
- No unrelated cleanup. The diff is for the bug at hand, not for the codebase at large.
- No "while I am here" refactor. Open a separate ticket for it if the urge is real.

Produce:

- **Quick fix** (the 10-minute unblock). This is what the PR will implement. Often: raise a constant, replace a silent `.filter()` with a toast, add a missing listener, copy a hook from the working surface to the broken one.
- **Durable fix** (the structural property). Goes in the Linear ticket as a follow-up note, not as code. Describe the **property** the fix should have, not a specific transport / vendor.
- **Alternatives considered**: 2-3 bullets from the enumeration above, one line each + the trade-off + why you didn't pick it.
- **Implications**: which other surfaces / hooks / constants get touched, migration concerns, data impact.
- **Regression risk**: for each caller from Step 3 angle 2, one line stating "no change to contract" or "contract changes in this way; mitigated by …". If any caller is *not* covered by an existing test, flag it as `test gap`.

## Step 6 — create the Linear ticket

The ticket is created **before** the branch and PR so its identifier can be embedded in branch name + PR title and Linear's GitHub integration auto-attaches the PR.

```
mcp__linear__save_issue({
  team: "BAP",
  title: "<Area>: <verb> <object>",                       // PR-style, < 70 chars, no em-dash
  description: "<see ticket body template below>",
  state: "<config.linear.statuses.triage>",               // start at Triage; Step 9 transitions to In Review
  labels: [
    "<config.linear.labels.bug | .feature>",
    "<config.linear.labels.dogfooding>",                  // every FDE-surfaced finding
    "<config.linear.labels.ui_ux>"                        // only if the finding lives in the UI
  ],
  assignee: "<config.linear.default_assignee_user_id>",   // Lubin for SIMPLE
  priority: 3                                             // 0=None 1=Urgent 2=High 3=Medium 4=Low; default 3
})
```

**Ticket body template** (markdown, French ok since the team is French). The ticket is a **status card**, not a report: Baptiste must see in one glance what was broken, what was fixed, and what to do next. All the deep-research artifacts (cause racine, alternatives, callers, tests, régression) belong in the PR body (Step 8), not here.

```markdown
**Status : PR ouverte, à review + merge par Baptiste.**

**Symptôme** : <une ligne en langue produit, ce que voit l'utilisateur>
**Fix** : <une ligne + file:line touché>

<!-- FINDING_CONTEXT
{
  "hash": "<sha256 of canonical finding form: kind|title|first code_ref|originalRunId>",
  "kind": "<bug or feature>",
  "originalDescription": "<the one-line description that triggered the bug-report invocation>",
  "affectedCoworker": "<@username if a specific coworker triggered the finding, else null>",
  "affectedSurfaces": ["<chat | coworker-output | prompt-bar | settings | panel | attachment-ui | sandbox | mcp | runtime | none>"],
  "originalRunId": "<bap run id where the finding fired, if applicable>",
  "originalEvidence": [
    { "kind": "code_ref", "value": "apps/web/src/components/prompt-bar.tsx:56" },
    { "kind": "log_excerpt", "value": "<short quote, max 200 chars>" },
    { "kind": "screenshot_path", "value": "/tmp/bug-report-...png" }
  ],
  "reproSteps": [
    "<one short imperative line per step, max 10 steps>"
  ],
  "successCriteria": [
    "<one assertion per line that the post-deploy verifier will check>"
  ]
}
END_FINDING_CONTEXT -->
```

The `FINDING_CONTEXT` block is **mandatory** and stays embedded in the ticket description (Linear preserves HTML comments). [bap-post-deploy-verify](../bap-post-deploy-verify/SKILL.md) reads it from the ticket description after the PR is merged + deployed. Without the block, the verifier returns `verdict: "no-finding-context"` and the loop stays open.

If the finding was passed to you with a pre-computed `hash`, use it verbatim. Otherwise compute it as `sha256(kind + "|" + title + "|" + first_code_ref_or_run_id)` so two findings on the same root cause produce the same hash.

Capture the ticket identifier (`BAP-<n>`) and URL (`https://linear.app/heybap/issue/BAP-<n>`) returned by `save_issue`. You will use both in the next steps.

**Attach every screenshot in `evidence.screenshots` to the ticket.** For each local file path captured in Step 2 (or provided by the user in chat), run:

```
upload  = mcp__linear__prepare_attachment_upload({ issueId: "<ticket uuid>", filename: "<basename>", contentType: "image/png" })
# PUT the file bytes to upload.uploadUrl using the headers returned by prepare
mcp__linear__create_attachment_from_upload({ issueId: "<ticket uuid>", assetUrl: upload.assetUrl, filename: "<basename>", title: "Repro screenshot" })
```

Record each returned `attachment.url` into `evidence.screenshotAttachments[]`; Step 10 cites them in the Slack post. If a screenshot path is in `/var/folders/.../T/` or another temp location, copy it to `~/HeyBap Pipeline/artifacts/BAP-<n>/` first so the upload doesn't race with cleanup.

If `evidence.screenshots` is empty (purely backend bug, Step 2 was skipped, user pasted nothing), skip this substep. Do not invent screenshots.

Title rules:
- Match the convention from recent merged PRs in `the-agentic-company/bap`: `<Area>: <verb> <object>`. Check `gh pr list --state merged --limit 10` if unsure.
- Under 70 chars.
- No em-dashes anywhere.
- Do not prefix the Linear ticket title itself with `BAP-<n>`; Linear adds the identifier on display.

## Step 7 — implement the fix on a branch

On the local clone:

```bash
cd /tmp/bap-investigation   # or wherever the clone lives
git checkout main && git pull
git checkout -b fix/bap-<n>-<short-slug>     # or feat/bap-<n>-<short-slug> for features
```

Slug rules: kebab-case, ≤4 words, derived from the bug noun (e.g. `chat-column-collapse`, `audio-attachment-size`, `coworker-postmessage-listener`). The `bap-<n>` prefix lets Linear's GitHub integration auto-attach the branch + PR.

**Implement the QUICK FIX, nothing more.** Constraints:

- Smallest possible diff. One or two files.
- No refactor, no unrelated cleanup, no defensive coding for cases that cannot happen, no comments explaining the fix (the ticket description and PR body explain).
- No new abstractions for hypothetical future use.
- If the durable fix is large (new hook, new endpoint, new component), it does NOT go in this PR. Mention it in the ticket's "Fix durable" section for follow-up.
- For **feature requests**: if the implementation is larger than ~50 lines, open a **draft** PR with the smallest scaffold and a detailed TODO list in the body. Do not autonomously ship a 500-line feature without review.

**Pre-commit regression sweep (mandatory)**: before staging the change, re-open each caller from Step 3 angle 2 and confirm the contract still holds. Then run the full local test suite for the touched packages:

- if the change touches `apps/web/`: `cd apps/web && bun run test:integration` (vitest, scoped to that package).
- if the change touches `packages/core/`: `cd packages/core && bun run test:unit`.
- if both: `bun run test:ci` from the repo root.
- always run `cd apps/web && bun run typecheck` and `bun run lint` (oxlint) on the touched files.

Observe a green pass before staging. If a test breaks unexpectedly, do not edit the test to make it pass; treat the breakage as new evidence that the fix is wrong and return to Step 4 to pick a different alternative. If the local run is red, fix the cause; do not push and rely on CI to catch it.

Commit with a Bap-style message that references the ticket:

```
<Area>: <verb> <object> (BAP-<n>)

<one paragraph: what changed and why, with file:line refs>
```

Areas seen on the repo: `Web`, `Sandbox`, `Skills`, `Core`, `Agents`, `Chat`. Pick the most fitting.

## Step 7.5 — verify the fix end-to-end on localhost (Chrome MCP, mandatory for UI changes)

**This step is the contract.** The skill does NOT post "Fixed, to review" unless this verification passed (or was explicitly skipped with a justified reason). A screenshot alone is not enough — the skill must reproduce the same path that triggered the bug in Step 2 and assert that the symptom is gone.

### A. Branch swap on the operator's main checkout

The fix lives on a feature branch pushed to GitHub (Step 7). To verify against the operator's running dev server (which serves `<config.local_dev.dev_server_url>` out of `<config.local_dev.bap_main_checkout>`), the skill swaps that working tree to the fix branch, lets HMR recompile, runs the verification, then swaps back.

```bash
MAIN="<config.local_dev.bap_main_checkout>"
BRANCH="<fix branch name pushed in Step 7>"

# Capture current state so we can restore it
PREV_BRANCH=$(git -C "$MAIN" rev-parse --abbrev-ref HEAD)
DIRTY=$(git -C "$MAIN" status --porcelain)
if [ -n "$DIRTY" ]; then
  git -C "$MAIN" stash push --include-untracked --message "bap-bug-report-verify-BAP-<n>"
  STASHED=1
fi

git -C "$MAIN" fetch origin "$BRANCH"
git -C "$MAIN" switch "$BRANCH"
sleep <config.local_dev.hmr_wait_seconds>   # let Next.js HMR recompile
```

If any of the swap commands fail (uncommitted merge, locked index, branch not yet pushed), set `verifyResult = { passed: false, skipped: true, reason: "branch-swap-failed: <error>" }` and jump to subsection D (restore). Step 10 will use the SKIPPED template.

### B. Reproduce the same path and assert the symptom is gone

Re-drive the exact path captured in Step 2, on the same URL, in the same Chrome window the operator has signed in. The assertion uses `evidence.symptomAssertion` verbatim — it is the contract between the BEFORE and the AFTER.

```
mcp__Claude_in_Chrome__navigate({ url: "<config.local_dev.dev_server_url>/<bug-path>" })
# If the bug required interaction to surface, redrive the same clicks / form_input here.
mcp__Claude_in_Chrome__screenshot({ })  # save bytes to ~/HeyBap Pipeline/artifacts/BAP-<n>/after.png
afterText  = mcp__Claude_in_Chrome__get_page_text({ })
console    = mcp__Claude_in_Chrome__read_console_messages({ })
network    = mcp__Claude_in_Chrome__read_network_requests({ })
```

Evaluate the assertion against `afterText` / `console` / `network`. Examples:

| `symptomAssertion`                                                  | Pass criterion (the symptom is GONE)                                                |
| ------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| "workspace switch lands on `/` instead of `/agents`"                | current URL ends with `/agents` (or `/agents/...`), not `/`                         |
| "dropzone shows a red error toast 'fichier trop volumineux'"        | no `.toast--error` in `afterText`, no `413` / `payload too large` in `network`      |
| "chat send button stays disabled after typing"                      | `button[data-action='send']` has no `disabled` attribute after `form_input` typed   |
| "skill_add returns ok=true but the skill is missing from coworker"  | `coworker_get` (Bap MCP) lists the skill in `skills[]`                              |

The assertion check is plain code (string match on the text, regex on the URL, structural check on the DOM via `mcp__Claude_in_Chrome__find` / `inspect`). Do not let an LLM "judge" the screenshot.

Record the outcome:

```json
{
  "verifyResult": {
    "passed": true | false,
    "skipped": false,
    "assertion": "<verbatim from evidence.symptomAssertion>",
    "observed": "<one sentence: what Chrome actually showed>",
    "afterScreenshot": "~/HeyBap Pipeline/artifacts/BAP-<n>/after.png",
    "consoleClean": true | false,
    "networkClean": true | false
  }
}
```

Append the path to `evidence.screenshots` with `kind: "after"`.

### C. If verify FAILED — do not lie to Baptiste

If `verifyResult.passed === false` (the symptom still reproduces after the swap, or the expected fix evidence is missing):

- Do NOT proceed to Step 10's `Fixed, to review` post. The fix did not actually fix.
- Add a Linear comment on BAP-<n> citing the observed state and the failed assertion.
- Keep the PR open as **draft** (convert via `gh pr ready --undo <num>` if needed). It is still useful for Baptiste to read the code, but it is not "ready for review".
- Step 9 leaves the ticket on `In Progress` (NOT `In Review`) and assigned to Lubin (NOT reassigned to Baptiste). The autonomous loop can retry on the next tick once Lubin re-investigates.
- Step 10 still posts to `#pr-lubin` but with the FAILED template (subsection F of Step 10), pinging Lubin (not Baptiste) so he sees the broken fix first.

### D. Restore the operator's working tree (always — even on failure)

```bash
git -C "$MAIN" switch "$PREV_BRANCH"
if [ "${STASHED:-0}" = "1" ]; then
  git -C "$MAIN" stash pop
fi
```

Run subsection D inside a trap / finally so a thrown error in B does not leave the operator's checkout on the fix branch.

### E. Fallback paths

- **Playwright fallback** (autonomous loop, no Chrome MCP). Same swap + sleep + assertion logic, but the navigation + screenshot + console/network capture happens through the Playwright snippet from Step 2 (different output path). The headless context loses the operator's signed-in session, so use `storage-state.json`.
- **Backend-only fix** (no UI surface). Skip subsections A-D. Verify via `curl` against an API endpoint or via `mcp__bap-local__chat_run` / `coworker_run`, asserting on the response shape. Record `verifyResult.assertion` in plain English just the same.
- **Localhost down** OR **Chrome MCP disconnected** AND **Playwright fixture broken**. Set `verifyResult = { passed: false, skipped: true, reason: "..." }` and continue. Step 10 will use the SKIPPED template, explicitly flagging that nothing was verified — Baptiste then re-runs locally before merging.

## Step 8 — open the PR

The PR body carries **all the deep-research artefacts**: cause racine, alternatives, callers, tests, régression. The Linear ticket stays short (Step 6 is a status card); the PR is where Baptiste reviews the code and the context together.

```bash
git push -u origin <branch>
gh pr create \
  --title "BAP-<n> <Area>: <verb> <object>" \
  --base main \
  --body "$(cat <<'EOF'
Closes BAP-<n>

## Symptôme
<une ligne en langue produit, ce que voit l'utilisateur>

## Cause racine
<2-4 lignes, ancrées sur file:line, chaîne symptôme → cause issue de Step 3 angle 1>

## Ce que fait cette PR
<1 paragraphe + file:line touché ; référencer le pattern adjacent réutilisé (Step 3 angle 3) si applicable>

## Fix durable (pas dans cette PR)
<la propriété structurelle à viser plus tard, ou "—" si rien>

## Alternatives considérées (3 max)
- <option 1> : <trade-off + raison de ne pas l'avoir choisie>
- <option 2> : <trade-off + raison>
- <option 3 (si applicable)> : <trade-off + raison>

## Callers vérifiés (regression check)
- <file:line> : <contrat préservé | contrat modifié, mitigation = …>

## Tests dans la zone
- <test:line> : verrouille <behaviour>
- test gap : <surface non couverte> (si aucun test)

## Repro
<une ligne : où cliquer dans https://heybap.com>

## Régression connue
<commit hash + subject si trouvé via Step 3 angle 5, sinon "non identifié">
EOF
)"
```

For features whose implementation is over ~50 lines, add `--draft`. For bugs and small features, non-draft.

PR title rules:
- Must start with `BAP-<n>` so Linear auto-attaches.
- Then the standard `<Area>: <verb> <object>` from recent merged PRs.
- Under 70 chars total (so the area + verb + object stays concise).
- No em-dashes anywhere.

Capture the PR URL returned by `gh pr create`. You will need it for Step 9.

## Step 9 — update the Linear ticket: status + assignee + attach PR

**Conditional on `verifyResult` from Step 7.5.**

- If `verifyResult.passed === true` OR `verifyResult.skipped === true`: transition to `In Review` and reassign to Baptiste (the PR is ready for him to look at).
- If `verifyResult.passed === false && verifyResult.skipped === false` (verification ran and failed): keep status `In Progress`, keep assignee Lubin, add a comment with the observed failure. **Do not reassign to Baptiste on a broken fix.** Lubin will re-investigate; the autonomous loop can retry on the next tick.

Pass case (verified OR skipped):

```
mcp__linear__save_issue({
  id: "BAP-<n>",
  state: "<config.linear.statuses.in_review>",
  assignee: "<config.linear.reviewer_user_id>",      // Baptiste; PR is in his court now
  links: [
    { url: "<PR URL>", title: "PR #<num> — <PR title>" }
  ]
})
```

Fail case (verifyResult.passed === false, NOT skipped):

```
mcp__linear__save_issue({
  id: "BAP-<n>",
  state: "<config.linear.statuses.in_progress>",     // ticket stays in Lubin's queue
  links: [ { url: "<PR URL>", title: "PR #<num> (draft, verify KO)" } ]
})
mcp__linear__save_comment({
  issue: "BAP-<n>",
  body: "Vérif Chrome MCP KO sur la branche du fix.\nAssertion : <verifyResult.assertion>\nObservé : <verifyResult.observed>\nPR laissée en draft."
})
```

Linear's GitHub integration usually attaches the PR automatically once the branch lands (because the branch name contains `bap-<n>`). The explicit `links` attachment is a belt-and-braces fallback if the integration is delayed.

`bap-post-deploy-verify` later transitions the ticket from `In Review` to `Live` once Baptiste's merge + the prod deploy are confirmed by the verifier. Assignee can stay Baptiste at that point (he is the historical owner of the merged change).

`links` is append-only, so re-running this step in a retry is safe.

**Attach the AFTER screenshot** captured in Step 7.5 (UI changes only). Same flow as Step 6's BEFORE attachment:

```
upload  = mcp__linear__prepare_attachment_upload({ issue: "BAP-<n>", filename: "after.png", contentType: "image/png", size: <bytes> })
# PUT file bytes to upload.uploadRequest.url with the signed headers
mcp__linear__create_attachment_from_upload({ issue: "BAP-<n>", assetUrl: upload.assetUrl, title: "After fix" })
```

Record the returned `attachment.url` as the AFTER entry in `evidence.screenshotAttachments[]`. Step 10 cites it in the Slack post.

## Step 10 — Slack `#pr-lubin` notification (problem + fix + ping Baptiste for review)

**This step is MANDATORY**. Without the Slack post, Baptiste doesn't learn the PR exists and the contract is not fulfilled. The skill is NOT done at "PR opened + Linear updated" — it is done at "Slack #pr-lubin post permalink captured".

Required for every shipped PR. The team relies on this message — not on Linear's auto-broadcast — to know what is ready for review. Skip it and Baptiste does not learn the PR exists until he opens Linear on his own.

Resolve identifiers:

- channel id from `config.yaml` (`slack.pr_channel_id`); if it is the placeholder, fall back to `mcp__aa816864-db59-4de1-a375-68c8cccbfe71__slack_search_channels({ query: "pr-lubin" })` and cache for the session.
- reviewer id from `config.yaml` (`slack.review_user_id`); if missing, fall back to `mcp__aa816864-db59-4de1-a375-68c8cccbfe71__slack_search_users({ query: "Baptiste" })`.

The body template is **conditional on `verifyResult` from Step 7.5**. Three variants:

### Variant 1 — PASS template (verifyResult.passed === true)

```
Fixed, to review <@<reviewer-id>> <PR URL>
_<PR title without the BAP-<n> prefix>_
<problème en 1-2 phrases, langue produit>
<fix en 1-2 phrases avec file:line touché>. Ticket : BAP-<n>.
Verified : ✅ <verifyResult.assertion>. <verifyResult.observed>
Screenshots : <BEFORE Linear asset URL> · <AFTER Linear asset URL>
```

Concrete example:

```
Fixed, to review <@U0A87JNV8QP> https://github.com/the-agentic-company/bap/pull/51
_Web: land on coworker list after workspace switch_
Switching workspace from the sidebar dropdown (or from workspace settings) currently bounces the user to the public landing at /. For an established user toggling between workspaces, the expected destination is the coworker list.
Two-line change: navigate({ to: "/" }) to navigate({ to: "/agents" }) in app-sidebar.tsx:478 and settings/workspace.tsx:152. Ticket : BAP-50.
Verified : ✅ workspace switch lands on /agents. Chrome MCP on the fix branch redirected to /agents/info/scoop-monitor as expected.
Screenshots : https://uploads.linear.app/.../before.png · https://uploads.linear.app/.../after.png
```

### Variant 2 — SKIPPED template (verifyResult.skipped === true)

When verification could not run (localhost down, Chrome MCP disconnected, backend-only fix, etc.). The line gives Baptiste the explicit reason so he knows to re-run locally before merging.

```
Fixed, to review <@<reviewer-id>> <PR URL>
_<PR title without the BAP-<n> prefix>_
<problème en 1-2 phrases, langue produit>
<fix en 1-2 phrases avec file:line touché>. Ticket : BAP-<n>.
Verified : skipped (<verifyResult.reason>). À retester avant merge.
```

### Variant 3 — FAILED template (verifyResult.passed === false && !verifyResult.skipped)

When verification ran and the symptom still reproduces on the fix branch. The fix didn't fix — the post must NOT claim "Fixed, to review". Ping Lubin (operator), NOT Baptiste — Lubin re-investigates first.

```
Vérif KO, à reprendre <@<operator-id>> <PR URL>
_<PR title without the BAP-<n> prefix>_
<problème en 1-2 phrases, langue produit>
<tentative en 1-2 phrases avec file:line touché>. Ticket : BAP-<n>.
Verified : ❌ <verifyResult.assertion>. <verifyResult.observed>. PR laissée en draft.
Screenshots : <BEFORE Linear asset URL> · <AFTER Linear asset URL>
```

The `<operator-id>` is `config.slack.operator_user_id` (Lubin, `U0AT7378GSX`). Baptiste does NOT get pinged on a broken fix.

Send via `mcp__aa816864-db59-4de1-a375-68c8cccbfe71__slack_send_message` (channel_id from config — same `#pr-lubin` channel for all three variants).

Mandatory call sequence:

```
result = mcp__aa816864-db59-4de1-a375-68c8cccbfe71__slack_send_message({
  channel_id: "<config.slack.pr_channel_id>",
  text: "<composed body above>"
})
if result.ok != true OR result.permalink is null:
  # retry once with the same payload (transient API errors are common)
  result = mcp__aa816864-db59-4de1-a375-68c8cccbfe71__slack_send_message({ channel_id, text })
if result.ok != true OR result.permalink is null:
  # do NOT pretend success; surface the error in Step 12's return
  slackPostFailed = true
  slackPostError  = result.error or "no permalink returned"
else:
  slackPermalink = result.permalink
```

The return value (Step 12) must carry either `slackPermalink` OR `slackPostFailed: true` with the error. Never both null. Silently skipping the Slack post is a contract violation; the operator relies on this message to know what to merge.

Constraints:

- Exactly one message per PR (top-level, no thread reply). On a re-run, the skill detects the existing message via `slack_search_public({ query: "<PR URL>", limit: 5 })` and skips reposting; thread updates do not re-ping Baptiste.
- Line 1 prefix is the action label that tells the reader, in 4 words, what to do. PASS = `Fixed, to review` (ping Baptiste). SKIPPED = also `Fixed, to review` (still Baptiste's queue, just unverified). FAILED = `Vérif KO, à reprendre` (ping Lubin, not Baptiste).
- The ping (`<@U…>`) is what triggers a Slack notification; removing it makes the post silent. Baptiste on PASS / SKIPPED, Lubin on FAILED.
- The PR URL on line 1 is the actionable link. The italic PR title on line 2 reinforces "PR is open, just review the diff."
- No `Linear:` link line. The ticket reference at the end (`Ticket : BAP-<n>`) is enough; Linear auto-links bare identifiers.
- Both descriptive sentences (problem + fix) carry `file:line` references for the bridge between the PR diff and the symptom.
- Avoid em-dashes (team house style).
- The `Verified:` line is **mandatory** in every variant. The PASS / SKIPPED / FAILED prefix tells Baptiste (or Lubin, in the FAILED case) what the verification status is at a glance — Linear and Slack are both noisy, the verdict must be inline.
- The `Screenshots:` line is **mandatory whenever `evidence.screenshotAttachments` has at least a BEFORE entry** (PASS and FAILED variants always have BEFORE + AFTER; SKIPPED has only BEFORE if Step 2 ran). Cite the Linear asset URLs (Slack auto-unfurls them inline). Omit only for purely backend fixes where Step 2 was skipped.
- The Slack channel id `C0BCH5L6PQS` (`#pr-lubin`) and the reviewer user id `U0A87JNV8QP` (Baptiste) are pinned in config. Resolve via `slack_search_channels` / `slack_search_users` only if the config placeholder is unchanged; otherwise use the configured ids directly.

## Step 11 — watch CI, fix red until green

Required for every PR opened by this skill. The skill owns the green-up; never leave a red PR open for Baptiste to deal with.

1. **Watch CI.** After the push, poll `gh pr checks <num>` until every check completes. The Bap CI runs oxlint, typecheck (`tsgo`), Fallow audit (CRAP / dead-code / dupes), gitleaks, react-doctor, and `bun run test:ci` (vitest unit + integration).

2. **If any check is red: fix it, do not abandon.** Read the failure log with `gh run view <id> --log-failed`, identify the root cause, fix in code on the SAME branch (do not close + reopen), commit, push, and watch again. Loop until green. Common gates:
   - Fallow CRAP score at or above threshold → extract a small helper to drop the function's cyclomatic.
   - oxlint `curly` → braces around `if` bodies.
   - typecheck error → match the existing signature.
   - vitest failure → re-read Step 4, the fix is probably wrong.
   Never bypass with `--admin`, `--no-verify`, or by commenting-out the gate.

3. **When CI is green, stop here.** The operator (Lubin) no longer has merge rights on `the-agentic-company/bap`; **only Baptiste merges**. The skill's contract ends at "PR opened, CI green, Slack #pr-lubin pinged Baptiste at Step 10." Do NOT call `gh pr merge`. Do NOT trigger any deploy workflow. The Slack post from Step 10 is the handoff; Baptiste reviews + squash-merges from GitHub when he is ready.

4. **Post-merge cleanup is owned by `bap-post-deploy-verify`**, not by this skill. Once Baptiste merges and the staging / prod deploy lands, the verifier reads the FINDING_CONTEXT off the Linear ticket and confirms the fix in prod. This skill exits at "CI green."

## Step 12 — return to the user

Output exactly three blocks, no commentary, no headers:

1. The Linear ticket: `BAP-<n>  <ticket URL>`.
2. The PR URL.
3. The Slack permalink from Step 10, **or** `SLACK POST FAILED: <error>` if Step 10's retry also failed. Never silently omit this block.

Screenshots are already attached to the Linear ticket and referenced in the Slack post (Step 6 + Step 10) — no manual upload to mention to the user.

If `slackPostFailed: true`, the operator must repost manually before the PR can be considered handed off. The skill flags this loudly rather than pretending the run succeeded.

## Historical bugs (anchors)

Use as sanity checks if the current bug sounds similar:

- **`bap:agentic-app-prompt` button works in chat, not in coworker output** → asymmetry. Listener at `apps/web/src/components/chat/agentic-app-panel.tsx:110-183`, missing in `apps/web/src/routes/agents/-components/coworker-info-panels.tsx` (AgenticAppFrame L283, iframes L384 + L404) and in the prototype variant. Fix: extract listener into a shared hook, wire on both surfaces, force `onSendPrompt` to post into `run.conversationId`.
- **Attaching m4a / mp3 in run chat does nothing** → not a MIME filter. Silent 10 MB cap: `apps/web/src/components/prompt-bar.tsx:56` + L319 `.filter(...)` without toast. Dup pattern in `chat-input.tsx:17/123` and `inbox-create-input.tsx:24/81`. Compounding: attachments base64 in orpc body (+33%). Sandbox already at 50 MB (`packages/core/src/server/services/sandbox-file-service.ts:25`). Durable fix: get binary out of JSON body, transport agnostic.
- **Chat column collapses to 0% in coworker info view, no restore** → regression. `apps/web/src/components/ui/dual-panel-workspace.tsx:130-147` sets `isLeftPanelCollapsedByDrag = true` past the 25% threshold, L191-204 forces width 0%, flag never reset on pointerup. Only `coworker-info-page.tsx:482` and `:743` opt in via `allowLeftPanelDragCollapse`. Regression commit: `679c7fd6`.

## What NOT to do

- Do not push to `main`. Always a branch + PR.
- Do not implement the durable fix if it is larger than a small diff. It belongs in the follow-up section of the Linear ticket and PR body.
- Do not add comments in the code explaining the bug. The Linear ticket and PR body are the explanation.
- Do not assume Vercel / S3 / specific vendors unless the repo already uses them.
- Do not claim something is broken without a `file:line` proof.
- Do not use em-dashes anywhere (commit message, PR title, PR body, Linear ticket).
- Do not skip Step 10's Slack `#pr-lubin` notification. The team relies on the explicit problem + fix summary and the Baptiste ping to know what is ready for review; Linear's auto-broadcast alone is not enough.
- Do not drop the `<@reviewer-id>` ping from the Slack message. Without it, the post is silent and the review never starts.
- Do not leave screenshots as local paths in the ticket description when `evidence.screenshots` is non-empty. The Step 6 attachment substep must run and the Slack post (Step 10) must cite the resulting URLs. Telling the user to upload manually defeats the automation.
- Do not open the PR before the Linear ticket. The ticket identifier needs to be in the branch + title.
- Do not skip the FINDING_CONTEXT JSON block. The post-deploy verifier depends on it to close the loop.
- Do not skip Step 3's parallel-subagent fan-out, even on "obvious" bugs. The cost of one wasted research pass is 30 seconds; the cost of one wrong fix shipped is hours of regression. The 5 angles are mandatory.
- Do not pick the first plausible fix in Step 4. Enumerate 2 to 3 alternatives grounded in Step 3 and pick on the rubric (reuse > extend > additive > smallest surface). The "Alternatives considérées" section must be real, not retrofitted.
- Do not introduce a new abstraction, hook, service, or file when Step 3 angle 1 returned an adjacent implementation. Reuse the adjacency or explain why it does not fit.
- Do not edit a test to make it pass after the fix. A test break is evidence the fix is wrong; return to Step 4 and pick a different alternative.
- Do not call `gh pr merge` from this skill. Lubin no longer has merge rights on `the-agentic-company/bap`; Baptiste is the only person who merges. The contract stops at "CI green + Slack #pr-lubin pinged Baptiste."
- Do not trigger any deploy workflow (`release-main.yml`, `prod-release.yml`) from this skill. Deploys are owned by Baptiste post-merge.
- Do not post the PASS template (`Fixed, to review`) when `verifyResult.passed === false`. The fix did not fix; the post must be the FAILED template pinging Lubin instead. Lying to Baptiste burns his trust in this pipeline within one occurrence.
- Do not skip Step 7.5's Chrome MCP verification when `localhost:3000` is reachable and the bug has a UI surface. Falling back to "screenshot only, no assertion" defeats the point — the symptom must be reproduced post-fix and observed gone before any `Fixed` claim.
- Do not leave the operator's main checkout on the fix branch after Step 7.5. Step 7.5 subsection D restores the previous branch and pops the stash; this MUST run even on a thrown error (use a trap / finally).
- Do not invent the `symptomAssertion` in Step 7.5. It must come from `evidence.symptomAssertion` recorded in Step 2 — the BEFORE assertion and the AFTER assertion are the same sentence, only the truth value flips.

## Config

`lubin-skills/bap-bug-report/config.yaml` mirrors the router's `linear` block:

```yaml
linear:
  team_id: "5ff3b86a-a1a5-4241-ac5c-e65a143f16e3"
  team_key: "BAP"
  default_project_id: null
  default_assignee_user_id: "8fc555af-50cd-4093-9878-92f6f08e6d96"  # Lubin
  labels:
    bug: "e356eade-cc41-4abb-9447-00487b30583c"
    feature: "296529af-3672-4bd7-876d-64245d40c768"
    dogfooding: "50b28f0f-60be-460d-9db1-bd2e03e79f42"
    ui_ux: "848839d8-15da-440a-96e1-02e725dc153d"
  statuses:
    triage: "b63fe240-0351-4011-a754-3b69c3cc5c99"
    in_review: "423d89b9-126c-4db1-aa27-05b25baafd20"
github_repo: "the-agentic-company/bap"
```

Keep this in sync with `lubin-skills/feature-bug-complexity-classification/config.yaml`. The router is the canonical source.

## See also

- [feature-bug-complexity-classification](../feature-bug-complexity-classification/SKILL.md): the gate that dispatches SIMPLE findings to this skill.
- [bap-feature-brainstorm](../../.claude/skills/bap-feature-brainstorm/SKILL.md): the COMPLEX counterpart that creates a Linear ticket at status `Triage` with `Need More Shaping` instead of a PR.
- [bap-post-deploy-verify](../bap-post-deploy-verify/SKILL.md): closes the loop by transitioning this ticket to `Live` after the merge + deploy is verified in prod.
