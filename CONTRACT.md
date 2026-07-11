<!--
contract-version: 1.0.0
-->

# Phantom Consumer Contract

**contract-version: 1.0.0**

This document is the **frozen interface** between Phantom and everything that
depends on it — consumer applications that add a demo mode, the CI *smoke job*
that captures them (see [`docs/smoke-job-spec.md`](docs/smoke-job-spec.md)), and
any tooling that pins `phantom-docs`. Phantom may change *how* it captures
screenshots freely, but the promises below do not change without a
contract-version bump (see [§5](#5-versioning-rules)).

The contract is versioned **independently of the `phantom-docs` package**. The
current package exposes it as `phantom.__contract_version__` and
`phantom.contract.CONTRACT_VERSION`, and the machine-checkable half of every
promise here lives in [`src/phantom/contract.py`](src/phantom/contract.py),
mechanically verified by [`tests/contract/`](tests/contract/).

> **Terminology.** *Consumer app* = the application being screenshotted.
> *Phantom* = the `phantom-docs` tool that launches it and captures frames.
> *Manifest* = the consumer's `.phantom.yml`. *Smoke job* = the CI job (Step 3)
> that runs a consumer container in `PHANTOM_MODE` and collects artifacts.

---

## 1. Boot contract — `PHANTOM_MODE=1`

`PHANTOM_MODE` is the single environment variable that switches a consumer app
into a self-contained, reproducible *demo mode*.

### What Phantom guarantees

- **Phantom sets `PHANTOM_MODE=1` in the launched app's environment for every
  capture run.** This holds for all runners — `web`, `docker-compose`, `tui`,
  and `desktop` — and does **not** depend on the shell that invoked Phantom.
  The guarantee is implemented once in `phantom.contract.app_env()`.
  - For process runners (`web` / `tui` / `desktop`) the variable is injected
    directly into the child process environment.
  - For `docker-compose`, Phantom sets `PHANTOM_MODE=1` in the environment used
    to invoke `docker compose up`; the consumer's compose file **must** forward
    it to the app service (see [§1 consumer obligations](#what-the-consumer-app-must-guarantee)).
- **Detection semantics are exact:** demo mode is ON when
  `PHANTOM_MODE == "1"` and OFF for every other value (unset, `"0"`, `"true"`,
  `" 1"`, …). This is `phantom.contract.is_phantom_mode()`.
- **Precedence.** Lowest→highest: inherited process env → `PHANTOM_MODE=1`
  (the guarantee) → the manifest's explicit `setup.run.env`. A manifest may
  therefore override `PHANTOM_MODE` for a specific launch, but the default for
  every runner is demo mode ON.

### What the consumer app MUST guarantee

When it observes `PHANTOM_MODE=1`, a conformant consumer app **must**:

1. **Require no real credentials.** No login, no secrets, no API keys needed to
   reach a useful state. Bypass auth or auto-provision a demo session.
2. **Use deterministic seed data.** Same data, same layout, every run. Seed all
   RNG with a fixed value. Screenshots must be reproducible in content.
3. **Make no external network calls beyond the allowlist.** The permitted
   network surface is loopback (`localhost`, `127.0.0.1`, `::1`, `0.0.0.0`)
   plus any host explicitly declared in the manifest's `ready_check` /
   `fixtures`. Mock or stub everything else. Phantom's own probes only ever
   contact hosts in this allowlist (`phantom.contract.manifest_allowlist()`).
4. **Reach a healthy state unaided** within the declared timeout (see
   [§3](#3-health-contract)) — no manual step, no interactive prompt.
5. **For `docker-compose` consumers:** propagate `PHANTOM_MODE` into the app
   service, e.g.

   ```yaml
   services:
     app:
       environment:
         - PHANTOM_MODE          # inherits Phantom's PHANTOM_MODE=1
   ```

---

## 2. Config contract — `.phantom.yml` schema

The manifest is parsed by `phantom.models.load_manifest` → `PhantomManifest`.
Schema version is pinned by the top-level `phantom: "1"` field.

### Required fields

| Field | Type | Notes |
|-------|------|-------|
| `phantom` | string | **Must equal `"1"`.** Any other value is fatal. |
| `project` | string | Slug `^[a-z0-9][a-z0-9-]*$`. |
| `name` | string | Human-readable. |
| `setup` | mapping | Runner setup; requires `setup.type` and `setup.run` (`command` + `ready_check`). |
| `captures` | list | **≥ 1** capture; each needs `id` (slug), `name`, `output`. |

### Optional fields & defaults

| Field | Default | Notes |
|-------|---------|-------|
| `description` | `null` | |
| `fixtures` | `[]` | Seed steps (`script` / `http` / `file_copy`). |
| `capture_defaults` | `null` | Shared viewport/theme/timeout/retry defaults. |
| `processing` | built-in defaults | `format: png`, `optimize: true`, border, diff. |
| `publishing` | built-in defaults | `branch: main`, `strategy: direct`. |
| `triggers` | `[]` | |
| `groups` | `null` | |
| `tui` / `desktop` / `director` | `null` | Runner-specific blocks. |

Per-capture optional fields include `route`, `wait_for`, `actions`, `viewport`,
`theme`, `device_scale`, `full_page`, `timeout`, `format`, `retry`, `skip`,
`depends_on`, `parallel`, `readme_target`, `alt_text`. Defaults resolve via
`CaptureDefinition.resolve()`; see [`docs/manifest-reference.md`](docs/manifest-reference.md)
for the exhaustive list.

### Forward-compatibility rule (frozen)

> **Unknown keys are IGNORED and are NEVER fatal**, at the top level and at
> every nested level.

This lets Phantom add manifest fields in a minor release without breaking older
consumers, and lets consumers adopt new fields without a hard version floor.
A manifest that fails to parse does so only because of a **known** rule:
missing required field, `phantom != "1"`, bad slug, duplicate capture id,
`output` escaping the project root ([§4](#4-artifact-contract)), unknown
`depends_on`/`group` reference, or a dependency cycle.

---

## 3. Health contract

Under `PHANTOM_MODE` the consumer app **must expose its normal readiness
signal** and reach healthy **within a declared timeout**. Phantom polls that
signal before it captures anything; if it is not healthy in time, the run fails
loudly (no screenshots).

- **The timeout is declared** in the manifest at
  **`setup.run.ready_check.timeout`** (seconds). It **defaults to `30`**
  (`phantom.contract.DEFAULT_READY_TIMEOUT_SECONDS`).
- **Readiness probe types:** `http` (poll a URL for a status code — the normal
  healthcheck endpoint), `tcp` (port open), `stdout_match` (regex on app
  output), `delay` (fixed seconds), `screen_stable` (desktop/TUI: pixels
  settle). `interval` (default `1s`) controls poll cadence.
- The `http` probe is the canonical healthcheck path: point it at the app's
  existing health/readiness endpoint. The consumer is free to shortcut that
  endpoint under `PHANTOM_MODE` (e.g. skip external-dependency checks).

The health contract is intentionally the same signal a human or an orchestrator
would use — Phantom does not require a Phantom-specific health endpoint.

---

## 4. Artifact contract

- **Output location.** Each capture declares a project-root-**relative**
  `output:` path. By convention screenshots live under
  **`docs/screenshots/`** — the documented default artifact directory
  (`phantom.contract.DEFAULT_ARTIFACT_DIR`) that the CI smoke job collects and
  uploads.
- **Path safety (frozen).** `output` **must** be relative and **must not**
  contain `..`; absolute paths and parent-escapes are fatal at parse time.
  Screenshots therefore always land inside the consumer repo.
- **Naming.** The filename is exactly the capture's `output` basename (stable,
  author-chosen, e.g. `dashboard.png`). Capture `id`s are unique slugs.
- **Format.** `png` (default) or `webp`, set by `processing.format` and
  optionally overridden per capture via `format:`. The file extension matches
  the chosen format.

> The **artifact directory** (`docs/screenshots/`) is contractual — the smoke
> job depends on it. Individual filenames are author-chosen but stable across
> runs for a given manifest.

---

## 5. Versioning rules

Phantom versioning mirrors the **Docker image-pinning discipline**: pin a
range, not `latest`; a breaking change forces a new major you opt into
explicitly.

- **Consumers pin the package by minor range:** `phantom-docs==0.4.*`
  (equivalently `>=0.4,<0.5`) — analogous to pinning `myimage:1.4` rather than
  `myimage:latest`.
- **Consumers assert on the contract version, not the package version:** check
  `phantom.__contract_version__ == "1.x"`.
- **Contract-breaking change** (removing/renaming a promised field, changing
  `PHANTOM_MODE` semantics, moving the artifact dir, tightening unknown-key
  handling) ⇒ **package MAJOR** bump **and** **contract-version MAJOR** bump.
- **Additive change** (new optional manifest field, new probe type, new runner)
  ⇒ **package MINOR** and **contract-version MINOR**; unknown-key tolerance
  ([§2](#forward-compatibility-rule-frozen)) means older consumers keep working.
- **Patch** (bug fix, behavior made to match this contract) ⇒ package PATCH,
  contract-version unchanged.

The package version and the contract version move on **independent** tracks: a
package minor that only touches internals leaves the contract version untouched.

---

## 6. Non-goals — what this contract does NOT promise

- **Internals.** Module layout, class names, the runner registry, the darkroom
  pipeline stages, and any function not re-exported from
  `phantom.contract` are implementation detail and may change any time.
- **CLI surface outside the contract.** Only `PHANTOM_MODE`, the `.phantom.yml`
  schema, the readiness/timeout mechanism, and the artifact directory are
  frozen. Other CLI flags, subcommands, log format, and exit codes (beyond
  "non-zero on failure") are not part of the contract.
- **Operator/analyst env vars.** `PHANTOM_WEBHOOK_SECRET`,
  `PHANTOM_MANIFEST_MAP`, `PHANTOM_LLM_PROVIDER`, `PHANTOM_LLM_MODEL`,
  `PHANTOM_ANALYST_ENABLED`, `ANTHROPIC_API_KEY` configure Phantom itself, not
  the consumer interface, and are out of scope here.
- **Screenshot pixel stability.** The contract guarantees *content*
  determinism (same seed data, same states), **not** byte-for-byte or
  pixel-for-pixel identical images across Phantom versions, OS/browser
  versions, or font stacks. Do not diff-gate on exact bytes.
- **Processing/aesthetic output.** Borders, shadows, optimization level, and
  max-width are configurable and may evolve; their exact rendered result is not
  frozen.
- **Publishing behavior.** Commit/PR/squash strategies and quality-gating are
  operational features, not part of the consumer boot/capture contract.

---

*Machine-checkable source of truth:* [`src/phantom/contract.py`](src/phantom/contract.py) ·
*Conformance tests:* [`tests/contract/`](tests/contract/) ·
*Smoke-job spec:* [`docs/smoke-job-spec.md`](docs/smoke-job-spec.md)
