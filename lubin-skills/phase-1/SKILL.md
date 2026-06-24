---
name: phase-1
description: Runs Phase 1 of the HeyBap forward-deployment pipeline from a transcript, Grain link, or operator brief. Use when the user mentions phase 1, wants to build coworkers from a call transcript or brief, or asks to run the transcript-to-coworker pipeline in the current agent runtime.
---

# Phase 1

Use this provider-agnostic skill to launch Phase 1 with the active agent runtime.

## Inputs

Parse these from the request when present:

- `input`: transcript file path, Grain URL, `-` for stdin, or inline brief
- `prospect`: optional prospect/client name
- `call_type`: optional call type such as `discovery`, `kickoff`, `follow-up`, `technical`, `demo`, or `brief`
- `max_agents`: optional cap on coworkers to build, default `3`

## Runtime selection

- **Codex active**: run Phase 1 directly in Codex. Work from `/Users/lubin.danilo/bap/forward-deployment-kit`, read the FDK reference skills listed below, and execute the same pipeline yourself. Do not launch a Claude wrapper unless the user explicitly asks for the guarded wrapper or the direct path is blocked.
- **Claude / Claude Code active**: use the guarded FDK wrapper from the shell. The wrapper is the Claude adapter and owns the full chain.
- **Unknown runtime**: prefer the current runtime if it can read files, run shell commands, and perform the required downstream actions. If not, fall back to the guarded wrapper and state that choice.

## Codex workflow

1. Work from `/Users/lubin.danilo/bap/forward-deployment-kit`.
2. Read the relevant FDK references before acting:
   - `lubin-skills/parse-transcript-to-agent-spec/SKILL.md`
   - `lubin-skills/bap-prior-art-scout/SKILL.md`
   - `lubin-skills/bap-platform-feasibility-check/SKILL.md`
   - `lubin-skills/transcript-to-bap-coworker/SKILL.md`
   - `lubin-skills/bap-coworker-test-loop/SKILL.md`
3. Recreate the same end-to-end reasoning directly:
   - parse the transcript or brief into a structured coworker spec
   - inspect prior art and feasibility constraints
   - scaffold or update the coworker assets needed
   - validate through the local test loop when feasible
   - surface HeyBap gaps through the current Phase 2 skill when needed

## Claude wrapper workflow

1. `cd /Users/lubin.danilo/bap/forward-deployment-kit`
2. Run:

```bash
./scripts/build-from-transcript.sh "$INPUT" "$PROSPECT" "$CALL_TYPE" "$MAX_AGENTS"
```

3. If the user only provided inline text instead of a path or URL, pipe it through stdin:

```bash
echo "$INPUT" | ./scripts/build-from-transcript.sh - "$PROSPECT" brief
```

## Output contract

At the end, report:

1. Verdict
2. Spec or coworker surface identified
3. Assets or files created or updated
4. Validation performed
5. Any tickets, PRs, Slack permalinks, final report paths, or artifact paths produced
6. Any human follow-up still required

## Guardrails

- Do not keep separate provider-specific Phase 1 skills. This skill is the canonical Phase 1 contract; provider differences belong in the runtime selection above.
- Do not bypass the Phase 1 orchestration by calling only one leaf skill unless the selected runtime workflow says to read that leaf as part of the full chain.
- If an external dependency is unavailable, keep going with the best local artifact instead of failing early, and clearly report what was not live-executed.
- If the wrapper fails, debug from `build-from-transcript.sh` rather than re-routing manually.
