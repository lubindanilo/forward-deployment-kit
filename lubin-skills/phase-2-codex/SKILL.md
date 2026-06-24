---
name: phase-2-codex
description: Runs a Codex-native Phase 2 flow for HeyBap findings without delegating to the Claude CLI wrapper. Use when the user mentions phase 2 but wants Codex to handle the routing directly, or when the Claude-based FDK wrapper is unavailable or undesirable.
---

# Phase 2 Codex

Use this skill when the user wants the Phase 2 outcome, but wants Codex to do the work directly instead of launching `claude -p`.

## Inputs

Parse these from the request:

- `kind`: required, either `bug` or `feature`
- `description`: required, one-line summary of the finding

## Workflow

1. Work from `/Users/lubin.danilo/bap/forward-deployment-kit`.
2. Read the classification rubric in `lubin-skills/feature-bug-complexity-classification/SKILL.md`.
3. Do the same focused 5-minute investigation in the Bap codebase:
   - localize the likely surface
   - estimate lines changed and files touched
   - check the clarification gate before marking a small ambiguity complex
   - decide SIMPLE vs COMPLEX using the rubric strictly after that gate
   - if COMPLEX, decide SCOPED vs FUZZY using the fuzziness rules
4. Do not call the Claude wrapper. Codex performs the classification and downstream action itself.

## Downstream action

- `needs-clarification`: ask the user one concise question and stop before any
  ticket, artifact, or implementation work. Use this when the surface is
  localized, the likely fix is small, and the only blocker is operator intent
  such as exact UI placement or label wording.
- `simple`: implement the fix in the appropriate repo when feasible, verify it, and prepare the scoped commit/branch state.
- `complex-scoped`: prepare the brainstorm artifact the team needs, using the FDK brainstorm format as the reference.
- `complex-fuzzy`: prepare the direction-shaping artifact the team needs, using the FDK shaping format as the reference.

## Output contract

At the end, report:

1. Verdict
2. Classification
3. Surface identified
4. Files/lines estimate
5. Action taken
6. Any ticket / PR / artifact path produced

## Guardrails

- Do not route through `./scripts/submit-finding.sh`.
- Apply the file-count threshold from the current FDK rubric exactly.
- Do not classify a small localized UI/copy ambiguity as `complex-scoped` until
  the user has had a chance to answer the clarification question.
- If a required external tool is unavailable, continue with the best local artifact instead of blocking early.
- Keep the user informed when the result is a prepared artifact rather than a live Linear action.
