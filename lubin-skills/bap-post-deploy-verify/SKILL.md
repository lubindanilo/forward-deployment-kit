---
name: bap-post-deploy-verify
description: |
  Close the feedback loop after a PR has been merged on
  `the-agentic-company/bap` and deployed to production. Re-validates that
  the original finding (the one that triggered the PR) is actually fixed
  in prod. Three modes, chosen per finding: Mode A (re-run the affected
  coworker via `mcp__bap__coworker_run`, diff the logs), Mode B (drive
  heybap.com via the Claude-in-Chrome MCP, reproduce the scenario,
  capture before/after screenshots), Mode C (run a generated Playwright
  spec in headless Chromium). Default Mode A. On pass, comments the PR
  and closes the finding. On fail, opens a `regression after merge`
  finding via `bap-finding-router`. Use when a PR opened by
  `bap-bug-report` has been merged and you want autonomous validation
  before declaring the loop closed.
---

# Post-deploy verification for `the-agentic-company/bap`

The loop that `bap-finding-router` and `bap-bug-report` start has, until now, ended at "PR opened". This skill closes it. After a merge, it goes back into HeyBap (or the bap code paths) and confirms that the original finding is actually gone in prod.

Without this skill the pipeline ships PRs blind. With it, every PR is paired with a verification step whose verdict is recorded, and regressions are detected automatically.

## When to invoke

- A PR opened by `bap-bug-report` has been merged on `the-agentic-company/bap` and the deploy is live.
- An operator wants to spot-check that a recent merge fixed what it claimed to fix.
- A scheduled `/loop` over the last 24h of merged PRs that did not get a verdict yet.

Do not invoke when:

- The PR has not been merged yet (no point verifying a draft).
- The PR has been merged but not deployed (Vercel build still running on bap). Wait for deploy.
- The PR has no `finding_hash` embedded in its body and no operator-supplied finding context. There is nothing to verify against.

## Input contract

```json
{
  "prUrl": "https://github.com/the-agentic-company/bap/pull/123",
  "findingContext": {
    "hash": "<sha256 of canonical finding form>",
    "kind": "bug | feature",
    "originalDescription": "<one-line>",
    "affectedCoworker": "@username (optional)",
    "affectedSurfaces": ["chat | coworker-output | prompt-bar | settings | ..."],
    "originalRunId": "<bap run id where the finding fired (optional)>",
    "originalEvidence": [
      { "kind": "code_ref | run_id | log_excerpt | screenshot_path", "value": "..." }
    ]
  },
  "modePreference": "A | B | C | auto",
  "options": {
    "perStepTimeoutSeconds": 180,
    "screenshotDir": "/tmp/bap-verify-screenshots",
    "playwrightWorkspace": "lubin-skills/bap-post-deploy-verify/playwright-tests"
  }
}
```

If `findingContext` is missing, the skill tries to extract it from the PR body. `bap-bug-report` embeds it as an HTML comment of the form:

```html
<!-- FINDING_CONTEXT
{ "hash": "...", "kind": "bug", "originalDescription": "...", ... }
END_FINDING_CONTEXT -->
```

If neither input nor PR body has it, the skill refuses to run and returns `verdict: "no-finding-context"`. No silent guessing.

## Step 1 — confirm merge + deploy

```bash
gh pr view <num> --repo the-agentic-company/bap --json mergedAt,state,mergeCommit,baseRefName,headRefName
```

If `state != "MERGED"`, abort. Return `verdict: "not-merged"`.

Then verify the deploy. HeyBap is not on Vercel (per `bap-bug-report` rule, line 90 of its SKILL.md), so the deploy signal is project-specific. Two paths:

1. **GitHub deployments API**: `gh api repos/the-agentic-company/bap/deployments?ref=<mergeCommit>` and check the latest `state == "success"` and `environment == "production"`. Wait up to 10 minutes (poll every 30s) if pending.
2. **Production health probe**: `curl -sf https://heybap.com/api/health` (or whichever endpoint the bap repo exposes; grep `apps/web/src/routes/api/health` for the canonical path). If the response includes a commit SHA, compare against `mergeCommit`.

If after 10 minutes the deploy has not landed, return `verdict: "deploy-pending"` and surface a Slack note in `#technical-pr` so a human can re-trigger later.

## Step 2 — pick the validation mode

Default is Mode A. The skill switches to B or C based on the finding context:

| Trigger | Mode |
|---------|------|
| `findingContext.affectedSurfaces` contains any of `chat`, `coworker-output`, `prompt-bar`, `settings`, `panel`, `attachment-ui` | B (Chrome MCP, visual repro required) |
| `findingContext.kind == "feature"` AND `affectedCoworker` is set AND no UI surface listed | A (re-run coworker, diff logs) |
| `modePreference == "C"` OR a Playwright spec named `<finding-hash>.spec.ts` already exists in `playwrightWorkspace/` | C (Playwright headless, reuse existing spec or generate one) |
| Otherwise | A |

`modePreference: "auto"` runs this matrix. `modePreference: "A" | "B" | "C"` forces. The skill logs the chosen mode in its return value so reruns are reproducible.

## Step 3A — Mode A: re-run the affected coworker

The cheapest, most deterministic mode. Used when the finding was a coworker-side bug or a backend fix and the coworker exists in the workspace.

```ts
// 1. Pull the original run's input (if available)
const original = findingContext.originalRunId
  ? await mcp__bap__coworker_logs({ runId: findingContext.originalRunId })
  : null;
const replayInput = original?.run?.triggerPayload?.userInput
  ?? "[MODE TEST] post-deploy verify of <one-line description>";

// 2. Re-run with the same payload
const run = await mcp__bap__coworker_run({
  reference: findingContext.affectedCoworker,
  userInput: replayInput,
});

// 3. Poll until terminal
const newLog = await pollUntilTerminal(run.id, options.perStepTimeoutSeconds);
```

**Diff logic**:

- If `original` exists: compare `original.events` length / types / errorMessage vs `newLog.events`. Specifically check that the failure pattern that triggered the finding (e.g. `tool_calls.notion.create_page.count == 0`, `errorMessage contains "stopped making progress"`) is no longer present in the new logs.
- If `original` does not exist: assert the new run completed without error AND every `successCriteriaRef` from the finding's coworker spec passes (re-use the eval engine from `bap-coworker-test-loop`).

Return `verdict: "verified"` only if both: (a) the original failure pattern is absent in the new logs, (b) no NEW failure pattern appeared. Else `verdict: "regression"`.

## Step 3B — Mode B: Chrome MCP visual repro

Used when the finding lives in the UI. Drives a real Chrome session against https://heybap.com.

```ts
// 0. Ensure the live PR's commit is what is rendering
await mcp__Claude_in_Chrome__navigate({ url: "https://heybap.com" });
// (verify by inspecting a build-id meta tag or by reading the network response from /api/health)

// 1. Reproduce the original scenario step-by-step
// Steps come from findingContext.originalEvidence or, if not present,
// from a short prose recipe also embedded in the PR body by bap-bug-report
// under <!-- REPRO_STEPS ... END_REPRO_STEPS -->

for (const step of reproSteps) {
  await execute(step);  // mcp__Claude_in_Chrome__navigate / find / form_input / etc.
  // Light wait for animations / SSE
}

// 2. Capture the current state
const wide = await mcp__Claude_in_Chrome__preview_screenshot({ fullPage: true });
const zoomed = await mcp__Claude_in_Chrome__preview_screenshot({ /* zoom on the offending element */ });

// 3. Diff against the original screenshot (if any)
// Visual diff: pixel-perfect not required; we look for the absence of the
// original symptom (broken layout, missing toast, infinite spinner)
```

**Decision**:

- If `originalEvidence[].kind == "screenshot_path"` is present and points to a file that still exists locally: compute a structural diff (compare DOM trees and the offending element's bounding box / computed style). If the symptom is gone (no more 0% width, toast now visible, button now clickable), verdict `verified`.
- If no original screenshot: rely on a checklist from the finding context. Each item is a boolean assertion the operator (or `bap-bug-report` itself when filing) wrote: "after click X, the email modal opens"; "the attachment uploads at 15 MB"; "the panel does not collapse to 0% on drag". All pass → `verified`. Any fail → `regression`.

Save all screenshots under `options.screenshotDir` and reference them in the return value.

## Step 3C — Mode C: Playwright headless

Used for stable, repeatable scenarios that should run in CI on every future commit, not just this verification. Reuses the pattern that already lives in `vault/projects/li-seo/qa-visual/` (Playwright + Python pilot script).

Two sub-cases:

### 3C.1 — A spec already exists for this finding

`lubin-skills/bap-post-deploy-verify/playwright-tests/<finding-hash>.spec.ts` is present (committed in a previous verification cycle). Run it:

```bash
cd lubin-skills/bap-post-deploy-verify
npx playwright test playwright-tests/<finding-hash>.spec.ts \
  --reporter=json \
  --output=/tmp/bap-verify-playwright-<finding-hash>
```

Parse the JSON reporter output. `verdict: "verified"` if all tests pass; `regression` if any fail.

### 3C.2 — No spec yet, generate one

When this finding has never been Playwright-tested, the skill generates a spec from `findingContext.originalEvidence` + `reproSteps`:

```typescript
// playwright-tests/<finding-hash>.spec.ts (generated)
import { test, expect } from "@playwright/test";

test.describe("Finding <hash>: <one-line>", () => {
  test("symptom no longer present after merge", async ({ page }) => {
    await page.goto(process.env.HEYBAP_URL ?? "https://heybap.com");
    // ...steps generated from reproSteps...
    // ...assertions generated from successCriteria / checklist...
  });
});
```

Commit the spec to the FDK repo (`git add playwright-tests/<finding-hash>.spec.ts && git commit -m "test(post-deploy): add spec for finding <hash>"`). It becomes a permanent regression test, runnable in CI by anyone.

Reuse setup:

- `playwright.config.ts` at `lubin-skills/bap-post-deploy-verify/`. Single project Chromium headless. `baseURL: process.env.HEYBAP_URL || "https://heybap.com"`. Storage state (auth cookies) loaded from `~/.heybap-playwright-auth.json` (gitignored).
- Auth bootstrap: a one-off `npx playwright codegen https://heybap.com --save-storage=~/.heybap-playwright-auth.json` run by the operator the first time. Documented in the skill's README, not in this SKILL.md.

## Step 4 — verdict + actions

Possible verdicts and actions:

| Verdict | Action |
|---------|--------|
| `verified` | Comment on the PR (`gh pr comment <num> --body "..."` with the verification details and screenshots / log links). Notify `#technical-pr` (one-liner). If a `bap-finding-router` registry exists, mark the finding as closed. |
| `regression` | Open a new finding via `bap-finding-router` with `kind: "bug"`, title `regression after merge of #PR-<num>: <original description>`. Include the new evidence (logs, screenshots, Playwright report) in `findingContext.evidence`. Slack `#technical-pr` with the new finding link. |
| `no-finding-context` | Stop. Notify the operator (return-to-user) that the PR body does not carry the embedded JSON block. Suggest re-opening the PR via `bap-bug-report` with the context, or invoking this skill with the context inline. |
| `deploy-pending` | Schedule a re-invocation in 10 minutes (`/loop 10m` pattern, see "Autonomous mode" below). Notify Slack once with the deferral. |
| `not-merged` | Stop. Return-to-user: PR is not merged. |
| `flake` | The same run failed differently than the original finding. Surface to operator, do not auto-close, do not open regression (avoid spam). |

## Step 5 — return to caller

Structured return value:

```json
{
  "verdict": "verified | regression | no-finding-context | deploy-pending | not-merged | flake",
  "prUrl": "...",
  "mergeCommit": "...",
  "modeUsed": "A | B | C",
  "newRunId": "<bap run id if Mode A>",
  "screenshotPaths": ["..."],
  "playwrightReport": "/tmp/...",
  "prCommentUrl": "...",
  "slackPermalink": "...",
  "newFindingForRouter": "<finding object if verdict == regression>",
  "diagnosticNotes": "<1-2 lines for the human if verdict != verified>"
}
```

## Autonomous mode

This skill is the leaf of the post-merge half of the pipeline. To run it autonomously over a fleet of recent merges:

```
/loop 60m invoke bap-post-deploy-verify on the latest merged-but-unverified PR
```

Concretely the `/loop` wrapper runs every 60 minutes:

```bash
gh pr list --repo the-agentic-company/bap --state merged --limit 20 --json number,mergedAt,body,labels \
  --search "is:merged merged:>$(date -u -v-24H +%Y-%m-%dT%H:%M:%SZ) -label:post-deploy-verified"
```

For each PR returned, this skill is invoked with the PR URL. On `verified`, the PR is labelled `post-deploy-verified` (`gh pr edit <num> --add-label post-deploy-verified`). On `regression`, the label is `post-deploy-regression` and the new finding's link is posted on the PR thread.

The 60m cadence balances Vercel deploy latency with not waiting too long for verification. Adjust if your stack deploys faster.

## Config

`lubin-skills/bap-post-deploy-verify/config.yaml`:

```yaml
slack:
  technical_pr_channel_id: "C0BBTDDQ6AJ"
  baptiste_user_id: "U0A87JNV8QP"
github_repo: "the-agentic-company/bap"
deploy_check:
  method: "github_deployments | health_endpoint"
  health_endpoint: "https://heybap.com/api/health"
  build_sha_jsonpath: "$.commit"
  max_wait_minutes: 10
chrome_mcp:
  base_url: "https://heybap.com"
playwright:
  workspace: "lubin-skills/bap-post-deploy-verify"
  base_url_env: "HEYBAP_URL"
  storage_state_path: "~/.heybap-playwright-auth.json"
  reporter: "json"
loop:
  cadence_minutes: 60
  lookback_hours: 24
  pr_label_verified: "post-deploy-verified"
  pr_label_regression: "post-deploy-regression"
```

## Anti-patterns

- Running Mode A on a UI-only finding. The coworker re-run will pass even when the UI is still broken. Pick Mode B or C by surface.
- Generating a fresh Playwright spec every time for the same finding. The point of Mode C is the spec becomes a permanent CI artefact; if it already exists, run it, do not regenerate.
- Closing a finding on a `flake` verdict. Flakes are not validation; surface them, never silently treat them as pass.
- Trusting `gh pr view` for deploy status. Merge != deploy. Always check the deploy signal explicitly (Step 1).
- Posting a regression to Slack without also opening a `bap-finding-router` finding. The Slack ping is a notification; the finding is the unit of work.
- Running this skill on a PR that was not opened by `bap-bug-report` and that has no manually-supplied finding context. The skill is not a generic E2E test runner; without a finding to verify against, the output is noise.
- Letting Playwright auth state expire silently. The skill should fail loud (`verdict: "playwright-auth-expired"`) and ask the operator to re-run `playwright codegen`.

## See also

- [bap-finding-router](../bap-finding-router/SKILL.md): receives `regression` findings from this skill.
- [bap-bug-report](../bap-bug-report/SKILL.md): opens the PRs this skill verifies. Must embed `<!-- FINDING_CONTEXT ... -->` in PR body for context to flow.
- [bap-coworker-test-loop](../bap-coworker-test-loop/SKILL.md): the eval engine for Mode A reuses its `successCriteria` interpreter.
- [transcript-to-bap-coworker](../transcript-to-bap-coworker/SKILL.md): the orchestrator that originally surfaced the findings being verified here.
- `vault/projects/li-seo/qa-visual/` (in the operator's vault): the reference Playwright + Python pattern this skill borrows from.
