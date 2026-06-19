---
name: build-agents-for-bap
description: |
  Battle-tested gotchas for shipping reliable coworkers (agents) on Bap (Heybap).
  Covers skill design, MCP wiring, auth modes, sandbox layout, the two
  recurring runtime failure modes, and debugging via coworker_logs. Use when
  building, debugging, or hardening a Bap coworker, designing a skill that
  generates large artefacts (JSON / HTML / PDF), or wiring an MCP server to
  a coworker. Complements `build-mcp-for-bap` which covers the MCP server
  side.
---

# Build reliable agents on Bap (Heybap)

The default `coworker_create` ships an agent that works — until production. Most field failures fall in 6 buckets. The rules below come from shipping the BATIMGIE and Galien coworkers + the `hyperstack-transcribe` MCP and reading hundreds of run logs.

This skill is the agent-side counterpart of [build-mcp-for-bap](../build-mcp-for-bap/SKILL.md).

## 1. Golden rule — the agent never generates large artefacts

If your skill asks the LLM to produce more than ~5 KB of structured output (JSON, HTML, PDF body, big CSV), you will hit `The runtime stopped making progress. Please retry.` somewhere between 1 in 5 and 1 in 2 runs. The runtime is shaky on long generation paths.

**Fix**: bundle a deterministic script in the skill, have the agent assemble a small `data.json` (just the dynamic bits), and let the script do the rendering / merging / templating.

Wrong pattern (BATIMGIE v1):
- Skill asks agent to build a JSON of 113 socle items + 8 type-specific lists, inject into `template.html` via regex, send the whole HTML back.
- Result: runtime crashes on ~50 % of runs, output truncated when it does finish.

Right pattern (Galien `previsite-pdf-galien`, BATIMGIE v2):
- Skill bundles `render.py` (reportlab / templating).
- Agent only produces `data.json` ≈ 1–3 KB.
- Skill instructs: `find /app/.opencode/skills -name render.py && python <path>/render.py data.json output.html`.
- Script prints a summary that the agent quotes back.

ROI: −80 % tokens, runtime stable, output deterministic, byte-perfect across runs.

## 2. JSON-in-HTML — always escape `</`

When your bundled script injects a JSON payload inside a `<script id="data" type="application/json">…</script>` block, any `</script>` substring in the payload (e.g. in a transcript or a user-pasted comment) prematurely terminates the script tag. The page silently breaks: stuck on `Chargement…`, all buttons inert, JSON parsing throws.

```python
json_blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
html = template.replace("__DATA_JSON__", json_blob)
```

The bug passes unit tests (JSON is valid) and only shows up on real-world payloads with HTML-like fragments.

## 3. `localStorage` on `file://` is blocked

If you ship a standalone HTML file that the user downloads and opens locally, Safari and Firefox (strict mode) refuse `localStorage` on `file://`. All edits silently fail to persist, download buttons appear broken.

Wrap every access:

```js
const mem = {};
const lsGet = k => { try { return localStorage.getItem(k); } catch { return mem[k] ?? null; } };
const lsSet = (k, v) => { try { localStorage.setItem(k, v); } catch { mem[k] = v; } };
```

## 4. Re-download / re-export buttons — capture the original HTML at script load

A common pattern: a "Télécharger fiche à jour" button that reads `document.documentElement.outerHTML`, regex-replaces the data block, and offers a download. **This breaks** because:

- `outerHTML` re-serialises the current DOM (post-render), not the original template.
- Attribute order isn't guaranteed across browsers, so your regex can miss.

Fix: snapshot the original HTML *before* any rendering mutates the DOM, and rebuild from that.

```js
const ORIGINAL_HTML = document.documentElement.outerHTML;
// ...later, on download:
const re = /(<script[^>]*id=["']data["'][^>]*>)([\s\S]*?)(<\/script>)/i;
const payload = JSON.stringify(newData).replace(/<\/script/gi, '<\\/script');
const newHtml = ORIGINAL_HTML.replace(re, (_m, open, _old, close) => open + payload + close);
if (newHtml === ORIGINAL_HTML) throw new Error('data block not found');
```

## 5. MCPs are OFF by default on each coworker

`workspaceMcpServerIds: []` at creation. Registering an MCP at workspace level does **not** auto-attach it to existing coworkers. Source of silent failures: the tool isn't visible to the agent, the agent improvises a plausible-looking response from training data.

After registering the MCP in the workspace UI, update each coworker that should use it:

```ts
coworker_update({
  reference: "@my-coworker",
  workspaceMcpServerIds: ["04d8d12c-..."]
})
```

Confirm via `coworker_get` that the list is non-empty.

## 6. MCP tool names are namespaced

A tool named `transcribe` registered under workspace MCP "transcriptor" becomes `transcriptor_transcribe` inside the coworker. Always use the prefixed name in skill instructions, otherwise the agent searches for a non-existent tool and falls back to inventing the answer.

If you don't know the prefix, ask a first chat_run to list available tools and copy the exact name.

## 7. `chat_run` vs `coworker_run` — client timeout matters

- `chat_run` is synchronous with a client-side timeout (~60 s observed). Use for ping/list/quick tests only.
- `coworker_run` is async: returns a `runId` instantly, poll via `coworker_runs(coworkerId, limit:1)` or `coworker_logs(runId)`.

**For any tool >1 min** (transcription, big LLM step, large file processing), the only reliable path is `coworker_run`. With `chat_run` the work continues server-side but you lose the return value.

## 8. `authSource` × model — the compatibility matrix

| authSource | model family | Works? | Failure mode |
|------------|--------------|--------|--------------|
| `shared`   | `openai/*`   | ✅ if admin connected ChatGPT in workspace | `Selected ChatGPT model is not available for your current connection.` |
| `shared`   | `anthropic/*`| ✅ if admin connected Claude in workspace  | `This Claude model requires the shared workspace connection.` |
| `user`     | `openai/*`   | ✅ if user connected their ChatGPT account | `This ChatGPT model requires your connected account. Connect it in Settings > Connected AI Account.` |
| `user`     | `anthropic/*`| ❌ not supported                            | `Model provider "anthropic" does not support auth source "user".` |

Default safe choice in 2026: **`openai/gpt-5.5` + `shared`**. Earlier in 2026 `gpt-5.4` was the default, but on multi-tool runs with long system prompts (~14 KB) and 3+ wired tools, we now see `gpt-5.4` fail reproducibly with the rule-#9 "non-terminal state" error within ~12 s of generation start. Bumping to `gpt-5.5` clears the failure on the first retry without any other change. Keep `gpt-5.4-mini` in your back pocket for short single-step coworkers (cheaper, faster). Premium tiers like `gpt-5.5-pro` regularly disappear from shared connections without notice; if you depend on a specific one, watch the run errors and have a fallback model ready.

## 9. Two distinct runtime failures — distinguish them

```
errorMessage: "The runtime ended in a non-terminal state and could not be recovered. Retry the task to continue."
```
→ Infra flake (Bap-side), typically fires in the first 5–10 s. **Just retry**, same payload.

```
errorMessage: "The runtime stopped making progress. Please retry."
```
→ Your agent has been generating output for 2–5 min and the stack stalled. **Don't retry as-is** — it'll fail again. Refactor toward rule #1 (bundle a script, shrink the agent output).

Saves hours of false-positive debugging.

## 10. Sandbox layout — never hardcode paths

```
/app/.opencode/skills/<slug>/        ← files you bundle in the skill (template, JSON, .py)
/home/user/coworker-documents/<id>/  ← documents attached to the coworker via UI
/tmp/                                 ← scratch (writeable, wiped each run)
```

In SKILL.md, always tell the agent to discover the skill folder dynamically:

```bash
find /app/.opencode/skills -name fill_fiche.py
python <path>/fill_fiche.py /tmp/data.json /tmp/output.html
```

Root paths (`.opencode` vs `.claude`) can shift between runtimes; the find call survives.

## 11. `coworker_logs(runId)` is the debugger

When a run errored silently or produced bizarre output:

```ts
const log = await coworker_logs({ runId });
// log.run.events[] — chronological tool_use + tool_result entries
// log.run.sandboxFiles — output artefacts (path, fileId, mimeType, sizeBytes)
// log.run.triggerPayload.userInput — exact payload the run received
```

Patterns to grep:
- First `read` of your SKILL.md → did the agent even find it?
- `glob` and `bash find` calls → confirms it located bundled files
- Last `tool_result` before the error → where it stalled
- `sandboxFiles` in the `done` event → list of producible artefacts (download via fileId)

## 12. `requiresUserInput + userInputPrompt` is the input contract

Set `requiresUserInput: true` and write a `userInputPrompt` that documents the expected payload format in plain words:

```
Colle le transcript de la visite et précise le type
(audit | piscine | enr | solaire | pv | decret | mutualisation | std).
Joins les photos en pièces jointes si tu en as.
```

The human triggering the run sees it. Upstream agents (orchestrators) can also read it via `coworker_get(reference)`. Without it, callers improvise — and skip critical inputs.

## 13. Tool results — return structured metadata in the text body

MCPs return free-form text. To let the calling agent quote metrics without re-parsing:

```
<actual tool output>

---
Transcription complete (Groq whisper-large-v3-turbo, 4231 ms, 2435 KB source | silence-strip 1523 ms, 300s → 277s (92% kept)).
```

A `---` footer with a one-line metrics summary works as a stable contract. Apply this to every MCP tool.

## 14. Vercel deploy limits — design with them in mind

If you build an MCP (see [build-mcp-for-bap](../build-mcp-for-bap/SKILL.md)):

- Function unzipped ≤ 250 MB
- Function zipped ≤ 300 MB

This **rules out** native bundles like `onnxruntime-node` (~250 MB across the four platform binaries). When you need ML capabilities:

1. Delegate to a cloud API (Groq, Replicate, OpenAI) — cheapest dev time, lowest bundle.
2. Use a native CLI already present in the runtime (`ffmpeg`, `pdftotext`, `tesseract`) and shell out — zero extra bundle, very fast.
3. WASM ports (`onnxruntime-web`) — sometimes fits, often doesn't.

Concrete example: silero-vad ONNX inference is theoretically more accurate than `ffmpeg silenceremove`, but the ONNX bundle blows past Vercel's limit. The energy-based ffmpeg filter ships in 0 extra bytes, runs at ~150× realtime, and breaks the same whisper hallucination loops that motivated VAD in the first place. Ship the working option.

## 15. `app/output.html` opens the agentic-app panel — and how to wire its buttons

If your skill writes a single-file HTML document to **exactly** `/app/output.html`, Bap renders it in a sandboxed iframe beside the chat (the `agentic-app` skill contract). You don't need to mention it, attach it, or do anything else — the harness picks it up. The iframe is `allow-scripts allow-forms`: no `top.location`, no parent DOM access, no cookies, no parent `localStorage`. The only path back to the chat is `parent.postMessage` with the `bap:agentic-app-prompt` envelope.

This is the right place to put: interactive quote/invoice editors, dashboards, comparison surfaces — anything where "the artefact is the thing they look at" beats "transcript with file attachments". Combine with rule #1: the bundled script produces the filled HTML deterministically, the agent just calls it. Buttons inside the page let the user trigger the next agent turn without typing.

**Output path is hard-coded — say it explicitly in the render instructions.** Bap picks up only `/app/output.html`. Not `/app/outputs/output.html`, not `/tmp/output.html`, not `/app/output_v2.html`, not `output.html` written from an arbitrary cwd. The SKILL.md must instruct the agent to target that exact absolute path, e.g. `python <path>/render.py data.json /app/output.html`, or, when the agent writes the file directly, `Write to /app/output.html (exact path, no variation)`. Any other location leaves the panel blank with no error, no log, no hint — silent failure.

**UI quality — match the platform, not the prototype.** The panel sits next to the chat on the same screen. Treat it like a polished product surface, not a debug dump.

- **Less info = better.** Cut anything that does not drive the user's next action: timestamps, redundant labels ("EMAIL · DRAFT"), decorative metadata, summaries that repeat content already in the panel. Bap pages get glanced at, not read.
- **Standardised look across the coworker.** Cards, status pills, primary/secondary buttons in one consistent style across every panel a coworker emits. A tokens block at the top (`--bg`, `--text`, `--primary`, `--ok`, `--warn`) makes this enforceable across runs.
- **Fill the width, keep prose narrow.** Wide container (1500–1700 px), multi-column grid that collapses to one column under ~1040 px. Long-form text (email body, document preview) keeps a narrow reading column even on big screens.
- **No fake chrome.** No app header, no sidebar, no footer signature, no tab bar. The panel is the inside of a surface, not its own app.
- **Real tool schemas + deep-links.** When the page shows tickets, statuses, fields, use the actual target-tool names and choice IDs (Airtable single-select values, Linear status names) plus an `↗` to the live record. Faked field names cost trust.
- **Concrete editing, not decorative.** Editable values are real `<input>` / `<textarea>` / `<select>` / `contenteditable`, not styled text that looks editable. A button labelled "Edit" toggles edit mode; a button labelled "Send" / "Create" sends. Never combine "Edit & Send" on one button.

A shared design system for these panels (tokens, components, layout primitives reused across coworkers) is the next step and is not yet validated. Until it is, write each panel as if a client were seeing it on a 27-inch screen — same bar as a polished SaaS product page.

**Pre-built templates.** Canonical panels for common patterns live in [`templates/`](./templates/) next to this SKILL — currently `email-validate.html`, more to come (ticket list, devis editor, fiche). Each ships the design tokens, the button contract already wired (postMessage send + result listener + 5 s timeout fallback + one-shot ack), the Edit/Send/Cancel flow, and an auto-resize body. They declare their substitution slots in a top-of-file comment, e.g. `<!-- @slots to, subject, body -->`. Open the folder to see what is available and how the panels are structured; copy and fill the slots when a pattern matches, or use them as reference for a custom panel. Nothing forces you to start from them — they exist so coworkers do not reinvent the same JavaScript and CSS each run.

**The contract.** A button in the page is a transcript-injector. A click sends `postMessage` to the parent, the parent injects the `prompt` field as a new user message in the chat, the coworker reacts as if the user had typed it.

Send (iframe to parent), fired on a real click:

```js
parent.postMessage({
  type: 'bap:agentic-app-prompt',
  version: 1,
  prompt: 'Send the email to client@example.com'
}, '*');
```

Receive (parent to iframe), delivered after the parent processes the message:

```js
window.addEventListener('message', (event) => {
  if (event.data?.type !== 'bap:agentic-app-prompt-result') return;
  // event.data.status === 'sent'     → prompt was accepted and injected
  // event.data.status === 'rejected' → user declined, re-enable the button
});
```

`type` must be exactly `'bap:agentic-app-prompt'`. `version` is `1`. `targetOrigin` stays `'*'`: the agent doesn't know the parent URL at write time. Do not validate `event.origin` either; the parent serves from `heybap.com`, workspace subdomains, or preview URLs.

**User-activation gating.** The browser's user-activation rule applies. Bap will not deliver a `bap:agentic-app-prompt` that fires on page load, on `setTimeout`, in `MutationObserver`, or in any handler not triggered by a real gesture. Bind on `'click'`, do not wrap `postMessage` in `setTimeout` (even 0 ms; the gesture is consumed), and if you need an animation before sending, chain it inside the same handler via `transitionend` or `animationend`. Past one async hop, Safari drops the gesture.

**Pattern: validate / reject.** Disable both buttons on either click; a double-click on the wrong one is the most common production bug here.

```html
<button id="approve">Send</button>
<button id="reject">Cancel</button>
<script>
function send(prompt) {
  document.querySelectorAll('button').forEach(b => b.disabled = true);
  parent.postMessage({type: 'bap:agentic-app-prompt', version: 1, prompt}, '*');
}
document.getElementById('approve').onclick = () => send('Approved. Send the draft above.');
document.getElementById('reject').onclick = () => send('Rejected. Discard the draft and ask me again with my edits.');
</script>
```

**Pattern: edit then submit.** Let the user edit a `<textarea>` or `contenteditable` field, then submit the edited content. Strip backticks to avoid breaking the markdown fence inside the prompt:

```js
document.getElementById('send').addEventListener('click', function () {
  this.disabled = true;
  const body = document.getElementById('body').value.replace(/`/g, "'");
  parent.postMessage({
    type: 'bap:agentic-app-prompt',
    version: 1,
    prompt: 'Send this exact body (do not rephrase):\n\n```\n' + body + '\n```'
  }, '*');
});
```

**Pattern: pick one of N.** Mark the chosen button visually before sending so the user feels the click registered before the agent reacts. The iframe goes inert until the next `output.html` is generated.

```js
document.querySelectorAll('button[data-prompt]').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('button[data-prompt]').forEach(b => b.disabled = true);
    btn.classList.add('chosen');
    parent.postMessage({type: 'bap:agentic-app-prompt', version: 1, prompt: btn.dataset.prompt}, '*');
  });
});
```

**Pattern: structured payload.** For pages where the user edits many fields (a devis with line items, a calendar event with attendees), snapshot the state to JSON and embed it inside a markdown fence in the prompt with a tag header. Lets the agent re-derive intent from one payload rather than from prose:

```js
const payload = snapshotState();  // {entreprise, client, lignes:[{matiere, prix, qte}, ...], marge, tva, ...}
parent.postMessage({
  type: 'bap:agentic-app-prompt',
  version: 1,
  prompt: `[REGENERATE DEVIS]

The user edited values in the mini-app. Use STRICTLY the values below, do not re-generate the image at /app/outputs/piece.png. Re-send the email to client_email with the regenerated PDF.

\`\`\`json
${JSON.stringify(payload, null, 2)}
\`\`\``
}, '*');
```

Used in production by the BATIMGIE `devis-generateur` template: 30+ fields round-tripped through one click without prose-encoding each one.

**Result handling.** Known statuses on `bap:agentic-app-prompt-result`:

| status | meaning | what to do |
|--------|---------|------------|
| `'sent'` | prompt was injected into the chat | optimistic "Sent ✓" flip, then treat the iframe as stale |
| `'rejected'` | user declined the prompt | re-enable buttons, show a discreet hint |

Once accepted, the current `output.html` is stale: the next agent turn may regenerate it with new state. Do not try to mutate the iframe DOM to reflect "Sent ✓" and expect it to stay correct beyond the optimistic flip.

**Timeout fallback.** If the page is opened outside of Bap (local file, preview without shell), the parent never replies. Pair every `postMessage` with a 5 s timeout that re-enables the button, plus a one-shot listener that removes itself once the ack arrives (avoids stale state on multi-button pages):

```js
let acked = false;
const onAck = (e) => {
  if (!e.data || e.data.type !== 'bap:agentic-app-prompt-result') return;
  acked = true;
  window.removeEventListener('message', onAck);
  // handle e.data.status...
};
window.addEventListener('message', onAck);
parent.postMessage({type: 'bap:agentic-app-prompt', version: 1, prompt}, '*');
setTimeout(() => { if (!acked) { btn.textContent = 'Retry'; btn.disabled = false; } }, 5000);
```

**Gotchas.**

1. `parent` vs `window.parent`: same reference, both work.
2. No `type="module"`: the iframe runs the inline `<script>` as a classic script. No top-level `await`, no `import`. Wrap in an IIFE if you need scope.
3. Forms do nothing: `allow-forms` is granted, but a native `<form>` submit produces no `postMessage`. Always intercept with JS, `e.preventDefault()`, then `postMessage`.
4. Long prompts cap at a few KB. For a full edited document, summarise the action ("Send the body as edited in the panel") and let the agent re-read the artifact from the sandbox.
5. Localhost vs prod URLs: chat conversation IDs differ between local dev and prod. A `localhost` `output.html` cannot be opened against a prod conversation, and a prod page cannot be loaded standalone in a browser without the parent shell.
6. Iframe inertness after click: once a prompt is injected, the iframe is read-only from the user's perspective until the agent regenerates it. Do not promise live updates inside the iframe; do not poll for an answer.
7. Curly apostrophes (’) in French copy are safe in template literals or single-quoted strings. ASCII `'` inside an ASCII `'…'` will break the string.
8. **`/app/output.html` is not downloadable as a file.** The path backs the panel iframe; the chat does not auto-attach a download chip to it (Bap reserves the exact name for panel rendering), and the iframe itself has no "save as" affordance. When the user wants to download the rendered HTML (archive, share offline, review outside Bap), have the agent write a parallel copy to `/app/<slug>.html` (any name other than `output.html`, e.g. `/app/devis-saint-lazare.html`) and mention that path in the chat reply. Rule #17 then renders the download chip on the parallel path. Same rule for the underlying file: a chip mentioned in chat that points to a path with no real file on disk downloads as empty content. Always have the agent confirm the absolute path (`ls -la /app/<name>.html`) before announcing "file ready".

## 16. Sandbox CLIs fall back when the MCP says "unavailable"

The system-init message on a run often reads:

> Some selected tools are unavailable for this run:
> - gmail: Gmail MCP tools are unavailable: Workspace MCP Server is not visible to this user.

That refers to the **MCP tool wiring**, not the integration itself. For Gmail, Outlook, Slack and a few others, the sandbox also ships CLI binaries that talk to the same connected account through the integration plumbing. They work:

```bash
google-gmail --account <label> send \
  --to "client@example.com" \
  --subject "..." \
  --body "..." \
  --attachment /app/outputs/piece.png \
  --attachment /app/outputs/devis.pdf
```

`--account <label>` picks between multiple connected accounts (e.g. `lubin`, `louis`). Without it, the default account is used. Same pattern probably exists for `outlook`, `slack-cli`, etc. — check the sandbox before assuming the MCP failure means no path forward. Tell your agent in the SKILL.md to fall back to the CLI when the MCP route shows unavailable, instead of giving up.

## 17. Inline media and download buttons — both are markdown contracts

Two patterns to surface artefacts in the chat, no API call needed.

**Inline image preview** — write standard markdown:

```markdown
![Bague or jaune diamant 0,5ct](https://blob.example.com/img.png)
```

The chat renders with ReactMarkdown + `remarkGfm`, no rehype-sanitize, no `img` override → standard `<img>` element. The URL must be **publicly accessible and stable**. OpenAI's `images/generations` URLs expire in ~1 h — don't paste them, proxy through Vercel Blob or your own MCP first.

**Download buttons** — mention the sandbox path in your message text or markdown:

```
Output saved to /app/outputs/devis.pdf
```

Bap's chat scans every assistant message for `/app/...` and `/home/user/...` paths and turns them into clickable download chips. `turnFinalizer.collectAndExposeMentionedSandboxFiles` does the rest. No `attachments[]` to populate, no fileId to register. Just write the file, then mention its path.

## 18. Reference assets bigger than a few KB go to Vercel Blob, not `uploadDocument`

`mcp__bap__coworker_uploadDocument` accepts base64 content inline. The practical ceiling is ~2 KB before the parameter gets truncated/dropped (observed silently). For anything bigger (HTML templates, font files, mock datasets, design tokens, image references), upload to Vercel Blob and `curl` it at the start of the run.

```ts
// One-shot, anywhere with @vercel/blob access:
import { put } from '@vercel/blob';
const blob = await put('templates/devis-template.html', buf, {
  access: 'public', contentType: 'text/html; charset=utf-8',
  token: process.env.BLOB_READ_WRITE_TOKEN,
  addRandomSuffix: false, allowOverwrite: true,
});
// Returns: https://<hash>.public.blob.vercel-storage.com/templates/devis-template.html
```

Then in the SKILL.md:

```bash
curl -fsSL "https://<hash>.public.blob.vercel-storage.com/templates/devis-template.html" -o /tmp/template.html
```

Re-upload to update the template; every future run picks it up. No coworker re-deploy, no skill churn. Pairs naturally with rule #1: the template lives in Blob, the bundled Python script fills it.

## 19. Multi-step workflows need explicit validation signals or the LLM stalls

A coworker that does "step 1 → ask user → step 2 → ask user → step 3" will stop after step 1 even if the system prompt says "run all steps". The LLM treats the natural pause point (after rendering an image, after reading a doc, after an MCP call) as a turn boundary and emits a final assistant message.

Two fixes, applied together:

**A. Explicit validation signal list.** Tell the prompt which exact phrases trigger a phase transition, e.g.:

> Validation signals (case-insensitive): "ok", "c'est bon", "je valide", "validée", "on garde", "envoie le devis", "génère le devis", "go". On any of these in the user's reply, immediately proceed to phase 2 without asking anything else.

**B. One-shot test sentinel.** Add a `[MODE TEST]` (or similar) marker that the prompt detects and uses to bypass all interactive pauses. Lets you validate the full pipeline in a single `coworker.run` call without faking user replies between steps:

```
If userInput contains [MODE TEST] and all phase-2 inputs are present,
run phase 1 + phase 2 back-to-back without pausing.
```

Without these two, multi-step coworkers feel "stuck" even though the run completes successfully — the LLM just decided it was done.

## 20. `skill_add` uploads disabled — UI enable is mandatory before runs

`mcp__bap__skill_add` returns `enabled: false` on every fresh upload. Disabled skills are *not* written into the sandbox under `/app/.claude/skills/<slug>/` at pre-prompt time — only enabled skills are. So a coworker whose `allowedSkillSlugs` references a disabled skill behaves like this:

```
find /app/.opencode/skills -name SKILL.md | xargs grep -l 'my-slug'   →   (no output)
read /app/.claude/skills/my-slug/SKILL.md                              →   File not found
glob '**/my-slug/**'                                                   →   No files found
[agent gives up, run ends "completed" in 60 s with 0 tools fired]
```

No error in the run log. No warning at upload time. Pre-prompt timings even show `pre_prompt_skills_write_completed` — but that step writes only the built-in integration skills + enabled user skills. Yours is neither.

There is currently **no MCP tool to flip the enabled bit**. `skill_add` only inserts the row. Enable must be done in the workspace UI:

> HeyBap → Skills tab → find the slug → toggle on.

The fact that this isn't programmatic is itself a footgun for any automation that walks the full `skill_add` → `coworker_update` → `coworker_run` pipeline. The orchestrator (`transcript-to-bap-coworker`) treats this as a **HUMAN STOP** between upload and test, the same way an unbound workspace MCP triggers a stop. Wrap your pipeline accordingly:

1. `skill_add` returns ids, `enabled: false`.
2. Surface a human-action message listing the slugs to enable.
3. Block until the human acks.
4. Then run the test loop (rule #19 `[MODE TEST]` payloads will exercise the deployed SKILL.md).

The smoke check that catches this in seconds: pull `coworker_logs(runId)` right after the first test run and look for the first `read` or `bash find` for `SKILL.md`. If the result is `(no output)` or `File not found`, the skill never made it to the sandbox — the rest of the log is irrelevant. Re-enable, re-run.

When (if) `skill_enable` lands as an MCP tool, drop the human stop and call it inline.

## 21. `[MODE TEST]` and other dry-run modes need concrete artifacts, not "log it in chat"

When the dry-run path of a skill bypasses every external tool call (no Salesforce write, no Gmail send, no MCP push), the agent is left with no required work — and gpt-5.5 (and peers) treat that as "I've understood, done", emit a short acknowledgement, and stop. The model never produces the structured payload the skill asked for, even when the prompt explicitly says "log the data in chat".

Observed on `sales-call-wrap-up` v1 (2026-06-18): MODE TEST contract said *"n'écris pas dans Salesforce. Loggue le payload `data` complet en chat + simule la réponse"*. Agent read SKILL.md, thought for 18 s, emitted 512 output tokens, and stopped. No `data` JSON. No note. No custom fields. Run "completed", silently broken. v2 fixed the same agent by requiring 3 file artifacts; same transcript, same model, same MODE TEST sentinel — went from 512 → 1441 output tokens with 3 `sandboxFiles` produced.

**Fix:** require a *concrete artifact* the LLM cannot hand-wave. Force a file write (or a `/app/output.html` panel, or a deterministic-script call). Materialising output in the sandbox both forces real generation and produces `sandboxFiles[]` entries the human can verify post-hoc via `coworker_logs`.

Wrong:
```
[MODE TEST] : n'écris pas dans Salesforce. Loggue le payload `data` complet en chat + simule la réponse.
```

Right:
```
[MODE TEST] = simulation complète, non-négociable. Tu DOIS produire :
1. `data` JSON → écris dans /tmp/wrap-up-data.json puis cat
2. Note Salesforce simulée → écris dans /tmp/wrap-up-note.md puis cat
3. Mapping custom fields → écris dans /tmp/wrap-up-customfields.txt puis cat
4. Chat final structuré (5 lignes, format X)
Tu ne réponds JAMAIS juste "OK MODE TEST".
```

The same principle applies to any "preview", "rehearsal", or "diff-only" mode: concrete artifact > "log to chat". If the agent has nothing to *do*, it will decide there's nothing to *say* either.

This compounds with rule #15: panels (`/app/output.html`) are the cleanest artifact for MODE TEST because the agentic-app surface validates the output visually in one click. For non-panel coworkers, write a `/app/<slug>-data.json` (or similar) and reference its path in the chat reply — rule #17 turns the path into a downloadable chip and the human can spot-check.

## 22. Generating the panel is not validating the panel — interactive features need a real-receiver test

A panel produced under `[MODE TEST]` (rule #21) tells you the agent can extract the data, render the HTML, and write `/app/output.html` correctly. It tells you nothing about whether **clicking the button does anything**. The `parent.postMessage` send path, the parent acknowledgement, the chat injection of the structured prompt, the agent's reaction to that prompt, the actual Gmail/Salesforce/Slack write — all of that is downstream of the click and untested by MODE TEST.

Observed on `sales-followup-drip` (2026-06-18): MODE TEST run produced a clean `output.html` (8127 bytes, sandboxFile listed). Coworker shipped. First real user click on Send → nothing happened in the chat. The agent never reacted because the postMessage either never reached the parent, never injected, or never matched the agent's expected prefix. None of that is visible from the MODE TEST log; the panel was rendered, that was all.

**The rule.** Every coworker that ships an interactive feature (panel buttons, multi-turn user-input gates, real external writes) needs a **two-phase test**:

| Phase | Validates |
|-------|-----------|
| 1. MODE TEST with fake receiver | extraction, render, panel exists in sandboxFiles, structured artefacts produced |
| 2. Real run with tester's own receiver | click → chat injection works, real tool call fires, artefact lands in the target system |

Phase 2 **never** uses the prospect's email/case/channel as receiver — always the tester's own (`lubin@hyperstack.studio`, a sandbox Salesforce org, a `#test-*` Slack channel). The transcript-to-bap-coworker orchestrator gates declaring `live` on phase 2 passing, and surfaces a HUMAN STOP if the button-click loop needs a real gesture (which it does, today, by design of the user-activation rule — see rule #15).

**Minimum acceptable contract for the SKILL.md** of any panel coworker:

```
## Real-receiver E2E test (after MODE TEST passes)

Pour valider que le panel pousse bien la prompt au chat et que ${target_tool} envoie/écrit
pour de vrai, lance UN run sans `[MODE TEST]` avec le tester comme receiver :

- contactEmail / caseId / channel = ton propre <thing>, jamais celui du prospect
- Clique sur Send dans le panel
- Vérifie :
  (a) un message starting with "[<PREFIX FROM TEMPLATE>]" apparaît dans le chat
  (b) l'agent réagit (lit le prompt, appelle ${target_tool})
  (c) l'artefact arrive dans le système cible

Si (a) ne se produit pas → bug template/Bap. Inspecte devtools console du panel.
Si (a) ok mais (b) non → mismatch entre le préfixe du panel et celui que le prompt attend.
Si (b) ok mais (c) non → mauvais nom de tool namespacé (rule #6) ou intégration cassée.
```

This contract is now baked into the canonical templates (`build-agents-for-bap/templates/`). When you write a panel coworker, copy the test contract from the template's matching SKILL.md, fill the target tool name and the prefix, and run both phases before declaring live.

## 23. `type="button"` is mandatory on every `<button>` in an agentic-app panel

Without an explicit `type` attribute, a `<button>` element defaults to `type="submit"`. Inside the Bap agentic-app iframe, this default has a quiet but lethal consequence: the click event fires, JavaScript runs to completion (button visually disables, `parent.postMessage` is called), but the parent React app silently discards the prompt. No chat injection. No error. The button just greys out for 5 s, the user clicks again, same result.

Observed on `sales-followup-drip` v1 (2026-06-18): three buttons (Send / Edit / Cancel) shipped without `type="button"`. Click → button greyed → no message in chat. The reference test panel that Lubin ships (`output-2.html`) had `type="button"` explicit and worked nominally. v2 added `type="button"` and the postMessage went through.

**The rule.** Every `<button>` in `/app/output.html` (or any panel HTML the agent writes) carries `type="button"` explicitly:

```html
<button type="button" class="btn btn-primary" id="send">Send</button>
<button type="button" class="btn btn-ghost"   id="edit">Edit</button>
<button type="button" class="btn btn-secondary" id="cancel">Cancel</button>
```

No exceptions. Even when there is no `<form>` ancestor (and there usually isn't), the default-submit behaviour is intercepted by something in Bap's UI surface and the postMessage gets dropped. The canonical template `templates/email-validate.html` was missing this and is now fixed.

**Diagnostic, when a panel button greys but no chat message appears:**

1. Inspect the panel HTML via devtools. Every `<button>` should have `type="button"`. If any defaults to submit, fix it.
2. Open the panel iframe in `chrome://inspect`, click Send, watch the network panel for the postMessage event. If it fires but no chat injection happens upstream, escalate to Baptiste with the timestamps.
3. Check the panel's console for hydration errors (React #418 with `args[]=HTML` is a known symptom — usually downstream of the type=submit gotcha).

## Build / debug workflow

1. **Design** — write the SKILL.md focused on what the agent *decides*; offload everything mechanical to bundled scripts.
2. **Sandbox** — write the scripts (Python preferred, deterministic, idempotent). Test them locally with realistic `data.json` inputs.
3. **Upload** — push the skill folder to Bap (`skill_add` MCP tool or UI). Verify the agent sees the bundled files via a quick `chat_run` ping.
4. **Coworker config** — `coworker_create` (or `_update`) with: `model`, `authSource`, `allowedSkillSlugs`, `workspaceMcpServerIds`, `requiresUserInput=true`, `userInputPrompt`, `prompt` focused on role + which skill to invoke + output expectations.
5. **First end-to-end** — trigger via `coworker_run`, poll `coworker_runs`. On error, `coworker_logs` → diagnose by event type (rule #9 + #11).
6. **Harden** — for every observed failure mode, decide: agent-side fix (skill prompt), script-side fix (deterministic logic), or coworker-config fix (model/auth/MCP wiring).

## Anti-patterns to recognise

- Skill that says "now produce the full HTML, inject the JSON, save it" — rule #1.
- SKILL.md with hardcoded `/app/.claude/skills/…` paths — rule #10.
- Coworker referencing an MCP tool by short name (`transcribe`) instead of namespaced (`transcriptor_transcribe`) — rule #6.
- Tester running `chat_run` for a multi-minute tool, getting timeout, assuming the tool is broken — rule #7.
- Retrying a "stopped making progress" run without changing anything — rule #9.
- Pasting the OpenAI image-generation URL straight into a markdown `![]( )` and discovering the chat is broken an hour later — rule #17.
- Giving up on a Gmail/Outlook/Slack step because the system-init message says "unavailable" without trying the sandbox CLI — rule #16.
- Stuffing a 17 KB HTML template into `coworker_uploadDocument` and wondering why the agent only sees the first 2 KB — rule #18.
- Multi-step coworker that "stops after the first image" — missing validation signals, rule #19.
- Calling `coworker_run` right after `skill_add` and trusting `status: "completed"` — rule #20. The agent silently can't find the disabled SKILL.md, the run "completes" in 60 s having done nothing.
- Reporting a coworker as "live" without reading `coworker_logs` for the test run. Status `completed` ≠ agent did the right thing — read the events, see what fired.
- MODE TEST contract phrased as "log the data in chat and simulate" — rule #21. The agent will read the skill, decide there's nothing to do, and emit a 300-token ack. Make the simulation produce real files in the sandbox.
- Marking a panel-using coworker `live` after a MODE TEST run because `/app/output.html` appeared in `sandboxFiles`. Rule #22. MODE TEST renders the panel; it does not validate that clicking Send reaches the chat or that Gmail actually sends. Run a phase-2 test with your own email as receiver before declaring done.
- Writing `<button>Send</button>` instead of `<button type="button">Send</button>` in a panel — rule #23. The default is submit, the postMessage gets dropped silently, the button greys and nothing happens. Always set type=button explicitly on every panel button.

## See also

- [build-mcp-for-bap](../build-mcp-for-bap/SKILL.md) — the MCP server side: OAuth dance, Vercel scaffold, native binaries.
- The reference implementations in this repo: `examples/hyperstack-transcribe/` (MCP) and the BATIMGIE skill in your workspace (agent + bundled Python).
