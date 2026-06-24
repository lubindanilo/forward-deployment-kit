---
name: phase-1-codex
description: Runs a Codex-native Phase 1 flow for HeyBap forward deployment without delegating to the Claude CLI wrapper. Use when the user mentions phase 1 but wants Codex to handle the transcript-to-coworker flow directly, or when the Claude-based FDK wrapper is unavailable or undesirable.
---

# Phase 1 Codex

Use this skill when the user wants the Phase 1 outcome, but wants Codex to do the work directly instead of launching `claude -p`.

## Inputs

Parse these from the request when present:

- `input`: transcript file path, Grain URL, or inline brief
- `prospect`: optional prospect/client name
- `call_type`: optional call type such as `discovery`, `kickoff`, `follow-up`, `technical`, `demo`, or `brief`
- `max_agents`: optional cap on coworkers to build, default `3`

## Workflow

1. Work from `/Users/lubin.danilo/bap/forward-deployment-kit`.
2. Read the relevant FDK references before acting:
   - `lubin-skills/parse-transcript-to-agent-spec/SKILL.md`
   - `lubin-skills/bap-prior-art-scout/SKILL.md`
   - `lubin-skills/bap-platform-feasibility-check/SKILL.md`
   - `lubin-skills/transcript-to-bap-coworker/SKILL.md`
   - `lubin-skills/bap-coworker-test-loop/SKILL.md`
3. Recreate the same end-to-end reasoning directly in Codex:
   - parse the transcript or brief into a structured coworker spec
   - inspect prior art and feasibility constraints
   - scaffold or update the coworker assets needed
   - validate the outcome through the local test loop when feasible
   - surface HeyBap gaps through the current Phase 2 Codex flow when needed
4. Do not call the Claude wrapper. Codex performs the orchestration directly.

## Output contract

At the end, report:

1. Verdict
2. Spec or coworker surface identified
3. Assets or files created or updated
4. Validation performed
5. Any tickets, PRs, or artifact paths produced
6. Any human follow-up still required

## Guardrails

- Do not route through `./scripts/build-from-transcript.sh`.
- Reuse the FDK skill contracts and wording as the source of truth for the flow.
- If an external dependency is unavailable, keep going with the best local artifact rather than failing early.
- Keep the user informed when the result is a prepared artifact rather than a live deployed coworker.
