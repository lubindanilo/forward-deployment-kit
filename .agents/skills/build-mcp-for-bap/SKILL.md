---
name: build-mcp-for-bap
description: |
  Build a custom MCP server (HTTP + JSON-RPC over Streamable HTTP) compatible with Bap (Heybap) workspace MCPs.
  Deploys to Vercel by default with the `mcp-handler` library, exposes one or more tools, and supports the
  four Bap auth modes: none / bearer / api_key / oauth2. Use this skill when the user asks to "build an MCP",
  "expose a tool to Bap", "create a custom MCP server", "add an MCP for X service", or wants to integrate a
  third-party API into a Bap coworker.
---

# Build an MCP for Bap (Heybap)

A Bap workspace MCP is a remote HTTP endpoint that exposes one or more tools to a coworker. Bap reads `tools/list` and calls `tools/call` over JSON-RPC 2.0 with Streamable HTTP transport. The user adds the endpoint URL in Bap → Workspace settings → MCP servers, picks an auth mode, and the tools become available to any coworker that allows the server.

This skill covers the full lifecycle: scaffolding, implementing tools, picking the right auth mode, deploying to Vercel, and registering in Bap.

## Decision flow before writing code

1. **What tool(s) do we expose?** Name them and define the inputs/outputs. One MCP can host many tools; group by domain (e.g. one MCP for "transcription", one for "calendar admin", etc.).
2. **Auth mode** — pick BEFORE coding:
   - **`none`** — Anyone with the URL can call. Use only for safe, idempotent, free operations.
   - **`bearer`** *(default recommendation)* — Single static token in env var. Simple, secure enough for internal tooling. Bap UI: paste the token once.
   - **`api_key`** — Same as bearer but token goes in custom header or query param. Use if the upstream service expects an API key passthrough.
   - **`oauth2`** — Full OAuth 2.0 with `.well-known/oauth-protected-resource` + `.well-known/oauth-authorization-server` discovery. Heavy. Only do this if the MCP itself proxies a per-user OAuth-protected resource (e.g. user-scoped Gmail). For shared/server-side credentials, use `bearer`.
3. **Latency profile** — Vercel Hobby caps function `maxDuration` at 300s. If the tool needs longer (heavy LLM, large file processing), either chunk + parallelize, queue + poll, or move to Vercel Pro.
4. **Reuse** — Will other coworkers/projects use this MCP? If yes, give it a generic name (e.g. `hyperstack-transcribe`, not `batimgie-transcribe`) and put the project in the org's Vercel + Git.

## Scaffold (Vercel + Next.js + mcp-handler)

```
my-mcp/
├── package.json
├── tsconfig.json
├── next.config.mjs        # serverExternalPackages for any native deps
├── vercel.json            # maxDuration + memory
├── app/api/mcp/route.ts   # the MCP endpoint
└── README.md
```

### `package.json`

```json
{
  "name": "my-mcp",
  "version": "1.0.0",
  "private": true,
  "type": "module",
  "scripts": {
    "dev": "next dev",
    "build": "next build",
    "start": "next start"
  },
  "dependencies": {
    "mcp-handler": "^1.0.0",
    "next": "^15.3.0",
    "react": "^19.0.0",
    "react-dom": "^19.0.0",
    "zod": "^3.24.0"
  },
  "devDependencies": {
    "@types/node": "^22.10.0",
    "@types/react": "^19.0.0",
    "typescript": "^5.7.0"
  }
}
```

Don't add the pnpm `packageManager` field if you'll deploy from Vercel; use `npm install` to keep CI/CD simple.

### `next.config.mjs`

```js
/** @type {import('next').NextConfig} */
const nextConfig = {
  // Only needed when bundling native node modules (ffmpeg, sharp, etc.)
  serverExternalPackages: ["@ffmpeg-installer/ffmpeg"],
  outputFileTracingIncludes: {
    "/api/mcp": ["./node_modules/@ffmpeg-installer/**/*"],
  },
};
export default nextConfig;
```

### `vercel.json`

```json
{
  "functions": {
    "app/api/mcp/route.ts": {
      "maxDuration": 300,
      "memory": 2048
    }
  }
}
```

Memory cap is 2048 MB on Hobby. `maxDuration` is 300s on Hobby, up to 800s on Pro.

### `tsconfig.json`

Standard Next 15 + app router config. The Next.js scaffold output is the source of truth.

## The MCP endpoint

`app/api/mcp/route.ts`:

```ts
import { createMcpHandler } from "mcp-handler";
import { z } from "zod";

const handler = createMcpHandler(
  (server) => {
    server.tool(
      "my_tool_name",                                  // tool identifier the LLM calls
      "Short description telling the LLM when to use this tool.",
      {
        someArg: z.string().describe("Plain-English description for the LLM."),
        optionalArg: z.number().optional().describe("..."),
      },
      async ({ someArg, optionalArg }) => {
        // Your business logic here. Throw to return an error.
        const result = await doWork(someArg, optionalArg);
        return {
          content: [{ type: "text", text: result }],
        };
      }
    );
    // Add as many server.tool(...) calls as you want.
  },
  {},                            // server options
  { basePath: "/api" }           // must match the route folder
);

export { handler as GET, handler as POST, handler as DELETE };
```

### Bearer auth wrapper (recommended default)

Wrap the handler before exporting so the token is checked on every request:

```ts
function withBearerAuth(
  inner: (req: Request) => Promise<Response> | Response
): (req: Request) => Promise<Response> {
  return async (req: Request) => {
    const expected = process.env.MCP_BEARER_TOKEN;
    if (expected) {
      const got = req.headers.get("authorization") || "";
      const ok = got === `Bearer ${expected}` || got === expected;
      if (!ok) {
        return new Response(JSON.stringify({ error: "unauthorized" }), {
          status: 401,
          headers: {
            "Content-Type": "application/json",
            "WWW-Authenticate": 'Bearer realm="my-mcp"',
          },
        });
      }
    }
    return inner(req);
  };
}

const guarded = withBearerAuth(handler);
export { guarded as GET, guarded as POST, guarded as DELETE };
```

Note the env var check: if `MCP_BEARER_TOKEN` is unset, the wrapper falls through (useful for local dev with `pnpm dev`). In production, always set it.

### Streaming long responses

If the tool produces incremental output (e.g. video processing progress), use the `server.tool` callback's progress reporting (see `mcp-handler` docs). Most tools should just return text at the end — simpler and works fine for sub-300s operations.

### Native binaries (ffmpeg, sharp, etc.)

If you need a native binary on Vercel Functions:
1. Add the npm wrapper that bundles per-arch binaries: `@ffmpeg-installer/ffmpeg`, `sharp`, etc.
2. Add it to `serverExternalPackages` in `next.config.mjs`.
3. Add the directory to `outputFileTracingIncludes` so Vercel ships it.
4. The runtime is Linux x64 — verify the wrapper has that target installed (`node_modules/@ffmpeg-installer/linux-x64/` should exist after `npm install`).

## Deploy to Vercel

```bash
vercel link --yes --project my-mcp                    # one-time
echo "$TOKEN" | vercel env add MCP_BEARER_TOKEN production
vercel deploy --prod --yes
```

Generate the token once:
```bash
openssl rand -hex 32                                  # → 064c...e2c, save it for Bap
```

After deploy, **disable Vercel SSO protection** (default on Hobby personal projects):

```bash
vercel project protection disable --sso
```

Without this step, every MCP request returns the Vercel auth HTML page → Bap can't reach the JSON-RPC handler.

Get the stable URL:
```bash
vercel inspect <latest-deployment> | grep -A 5 Aliases
# → https://my-mcp.vercel.app
```

The MCP endpoint is `https://my-mcp.vercel.app/api/mcp`.

## Register in Bap

Workspace admin → **MCP servers** → **Add new** → fill:

| Field | Value |
|---|---|
| **Name** | Anything human-readable |
| **URL** | `https://my-mcp.vercel.app/api/mcp` |
| **Auth** | **Pick `Bearer token`** (Bap's UI defaults to OAuth — change it!) |
| **Header name** | `Authorization` (default) |
| **Prefix** | `Bearer ` (default — keep the trailing space) |
| **Secret / Token** | Paste the `openssl rand -hex 32` token |

Save. The status should immediately flip to `Connected`. Enable the MCP for the specific coworker(s) that should use it.

### Common Bap UI gotcha

The UI defaults `authType` to `oauth2` (cf. `apps/web/src/components/executor-source-form.tsx:80-96` in the bap repo). If you forget to change it and click "Connect OAuth", Bap fails with an internal 500 because it tries to fetch `.well-known/oauth-protected-resource` on your MCP (which doesn't exist). **Always change the Auth dropdown before saving.**

## Smoke-test the MCP from the terminal

```bash
TOKEN="..."  # the value you stored in MCP_BEARER_TOKEN

# 1. initialize (creates a session)
SID=$(curl -s -i -X POST https://my-mcp.vercel.app/api/mcp \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"smoke","version":"0"}}}' \
  | grep -i mcp-session-id | tr -d '\r' | awk '{print $2}')

# 2. notify initialized
curl -s -X POST https://my-mcp.vercel.app/api/mcp \
  -H "Authorization: Bearer $TOKEN" \
  -H "mcp-session-id: $SID" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","method":"notifications/initialized"}' > /dev/null

# 3. list tools
curl -s -X POST https://my-mcp.vercel.app/api/mcp \
  -H "Authorization: Bearer $TOKEN" \
  -H "mcp-session-id: $SID" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list"}' \
  | sed 's/event: message//; s/^data: //'

# 4. call a tool
curl -s -X POST https://my-mcp.vercel.app/api/mcp \
  -H "Authorization: Bearer $TOKEN" \
  -H "mcp-session-id: $SID" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json, text/event-stream" \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"my_tool_name","arguments":{"someArg":"hello"}}}' \
  | sed 's/event: message//; s/^data: //'
```

A 401 from step 1 means the bearer header is wrong. A successful step 3 returns `{"result":{"tools":[...]}}` — those are the tools that will appear in the coworker.

## Bap auth modes — implementation cheat-sheet

| Mode | When to use | Server-side check |
|---|---|---|
| `none` | Tool is safe + free for anyone (e.g. read-only public data lookup) | None |
| `bearer` | Default for internal MCPs | `Authorization: Bearer <token>` |
| `api_key` | Upstream API expects key in header/query | Custom header/query check |
| `oauth2` | Per-user OAuth resource (Gmail, Calendar with user account) | Full RFC 8414 + RFC 9728 discovery endpoints |

For OAuth, you must expose **both** discovery endpoints and implement the full code → token flow with PKCE. Bap uses `{APP_URL}/api/oauth/callback` as redirect URI, `token_endpoint_auth_method: "none"` (public client). Don't go OAuth unless you really need per-user delegation.

## Pitfalls

- **Forgot to disable Vercel SSO** → all requests return HTML auth page. Run `vercel project protection disable --sso`.
- **Wrong basePath** in `createMcpHandler` → 404. The third arg `basePath` must match the route folder (`/api` if the route file is at `app/api/mcp/route.ts`).
- **Native binary path errors at runtime** (`Cannot find module '@ffmpeg-installer/...'`) → missing `outputFileTracingIncludes` in `next.config.mjs`.
- **Tool not appearing in coworker** → check that the workspace MCP is enabled for THAT specific coworker (per-coworker toggle).
- **Token won't validate** → the bearer wrapper does an exact-string equality. Make sure the env var has no trailing newline (Vercel CLI auto-strips it but check).
- **maxDuration too short** → Vercel cancels at 300s on Hobby. For longer operations, parallelize internally or upgrade to Pro (800s).

## When NOT to build an MCP

- The tool is a one-off used by a single coworker → use a skill with embedded Python/bash instead, runs in the sandbox.
- The data fits in a coworker document (PDF, CSV, image, txt) → upload it directly.
- The "tool" is a fixed answer / template → use a skill, not an MCP.

MCPs are best when **multiple coworkers** call the same logic, or when the logic requires **secrets that shouldn't be in the coworker's sandbox** (e.g. paid API keys).

## Reference implementation

The `hyperstack-transcribe` MCP is the canonical reference for this skill — single-tool MCP (audio URL → text via Groq Whisper), Bearer auth, native ffmpeg, deployed on Vercel Hobby. Code: https://github.com/lubindanilo/hyperstack-transcribe (or wherever the user has it).
