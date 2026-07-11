# Phantom CI Smoke-Job — Specification

> **Status:** specification only. This document defines the reusable GitHub
> Actions job that **PR-004 Step 3** will implement. It is written against
> **Phantom Consumer Contract v1.0.0** ([`CONTRACT.md`](../CONTRACT.md)). No
> workflow is created by this document — the YAML below is the *target design*,
> not an active workflow.

## Purpose

Give any consumer repo a one-line, reusable CI job that proves — on every PR —
that its app still **boots in `PHANTOM_MODE`, reaches healthy, and produces
screenshots**. It is a smoke test: a red run means "the demo-mode boot or a
capture broke," caught before merge. It captures frames and uploads them as PR
artifacts for human review; it does **not** commit them (that is the separate
publish flow in `phantom-capture.yml`).

The job depends only on the frozen contract surface: `PHANTOM_MODE=1`, the
`.phantom.yml` schema, the `ready_check` timeout, and the `docs/screenshots/`
artifact directory.

## Inputs (`workflow_call.inputs`)

| Input | Required | Default | Purpose |
|-------|----------|---------|---------|
| `image-ref` | no¹ | `""` | Prebuilt container image to run in `PHANTOM_MODE` (e.g. `ghcr.io/org/app:pr-${{ github.sha }}`). If empty, the job builds from the repo's `docker-compose.yml` referenced by `.phantom.yml`. |
| `healthcheck-url` | no | from manifest | Overrides the readiness URL; otherwise taken from `setup.run.ready_check.url`. |
| `healthcheck-timeout` | no | from manifest (`30`) | Seconds to wait for healthy; otherwise `setup.run.ready_check.timeout`. |
| `phantom-contract-version` | **yes** | — | The contract major the consumer targets, e.g. `1.x`. The job asserts `phantom.__contract_version__` satisfies it and fails fast on a major mismatch. |
| `phantom-version` | no | `>=0.4,<0.5` | Package version range to install (pins the contract major — see [Contract §5](../CONTRACT.md#5-versioning-rules)). |
| `project-type` | **yes** | — | `web` \| `docker-compose` \| `tui` \| `desktop` (selects the runner's system deps). |
| `artifact-name` | no | `phantom-smoke-screenshots` | Name of the uploaded PR artifact. |

¹ Exactly one of `image-ref` or a compose-based `.phantom.yml` must be present.

### Secrets

None required for the smoke job. Demo mode forbids real credentials
([Contract §1](../CONTRACT.md#1-boot-contract--phantom_mode1)); the job runs
without repo secrets so forks can run it too. `anthropic-key` is **not** used —
smoke captures are deterministic and AI-free.

## What the consumer repo MUST provide

1. **A `.phantom.yml`** at the repo root (schema `phantom: "1"`), with at least
   one capture writing under `docs/screenshots/`
   ([Contract §2](../CONTRACT.md#2-config-contract--phantomyml-schema),
   [§4](../CONTRACT.md#4-artifact-contract)).
2. **A readiness signal** the app exposes under `PHANTOM_MODE`
   ([Contract §3](../CONTRACT.md#3-health-contract)) — normally an HTTP health
   endpoint named in `setup.run.ready_check`.
3. **`PHANTOM_MODE` demo mode** in the app: no real creds, deterministic seed
   data, no external network beyond the allowlist
   ([Contract §1](../CONTRACT.md#1-boot-contract--phantom_mode1)).
4. **For `docker-compose` / `image-ref` consumers:** the container/compose must
   **propagate `PHANTOM_MODE`** to the app process, e.g.
   ```yaml
   services:
     app:
       environment: [PHANTOM_MODE]     # inherits PHANTOM_MODE=1 from the job
       # optional: a Docker HEALTHCHECK the job can also poll
   ```

## Steps (normative sequence)

1. **Checkout** the calling repo.
2. **Install Phantom** at `phantom-version` and **assert the contract version**:
   fail fast unless `phantom.__contract_version__` matches
   `phantom-contract-version` (major must match).
3. **Install runner system deps** for `project-type` (Playwright/chromium for
   web & docker; Rust+silicon for tui; xvfb+xdotool+imagemagick for desktop).
4. **Validate the manifest:** `phantom validate .phantom.yml` (fails on schema
   errors; unknown keys are ignored per [Contract §2](../CONTRACT.md#forward-compatibility-rule-frozen)).
5. **Start the app in `PHANTOM_MODE`** — the job exports `PHANTOM_MODE=1`, and
   Phantom's runner also guarantees it in the app env. For `image-ref`, the job
   runs the container with `-e PHANTOM_MODE=1`.
6. **Poll health** at `healthcheck-url` until 2xx or `healthcheck-timeout`
   seconds elapse. (Phantom's own `ready_check` performs this; the explicit
   inputs allow the smoke job to gate independently.)
7. **Capture screenshots:** `phantom run --project . --skip-publish --fail-on-quality-error`.
   `--skip-publish` means nothing is committed/pushed. `--fail-on-quality-error`
   fails the job on an error-severity frame (blank / too-small / wrong-dims).
8. **Collect & upload** `docs/screenshots/` as a PR artifact named
   `artifact-name`, gated on `success()` (never upload a failed/sensitive frame).
9. **Teardown** the container/process (always runs).

## Pass / fail semantics

| Outcome | Result |
|---------|--------|
| App reaches healthy within timeout **and** all captures pass quality | ✅ pass; screenshots uploaded as PR artifact |
| App fails `ready_check` within timeout | ❌ fail (boot/health regression) |
| Any capture hits an **error-severity** quality issue | ❌ fail (via `--fail-on-quality-error`); artifact **not** uploaded |
| Manifest invalid (known rule) | ❌ fail at validate step |
| Warning-severity quality issue (e.g. low entropy) | ✅ pass (advisory only) |

The smoke job is **read-only with respect to the repo**: it never commits,
pushes, or opens a PR. Publishing remains the job of `phantom-capture.yml`.

## Target job design (illustrative — implemented in Step 3)

```yaml
# .github/workflows/phantom-smoke.yml  (created in Step 3, not here)
name: Phantom Smoke (Reusable)
on:
  workflow_call:
    inputs:
      project-type:             { required: true,  type: string }
      phantom-contract-version: { required: true,  type: string }   # e.g. "1.x"
      phantom-version:          { required: false, type: string, default: ">=0.4,<0.5" }
      image-ref:                { required: false, type: string, default: "" }
      healthcheck-url:          { required: false, type: string, default: "" }
      healthcheck-timeout:      { required: false, type: number, default: 30 }
      artifact-name:            { required: false, type: string, default: "phantom-smoke-screenshots" }

jobs:
  smoke:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      pull-requests: write      # to attach the artifact link to the PR
    steps:
      - uses: actions/checkout@v4

      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }

      - name: Install Phantom & assert contract version
        run: |
          pip install "phantom-docs${{ inputs.phantom-version }}"
          python - <<'PY'
          import os, phantom
          want = os.environ["WANT"].split(".")[0]
          have = phantom.__contract_version__.split(".")[0]
          assert have == want, f"contract major {have} != required {want}"
          print("phantom", phantom.__version__, "contract", phantom.__contract_version__)
          PY
        env:
          WANT: ${{ inputs.phantom-contract-version }}

      # ... project-type-specific runner deps (see phantom-capture.yml) ...

      - name: Validate manifest
        run: phantom validate .phantom.yml

      - name: Capture in PHANTOM_MODE
        env:
          PHANTOM_MODE: "1"
        run: phantom run --project . --skip-publish --fail-on-quality-error

      - name: Upload screenshots (PR artifact)
        if: success()
        uses: actions/upload-artifact@v4
        with:
          name: ${{ inputs.artifact-name }}
          path: docs/screenshots/
          if-no-files-found: error
```

> The `image-ref` path (run a prebuilt container with `-e PHANTOM_MODE=1`, poll
> `healthcheck-url`, then `phantom run` against it) is the Step-3 extension of
> the compose flow above and is specified by the Inputs/Steps tables, not by
> this sketch.

## Relationship to `phantom-capture.yml`

`phantom-capture.yml` (existing) **publishes** refreshed screenshots (commit /
PR / squash) and already exports `PHANTOM_MODE: "1"`. The smoke job is its
**non-publishing sibling**: same boot/health/capture core, but its only output
is a pass/fail signal plus a review artifact. Step 3 may factor the shared
setup into a common composite action; that refactor is out of scope for the
contract freeze.
