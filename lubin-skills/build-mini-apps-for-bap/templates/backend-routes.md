# Backend route templates — Next.js 15 App Router + `@vercel/kv`

Drop these into a fresh `next` app. Adjust the data shape to your mini-app.

---

## `app/api/sessions/[id]/state/route.ts` — initial snapshot

```ts
import { NextRequest, NextResponse } from "next/server";
import { kv } from "@vercel/kv";

export const runtime = "nodejs";

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

export async function OPTIONS() {
  return new Response(null, { status: 204, headers: CORS_HEADERS });
}

export async function GET(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id: sessionId } = await ctx.params;
  const items = (await kv.lrange<string>(`session:${sessionId}:items`, 0, -1))
    .map(r => typeof r === "string" ? JSON.parse(r) : r);
  return NextResponse.json({ session_id: sessionId, items }, { headers: CORS_HEADERS });
}
```

---

## `app/api/sessions/[id]/stream/route.ts` — SSE live deltas (pub/sub)

```ts
import type { NextRequest } from "next/server";
import { kv } from "@vercel/kv";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";
export const maxDuration = 300;

const HEARTBEAT_MS = 30_000;

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "GET, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

export async function OPTIONS() {
  return new Response(null, { status: 204, headers: CORS_HEADERS });
}

export async function GET(_req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id: sessionId } = await ctx.params;
  const encoder = new TextEncoder();

  const stream = new ReadableStream({
    async start(controller) {
      let cancelled = false;
      const buffered: any[] = [];
      let wakeup: (() => void) | null = null;

      const send = (data: unknown) => {
        if (cancelled) return;
        try {
          controller.enqueue(encoder.encode(`data: ${JSON.stringify(data)}\n\n`));
        } catch { cancelled = true; }
      };

      const finish = () => {
        cancelled = true;
        try { controller.close(); } catch {}
        try { subscriber.unsubscribe(); } catch {}
        clearInterval(hb);
        if (wakeup) { wakeup(); wakeup = null; }
      };

      const subscriber = kv.subscribe<string>([`events:${sessionId}`]);
      subscriber.on("message", (msg: { message: string }) => {
        try {
          buffered.push(JSON.parse(msg.message));
          if (wakeup) { wakeup(); wakeup = null; }
        } catch {}
      });
      subscriber.on("error", () => finish());

      send({ type: "hello", session_id: sessionId });
      const hb = setInterval(() => send({ type: "heartbeat", t: Date.now() }), HEARTBEAT_MS);

      while (!cancelled) {
        if (buffered.length > 0) {
          while (buffered.length > 0 && !cancelled) send(buffered.shift());
          continue;
        }
        await new Promise<void>(r => {
          wakeup = r;
          setTimeout(() => { if (wakeup === r) { wakeup = null; r(); } }, 60_000);
        });
      }
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
      ...CORS_HEADERS,
    },
  });
}
```

---

## `app/api/sessions/[id]/action/route.ts` — POST mutations

```ts
import { NextRequest, NextResponse } from "next/server";
import { kv } from "@vercel/kv";

export const runtime = "nodejs";

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type",
};

export async function OPTIONS() {
  return new Response(null, { status: 204, headers: CORS_HEADERS });
}

export async function POST(req: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  const { id: sessionId } = await ctx.params;
  const body = await req.json();
  const { action, item_id, idempotency_key } = body;

  // Idempotency: dedupe by key
  const added = await kv.sadd(`session:${sessionId}:seen`, idempotency_key);
  await kv.expire(`session:${sessionId}:seen`, 60 * 60 * 24);
  if (added === 0) {
    return NextResponse.json({ ok: true, deduped: true }, { headers: CORS_HEADERS });
  }

  // Apply mutation (example: remove approved/rejected items)
  if (action === "approve" || action === "reject") {
    // Pseudo-code — adapt to your storage
    await kv.publish(`events:${sessionId}`, JSON.stringify({
      type: "item_removed",
      id: item_id,
    }));
  }

  return NextResponse.json({ ok: true }, { headers: CORS_HEADERS });
}
```

---

## `app/api/mcp/route.ts` — start_session via `mcp-handler`

```ts
import { createMcpHandler } from "mcp-handler";
import { z } from "zod";
import { randomUUID } from "node:crypto";
import { kv } from "@vercel/kv";

const handler = createMcpHandler(server => {
  server.tool(
    "start_session",
    "Spin up a session on the mini-app and return a live_url to render.",
    {
      title: z.string().optional(),
      config: z.record(z.unknown()).optional(),
    },
    async (input, _meta) => {
      const sessionId = randomUUID();
      await kv.set(`session:${sessionId}`, {
        id: sessionId,
        createdAt: Date.now(),
        title: input.title ?? "Untitled",
        config: input.config ?? {},
      }, { ex: 60 * 60 * 24 * 7 });

      const origin = process.env.PUBLIC_ORIGIN ?? "https://your-app.vercel.app";
      const liveUrl = `${origin}/live/${sessionId}`;

      return {
        content: [{ type: "text", text: JSON.stringify({ session_id: sessionId, live_url: liveUrl }) }],
      };
    },
  );
});

export { handler as GET, handler as POST };
```

---

## Producer (anywhere you generate events) — `kv.publish`

```ts
// Inside a webhook handler, a cron, an LLM streaming callback, anywhere:
await kv.publish(`events:${sessionId}`, JSON.stringify({
  type: "item_added",
  item: { id: randomUUID(), title: "New thing", body: "..." },
}));

// And persist it too, so a reconnecting page sees it in /state:
await kv.rpush(`session:${sessionId}:items`, JSON.stringify(item));
```

---

## Required env vars

- `KV_REST_API_URL`, `KV_REST_API_TOKEN` — auto-provisioned by Vercel Marketplace (Upstash Redis)
- `PUBLIC_ORIGIN` — set to your canonical production URL (e.g. `https://my-app.vercel.app` or custom domain)
