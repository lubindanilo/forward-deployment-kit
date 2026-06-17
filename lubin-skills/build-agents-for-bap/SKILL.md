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

Default safe choice in 2026: `openai/gpt-5.4` + `shared`. Premium tiers like `gpt-5.5-pro` regularly disappear from shared connections without notice; if you depend on a specific one, watch the run errors and have a fallback model ready.

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

## See also

- [build-mcp-for-bap](../build-mcp-for-bap/SKILL.md) — the MCP server side: OAuth dance, Vercel scaffold, native binaries.
- The reference implementations in this repo: `examples/hyperstack-transcribe/` (MCP) and the BATIMGIE skill in your workspace (agent + bundled Python).
