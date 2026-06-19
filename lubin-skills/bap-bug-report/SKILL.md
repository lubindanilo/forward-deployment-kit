---
name: bap-bug-report
description: |
  Deeply analyse a bug or feature request in the Bap repo
  (the-agentic-company/bap), implement the fix on a branch, open a Pull
  Request on GitHub, and create a Linear ticket in team `Bap` (key BAP)
  at status `In Review`, labelled `Bug` (or `Feature`) + `Dogfooding`,
  assigned to the operator (Lubin), with the PR attached as a link. Linear's
  notifications (Slack integration, email, in-app) replace any direct
  Slack post. Use when the user describes a bug or feature gap in Bap
  / HeyBap (chat, coworker output, attachments, MCP, skills UI, run
  flow…) and wants the fix proposed as a PR + a tracked Linear ticket
  without manual copy-paste. Triggers: "Bug: …", "Feature: …", "ouvre
  un ticket pour …", "open a PR for …", "audit the bug …".
---

# Bap bug / feature → PR + Linear ticket

Goal: the user gives a short one-line bug or feature description; you investigate the Bap codebase in depth; you **create a Linear ticket in team `Bap` first to obtain its identifier (e.g. `BAP-123`), then implement the fix on a branch in `the-agentic-company/bap`, open a Pull Request that references the ticket identifier in its title, and update the Linear ticket to status `In Review` with the PR attached as a link**.

The Linear ticket is the report. Linear's own integrations notify the team on create / update; no direct Slack post is sent from this skill.

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

## Step 2 — reproduce in the live product (Chrome MCP, when relevant)

For any UI / UX / layout / interaction / visual bug, **reproduce the issue live in https://heybap.com before concluding**. Static code reading alone misses half the picture (overflow, z-index, layout collapse, hover states, transition glitches, race conditions on load).

Use the Claude-in-Chrome MCP tools (`mcp__Claude_in_Chrome__*`):

- `navigate` to https://heybap.com and reach the relevant route. The user's session should already be authenticated.
- Reproduce the user's exact scenario: open the run, the coworker, the HTML output, the attachment flow, whatever the bug describes.
- `preview_screenshot` (or `computer` action) to capture the broken state. Take 1 to 3 screenshots: one wide shot, one zoomed, one of the working baseline for comparison if relevant.
- `read_console_messages` and `read_network_requests` to catch silent errors, 4xx/5xx, unexpected payloads.
- Use `find` / `javascript_tool` to probe DOM state, computed styles, dataset attributes.
- Save screenshot file paths. Reference them in the Linear ticket description (Linear renders local paths as plain text, but the team can upload them on the ticket via the Linear UI if needed).

Skip Chrome reproduction only for purely backend / non-visual bugs. Justify the skip in one line in the ticket description.

The visual evidence refines the diagnosis. It does not replace the code-level root cause.

## Step 3 — investigate the codebase in depth (use the Agent tool)

Delegate to a subagent (`general-purpose` or `Explore`) with a self-contained briefing including:

- The exact bug / feature description.
- The repo path on disk.
- The known monorepo layout above.
- The Chrome findings from Step 2 (screenshots, console errors, computed styles).
- An instruction to check **both** the chat surface and the coworker surface when the issue could exist in either (asymmetry is a common Bap pattern, see Historical Bugs at the bottom).
- A requirement that every claim carries a `file:line` reference.

Cover systematically:

1. Frontend filters / validation — `accept=`, MIME whitelists, size caps, silent `.filter(...)` drops, dropzone configs.
2. Client → server boundary — orpc routers, payload serialization (`dataUrl` base64 in JSON body is a known cost center).
3. Server services — sandbox limits, storage validation.
4. Surface asymmetry.
5. UX feedback — silent drops with no toast/error.
6. **DO NOT assume Vercel, S3, Cloudflare, etc.** Bap is **not** on Vercel. Frame body-limit / runtime claims as "any host body limit", not vendor-specific.

## Step 4 — design the fix, honestly

Produce:

- **Quick fix** (the 10-minute unblock). This is what the PR will implement. Often: raise a constant, replace a silent `.filter()` with a toast, add a missing listener, copy a hook from the working surface to the broken one.
- **Durable fix** (the structural property). Goes in the PR body and the Linear ticket as a follow-up note, not as code. Describe the **property** the fix should have, not a specific transport / vendor.
- **Alternatives considered**: 2-3 bullets, one line each, trade-offs.
- **Implications**: which other surfaces / hooks / constants get touched, migration concerns, data impact.

## Step 5 — dedup check (mandatory, before any side effect)

Two checks, both required. The router may have done a first pass, but redo them here with the post-investigation knowledge.

**a) Linear `Bap` team** for an open ticket on the same root cause (60-day window):

```
mcp__linear__list_issues({
  team: "BAP",
  query: "<distinctive token, e.g. file path or symbol>",
  createdAt: "-P60D",
  limit: 50,
  includeArchived: false
})
```

Run 2 or 3 queries with different tokens. Ignore tickets in status `Canceled` or `Duplicate`. If a clear duplicate exists, **stop here**: do not open a PR, do not create a new ticket. Return to the caller with `Already covered by: BAP-<n> <ticket URL>` and the draft you would have shipped, so the user can comment on the existing ticket.

**b) Open PRs on the bap repo** touching the same files or symptom:

```bash
gh pr list --state open --search "<keyword>" --json number,title,headRefName,url
```

Run with 2-3 keyword variants (file path, symbol name, symptom noun). If a clear duplicate PR exists, check whether it already has a `BAP-` identifier in its title; if yes, **stop** and return that identifier + PR URL. If no, the next step will create the Linear ticket and you should comment on the existing PR with the new ticket identifier instead of opening a second PR.

Borderline (one shared keyword, different root cause) → continue; mention the related ticket / PR in the new ticket description.

Never silently skip. Never create a duplicate.

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

**Ticket body template** (markdown, French ok since the team is French):

```markdown
## Symptôme
<une ligne : ce que voit l'utilisateur>

## Cause racine
<2-4 lignes, ancrées sur file:line>

## Fix proposé (quick)
<le diff de la PR, file:line touché>

## Fix durable (suivi, pas dans cette PR)
<la propriété structurelle que le fix devrait avoir>

## Alternatives considérées
- <option 1> : <trade-off>
- <option 2> : <trade-off>

## Repro
<une ligne : où cliquer dans https://heybap.com>
Screenshots : <chemins locaux, à uploader manuellement si besoin>

## Régression connue
<commit hash + subject si trouvé, sinon "non identifié">

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

Commit with a Bap-style message that references the ticket:

```
<Area>: <verb> <object> (BAP-<n>)

<one paragraph: what changed and why, with file:line refs>
```

Areas seen on the repo: `Web`, `Sandbox`, `Skills`, `Core`, `Agents`, `Chat`. Pick the most fitting.

## Step 8 — open the PR

```bash
git push -u origin <branch>
gh pr create \
  --title "BAP-<n> <Area>: <verb> <object>" \
  --base main \
  --body "$(cat <<'EOF'
Closes BAP-<n>

## What this PR does
<the quick fix, with the touched file:line>

## Linear ticket
The full context (symptom, root cause, alternatives, FINDING_CONTEXT for post-deploy verify) lives in BAP-<n>: https://linear.app/heybap/issue/BAP-<n>

## Repro
<one line: where to click in https://heybap.com>
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

## Step 9 — update the Linear ticket: status In Review + attach PR

```
mcp__linear__save_issue({
  id: "BAP-<n>",
  state: "<config.linear.statuses.in_review>",
  links: [
    { url: "<PR URL>", title: "PR #<num> — <PR title>" }
  ]
})
```

Linear's GitHub integration usually attaches the PR automatically once the branch lands (because the branch name contains `bap-<n>`). The explicit `links` attachment is a belt-and-braces fallback if the integration is delayed.

`links` is append-only, so re-running this step in a retry is safe.

## Step 10 — return to the user

Output exactly three blocks, no commentary, no headers:

1. The Linear ticket: `BAP-<n>  <ticket URL>`.
2. The PR URL.
3. If Chrome screenshots were captured in Step 2, one final line: `Screenshots: <paths>` so the user can attach them to the Linear ticket manually.

If the dedup step (Step 5) stopped you, output instead:
- `Already covered by: BAP-<n> <ticket URL>` (or the existing PR URL if no ticket exists yet)
- The draft ticket description you would have shipped, so the user can update the existing ticket / PR.

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
- Do not post to Slack from this skill. Linear's integrations broadcast create / update events; that is the team's chosen notification surface.
- Do not open the PR before the Linear ticket. The ticket identifier needs to be in the branch + title.
- Do not skip the FINDING_CONTEXT JSON block. The post-deploy verifier depends on it to close the loop.

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
dedup_window_days: 60
```

Keep this in sync with `lubin-skills/bap-finding-router/config.yaml`. The router is the canonical source.

## See also

- [bap-finding-router](../bap-finding-router/SKILL.md): the gate that dispatches SIMPLE findings to this skill.
- [bap-feature-brainstorm](../../.claude/skills/bap-feature-brainstorm/SKILL.md): the COMPLEX counterpart that creates a Linear ticket at status `Triage` with `Need More Shaping` instead of a PR.
- [bap-post-deploy-verify](../bap-post-deploy-verify/SKILL.md): closes the loop by transitioning this ticket to `Live` after the merge + deploy is verified in prod.
