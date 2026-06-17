---
name: bap-coworker-runtime-patterns
description: |
  Operational patterns for shipping a Bap coworker that actually works at runtime. Use when you've nailed the PRD with `bap-coworker-orchestrator` and now need to make the coworker behave correctly in the sandbox, render its outputs in the chat panel, talk to integrations, and survive the model layer. Covers the sandbox filesystem, MCP custom tool naming, Gmail CLI vs MCP, image preview in chat, HTML mini-apps in the agentic panel, weasyprint for PDF, large templates via Vercel Blob, validation signals and one-shot test mode, and which model id is stable for multi-tool runs.
---

# Bap Coworker — Runtime Patterns

Process skills (`bap-coworker-orchestrator`, `bap-coworker-implementer`, `bap-coworker-reviewer`) drive the build loop. This skill covers what makes a coworker actually run correctly once it's shipped — the kind of things you only learn by watching a real run fail.

Most of these patterns aren't bugs in Bap — they're side effects of the runtime (OpenCode + Daytona sandbox), the MCP wiring, and how the LLM behaves under a multi-step prompt. Documenting them in the system prompt up front saves a debugging round on every new coworker.

---

## 1. Sandbox workdir is `/app`, not `/home/user`

The OpenCode sandbox starts every run with `cwd = /app`. Documentation elsewhere references `/home/user/uploads/` because that's where user-attached files land via `prompt-attachments.ts`, but the coworker's own scratch directory is `/app/outputs/`.

Both paths exist (or can be `mkdir -p`'d) and both are detected by Bap's file-path regex in the chat (`/(?<!\S)(\/(?:app|home\/user)\/[^\s\])"']+\.[a-zA-Z0-9]+)(?!\S)/g`) so a mention in markdown turns into a download button. **Use `/app/outputs/` as the canonical place to write generated artifacts** (PNG, PDF, HTML, JSON). It's shorter, lives next to `app/output.html`, and avoids the "let me first `ls /home/user/`" tool call you'll see the LLM make if the prompt is ambiguous.

```bash
mkdir -p /app/outputs
# ... produce files here
```

## 2. `app/output.html` opens the agentic-app panel automatically

If your coworker writes a single-file HTML document to **exactly** `/app/output.html`, Bap renders it in a sandboxed iframe beside the chat — no need to mention it in your reply, the harness picks it up. This is the `agentic-app` skill contract. Useful for:

- Interactive quote/invoice editors (the user tweaks numbers live).
- Status dashboards, decision boards, comparison tables.
- Any artifact where "the thing they look at" is the artifact, not the chat transcript.

The iframe sandbox is `allow-scripts allow-forms` only. The only channel back to the chat is `parent.postMessage({type: "bap:agentic-app-prompt", version: 1, prompt: "..."}, "*")`, gated on a real user interaction (click or submit). See the bundled `agentic-app` skill for the protocol details — your coworker prompt should reference it when the mini-app needs to drive a follow-up turn.

## 3. Workspace MCP tools are namespaced — use the prefixed name

A workspace MCP registered as `my-thing` exposes its tool `do_x` to the coworker as **`my-thing_do_x`** (underscore-joined). The prompt has to use the prefixed name, otherwise the LLM hallucinates a call to `do_x` that the runtime can't route.

Find the prefix by:
- Running the coworker once and reading the `tool_use.toolName` in `coworker.logs` events, or
- Asking the workspace admin who set up the MCP (they named it when pasting the URL).

Bake the exact tool name into the system prompt. Don't paraphrase ("the image generation tool") — name it explicitly: `image-generation_generate_image`.

## 4. `toolAccessMode: "all"` skips the per-coworker MCP allow-list

By default, a coworker only sees the integrations and workspace MCPs that are explicitly listed in `allowedIntegrations` / `allowedWorkspaceMcpServerIds`. Adding a freshly registered workspace MCP to every coworker is an extra UI click each time.

When you call `mcp__bap__coworker_create` or `coworker_update`, set `toolAccessMode: "all"`. The coworker inherits every workspace-level tool automatically. Trade-off: you lose the explicit scoping; only use this on coworkers you trust to pick the right tool from a large list.

## 5. Gmail send: the sandbox CLI works even when the MCP says "unavailable"

The system-init message often reads:

> Some selected tools are unavailable for this run:
> - gmail: Gmail MCP tools are unavailable: Workspace MCP Server is not visible to this user.

That message refers to the **MCP tool wiring**. The sandbox also ships a CLI binary called `google-gmail` that talks to the same Gmail account through the connected-integration plumbing. It works. The coworker prompt should explicitly tell the LLM **not to give up on the MCP failure** and fall back to the CLI:

```bash
google-gmail --account <label> send \
  --to "client@example.com" \
  --subject "..." \
  --body "..." \
  --attachment /app/outputs/piece.png \
  --attachment /app/outputs/devis.pdf
```

`--account <label>` selects between multiple connected Gmail accounts when several are linked (e.g. `lubin`, `louis`). Without it, the CLI picks the default.

The same pattern probably applies to other Workspace-MCP-fronted integrations (Outlook, Slack…) — check the sandbox for a matching CLI before assuming the MCP failure means no path forward.

## 6. Inline image preview = plain markdown, but the URL must be stable

The chat renders LLM messages with ReactMarkdown (`remarkGfm`, no rehype-sanitize, no `img` override). A line like:

```markdown
![Bague or jaune](https://example.com/img.png)
```

…becomes a real `<img>` in the chat bubble. The URL must:

- Be **publicly accessible** (no auth, no CORS issues — Bap fetches from the user's browser).
- Survive long enough that re-opening the conversation later still shows the image.

OpenAI's `images/generations` / `images/edits` response URLs **expire in ~1 hour**. Don't paste them directly — proxy through Vercel Blob, S3, or an MCP that stores the upload and returns a permanent URL.

## 7. Download buttons = just mention the sandbox path in your message

The chat scans every assistant message for `/app/...` or `/home/user/...` paths and turns them into clickable download chips (`MarkdownFileButton`). To expose a file to the user:

1. Write it to `/app/outputs/<name>.<ext>`.
2. Mention `/app/outputs/<name>.<ext>` somewhere in your message text or markdown.

That's it. No `attachments` array to populate, no `sandboxFiles` to register. Bap's `turnFinalizer.collectAndExposeMentionedSandboxFiles` does the rest.

Don't use the URL of the file. Use the local sandbox path. The path is what triggers the button.

## 8. Large templates and reference data go to Vercel Blob, not `uploadDocument`

`mcp__bap__coworker_uploadDocument` accepts base64 inline. Practical ceiling: a few KB. Anything bigger (HTML templates, font files, mock datasets, design tokens) gets truncated silently or fails the parameter validation.

For ≥5 KB reference assets:

1. `vercel blob put ./template.html` (or use `@vercel/blob` from a one-shot Node script).
2. Paste the resulting `https://<hash>.public.blob.vercel-storage.com/...` URL into the coworker system prompt.
3. Tell the coworker to `curl -fsSL <URL> -o /tmp/<filename>` at the start of its run.

The Blob URL is the source of truth — re-upload to update the template and every future run picks it up. No coworker re-deploy.

## 9. PDF from HTML: weasyprint installs cleanly in the sandbox

The Daytona base image doesn't ship a PDF tool, but `pip install --quiet weasyprint` runs in ~10 s and works. Pattern:

```bash
pip install --quiet weasyprint 2>&1 | tail -1
```

```python
from weasyprint import HTML
HTML(string=devis_html).write_pdf('/app/outputs/devis.pdf')
```

For A4 print rendering, add a `@page` rule in the inline `<style>`:

```css
@page { size: A4; margin: 18mm 16mm; }
body { background: #fff; margin: 0; }
```

**Embed images as base64 data URIs**, not URLs. Weasyprint will fetch remote URLs by default, but if the sandbox loses network mid-render or the URL needs an auth header, the PDF ends up with a broken-image placeholder. Encode once, embed in the HTML, done.

For French-formatted euros, format in Python (weasyprint doesn't have CSS-level locale formatting):

```python
def fr_euro(n):
    s = f"{n:,.2f}"
    return s.replace(',', ' ').replace('.', ',') + ' €'
```

## 10. Multi-step workflows need explicit validation signals or the LLM stalls

A coworker that does "step 1 → wait for user → step 2 → wait → step 3" will stop after step 1 even if you ask it to "go through all steps". The LLM treats the natural pause point (after rendering an image, after reading a doc) as a turn boundary and emits a final message.

Two fixes, used together:

**A. Explicit validation signal list in the prompt.** Tell the model which phrases trigger a phase transition:

> Signals (case-insensitive): "ok", "c'est bon", "je valide", "validée", "on garde", "envoie le devis", "génère le devis", "go". On any of these in the user message, immediately proceed to phase 2 without asking anything else.

**B. One-shot test mode for internal runs.** Add a sentinel like `[MODE TEST]` that the prompt detects and uses to bypass all interactive pauses. Lets you validate the full pipeline in a single `coworker.run` call without having to fake user replies:

```
If userInput contains [MODE TEST] and all phase-2 inputs are present, run phase 1 + phase 2 back-to-back without pausing.
```

Without these two, multi-step coworkers feel "stuck" even though the run completes successfully — the LLM just decided it was done.

## 11. Model choice matters — `gpt-5.5` is the safe default for multi-tool runs

If a run errors out in **under 20 s** with:

> The runtime ended in a non-terminal state and could not be recovered. Retry the task to continue.

…it's usually the model layer (rate-limit on the shared key, model-side hiccup, or a `gpt-5.4`-class instability we observed reproducibly). Bumping `model: "openai/gpt-5.5"` cleared the failure on the first retry on a 14 KB system prompt with 3+ tools wired in.

Rule of thumb:

- **gpt-5.5** — default for production coworkers, especially multi-tool. Stable on long system prompts.
- **gpt-5.4-mini** — cheaper/faster, fine for "fill this template" or "summarize this doc" single-step jobs.
- **gpt-5.4** — works most of the time but is the one we saw fail. Don't pin to it for new coworkers.

`gpt-5.1-codex-max` and `gpt-5.2` are also available; we haven't stress-tested them.

## 12. Clean up template artifacts before rendering the mini-app

If your coworker fills an HTML template (quote generator, report shell, slide deck), the unfilled template often ships with visible scaffolding: a `<b>TEMPLATE</b>` banner, italic placeholder text (`[Jewel photo — added on each run]`), generic `<title>`. These survive a naive `str.replace(client_name, …)` pass and show up in the final mini-app — looking unprofessional.

Bake the cleanup into the build step. For each placeholder element, write a `re.sub` or `html.replace` that removes it deterministically:

```python
# A.1) Remove the TEMPLATE banner
html = re.sub(
    r'<div style="max-width:[^"]+">\s*<div style="border:1px dashed[^>]+>\s*<b[^>]*>TEMPLATE</b>[^<]+</div>\s*</div>\s*',
    '', html, flags=re.DOTALL,
)
# A.2) Remove the photo placeholder italic
html = re.sub(
    r'<span style="color:#9fb0c2;font-size:13px;font-style:italic">\[Jewel photo[^<]+</span>\s*',
    '', html,
)
# A.3) Personalize <title>
html = html.replace('<title>Quote Generator — Template</title>',
                    f'<title>Quote — {client_nom} — {entreprise}</title>')
```

After the build, **assert** with a tiny Python check that each artifact is gone before the run continues. Catches regressions when the template gets a new "TEMPLATE" overlay you forgot about:

```python
assert "Shell of the Quote Generator" not in html
assert "[Jewel photo" not in html
assert "<title>Quote Generator — Template</title>" not in html
```

## When this skill is not the right tool

- You're still scoping the coworker → use `bap-coworker-orchestrator`.
- You're implementing the PRD step by step → use `bap-coworker-implementer`.
- You're gating an implementation for merge → use `bap-coworker-reviewer`.

This skill is the *what to bake into the system prompt* layer that sits between the PRD and the working coworker. Add it as supplementary reading for implementers and reviewers — both benefit from the runtime context.
