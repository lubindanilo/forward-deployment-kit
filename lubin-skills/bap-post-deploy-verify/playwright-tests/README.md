# playwright-tests

This folder holds the generated Playwright specs that `bap-post-deploy-verify` uses in **Mode C** (headless validation of a finding after a PR is merged on `the-agentic-company/bap`).

One spec per finding. Naming convention:

```
<finding-hash>.spec.ts
```

Where `<finding-hash>` is the SHA-256 of the canonical finding form (also embedded in the PR body by `bap-bug-report` as `FINDING_CONTEXT.hash`).

## How a spec is created

`bap-post-deploy-verify` generates the spec on first verification of a finding (see step 3C.2 of its `SKILL.md`). Subsequent verifications of the same finding reuse the existing file.

A generated spec has this shape:

```typescript
import { test, expect } from "@playwright/test";

test.describe("Finding <hash>: <one-line description>", () => {
  test("symptom no longer present after merge", async ({ page }) => {
    await page.goto("/");
    // ...steps derived from the finding's reproSteps...
    // ...assertions derived from successCriteria or checklist...
  });
});
```

## Running locally

One-off auth bootstrap (writes `~/.heybap-playwright-auth.json`):

```bash
npm install
npx playwright install chromium
HEYBAP_URL=https://heybap.com npm run auth:bootstrap
# log in once; the storage state is reused by every spec from then on
```

Run all specs:

```bash
HEYBAP_URL=https://heybap.com npm run verify
```

Run a single spec:

```bash
HEYBAP_URL=https://heybap.com npx playwright test playwright-tests/<finding-hash>.spec.ts
```

Headed for debugging:

```bash
HEYBAP_URL=https://heybap.com npm run verify:headed
```

## CI

Once a spec lives in this folder, it is a permanent regression test. A future GitHub Actions workflow on `the-agentic-company/bap` can run `npm run verify` against the production deploy on every merge, independently of the `bap-post-deploy-verify` skill invocation. The skill remains responsible for the **first** verification (Mode A or B or C, picked per finding), the CI handles the **ongoing** verifications.

## What does NOT live here

- Specs for new features (those belong in the `bap` repo's own test suite).
- Authentication credentials (storage state lives outside the repo, under `~/.heybap-playwright-auth.json`).
- Screenshots and videos (Playwright writes them to `/tmp/bap-verify-playwright`, not committed).
