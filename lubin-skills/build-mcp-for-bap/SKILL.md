---
name: build-mcp-for-bap
description: |
  Build a custom MCP server (HTTP + JSON-RPC over Streamable HTTP) compatible with Bap (Heybap) workspace MCPs.
  Deploys to Vercel by default with the `mcp-handler` library, exposes one or more tools, and ships the
  auto-approving OAuth 2.0 flow that Bap's UI requires (Bap only shows the "Connect OAuth" button — no
  Bearer / no-auth alternative in the form). Use this skill when the user asks to "build an MCP",
  "expose a tool to Bap", "create a custom MCP server", "add an MCP for X service", or wants to integrate a
  third-party API into a Bap coworker.
---

# Build an MCP for Bap (Heybap)

A Bap workspace MCP is a remote HTTP endpoint that exposes one or more tools to a coworker. Bap reads `tools/list` and calls `tools/call` over JSON-RPC 2.0 with Streamable HTTP transport.

**The Bap UI for adding a workspace MCP only asks for a URL and ships a "Connect OAuth" button.** There's no auth-mode dropdown in practice — the workspace forces OAuth 2.0. So every Bap-compatible MCP MUST implement OAuth 2.0 discovery + authorization + token endpoints. This skill walks through the auto-approving pattern that satisfies Bap without ever showing a consent screen, then exposes your tools via a static internal bearer.

## What you'll build

```
my-mcp.vercel.app/
├── /.well-known/oauth-protected-resource       ← RFC 9728 discovery
├── /.well-known/oauth-authorization-server     ← RFC 8414 discovery
├── /oauth/register                              ← DCR echo
├── /oauth/authorize                             ← auto-approve, 302 with JWT code
├── /oauth/token                                 ← verify PKCE, return static bearer
└── /api/mcp                                     ← your tools (Streamable HTTP)
```

The flow Bap will follow:

1. User pastes the MCP URL in Bap → workspace MCP settings.
2. Bap fetches `.well-known/oauth-protected-resource` and `.well-known/oauth-authorization-server`.
3. Bap POSTs `/oauth/register` to get a `client_id` (your endpoint just echoes back).
4. User clicks **Connect OAuth** → Bap opens a popup to your `/oauth/authorize?...&code_challenge=...`.
5. Your endpoint immediately 302s back to `{BAP_URL}/api/oauth/callback?code=<signed JWT>&state=...` — no consent screen, no login.
6. Bap exchanges the code at your `/oauth/token` with the PKCE verifier → receives a bearer (your static `MCP_BEARER_TOKEN`).
7. Bap stores the bearer and uses it as `Authorization: Bearer <token>` on every `/api/mcp` call. Status flips to `Connected`.

Why this is safe: the bearer is server-only, the JWT-signed code is bound to the redirect_uri + PKCE challenge, and there's no real user delegation to fake — your MCP runs on shared credentials (your Groq key, your DB cred, etc.). The OAuth dance is purely ceremonial to satisfy Bap's UI.

## Decision flow before writing code

1. **Feasibility pre-flight (mandatory for external platforms)** — Before scaffolding any MCP that wraps a third-party platform (Leboncoin, Se Loger, LinkedIn, Indeed, Welcome to the Jungle, Vinted, Booking, PAP, Bien Ici, Pipedrive, ...), invoke [bap-platform-feasibility-check](../bap-platform-feasibility-check/SKILL.md) with the platform name + interaction shape. The skill runs a 5-angle web research (API + tier, ToS, community connectors, browser automation, incidents) and returns a verdict. **Refuse to scaffold** when the verdict is `legally-risky` or `infeasible`, unless the operator passes an explicit `overrideFeasibility: true` (logged in the generated MCP's README). When the verdict is `feasible-via-mcp` (a maintained community MCP already covers the need), bind the existing URL in Bap instead of building a new MCP; this skill is not the right path. Skip the feasibility check for platforms on Bap's canonical native list (Slack, Gmail, Notion, Linear, Airtable, Outlook, Google Calendar, Google Drive, Salesforce, HubSpot) and for purely internal MCPs (your own service, no external platform involved).
2. **What tool(s) do we expose?** Name them and define the inputs/outputs. One MCP can host many tools; group by domain (e.g. one MCP for "transcription", one for "calendar admin").
3. **Latency profile** — Vercel Hobby caps function `maxDuration` at 300s. If the tool needs longer (heavy LLM, large file processing), either chunk + parallelize internally, queue + poll, or move to Vercel Pro.
4. **Reuse** — Will other coworkers/projects use this MCP? If yes, give it a generic name (`hyperstack-transcribe`, not `batimgie-transcribe`) and put the project in the org's Vercel + Git.

## Scaffold (Vercel + Next.js + mcp-handler)

```
my-mcp/
├── package.json
├── tsconfig.json
├── next.config.mjs
├── vercel.json
├── lib/
│   └── oauth.ts                                 ← JWT code signing + PKCE helpers
└── app/
    ├── api/mcp/route.ts                         ← MCP tool handler
    ├── .well-known/
    │   ├── oauth-protected-resource/route.ts
    │   └── oauth-authorization-server/route.ts
    └── oauth/
        ├── authorize/route.ts
        ├── token/route.ts
        └── register/route.ts
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
    "jose": "^5.10.0",
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

Don't add the `packageManager` field if you'll deploy from Vercel; use `npm install` to keep CI/CD simple.

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

Hobby caps: 300s max duration, 2048 MB memory.

### `lib/oauth.ts` — JWT code signing + PKCE helpers

```ts
import { SignJWT, jwtVerify } from "jose";
import { createHash, randomUUID } from "node:crypto";

function getSecret(): Uint8Array {
  const raw = process.env.OAUTH_SIGNING_SECRET || process.env.MCP_BEARER_TOKEN || "dev-only";
  return new TextEncoder().encode(raw);
}

export interface CodePayload {
  redirect_uri: string;
  code_challenge: string;
  code_challenge_method: "S256" | "plain";
  client_id: string;
  scope?: string;
}

export async function signCode(payload: CodePayload, ttlSeconds = 600): Promise<string> {
  return new SignJWT({ ...payload, jti: randomUUID() })
    .setProtectedHeader({ alg: "HS256" })
    .setIssuedAt()
    .setExpirationTime(Math.floor(Date.now() / 1000) + ttlSeconds)
    .sign(getSecret());
}

export async function verifyCode(code: string): Promise<CodePayload> {
  const { payload } = await jwtVerify(code, getSecret());
  return payload as unknown as CodePayload;
}

export function verifyPkce(verifier: string, challenge: string, method: "S256" | "plain"): boolean {
  if (method === "plain") return verifier === challenge;
  const hash = createHash("sha256").update(verifier).digest("base64url");
  return hash === challenge;
}

export function getAccessToken(): string {
  const t = process.env.MCP_BEARER_TOKEN;
  if (!t) throw new Error("MCP_BEARER_TOKEN env var not set");
  return t;
}
```

## The 5 OAuth routes

### `app/.well-known/oauth-protected-resource/route.ts`

```ts
import { NextRequest, NextResponse } from "next/server";

export async function GET(req: NextRequest) {
  const origin = new URL(req.url).origin;
  return NextResponse.json(
    {
      resource: origin,
      authorization_servers: [origin],
      scopes_supported: ["mcp"],
      bearer_methods_supported: ["header"],
    },
    { headers: { "Access-Control-Allow-Origin": "*" } }
  );
}

export async function OPTIONS() {
  return new NextResponse(null, {
    status: 204,
    headers: { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, OPTIONS" },
  });
}
```

### `app/.well-known/oauth-authorization-server/route.ts`

```ts
import { NextRequest, NextResponse } from "next/server";

export async function GET(req: NextRequest) {
  const origin = new URL(req.url).origin;
  return NextResponse.json(
    {
      issuer: origin,
      authorization_endpoint: `${origin}/oauth/authorize`,
      token_endpoint: `${origin}/oauth/token`,
      registration_endpoint: `${origin}/oauth/register`,
      response_types_supported: ["code"],
      grant_types_supported: ["authorization_code", "refresh_token"],
      code_challenge_methods_supported: ["S256"],
      token_endpoint_auth_methods_supported: ["none"],
      scopes_supported: ["mcp"],
    },
    { headers: { "Access-Control-Allow-Origin": "*" } }
  );
}

export async function OPTIONS() {
  return new NextResponse(null, {
    status: 204,
    headers: { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "GET, OPTIONS" },
  });
}
```

### `app/oauth/register/route.ts`

```ts
import { NextRequest, NextResponse } from "next/server";
import { randomUUID } from "node:crypto";

export async function POST(req: NextRequest) {
  const body = (await req.json().catch(() => ({}))) as Record<string, unknown>;
  return NextResponse.json(
    {
      client_id: (body.client_id as string) || `client_${randomUUID()}`,
      client_id_issued_at: Math.floor(Date.now() / 1000),
      redirect_uris: body.redirect_uris || [],
      response_types: body.response_types || ["code"],
      grant_types: body.grant_types || ["authorization_code", "refresh_token"],
      token_endpoint_auth_method: "none",
      scope: "mcp",
      client_name: body.client_name || "bap-client",
    },
    { status: 201, headers: { "Access-Control-Allow-Origin": "*" } }
  );
}

export async function OPTIONS() {
  return new NextResponse(null, {
    status: 204,
    headers: { "Access-Control-Allow-Origin": "*", "Access-Control-Allow-Methods": "POST, OPTIONS" },
  });
}
```

### `app/oauth/authorize/route.ts`

```ts
import { NextRequest, NextResponse } from "next/server";
import { signCode } from "@/lib/oauth";

export async function GET(req: NextRequest) {
  const url = new URL(req.url);
  if (url.searchParams.get("response_type") !== "code") {
    return NextResponse.json({ error: "unsupported_response_type" }, { status: 400 });
  }
  const redirectUri = url.searchParams.get("redirect_uri");
  const codeChallenge = url.searchParams.get("code_challenge");
  if (!redirectUri || !codeChallenge) {
    return NextResponse.json({ error: "invalid_request" }, { status: 400 });
  }

  const code = await signCode({
    redirect_uri: redirectUri,
    code_challenge: codeChallenge,
    code_challenge_method: (url.searchParams.get("code_challenge_method") || "S256") as "S256" | "plain",
    client_id: url.searchParams.get("client_id") || "anonymous",
    scope: url.searchParams.get("scope") || "mcp",
  });

  const target = new URL(redirectUri);
  target.searchParams.set("code", code);
  const state = url.searchParams.get("state");
  if (state) target.searchParams.set("state", state);
  return NextResponse.redirect(target.toString(), 302);
}
```

### `app/oauth/token/route.ts`

```ts
import { NextRequest, NextResponse } from "next/server";
import { verifyCode, verifyPkce, getAccessToken } from "@/lib/oauth";

export async function POST(req: NextRequest) {
  const text = await req.text();
  const body = Object.fromEntries(new URLSearchParams(text));

  if (body.grant_type === "refresh_token") {
    return NextResponse.json({
      access_token: getAccessToken(),
      token_type: "Bearer",
      expires_in: 31536000,
      refresh_token: body.refresh_token,
      scope: "mcp",
    });
  }
  if (body.grant_type !== "authorization_code") {
    return NextResponse.json({ error: "unsupported_grant_type" }, { status: 400 });
  }

  const payload = await verifyCode(body.code);
  if (payload.redirect_uri !== body.redirect_uri) {
    return NextResponse.json({ error: "invalid_grant" }, { status: 400 });
  }
  if (!verifyPkce(body.code_verifier, payload.code_challenge, payload.code_challenge_method)) {
    return NextResponse.json({ error: "invalid_grant", error_description: "PKCE mismatch" }, { status: 400 });
  }

  return NextResponse.json({
    access_token: getAccessToken(),
    token_type: "Bearer",
    expires_in: 31536000,
    refresh_token: getAccessToken(),
    scope: payload.scope || "mcp",
  });
}

export async function OPTIONS() {
  return new NextResponse(null, {
    status: 204,
    headers: {
      "Access-Control-Allow-Origin": "*",
      "Access-Control-Allow-Methods": "POST, OPTIONS",
      "Access-Control-Allow-Headers": "Content-Type, Authorization",
    },
  });
}
```

## The MCP endpoint

`app/api/mcp/route.ts`:

```ts
import { createMcpHandler } from "mcp-handler";
import { z } from "zod";

const handler = createMcpHandler(
  (server) => {
    server.tool(
      "my_tool_name",
      "Short description telling the LLM when to use this tool.",
      {
        someArg: z.string().describe("Plain-English description for the LLM."),
        optionalArg: z.number().optional().describe("..."),
      },
      async ({ someArg, optionalArg }) => {
        const result = await doWork(someArg, optionalArg);
        return { content: [{ type: "text", text: result }] };
      }
    );
  },
  {},
  { basePath: "/api" }
);

// Validate the bearer that Bap obtained from /oauth/token.
function withBearerAuth(
  inner: (req: Request) => Promise<Response> | Response
): (req: Request) => Promise<Response> {
  return async (req: Request) => {
    const expected = process.env.MCP_BEARER_TOKEN;
    if (expected) {
      const got = req.headers.get("authorization") || "";
      if (got !== `Bearer ${expected}` && got !== expected) {
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

The bearer middleware protects `/api/mcp` from non-Bap callers who didn't go through the OAuth flow. Callers who completed `/oauth/token` get the same static token, so the check is a fixed string equality.

### Native binaries (ffmpeg, sharp, etc.)

If your tool needs a native binary:
1. Add the npm wrapper that bundles per-arch binaries: `@ffmpeg-installer/ffmpeg`, `sharp`, etc.
2. Add it to `serverExternalPackages` in `next.config.mjs`.
3. Add the directory to `outputFileTracingIncludes` so Vercel ships it.
4. Verify the linux-x64 wrapper installs (`node_modules/@ffmpeg-installer/linux-x64/` should exist after `npm install`).

## Deploy to Vercel

```bash
vercel link --yes --project my-mcp
TOKEN=$(openssl rand -hex 32)
echo "$TOKEN" | vercel env add MCP_BEARER_TOKEN production
vercel deploy --prod --yes
```

The token is also used as the JWT signing secret for OAuth codes (via `lib/oauth.ts` fallback). One secret, no extra env needed.

After deploy, **disable Vercel SSO protection** — without this every MCP request returns Vercel's auth HTML page, breaking discovery:

```bash
vercel project protection disable --sso
```

Get the stable URL:
```bash
vercel inspect <latest-deployment> | grep -A 5 Aliases
# → https://my-mcp.vercel.app
```

Your MCP endpoint is `https://my-mcp.vercel.app/api/mcp`.

## Register in Bap

Workspace admin → **MCP servers** → **Add new** → paste the URL → save.

On the MCP fiche, click **Connect OAuth** → Bap does the full discovery + auto-approve dance → status flips to `Connected`. No token to paste, no dropdown to change.

Enable the MCP for the specific coworker(s) that should use it.

## Smoke-test the OAuth flow from the terminal

```bash
ORIGIN="https://my-mcp.vercel.app"
REDIRECT="https://bap.example.com/api/oauth/callback"
VERIFIER="randomstring1234567890abcdefghijklmnopqr"
CHALLENGE=$(echo -n "$VERIFIER" | openssl dgst -sha256 -binary | base64 | tr '+/' '-_' | tr -d '=')

# 1. Discovery
curl -s "$ORIGIN/.well-known/oauth-authorization-server" | jq .

# 2. Authorize → 302
LOC=$(curl -s -o /dev/null -w "%{redirect_url}" \
  "$ORIGIN/oauth/authorize?response_type=code&client_id=test&redirect_uri=$REDIRECT&state=xyz&code_challenge=$CHALLENGE&code_challenge_method=S256")
CODE=$(echo "$LOC" | grep -oE 'code=[^&]+' | cut -d= -f2)

# 3. Token exchange → bearer
curl -s -X POST "$ORIGIN/oauth/token" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "grant_type=authorization_code" \
  --data-urlencode "code=$CODE" \
  --data-urlencode "redirect_uri=$REDIRECT" \
  --data-urlencode "code_verifier=$VERIFIER" \
  --data-urlencode "client_id=test" | jq .
# → { "access_token": "...", "token_type": "Bearer", ... }
```

If step 3 returns an access_token equal to your `MCP_BEARER_TOKEN`, the OAuth chain works end-to-end. Now Bap can connect.

## Pitfalls

- **Forgot to disable Vercel SSO** → all requests return HTML auth page, Bap discovery breaks. Run `vercel project protection disable --sso`.
- **Wrong basePath** in `createMcpHandler` → 404. The third arg must match the route folder (`/api` if the route file is at `app/api/mcp/route.ts`).
- **Discovery endpoints in wrong location** → `.well-known/*` MUST be at the origin root (`app/.well-known/...`), NOT under `/api`. Bap fetches the raw origin.
- **PKCE mismatch** → `sha256(verifier)` must be **base64url** encoded (no padding, `+/` → `-_`). Common bug: using plain base64.
- **Native binary path errors at runtime** (`Cannot find module '@ffmpeg-installer/...'`) → missing `outputFileTracingIncludes` in `next.config.mjs`.
- **Tool not appearing in coworker** → check that the workspace MCP is enabled for THAT specific coworker (per-coworker toggle).
- **maxDuration too short** → Vercel cancels at 300s on Hobby. For longer operations, parallelize internally or upgrade to Pro (800s).

## When NOT to build an MCP

- The tool is a one-off used by a single coworker → use a skill with embedded Python/bash instead, runs in the sandbox.
- The data fits in a coworker document (PDF, CSV, image, txt) → upload it directly.
- The "tool" is a fixed answer / template → use a skill, not an MCP.

MCPs are best when **multiple coworkers** call the same logic, or when the logic requires **secrets that shouldn't be in the coworker's sandbox** (paid API keys, DB creds).

## Reference implementation

`hyperstack-transcribe` — single-tool MCP (audio URL → text via Groq Whisper), OAuth auto-approve, ffmpeg auto-chunking, deployed on Vercel Hobby. Copy its `app/` and `lib/` folders as your starting point.
