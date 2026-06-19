---
name: build-mini-apps-for-bap
description: |
  Build INTERACTIVE mini-apps inside Bap (Heybap) coworkers — not just static HTML pages.
  Pattern: pair a thin Bap skill (renders /app/output.html once) with an EXTERNAL backend
  (Vercel / Fly / Cloudflare) that handles live state, async work, persistence, and pub/sub.
  Use when the coworker needs anything beyond a one-shot artefact: live updates,
  user actions that mutate state, long-running jobs, multi-user collaboration, dashboards,
  copilots, queues, real-time anything. Complements `build-agents-for-bap` (skill side) and
  `build-mcp-for-bap` (MCP server side) — this skill is about the HTML+backend pair.
---

# Build INTERACTIVE mini-apps on Bap (Heybap)

Bap's `/app/output.html` is officially just a "rendered page", served once per run in a sandboxed iframe. That misleads people. The sandbox is `allow-scripts allow-forms`, so the HTML can `fetch` and open `EventSource` connections against any HTTPS endpoint it wants. That single fact turns Bap from a "static viewer" into a **shell for real-time, stateful, mutable apps** — provided the backend lives outside Bap.

The `heybap-live-copilot` coworker is the reference build: each run, the agent calls one MCP tool that spins up a session on a Vercel app, then writes a self-contained HTML that opens an SSE stream to that Vercel app. The user sees a fully live UI (transcript scrolling, AI suggestions streaming) inside Bap — but nothing live actually runs *inside* Bap.

Use this skill to ship that pattern in hours instead of days.

## Mental model

```
┌──────────────────┐   1. coworker_run             ┌─────────────────────┐
│   Bap coworker   │ ────────────────────────────► │  External backend   │
│   (chat agent)   │   (MCP tool: start_session)   │  Vercel / Fly / CF  │
│                  │ ◄──────────────────────────── │  Next.js + KV/Pub-  │
│                  │   session_id + live_url       │  Sub + your logic   │
└────────┬─────────┘                                └──────────┬──────────┘
         │ 2. python render.py <live_url>                      ▲
         ▼                                                     │
 ┌────────────────┐  3. EventSource(live_url + /stream)        │
 │/app/output.html│ ◄────────── SSE stream (events) ────────── │
 │ (sandboxed     │                                            │
 │  iframe, JS    │  4. fetch POST /api/action ────────────────┘
 │  allowed)      │     (CORS-enabled mutations)
 └────────────────┘
```

The Bap side is dumb: it renders ONE HTML file with a `<live_url>` baked in. All state, all logic, all persistence lives on the backend. The HTML reconnects automatically (`EventSource` retries on disconnect) and can post user actions back via `fetch` — both work fine inside Bap's sandbox.

## When to use this pattern

Yes:
- Live copilot / co-pilot during an external event (call, ticket, support session)
- Real-time dashboards (queues, deals pipeline, support tickets, ETA, anything)
- Long-running jobs where the user needs to watch progress (deploys, batch processing, scrapes)
- Interactive review/approval queues (validate, reject, comment — each click POSTs to backend)
- Multi-step wizards that mutate external state (CRM update, send email, push to Jira)
- Anything that needs to survive a page reload — Bap re-runs the skill, the page reads fresh state from backend
- Anything that needs >1 user touching the same view

No (use a plain `render.py` to `/app/output.html` with no backend):
- One-shot artefact (PDF preview, report, summary, deck) — pure static is simpler
- The agent has all the data in `data.json` and just needs HTML around it

## 1. The Bap skill is a 3-step thin facade

Your SKILL.md does THREE things and nothing else:

1. Read any per-run inputs (a URL, a config file, a `context.md`) from the chat or the sandbox.
2. Call ONE MCP tool that creates a session on the backend and returns `{ session_id, live_url }`.
3. Run a bundled `render_panel.py` that writes `/app/output.html` with `<live_url>` baked in.

That's it. No HTML in the prompt. No multi-step orchestration in chat. No descriptive messages. One sentence in chat ("Lancé. Plein écran : <live_url>") and shut up. The HTML is the UI; the chat is not.

Anti-pattern: agent that "narrates" what's happening in the panel ("now connecting...", "session started...", "fetching data..."). The HTML already shows that. The agent's job is over the second `output.html` is written.

## 2. The HTML is self-contained AND stateless

Bap's CSP blocks external CDNs, external fonts, external images, anything not inline. So:

- All CSS in a single `<style>` block.
- All JS in a single `<script>` block.
- No `<link rel="stylesheet">`, no `<script src="...">`, no `<img src="https://...">`. Data URIs are fine.
- System font stack only (`-apple-system`, `BlinkMacSystemFont`, `system-ui`...).

And stateless because Bap re-runs the skill on every chat turn that triggers it. The HTML doesn't keep state — it reads fresh state from the backend on load (segments, suggestions, anything persistent) AND opens an SSE stream for live deltas:

```js
const sessionId = "{{SESSION_ID}}";  // baked at render time
const apiBase = "{{API_BASE}}";

// 1. Initial snapshot — what already happened before this page mounted
fetch(`${apiBase}/api/sessions/${sessionId}/state`)
  .then(r => r.json())
  .then(renderInitialState);

// 2. Live deltas — anything new from now on
const es = new EventSource(`${apiBase}/api/sessions/${sessionId}/stream`);
es.addEventListener("message", e => applyDelta(JSON.parse(e.data)));
es.addEventListener("error", () => { /* EventSource auto-reconnects, do nothing */ });
```

Notice the split: `state` GET = persisted snapshot, `stream` SSE = live fan-out. Don't try to merge them.

## 3. Backend MUST send CORS headers — every endpoint, no exceptions

Bap's HTML runs from `app.heybap.com` (or your client's white-label). Your backend is on `your-app.vercel.app`. Cross-origin. Without CORS the browser silently kills the request and your page renders blank.

Every backend route needs:

```ts
const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

export async function OPTIONS() {
  return new Response(null, { status: 204, headers: CORS_HEADERS });
}
```

Then attach `CORS_HEADERS` to every `Response` you return. Yes, even errors. Yes, even the SSE stream. Especially the SSE stream — Safari is brutal about this.

Don't use `Access-Control-Allow-Origin: *` if you accept cookies. For tokens-in-URL or bearer-in-header you're fine.

## 4. Live updates: pub/sub, not polling

The naive design: HTML polls `GET /api/state` every 1s. Don't. You will burn through your Redis/Upstash request quota in hours. (Speaking from experience — see `lib/session.ts` in heybap-live-copilot for what NOT to do.)

The right design: SSE on the server, pub/sub on the storage. With Upstash + `@vercel/kv`:

```ts
// Producer (webhook, agent, whatever generates events):
await kv.publish(`events:${sessionId}`, JSON.stringify(event));

// Consumer (your /stream route, one ReadableStream per connected page):
const subscriber = kv.subscribe([`events:${sessionId}`]);
subscriber.on("message", msg => {
  controller.enqueue(encoder.encode(`data: ${msg.message}\n\n`));
});
```

One Redis subscribe call per connected page, held for the function's lifetime (300s on Vercel Fluid Compute by default, then the browser EventSource auto-reconnects). Cost: ~12 commands per hour per open page, regardless of event volume. Polling at 1s = 3600/hour. **300x more expensive**.

Same applies to other backends:
- Postgres → `LISTEN/NOTIFY`
- Redis (raw) → `SUBSCRIBE`
- Cloudflare → Durable Objects with WebSockets (then bridge WS → SSE in your worker, since Bap's iframe handles SSE more reliably than WS)
- Worst-case (no pub/sub available) → poll on the BACKEND with internal cache and only emit SSE deltas to the page; never let the iframe drive the polling

## 5. User actions: plain `fetch` POST, idempotent, with a session token

The HTML lets the user click buttons → mutate backend state. Use `fetch` POST with JSON. Don't try anything fancy.

```js
async function approveItem(itemId) {
  const r = await fetch(`${apiBase}/api/items/${itemId}/approve`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, idempotency_key: crypto.randomUUID() }),
  });
  // Server should publish a delta event to the SSE stream too, so the UI updates
  // for everyone watching this session — including this user, via the same SSE.
  // Don't optimistically update the DOM here; let the round-trip drive it.
}
```

Two non-obvious rules:
- **Don't optimistically update the DOM after a POST**. Wait for the SSE delta. The user sees the same code path as everyone else watching, which means if your mutation fails on the server, no UI drift to clean up.
- **Idempotency key in the POST body**. Bap can re-run the skill on the same chat turn (e.g. retries on transient errors), and EventSource auto-reconnects can fire stale state. An idempotency key on every mutation kills the duplicate.

## 6. Auth: session token in the URL, scoped + short-lived

The HTML lives in Bap's sandbox; you can't put secrets in it. So the `live_url` baked at render time contains a session-scoped token that the backend validates on every request.

Recipe:
- MCP `start_session` tool generates `session_id = uuid()` and `session_token = hmac(secret, session_id + expires_at)`.
- Returns `live_url = "https://your-app.vercel.app/live/${session_id}?token=${session_token}"`.
- Every backend endpoint that takes `session_id` also takes `token` (query string or header) and validates it.
- Expire after 6 hours. If the user re-opens the panel later, they re-run the skill, which mints a new token.

Don't use a global bearer in the HTML. Don't use the user's HeyBap auth — the HTML can't access it.

## 7. Bundle a `render_panel.py` — never let the agent generate the HTML

The Golden Rule from `build-agents-for-bap` applies double here. Your HTML is 200–500 lines of CSS + JS. If the agent tries to emit that as a Claude response, you will hit `The runtime stopped making progress` every few runs.

Instead:
- Bundle a Python `render_panel.py` in the skill folder.
- The script takes ARGV: `live_url`, optional config flags.
- The script writes `/app/output.html` deterministically.
- The agent's last action is one `bash` call: `python3 $(find /app -name render_panel.py | head -1) "<live_url>"`.

Use the template at `templates/render_panel.py` as a starting point.

## 8. URL hygiene — public origin, never localhost

The HTML runs in the user's browser, not in your Vercel function. So `live_url` MUST be the public origin (`https://your-app.vercel.app` or your custom domain), never `localhost`, never `vercel.app` internal URLs.

In your MCP tool:

```ts
const origin = process.env.PUBLIC_ORIGIN ?? new URL(req.url).origin;
const liveUrl = `${origin}/live/${sessionId}`;
```

Set `PUBLIC_ORIGIN` as an env var in production so it stays canonical even when called from preview deployments.

## 9. The reload story — Bap will re-run the skill, often

Users hit "Re-run" in Bap. The agent fires again. The MCP tool gets called again. You DON'T want to spin up a new session every time — you want to find the existing one for this conversation/user/whatever, return its `live_url`, and let the page reconnect to the SAME state.

In the MCP tool:

```ts
const existingSessionId = await findActiveSessionForUser(userId);
if (existingSessionId && !options.force_new) {
  return { session_id: existingSessionId, live_url: urlFor(existingSessionId), reused: true };
}
// else create a new one
```

The HTML on reconnect reads the snapshot (`GET /state`) and resumes. Users see no jank, just "back to where I was".

## 10. Common stack — picked because boring

For most cases you don't need to think:

- **Backend**: Next.js 15 App Router on Vercel (Fluid Compute, Node.js runtime, 300s max duration)
- **State**: Upstash Redis via `@vercel/kv` (lists for ordered data, hashes for state, pub/sub for live deltas)
- **AI** (if needed): Claude via the Anthropic SDK or AI SDK v6 with the Vercel AI Gateway — stream tokens to SSE
- **MCP server**: `mcp-handler` library, deploy as another route in the same Next.js app (saves an env var)
- **Bap skill**: SKILL.md + render_panel.py + (optional) extra resources, uploaded via `coworker_uploadDocument` or shipped in the FDK repo

This stack ships in an afternoon for v1 of a new mini-app. Heavier stacks (Postgres, queues, separate workers) come when you need them.

## 11. The dev loop

- Iterating on the **HTML/CSS**: just re-run the coworker. New `output.html` written, new render.
- Iterating on the **backend**: push to main → Vercel deploys → next page reload picks up the new code (SSE reconnects automatically on browser-side after function restart).
- Iterating on the **agent prompt**: `coworker_update` with the new SKILL.md — the next run uses it.

Don't try to live-reload anything inside Bap. Each run is its own thing.

## 12. Failure modes & how to debug

| Symptom | Cause | Fix |
| --- | --- | --- |
| Panel blank, no errors | CSP / CORS rejection. Open the Bap iframe via "Open in new tab" and check DevTools console. | Add CORS headers to every backend route, including OPTIONS preflight. |
| Panel loads but no live updates | SSE connection silently failing. Common: wrong origin, missing `Content-Type: text/event-stream`, or proxy buffering. | Set `X-Accel-Buffering: no` and `Cache-Control: no-cache, no-transform` headers on the SSE response. |
| Each reload spins a new session | MCP tool always creates instead of reusing. | Index sessions by `user_id` (or conversation_id) on the backend and check first. |
| "I see my own clicks but other users in the same session don't" | UI updated optimistically instead of via SSE delta. | Remove the optimistic update; let the round-trip drive the DOM. |
| KV / Redis quota explodes | Polling instead of pub/sub. | Switch the SSE route to `kv.subscribe` (or your storage's equivalent). |
| HTML can't reach backend after function timeout | Function killed at maxDuration; EventSource is trying to reconnect to a request that's gone. | Normal — let it reconnect; the next page-tab GET gets a fresh function. Make sure `state` GET returns the full snapshot so the page catches up. |
| Buttons in HTML inert | `</` in JSON payload broke the inline script tag. See rule 2 in `build-agents-for-bap`. | Escape `</` in any JSON dumped into `<script>` blocks. |

## 13. The 30-minute starter

If you want to ship a new mini-app from scratch in one focused session:

1. **Backend skeleton**: `pnpm create next-app@latest my-app --typescript --app --no-tailwind --src-dir`. Add `@vercel/kv`. Deploy to Vercel. Connect a KV (Upstash via Marketplace).
2. **One MCP route**: `app/api/mcp/route.ts` exposing `start_session` (creates session in KV, returns `{session_id, live_url}`).
3. **One SSE route**: `app/api/sessions/[id]/stream/route.ts` (subscribe + replay + CORS — copy from `heybap-live-copilot`).
4. **One state route**: `app/api/sessions/[id]/state/route.ts` (return persisted snapshot — segments / items / whatever).
5. **One action route**: `app/api/sessions/[id]/action/route.ts` (POST, mutate KV, `kv.publish` a delta event).
6. **Bap skill**: 1 file SKILL.md + 1 file render_panel.py. SKILL.md tells the agent: read input, call MCP, run script, send one chat line. Done.
7. **Wire MCP into Bap coworker** via `coworker_create` with the MCP URL + bearer.
8. **Test loop**: `bap-coworker-test-loop` skill takes over.

This is the architecture of `heybap-live-copilot`. Look at it for a working reference.

## 14. What you're NOT trying to do

- **You're not building a SPA**. The HTML re-renders fresh on every skill run. No React, no router. Vanilla JS is plenty.
- **You're not building a long-lived backend session per user**. The session is the data; the backend functions are stateless and re-entered on every request.
- **You're not bridging the chat and the panel via tool calls back-and-forth**. The chat agent does one thing (start_session) and then steps back. The panel takes over.
- **You're not putting business logic in the HTML**. The HTML is a view + input layer. All decisions happen server-side.

If you find yourself fighting any of those, the design has drifted. Re-anchor: thin skill, fat backend, dumb HTML.
