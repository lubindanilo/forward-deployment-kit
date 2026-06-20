---
name: bap-platform-feasibility-check
description: |
  Before classifying a tool as `custom_mcp_to_build` or wiring a coworker
  to interact with a specific third-party platform (Leboncoin, Se Loger,
  LinkedIn, Indeed, Vinted, Shopify, Booking, PAP, Bien Ici, etc.), do a
  web research pass to verify the integration is actually achievable.
  Each platform gets a parallel multi-angle research: official API
  existence + tier (free / paid / partner-only / closed), ToS posture on
  programmatic access, community MCPs / SDKs / connectors that already
  exist, browser-automation feasibility (anti-bot, captcha, account
  suspension risk), known incidents. Returns a verdict per platform
  (`feasible-via-api` | `feasible-via-mcp` | `feasible-via-browser` |
  `legally-risky` | `infeasible`) plus a recommended strategy. Use when
  `parse-transcript-to-agent-spec` flags a tool that is not in the Bap
  canonical native list AND not in the operator's prior art (per
  `bap-prior-art-scout`), or when the orchestrator is about to invoke
  `build-mcp-for-bap` for a new custom MCP. Stops the pipeline from
  burning hours on an MCP whose target platform will block it.
---

# External-platform feasibility check

The forward-deployment pipeline assumes that, once a tool is identified, there is *some* path to wire it up: native integration, existing MCP, custom MCP, browser automation, sandbox CLI. That assumption breaks on platforms whose API is closed (LinkedIn outbound, most French job boards), platforms that aggressively block bots (Indeed search, Leboncoin posting), and platforms with ToS that explicitly forbid programmatic access (most consumer marketplaces).

Without this check, the pipeline burns hours building an MCP that hits 403 / captcha / account-ban within minutes of going live. With it, the operator sees the constraint upfront and either accepts the workaround (manual step, partner API request, broker-style relay), picks a different platform, or scopes the agent differently.

This skill is the **external** mirror of [bap-prior-art-scout](../bap-prior-art-scout/SKILL.md) (which scans the operator's own prior work) and runs alongside it before any new MCP scaffolding starts.

## When to invoke

- `parse-transcript-to-agent-spec` Step 5: every `neededTools[]` item whose `kind` is `custom_mcp_to_build` AND whose `name` is not a generic verb (it names a specific platform: "Leboncoin", "Welcome to the Jungle", "Vinted", "Booking", "Pipedrive").
- `transcript-to-bap-coworker` Step 1.5, right after `bap-prior-art-scout` returns: if the scout finds no prior MCP for the platform, run this skill before continuing.
- `build-mcp-for-bap`: pre-flight before scaffolding. If feasibility says `legally-risky` or `infeasible`, refuse to scaffold and surface to the operator.
- Standalone, when the operator asks "can I make a coworker that posts on X" or "is there a way to read Y programmatically".

Do not invoke for platforms already on Bap's canonical native list (Slack, Gmail, Notion, Linear, Airtable, Outlook, Google Calendar, Google Drive, Salesforce, HubSpot). For those, feasibility is settled by the existence of the native integration.

## Input contract

```json
{
  "platforms": [
    {
      "name": "Leboncoin",
      "interactionShape": "post | read | both",
      "region": "FR | EU | WW",
      "authNeeded": "user-credentials | api-key | none",
      "frequency": "one-shot | daily | hourly | realtime",
      "context": "<one-line: what the agent does with this platform>"
    }
  ],
  "options": {
    "researchTimeCapMinutesPerPlatform": 6,
    "maxResultsPerAngle": 5
  }
}
```

`platforms` is always an array (even for one platform) so the skill can fan out research across the full set in parallel.

## Step 1 — deep parallel web research (5 angles per platform)

For each platform, run the angles below as parallel subagents (Agent tool, `general-purpose`, one subagent per angle, single Agent message per platform). Each subagent uses `WebSearch` + `WebFetch` and returns evidence-anchored bullets (every claim carries a source URL + retrieval date). If multiple platforms are checked in one invocation, run their angle sets concurrently too.

### Angle 1 — Official API + access tier

Queries: `"<platform> API documentation"`, `"<platform> developer access"`, `"<platform> partner API"`, `"<platform> public API"`. Look for:

- Does an official API exist? Documented URL.
- Access tier: open public, requires app registration, paid-only, partner-only, closed (announcement of deprecation / shutdown).
- Rate limits, quotas.
- Auth scheme (OAuth2 / API key / user credentials / partner agreement).
- Recent changes (an API closing or being restricted in the last 12 months is a red flag).

Return: one block per platform with the answers + source URLs.

### Angle 2 — Programmatic access posture (ToS + legal)

Queries: `"<platform> terms of service scraping"`, `"<platform> robots.txt"`, `"<platform> automated access policy"`, `"<platform> CGU API tiers"`. Fetch the actual ToS page when found. Look for:

- Explicit clauses on programmatic / automated access.
- Anti-scraping language.
- Account-ban risk (clauses that say repeated programmatic access leads to account termination).
- Region-specific posture (some platforms have stricter rules in the EU under GDPR).

Return: ToS verdict (`permits-api-only`, `forbids-scraping-explicitly`, `silent-and-gray-zone`, `explicitly-permits`) + the relevant clause excerpts + URLs.

### Angle 3 — Community MCPs / SDKs / connectors

Queries: `"<platform> MCP server"`, `"<platform> python sdk"`, `"<platform> node client"`, `"<platform> n8n integration"`, `"<platform> Zapier"`, `"<platform> Make.com"`. Look for:

- An existing MCP on `mcp.so` / GitHub MCP registry / Glama.
- Official SDK in any language (means the API is real and usable).
- Third-party integrations on n8n / Zapier / Make / Pipedream (signals the platform is automatable and how).
- Maintenance status (last commit, open issues count).

Return: list of relevant connectors with URL, maintenance signal, and a one-line note on whether each is usable from a Bap workspace MCP.

### Angle 4 — Browser-automation feasibility

Queries: `"<platform> Playwright scraping"`, `"<platform> Selenium login"`, `"<platform> captcha bypass"`, `"<platform> Cloudflare protection"`, `"<platform> bot detection"`. Look for:

- Anti-bot stack in use (Cloudflare, Akamai, DataDome, PerimeterX, hCaptcha, reCAPTCHA v3).
- Reports of accounts banned for automated browsing.
- Whether login can be done programmatically or requires 2FA / SMS verification that breaks automation.
- Recent (12-month) blog posts / GitHub issues describing successful or failed automation.

Return: feasibility verdict (`easy`, `requires-stealth`, `frequently-blocked`, `hard-ban-risk`) + evidence.

### Angle 5 — Known incidents + alternative routes

Queries: `"<platform> account banned scraping"`, `"<platform> lawsuit scraping"`, `"<platform> alternative API"`, `"<platform> reseller program"`, `"<platform> data partner"`. Look for:

- Public lawsuits or cease-and-desist letters (LinkedIn vs hiQ is the canonical example; surface anything similar for the platform at hand).
- Official alternative routes (reseller, data partner, RSS feed, public dataset, weekly export).
- Aggregators that bundle the platform's data via a clean API (e.g. for real estate: Meilleurs Agents, Imodata, ImmoFacile).

Return: list of incidents + list of alternative routes (with URLs and access tier).

## Step 2 — verdict per platform

After all 5 angles return per platform, synthesise into a single verdict using the priority order below (first match wins):

| Verdict | Trigger |
|---------|---------|
| `feasible-via-api` | Angle 1 returns an open / app-registered API AND Angle 2 ToS permits it AND quotas fit `frequency`. |
| `feasible-via-mcp` | Angle 3 returns a maintained community MCP OR official SDK that covers the `interactionShape`. Bind it as a workspace MCP. |
| `feasible-via-browser` | No API / SDK available BUT Angle 2 ToS is silent or grey AND Angle 4 verdict is `easy` or `requires-stealth` AND no recent ban incidents in Angle 5. Strategy: Playwright in the Bap sandbox or via a custom MCP that proxies to a headless browser pool. |
| `legally-risky` | Angle 2 ToS explicitly forbids automated access AND Angle 5 shows recent account-ban incidents OR lawsuit precedent. Even if technically feasible, refuse to auto-scaffold; require operator override. |
| `infeasible` | Angle 1 says API is closed / partner-only without the operator having a partnership, AND Angle 3 has no working SDK / MCP, AND Angle 4 says hard-ban-risk. The platform is a dead end. |

When between two verdicts, pick the more conservative (lower in the priority list).

## Step 3 — recommended strategy + alternatives

For each platform, produce a one-paragraph recommendation:

- The recommended path (which strategy + which concrete artefact: API endpoint, SDK package, MCP URL, Playwright pattern, partner sign-up form).
- One backup path if the primary fails (e.g. "if the API rate-limit blocks `frequency: daily`, fall back to the RSS feed at <URL>").
- Required credentials / partnerships / paid tiers and how to obtain them (linking to the platform's developer signup or partner application page).
- If `legally-risky` or `infeasible`, the explicit alternative the operator should consider (different platform, aggregator, manual handoff step in the coworker prompt).

Cross-platform synthesis: when the input has multiple platforms in the same domain (e.g. Leboncoin + Se Loger + PAP + Bien'Ici for real estate), surface common patterns. If two platforms share an aggregator (e.g. ImmoFacile), recommend the aggregator as the single integration target.

## Output

```json
{
  "platforms": [
    {
      "name": "Leboncoin",
      "verdict": "legally-risky",
      "evidence": {
        "officialApi": { "exists": false, "tier": "closed-partner-only", "notes": "...", "sourceUrls": ["..."] },
        "tos": { "stance": "forbids-scraping-explicitly", "clauseExcerpt": "...", "sourceUrls": ["..."] },
        "communityConnectors": [ { "name": "...", "url": "...", "maintained": false, "usableFromBap": "no" } ],
        "browserAutomation": { "verdict": "frequently-blocked", "antiBotStack": "DataDome", "sourceUrls": ["..."] },
        "incidents": [ { "what": "...", "year": 2025, "url": "..." } ],
        "alternativeRoutes": [ { "name": "...", "tier": "...", "url": "..." } ]
      },
      "recommendation": {
        "primary": "<one paragraph>",
        "backup": "<one line>",
        "credentialsNeeded": [ { "what": "...", "where": "<signup URL>" } ]
      },
      "researchTimeSeconds": 220
    }
  ],
  "crossPlatformNotes": "<one paragraph; aggregator suggestion, common workaround>",
  "overallVerdict": "feasible | partially-feasible | infeasible",
  "humanStopRequired": true
}
```

`humanStopRequired` is `true` when any platform verdict is `legally-risky` or `infeasible`. The orchestrator must surface this to the operator before going further.

## Integration with the pipeline

### `parse-transcript-to-agent-spec` Step 5

After tool classification, gather all `neededTools[]` items whose `kind == "custom_mcp_to_build"` AND whose `name` matches a specific platform (not a generic verb like "calendar" or "crm"). Invoke this skill with the list. Attach the result to the spec as a top-level `platformFeasibility` field. The orchestrator reads it at Step 1.5.

### `transcript-to-bap-coworker` Step 1.5 (paired with `bap-prior-art-scout`)

Run order at Step 1.5:

1. `bap-prior-art-scout` first (does the operator already have an MCP for this platform locally?). Persist `prior-art.json`.
2. For each platform that the scout did NOT find a prior MCP for, invoke `bap-platform-feasibility-check`. Persist `platform-feasibility.json`.
3. If `humanStopRequired: true`, emit a HUMAN STOP with the verdict + the recommended path, before any MCP is scaffolded.

If feasibility recommends `feasible-via-mcp` with a maintained community MCP, the orchestrator skips `build-mcp-for-bap` for that platform and instructs the operator to bind the community MCP URL in Bap workspace settings (same HUMAN STOP shape as Step 2b today).

### `build-mcp-for-bap` pre-flight

Refuse to scaffold a new MCP for a platform when `bap-platform-feasibility-check` returned `legally-risky` or `infeasible` for it, unless the operator passes an explicit `overrideFeasibility: true` flag. The override is logged and noted in the generated MCP's README so future maintainers see the constraint.

## Standalone invocation

```
invoke bap-platform-feasibility-check
  platforms: [
    { name: "Leboncoin", interactionShape: "post", region: "FR", authNeeded: "user-credentials", frequency: "daily", context: "real estate listings publishing" },
    { name: "Se Loger", interactionShape: "both", region: "FR", authNeeded: "api-key", frequency: "daily", context: "real estate listings sync" },
    { name: "PAP", interactionShape: "read", region: "FR", authNeeded: "none", frequency: "hourly", context: "private-seller listings scrape" }
  ]
```

Returns the per-platform payload + cross-platform synthesis.

## Anti-patterns

- Skipping this skill when a platform is "obvious". LinkedIn is the obvious one and is also the canonical lawsuit example (hiQ); the skill exists precisely to catch obvious-looking platforms whose ToS or anti-bot stack makes them unreachable.
- Trusting a single source for a verdict. The 5 angles must all run; a community MCP that exists on GitHub but hasn't been touched in 3 years is not a valid integration path.
- Citing a verdict without source URLs. Every claim in the output carries the URL + retrieval date.
- Recommending browser automation when ToS forbids it. `feasible-via-browser` requires Angle 2 to be silent / grey, not negative. Otherwise default to `legally-risky`.
- Auto-overriding `legally-risky` because the use case is exciting. The override is operator-explicit.
- Burning more than `researchTimeCapMinutesPerPlatform` (6 by default) per platform. The 5 angles are wall-clock parallel; the cap is on the longest angle, not the sum.
- Running the skill on Bap canonical native integrations (Slack, Gmail, Notion, ...). Their feasibility is settled.

## Config

`lubin-skills/bap-platform-feasibility-check/config.yaml`:

```yaml
research_time_cap_minutes_per_platform: 6
max_results_per_angle: 5
canonical_native_platforms_to_skip:
  - slack
  - gmail
  - notion
  - linear
  - airtable
  - outlook
  - google-calendar
  - google-drive
  - salesforce
  - hubspot
verdict_priority:                        # first match wins, top to bottom
  - feasible-via-api
  - feasible-via-mcp
  - feasible-via-browser
  - legally-risky
  - infeasible
human_stop_verdicts:
  - legally-risky
  - infeasible
mcp_registries_to_check:
  - "https://mcp.so"
  - "https://github.com/modelcontextprotocol/servers"
  - "https://glama.ai/mcp/servers"
automation_tools_to_check:
  - n8n
  - zapier
  - make.com
  - pipedream
```

## See also

- [bap-prior-art-scout](../bap-prior-art-scout/SKILL.md): runs first at Step 1.5 to check INTERNAL prior art. This skill complements it for EXTERNAL feasibility on non-native platforms.
- [parse-transcript-to-agent-spec](../parse-transcript-to-agent-spec/SKILL.md): primary upstream invoker.
- [transcript-to-bap-coworker](../transcript-to-bap-coworker/SKILL.md): orchestrator chains prior-art + feasibility before generation.
- [build-mcp-for-bap](../build-mcp-for-bap/SKILL.md): refuses to scaffold without a feasibility green light.
- [bap-capability-impact-analyzer](../bap-capability-impact-analyzer/SKILL.md): the analysis-side complement for capability gaps inside HeyBap itself.
