---
name: phase-2
description: Runs Phase 2 of the HeyBap forward-deployment pipeline for a bug or feature finding. Use when the user mentions phase 2, wants to submit a HeyBap bug or feature finding, asks to route an issue through the classification gate, or wants the active agent runtime to handle Phase 2.
---

# Phase 2

Use this provider-agnostic skill to route a HeyBap finding through Phase 2 with
the active agent runtime.

## Inputs

Parse these from the request:

- `kind`: required, either `bug` or `feature`
- `description`: required, one-line summary of the finding

## Runtime selection

- **Codex active**: run Phase 2 directly in Codex. Work from `/Users/lubin.danilo/bap/forward-deployment-kit`, read the classifier rubric, investigate, classify, and take the downstream action yourself. Do not launch a Claude wrapper unless the user explicitly asks for the guarded wrapper or the direct path is blocked.
- **Claude / Claude Code active**: use the guarded FDK wrapper from the shell. The wrapper is the Claude adapter and owns the full classifier dispatch.
- **Unknown runtime**: prefer the current runtime if it can read files, run shell commands, and perform the required downstream actions. If not, fall back to the guarded wrapper and state that choice.

## Codex workflow

1. Work from `/Users/lubin.danilo/bap/forward-deployment-kit`.
2. Read `lubin-skills/feature-bug-complexity-classification/SKILL.md`.
3. Do the focused investigation in the Bap codebase:
   - localize the likely surface
   - estimate lines changed and files touched
   - check the clarification gate before marking a small ambiguity complex
   - decide SIMPLE vs COMPLEX using the rubric strictly after that gate
   - if COMPLEX, decide SCOPED vs FUZZY using the fuzziness rules

## Codex downstream action

- `needs-clarification`: ask the user one concise question and stop before any ticket, artifact, or implementation work.
- `simple`: implement the fix in the appropriate repo when feasible, verify it, and prepare the scoped commit/branch state.
- `complex-scoped`: prepare the brainstorm artifact the team needs, using the FDK brainstorm format as the reference.
- `complex-fuzzy`: prepare the direction-shaping artifact the team needs, using the FDK shaping format as the reference.

## Claude wrapper workflow

1. `cd /Users/lubin.danilo/bap/forward-deployment-kit`
2. Run:

```bash
./scripts/submit-finding.sh "$KIND" "$DESCRIPTION"
```

3. If the wrapper returns `needs-clarification`, relay the exact clarification
   question to the user and stop. Do not call downstream skills or create a
   local workaround ticket.

## Output contract

At the end, report:

1. Verdict
2. Classification
3. Surface identified
4. Files/lines estimate when available
5. Action taken
6. Any ticket, PR, clarification question, Slack thread, or artifact path produced

## Guardrails

- Do not keep separate provider-specific Phase 2 skills. This skill is the canonical Phase 2 contract; provider differences belong in the runtime selection above.
- Never bypass the classifier by calling `bap-bug-report`, `bap-feature-brainstorm`, or other leaf skills directly unless this skill has already classified the finding for the active runtime path.
- Do not classify a small localized UI/copy ambiguity as `complex-scoped` until the user has had a chance to answer the clarification question.
- If the wrapper fails, debug from `submit-finding.sh` rather than re-routing manually.
