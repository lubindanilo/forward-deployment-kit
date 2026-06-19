---
name: bap-bug-report
description: |
  Deeply analyse a bug or feature request in the Bap repo
  (the-agentic-company/bap), implement the fix on a branch, open a Pull
  Request on GitHub, and autonomously post the PR link to Slack
  #technical-pr (workspace: The Agentic Company) with @Baptiste pinged.
  Use when the user describes a bug or feature gap in Bap / Heybap (chat,
  coworker output, attachments, MCP, skills UI, run flow…) and wants the
  fix proposed as a PR to the CTO without manual copy-paste. Triggers:
  "Bug: …", "Feature: …", "explain this to Baptiste", "open a PR for …",
  "audit the bug …".
---

# Bap bug / feature → PR + Slack notification

Goal: the user gives a short one-line bug or feature description; you investigate the Bap codebase in depth; you **implement the fix on a branch in `the-agentic-company/bap` and open a Pull Request**; you then post a short notification in Slack `#technical-pr` (workspace **The Agentic Company**), pinging **Baptiste (CTO)** at the start.

No more direct Slack post in `#bugs` or `#feature-request`. The PR is the report. Slack only notifies.

## Repo & context (always)

- GitHub: https://github.com/the-agentic-company/bap
- Owner: `the-agentic-company`.
- CTO: Baptiste. The user (Lubin) is Chief of Staff at Hyperstack/CmdClaw and uses Bap heavily as a power user.
- Codebase layout (monorepo):
  - `apps/web/` — Next.js frontend (chat, coworker UIs, prompt bar, attachments, settings).
  - `packages/core/` — server services (sandbox, file service, orpc routers like `generation.startGeneration`, `coworker.trigger`).
  - Two recurring UI surfaces matter and are often asymmetric:
    1. **Chat panel** (`apps/web/src/components/chat/…`).
    2. **Coworker run output** (`apps/web/src/routes/agents/-components/coworker-info-panels.tsx`) + the prototype variant `apps/web/src/routes/prototype/coworker/info/-components/coworker-info-prototype.tsx`.
  - MIME validation for skill / coworker documents: `apps/web/src/server/storage/validation.ts` (separate from chat attachments).
  - Sandbox file limit: `packages/core/src/server/services/sandbox-file-service.ts`.
- PR conventions on this repo (look at recent merged PRs to confirm):
  - Title format: `<Area>: <verb> <object>` (e.g. `Web: fix coworker builder chat scrolling`, `Sandbox: fix coworker APP_URL sync`, `Skills: enable imports by default`).
  - Branch format: `fix/<slug>` for bugs, `feat/<slug>` for features. Slug is short, kebab-case.
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
- Save screenshot file paths. Include them in the PR body (markdown image refs to local paths are fine, GitHub will not render them but they document the investigation) and surface them to the user at the end so they can drop them into the PR conversation manually.

Skip Chrome reproduction only for purely backend / non-visual bugs. Justify the skip in one line.

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
- **Durable fix** (the structural property). Goes in the PR body as a follow-up note, not as code. Describe the **property** the fix should have, not a specific transport / vendor.
- **Alternatives considered**: 2-3 bullets, one line each, trade-offs.
- **Implications**: which other surfaces / hooks / constants get touched, migration concerns, data impact.

## Step 5 — implement the fix on a branch

On the local clone:

```bash
cd /tmp/bap-investigation   # or wherever the clone lives
git checkout main && git pull
git checkout -b fix/<short-slug>     # or feat/<short-slug> for features
```

Slug rules: kebab-case, ≤4 words, derived from the bug noun (e.g. `chat-column-collapse`, `audio-attachment-size`, `coworker-postmessage-listener`).

**Implement the QUICK FIX, nothing more.** Constraints:

- Smallest possible diff. One or two files.
- No refactor, no unrelated cleanup, no defensive coding for cases that cannot happen, no comments explaining the fix (the PR body explains).
- No new abstractions for hypothetical future use.
- If the durable fix is large (new hook, new endpoint, new component), it does NOT go in this PR. Mention it in the PR body for follow-up.
- For **feature requests**: if the implementation is larger than ~50 lines, open a **draft** PR with the smallest scaffold and a detailed TODO list in the body. Do not autonomously ship a 500-line feature without review.

Commit with a Bap-style message:

```
<Area>: <verb> <object>

<one paragraph: what changed and why, with file:line refs>
```

Areas seen on the repo: `Web`, `Sandbox`, `Skills`, `Core`, `Agents`, `Chat`. Pick the most fitting.

## Step 6 — open the PR

```bash
git push -u origin <branch>
gh pr create \
  --title "<Area>: <verb> <object>" \
  --base main \
  --body "$(cat <<'EOF'
## Bug
<one-line restatement>

## Symptom
<what the user sees, 1 line>

## Root cause
<root cause grounded in file:line refs, 2-4 lines>

## What this PR does
<the quick fix, with the touched file:line>

## Durable fix (follow-up, not in this PR)
<property the structural fix should have, 1-2 lines>

## Alternatives considered
- <option 1>: <trade-off>
- <option 2>: <trade-off>

## Regression commit (if found)
`<hash> <subject>`

## Repro
<one line: where to click in https://heybap.com to see the bug; screenshot paths if any>
EOF
)"
```

For features, add `--draft`. For bugs, non-draft.

Capture the PR URL returned by `gh pr create`. You will need it for Step 8.

PR title rules:
- Match the convention from recent merged PRs in `the-agentic-company/bap`: `<Area>: <verb> <object>`. Check `gh pr list --state merged --limit 10` if unsure.
- Under 70 chars.
- No em-dashes anywhere.

## Step 7 — dedup check (mandatory, before notifying Slack)

Two checks, both required:

**a) Open PRs on the bap repo** touching the same files or symptom:

```bash
gh pr list --state open --search "<keyword>" --json number,title,headRefName,url
```

Run with 2-3 keyword variants (file path, symbol name, symptom noun). If a clear duplicate exists, **close your PR** (`gh pr close <number>`) and skip Step 8. Return to the user with the existing PR link + a one-line note.

**b) Slack `#technical-pr`** (channel id `C0BBTDDQ6AJ`) for recent posts referencing the same files or symptom (60-day window):

```
slack_search_public(query="in:#technical-pr <distinctive token>")
```

Run 2-3 short queries. If a clear duplicate exists, **close your PR** and skip Step 8. Return the existing thread permalink.

Borderline (one shared keyword, different root cause) → keep the PR, post in Slack but mention the related thread in the return-to-user note.

Never silently skip. Never post when a clear duplicate exists.

## Step 8 — notify in Slack `#technical-pr` (autonomous)

Post a **short** message in `#technical-pr` (`C0BBTDDQ6AJ`), pinging Baptiste at the start.

Baptiste's Slack user id: `U0A87JNV8QP`. Prepend `<@U0A87JNV8QP> ` (with trailing space).

Message structure (target: 60-100 words, no more):

```
<@U0A87JNV8QP> <PR URL>

*<one-line summary, same as PR title>*

<2-3 lines: what breaks for the user + the one-line root cause with the key file:line>

<one line: what this PR changes>
```

Style:

- English, sober, factual.
- **NO em-dashes (— / –).**
- No fluff, no "I just opened a PR", no business framing.
- The PR body holds the depth. The Slack message is a notification, not a duplicate of the PR.

Send via `mcp__aa816864-db59-4de1-a375-68c8cccbfe71__slack_send_message` (not the draft variant). `channel_id = "C0BBTDDQ6AJ"`.

If the message accidentally crosses ~120 words, cut it. Slack #technical-pr is a stream, not a doc.

## Step 9 — return to the user

Output exactly three blocks, no commentary, no headers:

1. The PR URL.
2. The Slack permalink returned by `slack_send_message`, prefixed with `Posted: `.
3. If Chrome screenshots were captured in Step 2, one final line: `Screenshots: <paths>` so the user can attach them to the PR conversation manually.

If the dedup step closed your PR, output instead:
- `Already covered by: <existing PR URL or Slack permalink>`
- The draft PR body you would have shipped, so the user can comment on the existing thread.

## Historical bugs (anchors)

Use as sanity checks if the current bug sounds similar:

- **`bap:agentic-app-prompt` button works in chat, not in coworker output** → asymmetry. Listener at `apps/web/src/components/chat/agentic-app-panel.tsx:110-183`, missing in `apps/web/src/routes/agents/-components/coworker-info-panels.tsx` (AgenticAppFrame L283, iframes L384 + L404) and in the prototype variant. Fix: extract listener into a shared hook, wire on both surfaces, force `onSendPrompt` to post into `run.conversationId`.
- **Attaching m4a / mp3 in run chat does nothing** → not a MIME filter. Silent 10 MB cap: `apps/web/src/components/prompt-bar.tsx:56` + L319 `.filter(...)` without toast. Dup pattern in `chat-input.tsx:17/123` and `inbox-create-input.tsx:24/81`. Compounding: attachments base64 in orpc body (+33%). Sandbox already at 50 MB (`packages/core/src/server/services/sandbox-file-service.ts:25`). Durable fix: get binary out of JSON body, transport agnostic.
- **Chat column collapses to 0% in coworker info view, no restore** → regression. `apps/web/src/components/ui/dual-panel-workspace.tsx:130-147` sets `isLeftPanelCollapsedByDrag = true` past the 25% threshold, L191-204 forces width 0%, flag never reset on pointerup. Only `coworker-info-page.tsx:482` and `:743` opt in via `allowLeftPanelDragCollapse`. Regression commit: `679c7fd6`.

## What NOT to do

- Do not push to `main`. Always a branch + PR.
- Do not implement the durable fix if it is larger than a small diff. It belongs in the follow-up section of the PR body.
- Do not add comments in the code explaining the bug. The PR body is the explanation.
- Do not assume Vercel / S3 / specific vendors unless the repo already uses them.
- Do not claim something is broken without a `file:line` proof.
- Do not use em-dashes anywhere (commit message, PR title, PR body, Slack post).
- Do not post in `#bugs` or `#feature-request` from this skill. Those channels are for free-form reports, not for PR notifications. This skill posts only in `#technical-pr`.
- Do not open a second Slack message. One notification per PR.
