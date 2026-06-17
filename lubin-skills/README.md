# lubin-skills

Field-tested skills contributed by [Lubin Danilo](https://github.com/lubindanilo) for shipping coworkers + MCPs on Bap (Heybap). Each skill captures gotchas learned from production deployments (BATIMGIE energy audits, Galien pharmacy pre-visits, `hyperstack-transcribe` MCP) that aren't documented elsewhere.

## Contents

| Skill | One-liner |
|-------|-----------|
| [`build-mcp-for-bap`](build-mcp-for-bap/SKILL.md) | Scaffold a custom HTTP MCP server (Next.js + Vercel) that satisfies Bap's OAuth 2.0 auto-approve dance. |
| [`build-agents-for-bap`](build-agents-for-bap/SKILL.md) | Ship reliable coworkers — skill design, MCP wiring, auth modes, sandbox layout, debugging via `coworker_logs`. The agent-side counterpart of `build-mcp-for-bap`. |

## How to use these in your own setup

These skills are designed to be installed in Bap as user skills via the `skill_add` MCP tool, or copied into `.agents/skills/` of an FDK fork. They reference each other (`../<other-skill>/SKILL.md`) so keep them side by side.

The two skills together cover the full development loop : `build-mcp-for-bap` builds the tool layer, `build-agents-for-bap` wires it into a coworker that actually works in production.
