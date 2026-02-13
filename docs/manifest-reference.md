# Phantom Manifest Reference

Complete field reference for the `.phantom.yml` configuration file.

All fields are documented with their types, default values, constraints, and usage
examples. The manifest is validated at load time using Pydantic v2 models defined in
`src/phantom/models.py`.

---

## Table of Contents

- [Top-Level Fields](#top-level-fields)
- [setup](#setup)
  - [setup.run](#setuprun)
  - [ready_check](#ready_check)
- [fixtures](#fixtures)
- [capture_defaults](#capture_defaults)
- [captures](#captures)
- [Actions](#actions)
- [processing](#processing)
- [publishing](#publishing)
- [triggers](#triggers)
- [tui](#tui)
- [desktop](#desktop)
- [director](#director)
- [groups](#groups)
- [Full Examples](#full-examples)

---

## Top-Level Fields

| Field         | Type              | Required | Default | Description                                    |
|---------------|-------------------|----------|---------|------------------------------------------------|
| `phantom`     | `string`          | Yes      | --      | Schema version. Must be `"1"`.                 |
| `project`     | `string`          | Yes      | --      | Project slug. Pattern: `^[a-z0-9][a-z0-9\-]*$` |
| `name`        | `string`          | Yes      | --      | Human-readable project name.                   |
| `description` | `string \| null`  | No       | `null`  | Project description.                           |
| `setup`       | `SetupConfig`     | Yes      | --      | How to build and run the target application.   |
| `fixtures`    | `list[Fixture]`   | No       | `[]`    | Data fixtures to load before capturing.        |
| `capture_defaults` | `CaptureDefaults \| null` | No | `null` | Default values applied to all captures.   |
| `captures`    | `list[CaptureDefinition]` | Yes | --   | At least one capture definition is required.   |
| `processing`  | `ProcessingConfig` | No      | See [processing](#processing) | Image post-processing pipeline. |
| `publishing`  | `PublishingConfig` | No      | See [publishing](#publishing) | How and where to publish results. |
| `triggers`    | `list[TriggerConfig]` | No   | `[]`    | CI/CD trigger definitions.                     |
| `groups`      | `dict[string, list[string]] \| null` | No | `null` | Named groups of capture IDs.       |
| `tui`         | `TUIConfig \| null` | No      | `null` | TUI runner configuration.                      |
| `desktop`     | `DesktopConfig \| null` | No  | `null`  | Desktop runner configuration.                  |
| `director`    | `DirectorConfig \| null` | No | `null`  | AI director configuration.                     |

**Validation rules:**

- `phantom` must equal `"1"`.
- All capture `id` values must be unique.
- Capture `output` paths must be relative and must not contain `..`.
- Any `depends_on` reference must point to an existing capture ID.
- Group members must reference existing capture IDs.
- Circular dependencies between captures are rejected.

```yaml
phantom: "1"
project: my-app
name: My Application
description: Screenshot automation for My Application
```

---

## setup

Configures how the target application is built, started, and torn down.

| Field              | Type                   | Required | Default | Description                                         |
|--------------------|------------------------|----------|---------|-----------------------------------------------------|
| `type`             | `string`               | Yes      | --      | Runner type identifier. Pattern: `^[a-z][a-z0-9-]*$`. Common values: `web`, `tui`, `docker-compose`, `desktop`. |
| `requires`         | `list[string] \| null` | No       | `null`  | System dependencies to check before running.        |
| `build`            | `list[string] \| null` | No       | `null`  | Shell commands to build the project before starting. |
| `run`              | `RunConfig`            | Yes      | --      | How to start the application. See [setup.run](#setuprun). |
| `teardown`         | `list[string] \| null` | No       | `null`  | Shell commands to run after captures complete.      |
| `runner_timeout`   | `int`                  | No       | `300`   | Maximum seconds for the entire runner execution. Must be > 0. |
| `compose_file`     | `string \| null`       | No       | `null`  | Path to docker-compose file. **Required** when `type` is `docker-compose`. |
| `compose_profiles` | `list[string] \| null` | No       | `null`  | Docker Compose profiles to activate.                |
| `services`         | `list[string] \| null` | No       | `null`  | Specific docker-compose services to start.          |

```yaml
setup:
  type: web
  requires:
    - node
    - npm
  build:
    - npm ci
    - npm run build
  run:
    command: npm run dev
    env:
      PORT: "3000"
      NODE_ENV: development
    ready_check:
      type: http
      url: http://localhost:3000
  teardown:
    - npm run cleanup
  runner_timeout: 600
```

### setup.run

Defines the command to start the application and how to detect when it is ready.

| Field         | Type                      | Required | Default | Description                                |
|---------------|---------------------------|----------|---------|--------------------------------------------|
| `command`     | `string`                  | Yes      | --      | Shell command to start the application.    |
| `env`         | `dict[string, string] \| null` | No  | `null`  | Environment variables for the command.     |
| `ready_check` | `ReadyCheck`             | Yes      | --      | How to determine the app is ready. See [ready_check](#ready_check). |

```yaml
run:
  command: python -m http.server 8080
  env:
    PYTHONDONTWRITEBYTECODE: "1"
  ready_check:
    type: tcp
    port: 8080
```

### ready_check

Determines when the application is ready to accept capture requests. The `type` field
selects the strategy and determines which other fields are required.

#### Common fields (all types)

| Field      | Type  | Required | Default | Description                                  |
|------------|-------|----------|---------|----------------------------------------------|
| `type`     | `string` | Yes   | --      | One of: `http`, `tcp`, `stdout_match`, `delay`, `screen_stable`. |
| `timeout`  | `int` | No       | `30`    | Maximum seconds to wait for readiness. Must be > 0. |
| `interval` | `int` | No       | `1`     | Seconds between check attempts. Must be > 0. |

#### type: http

Polls an HTTP endpoint until it returns the expected status code.

| Field         | Type     | Required | Default | Description                    |
|---------------|----------|----------|---------|--------------------------------|
| `url`         | `string` | **Yes**  | --      | URL to poll.                   |
| `status_code` | `int`    | No       | `200`   | Expected HTTP status code.     |

```yaml
ready_check:
  type: http
  url: http://localhost:3000/health
  status_code: 200
  timeout: 60
  interval: 2
```

#### type: tcp

Polls a TCP port until a connection is accepted.

| Field  | Type  | Required | Default | Description              |
|--------|-------|----------|---------|--------------------------|
| `port` | `int` | **Yes**  | --      | TCP port number to probe. |

```yaml
ready_check:
  type: tcp
  port: 5432
  timeout: 30
```

#### type: stdout_match

Watches the process stdout for a regex pattern.

| Field     | Type     | Required | Default | Description                          |
|-----------|----------|----------|---------|--------------------------------------|
| `pattern` | `string` | **Yes**  | --      | Regex pattern to match in stdout.    |

```yaml
ready_check:
  type: stdout_match
  pattern: "Server listening on"
  timeout: 30
```

#### type: delay

Waits a fixed number of seconds.

| Field     | Type  | Required | Default | Description              |
|-----------|-------|----------|---------|--------------------------|
| `seconds` | `int` | **Yes**  | --      | Seconds to wait.         |

```yaml
ready_check:
  type: delay
  seconds: 5
```

#### type: screen_stable

Waits until the screen content stops changing (useful for TUI/desktop runners).

| Field               | Type  | Required | Default | Description                                      |
|---------------------|-------|----------|---------|--------------------------------------------------|
| `stability_window`  | `int` | No       | `500`   | Milliseconds the screen must remain unchanged. Must be > 0. |
| `check_interval`    | `int` | No       | `100`   | Milliseconds between screen comparisons. Must be > 0. |

```yaml
ready_check:
  type: screen_stable
  stability_window: 1000
  check_interval: 200
  timeout: 30
```

---

## fixtures

Fixtures load data or perform setup tasks after the application is running but before
captures begin. Each fixture has a `type` that determines its required fields.

#### Common fields (all types)

| Field     | Type     | Required | Default | Description                          |
|-----------|----------|----------|---------|--------------------------------------|
| `name`    | `string` | Yes      | --      | Human-readable fixture name.         |
| `type`    | `string` | Yes      | --      | One of: `script`, `http`, `file_copy`. |
| `timeout` | `int`    | No       | `30`    | Maximum seconds for fixture execution. Must be > 0. |

#### type: script

Runs a shell command.

| Field | Type     | Required | Default | Description              |
|-------|----------|----------|---------|--------------------------|
| `run` | `string` | **Yes**  | --      | Shell command to execute. |

```yaml
fixtures:
  - name: seed-database
    type: script
    run: python manage.py seed --count 50
    timeout: 60
```

#### type: http

Makes an HTTP request (e.g., to seed an API).

| Field             | Type                         | Required | Default | Description                    |
|-------------------|------------------------------|----------|---------|--------------------------------|
| `url`             | `string`                     | **Yes**  | --      | Request URL.                   |
| `method`          | `string \| null`             | No       | `null`  | HTTP method (GET, POST, etc.). |
| `headers`         | `dict[string, string] \| null` | No    | `null`  | Request headers.               |
| `body`            | `string \| null`             | No       | `null`  | Request body.                  |
| `expected_status` | `int \| null`                | No       | `null`  | Expected response status code. |

```yaml
fixtures:
  - name: create-sample-data
    type: http
    url: http://localhost:3000/api/seed
    method: POST
    headers:
      Content-Type: application/json
      Authorization: Bearer test-token
    body: '{"count": 25}'
    expected_status: 201
```

#### type: file_copy

Copies a file into place (e.g., test config files, sample data).

| Field         | Type     | Required | Default | Description            |
|---------------|----------|----------|---------|------------------------|
| `source`      | `string` | **Yes**  | --      | Source file path.      |
| `destination` | `string` | **Yes**  | --      | Destination file path. |

```yaml
fixtures:
  - name: copy-test-config
    type: file_copy
    source: tests/fixtures/config.json
    destination: app/config.json
```

---

## capture_defaults

Default values applied to every capture unless overridden at the capture level. All
fields are optional.

| Field               | Type                                      | Default  | Description                                  |
|---------------------|-------------------------------------------|----------|----------------------------------------------|
| `viewport`          | `Viewport \| null`                        | `null`   | Default viewport. Falls back to 1280x800 during resolution if null. |
| `theme`             | `"dark" \| "light" \| "system" \| "none"` | `"dark"` | Color scheme preference.                     |
| `device_scale`      | `int`                                     | `2`      | Device pixel ratio. Range: 1--3.             |
| `full_page`         | `bool`                                    | `false`  | Capture the full scrollable page.            |
| `wait_after_actions` | `int`                                    | `500`    | Milliseconds to wait after actions complete before capturing. Min: 0. |
| `timeout`           | `int`                                     | `15`     | Seconds before a single capture times out. Must be > 0. |
| `retry`             | `RetryConfig \| null`                     | `null`   | Retry policy. Falls back to `max_attempts: 3, backoff_ms: 1000` during resolution if null. |

**Viewport** has two fields:

| Field    | Type  | Required | Description               |
|----------|-------|----------|---------------------------|
| `width`  | `int` | Yes      | Viewport width in pixels. Must be > 0.  |
| `height` | `int` | Yes      | Viewport height in pixels. Must be > 0. |

**RetryConfig** has two fields:

| Field          | Type  | Default | Description                              |
|----------------|-------|---------|------------------------------------------|
| `max_attempts` | `int` | `3`     | Maximum number of attempts. Min: 1.      |
| `backoff_ms`   | `int` | `1000`  | Milliseconds between retries. Min: 0.    |

```yaml
capture_defaults:
  viewport:
    width: 1280
    height: 800
  theme: dark
  device_scale: 2
  full_page: false
  wait_after_actions: 500
  timeout: 15
  retry:
    max_attempts: 3
    backoff_ms: 1000
```

---

## captures

Each entry defines a single screenshot to take. At least one capture is required in
every manifest. Captures are identified by their `id` and produce output at the
specified `output` path.

| Field               | Type                                      | Required | Default     | Description                                                  |
|---------------------|-------------------------------------------|----------|-------------|--------------------------------------------------------------|
| `id`                | `string`                                  | Yes      | --          | Unique identifier. Pattern: `^[a-z0-9][a-z0-9\-]*$`.        |
| `name`              | `string`                                  | Yes      | --          | Human-readable name.                                         |
| `description`       | `string \| null`                          | No       | `null`      | Description of what this capture shows.                      |
| `route`             | `string \| null`                          | No       | `null`      | URL path to navigate to before actions.                      |
| `wait_for`          | `string \| null`                          | No       | `null`      | CSS selector to wait for before capturing.                   |
| `wait_for_state`    | `"visible" \| "attached" \| "hidden" \| "detached"` | No | `"visible"` | State the `wait_for` selector must reach.               |
| `output`            | `string`                                  | Yes      | --          | Relative output file path. Must not start with `/` or contain `..`. |
| `readme_target`     | `string \| null`                          | No       | `null`      | Target marker in README for image insertion.                 |
| `alt_text`          | `string \| null`                          | No       | `null`      | Alt text for the image. Falls back to `description` during resolution. |
| `viewport`          | `Viewport \| null`                        | No       | `null`      | Overrides `capture_defaults.viewport`.                       |
| `theme`             | `"dark" \| "light" \| "system" \| "none" \| null` | No | `null`   | Overrides `capture_defaults.theme`.                          |
| `device_scale`      | `int \| null`                             | No       | `null`      | Overrides `capture_defaults.device_scale`. Range: 1--3.      |
| `full_page`         | `bool \| null`                            | No       | `null`      | Overrides `capture_defaults.full_page`.                      |
| `wait_after_actions` | `int \| null`                            | No       | `null`      | Overrides `capture_defaults.wait_after_actions`. Min: 0.     |
| `timeout`           | `int \| null`                             | No       | `null`      | Overrides `capture_defaults.timeout`. Must be > 0.           |
| `actions`           | `list[Action]`                            | No       | `[]`        | Actions to perform before capturing. See [Actions](#actions). |
| `skip`              | `bool`                                    | No       | `false`     | Skip this capture during execution.                          |
| `depends_on`        | `string \| null`                          | No       | `null`      | ID of a capture that must run first. Cannot be used with `parallel`. |
| `parallel`          | `bool`                                    | No       | `false`     | Allow this capture to run in parallel. Cannot be used with `depends_on`. |
| `format`            | `"png" \| "webp" \| null`                 | No       | `null`      | Override the output format for this capture.                 |
| `retry`             | `RetryConfig \| null`                     | No       | `null`      | Override retry configuration for this capture.               |

**Validation rules:**

- A capture cannot set both `parallel: true` and `depends_on`.
- The `depends_on` target must exist as another capture's `id`.
- Circular dependency chains are rejected.

```yaml
captures:
  - id: dashboard
    name: Dashboard View
    description: Main dashboard with sample data loaded
    route: /dashboard
    wait_for: "#data-table"
    wait_for_state: visible
    output: docs/images/dashboard.png
    readme_target: "<!-- phantom:dashboard -->"
    alt_text: Dashboard showing sample data
    viewport:
      width: 1440
      height: 900
    theme: dark
    device_scale: 2
    full_page: false
    wait_after_actions: 1000
    timeout: 30
    format: png
    retry:
      max_attempts: 5
      backoff_ms: 2000
    actions:
      - type: click
        selector: "#load-data"
      - type: wait
        ms: 500
```

---

## Actions

Actions are steps performed between navigating to a route and taking the screenshot.
Each action is a mapping with a `type` field that determines the available parameters.

### navigate

Navigate to an absolute URL.

| Field | Type     | Required | Description       |
|-------|----------|----------|-------------------|
| `type` | `"navigate"` | Yes | --               |
| `url` | `string` | Yes      | Full URL to load. |

```yaml
- type: navigate
  url: http://localhost:3000/settings
```

### route

Navigate to a relative path (appended to the base URL).

| Field  | Type      | Required | Description     |
|--------|-----------|----------|-----------------|
| `type` | `"route"` | Yes      | --              |
| `path` | `string`  | Yes      | Relative path.  |

```yaml
- type: route
  path: /settings/profile
```

### click

Click on an element or coordinate.

| Field      | Type                               | Required            | Default  | Description                    |
|------------|------------------------------------|---------------------|----------|--------------------------------|
| `type`     | `"click"`                          | Yes                 | --       | --                             |
| `selector` | `string \| null`                   | One of selector or x+y | `null` | CSS selector to click.        |
| `x`        | `int \| null`                      | One of selector or x+y | `null` | X coordinate.                 |
| `y`        | `int \| null`                      | One of selector or x+y | `null` | Y coordinate.                 |
| `button`   | `"left" \| "right" \| "middle"`    | No                  | `"left"` | Mouse button.                  |
| `count`    | `int`                              | No                  | `1`      | Number of clicks (2 = double). |

Either `selector` or both `x` and `y` must be provided.

```yaml
- type: click
  selector: "button.submit"
  button: left
  count: 1

- type: click
  x: 100
  y: 200
  button: right
```

### hover

Hover over an element.

| Field      | Type       | Required | Description          |
|------------|------------|----------|----------------------|
| `type`     | `"hover"`  | Yes      | --                   |
| `selector` | `string`   | Yes      | CSS selector.        |

```yaml
- type: hover
  selector: ".tooltip-trigger"
```

### scroll_to

Scroll an element into view.

| Field      | Type                                 | Required | Default    | Description                      |
|------------|--------------------------------------|----------|------------|----------------------------------|
| `type`     | `"scroll_to"`                        | Yes      | --         | --                               |
| `selector` | `string`                             | Yes      | --         | CSS selector of the target.      |
| `block`    | `"start" \| "center" \| "end"`       | No       | `"center"` | Vertical alignment of element.   |

```yaml
- type: scroll_to
  selector: "#footer"
  block: start
```

### scroll

Scroll the page by pixel offset.

| Field  | Type       | Required | Default | Description            |
|--------|------------|----------|---------|------------------------|
| `type` | `"scroll"` | Yes      | --      | --                     |
| `x`    | `int`      | No       | `0`     | Horizontal pixels.     |
| `y`    | `int`      | No       | `0`     | Vertical pixels.       |

```yaml
- type: scroll
  y: 500
```

### type

Type text into an element or the focused element.

| Field      | Type             | Required | Default | Description                        |
|------------|------------------|----------|---------|------------------------------------|
| `type`     | `"type"`         | Yes      | --      | --                                 |
| `selector` | `string \| null` | No       | `null`  | CSS selector to focus first.       |
| `text`     | `string`         | Yes      | --      | Text to type.                      |
| `delay`    | `int`            | No       | `50`    | Milliseconds between keystrokes. Min: 0. |

```yaml
- type: type
  selector: "#search-input"
  text: "hello world"
  delay: 50
```

### press

Press a single key.

| Field  | Type      | Required | Description                                    |
|--------|-----------|----------|------------------------------------------------|
| `type` | `"press"` | Yes      | --                                             |
| `key`  | `string`  | Yes      | Key name (e.g., `Enter`, `Tab`, `Escape`).     |

```yaml
- type: press
  key: Enter
```

### keyboard_shortcut

Press a key combination.

| Field  | Type                   | Required | Description                                    |
|--------|------------------------|----------|------------------------------------------------|
| `type` | `"keyboard_shortcut"`  | Yes      | --                                             |
| `keys` | `string`               | Yes      | Key combination (e.g., `Control+Shift+P`).     |

```yaml
- type: keyboard_shortcut
  keys: Control+Shift+P
```

### keystroke

*TUI runner only.* Send a single key to the terminal.

| Field  | Type           | Required | Description                            |
|--------|----------------|----------|----------------------------------------|
| `type` | `"keystroke"`  | Yes      | --                                     |
| `key`  | `string`       | Yes      | Key name (e.g., `enter`, `tab`, `q`).  |

```yaml
- type: keystroke
  key: enter
```

### type_text

*TUI runner only.* Type a string character by character into the terminal.

| Field   | Type          | Required | Default | Description                              |
|---------|---------------|----------|---------|------------------------------------------|
| `type`  | `"type_text"` | Yes      | --      | --                                       |
| `text`  | `string`      | Yes      | --      | Text to type.                            |
| `delay` | `int`         | No       | `80`    | Milliseconds between characters. Min: 0. |

```yaml
- type: type_text
  text: ":wq"
  delay: 80
```

### wait

Pause for a fixed duration.

| Field  | Type     | Required | Description                       |
|--------|----------|----------|-----------------------------------|
| `type` | `"wait"` | Yes      | --                                |
| `ms`   | `int`    | Yes      | Milliseconds to wait. Must be > 0. |

```yaml
- type: wait
  ms: 1000
```

### wait_for

Wait for a CSS selector to reach a given state.

| Field      | Type                                                  | Required | Default     | Description                       |
|------------|-------------------------------------------------------|----------|-------------|-----------------------------------|
| `type`     | `"wait_for"`                                          | Yes      | --          | --                                |
| `selector` | `string`                                              | Yes      | --          | CSS selector.                     |
| `state`    | `"visible" \| "attached" \| "hidden" \| "detached"`  | No       | `"visible"` | Target state.                     |
| `timeout`  | `int`                                                 | No       | `10`        | Seconds to wait. Must be > 0.     |

```yaml
- type: wait_for
  selector: ".loading-spinner"
  state: hidden
  timeout: 15
```

### wait_for_network

Wait for network activity to settle.

| Field     | Type                            | Required | Default  | Description                       |
|-----------|---------------------------------|----------|----------|-----------------------------------|
| `type`    | `"wait_for_network"`            | Yes      | --       | --                                |
| `state`   | `"idle" \| "no-pending"`        | No       | `"idle"` | Network state to wait for.        |
| `timeout` | `int`                           | No       | `10`     | Seconds to wait. Must be > 0.     |

```yaml
- type: wait_for_network
  state: idle
  timeout: 10
```

### set_theme

Switch the browser color scheme preference.

| Field   | Type            | Required | Description             |
|---------|-----------------|----------|-------------------------|
| `type`  | `"set_theme"`   | Yes      | --                      |
| `theme` | `"dark" \| "light"` | Yes  | Target color scheme.    |

```yaml
- type: set_theme
  theme: light
```

### set_viewport

Change the browser viewport dimensions mid-capture.

| Field    | Type             | Required | Description                      |
|----------|------------------|----------|----------------------------------|
| `type`   | `"set_viewport"` | Yes      | --                               |
| `width`  | `int`            | Yes      | New viewport width. Must be > 0. |
| `height` | `int`            | Yes      | New viewport height. Must be > 0.|

```yaml
- type: set_viewport
  width: 375
  height: 812
```

### evaluate

Execute arbitrary JavaScript in the page.

| Field  | Type         | Required | Description                |
|--------|--------------|----------|----------------------------|
| `type` | `"evaluate"` | Yes      | --                         |
| `js`   | `string`     | Yes      | JavaScript code to execute.|

```yaml
- type: evaluate
  js: "document.querySelector('.banner').remove()"
```

### set_cookie

Set a browser cookie.

| Field    | Type           | Required | Default       | Description        |
|----------|----------------|----------|---------------|--------------------|
| `type`   | `"set_cookie"` | Yes      | --            | --                 |
| `name`   | `string`       | Yes      | --            | Cookie name.       |
| `value`  | `string`       | Yes      | --            | Cookie value.      |
| `domain` | `string`       | No       | `"localhost"` | Cookie domain.     |

```yaml
- type: set_cookie
  name: session
  value: test-session-token
  domain: localhost
```

### xdotool

*Desktop runner only.* Execute an xdotool command.

| Field    | Type         | Required | Description                   |
|----------|--------------|----------|-------------------------------|
| `type`   | `"xdotool"`  | Yes      | --                            |
| `action` | `string`     | Yes      | xdotool command string.       |

```yaml
- type: xdotool
  action: "key ctrl+s"
```

### xdg_shortcut

*Desktop runner only.* Execute a desktop shortcut.

| Field      | Type              | Required | Description               |
|------------|-------------------|----------|---------------------------|
| `type`     | `"xdg_shortcut"`  | Yes      | --                        |
| `shortcut` | `string`          | Yes      | Shortcut key combination. |

```yaml
- type: xdg_shortcut
  shortcut: "Alt+F4"
```

### conditional

Execute actions conditionally based on a condition.

| Field  | Type                     | Required | Default | Description                        |
|--------|--------------------------|----------|---------|------------------------------------|
| `type` | `"conditional"`          | Yes      | --      | --                                 |
| `if`   | `dict[string, string]`   | Yes      | --      | Condition map to evaluate.         |
| `then` | `list[Action]`           | Yes      | --      | Actions if condition is true.      |
| `else` | `list[Action] \| null`   | No       | `null`  | Actions if condition is false.     |

```yaml
- type: conditional
  if:
    selector_exists: ".cookie-banner"
  then:
    - type: click
      selector: ".cookie-banner .accept"
    - type: wait
      ms: 500
  else:
    - type: wait
      ms: 100
```

---

## processing

Post-processing pipeline applied to captured images.

| Field       | Type             | Default                       | Description                    |
|-------------|------------------|-------------------------------|--------------------------------|
| `format`    | `"png" \| "webp"` | `"png"`                      | Output image format.           |
| `optimize`  | `bool`           | `true`                        | Apply lossless optimization.   |
| `max_width` | `int`            | `2800`                        | Maximum image width in pixels. Must be > 0. |
| `border`    | `BorderConfig`   | See [border](#border)         | Border and shadow settings.    |
| `diff`      | `DiffConfig`     | See [diff](#diff)             | Image diff settings.           |

### border

Controls the decorative border, shadow, and background applied to screenshots.

| Field           | Type                                               | Default            | Description                          |
|-----------------|----------------------------------------------------|--------------------|--------------------------------------|
| `style`         | `"drop-shadow" \| "rounded" \| "outline" \| "none"` | `"drop-shadow"`  | Border style.                        |
| `shadow_color`  | `string`                                           | `"rgba(0,0,0,0.3)"` | CSS color for the drop shadow.     |
| `shadow_offset` | `ShadowOffset`                                     | `{x: 0, y: 8}`    | Shadow offset in pixels.            |
| `shadow_blur`   | `int`                                              | `24`               | Shadow blur radius. Min: 0.         |
| `padding`       | `int`                                              | `32`               | Padding around the image in pixels. Min: 0. |
| `background`    | `string`                                           | `"transparent"`    | Background CSS color behind the image. |
| `corner_radius` | `int`                                              | `8`                | Corner rounding radius. Min: 0.     |

**ShadowOffset:**

| Field | Type  | Default | Description              |
|-------|-------|---------|--------------------------|
| `x`   | `int` | `0`     | Horizontal shadow offset.|
| `y`   | `int` | `8`     | Vertical shadow offset.  |

```yaml
processing:
  format: png
  optimize: true
  max_width: 2800
  border:
    style: drop-shadow
    shadow_color: "rgba(0,0,0,0.3)"
    shadow_offset:
      x: 0
      y: 8
    shadow_blur: 24
    padding: 32
    background: transparent
    corner_radius: 8
```

### diff

Controls image diffing to detect whether a screenshot has actually changed.

| Field            | Type                        | Default | Description                                   |
|------------------|-----------------------------|---------|-----------------------------------------------|
| `enabled`        | `bool`                      | `true`  | Enable diff checking.                         |
| `threshold`      | `float`                     | `0.95`  | Similarity threshold (0.0--1.0). Images above this are considered unchanged. |
| `algorithm`      | `"ssim" \| "pixelmatch"`    | `"ssim"` | Diff algorithm.                              |
| `ignore_regions` | `list[Region]`              | `[]`    | Rectangular regions to exclude from comparison. |

**Region:**

| Field    | Type  | Required | Description                   |
|----------|-------|----------|-------------------------------|
| `x`      | `int` | Yes      | Left edge in pixels. Min: 0.  |
| `y`      | `int` | Yes      | Top edge in pixels. Min: 0.   |
| `width`  | `int` | Yes      | Width in pixels. Must be > 0. |
| `height` | `int` | Yes      | Height in pixels. Must be > 0.|

```yaml
processing:
  diff:
    enabled: true
    threshold: 0.95
    algorithm: ssim
    ignore_regions:
      - x: 0
        y: 0
        width: 200
        height: 50
```

---

## publishing

Controls how and where captured images are committed and published.

| Field            | Type                       | Default                                 | Description                               |
|------------------|----------------------------|-----------------------------------------|-------------------------------------------|
| `branch`         | `string`                   | `"main"`                                | Target branch for commits.                |
| `commit_author`  | `CommitAuthor`             | `{name: "Phantom Bot", email: "phantom@noreply"}` | Git author for commits.       |
| `ci_skip_tag`    | `string`                   | `"[skip ci]"`                           | Tag appended to commit messages to skip CI. |
| `commit_message` | `string`                   | `"docs(screenshots): update via Phantom"` | Commit message template.               |
| `strategy`       | `"direct" \| "pr"`         | `"direct"`                              | Publish by direct commit or pull request. |
| `readme_update`  | `bool`                     | `true`                                  | Update README with new image references.  |
| `cleanup_stale`  | `bool`                     | `true`                                  | Remove images no longer in the manifest.  |
| `pr_title`       | `string \| null`           | `null`                                  | PR title (when `strategy: pr`).           |
| `pr_labels`      | `list[string] \| null`     | `null`                                  | Labels to apply to the PR.                |
| `pr_auto_merge`  | `bool \| null`             | `null`                                  | Enable auto-merge on the PR.              |

**CommitAuthor:**

| Field   | Type     | Default            | Description       |
|---------|----------|--------------------|-------------------|
| `name`  | `string` | `"Phantom Bot"`    | Author name.      |
| `email` | `string` | `"phantom@noreply"` | Author email.    |

```yaml
publishing:
  branch: main
  commit_author:
    name: Phantom Bot
    email: phantom@noreply
  ci_skip_tag: "[skip ci]"
  commit_message: "docs(screenshots): update via Phantom"
  strategy: pr
  readme_update: true
  cleanup_stale: true
  pr_title: "chore: update screenshots"
  pr_labels:
    - documentation
    - automated
  pr_auto_merge: true
```

---

## triggers

Define when Phantom runs in CI/CD. Each trigger has a `type` that determines its
required fields.

| Field      | Type                                 | Required | Default | Description                      |
|------------|--------------------------------------|----------|---------|----------------------------------|
| `type`     | `"release" \| "schedule" \| "push"`  | Yes      | --      | Trigger type.                    |
| `cron`     | `string \| null`                     | No       | `null`  | Cron expression. **Required** when `type` is `schedule`. |
| `branches` | `list[string] \| null`               | No       | `null`  | Branch filters for push triggers.|
| `paths`    | `list[string] \| null`               | No       | `null`  | Path filters for push triggers.  |

```yaml
triggers:
  - type: release

  - type: schedule
    cron: "0 2 * * 1"

  - type: push
    branches:
      - main
      - develop
    paths:
      - "src/**"
      - "docs/**"
```

---

## tui

Configuration for the TUI (terminal UI) runner. Only relevant when `setup.type` targets
a terminal application.

| Field             | Type              | Default                          | Description                       |
|-------------------|-------------------|----------------------------------|-----------------------------------|
| `terminal`        | `TerminalConfig`  | `{width: 120, height: 40}`       | Terminal dimensions.              |
| `renderer`        | `"silicon" \| "freeze" \| "termshot"` | `"silicon"`        | Tool used to render terminal output to images. |
| `renderer_config` | `RendererConfig`  | See below                        | Renderer appearance settings.     |

**TerminalConfig:**

| Field    | Type  | Default | Description                          |
|----------|-------|---------|--------------------------------------|
| `width`  | `int` | `120`   | Terminal width in columns. Must be > 0. |
| `height` | `int` | `40`    | Terminal height in rows. Must be > 0.   |

**RendererConfig:**

| Field             | Type     | Default              | Description                                  |
|-------------------|----------|----------------------|----------------------------------------------|
| `font`            | `string` | `"JetBrains Mono"`   | Font family for terminal rendering.          |
| `font_size`       | `int`    | `14`                 | Font size in points. Must be > 0.            |
| `theme`           | `string` | `"Catppuccin Mocha"` | Color theme name.                            |
| `line_numbers`    | `bool`   | `false`              | Show line numbers in output.                 |
| `padding`         | `int`    | `20`                 | Padding around the terminal content. Min: 0. |
| `background`      | `string` | `"#1e1e2e"`          | Background color.                            |
| `window_controls` | `bool`   | `true`               | Show macOS-style window control dots.        |
| `corner_radius`   | `int`    | `8`                  | Corner radius for the terminal window. Min: 0. |

```yaml
tui:
  terminal:
    width: 120
    height: 40
  renderer: silicon
  renderer_config:
    font: JetBrains Mono
    font_size: 14
    theme: Catppuccin Mocha
    line_numbers: false
    padding: 20
    background: "#1e1e2e"
    window_controls: true
    corner_radius: 8
```

---

## desktop

Configuration for the desktop application runner. Uses a virtual X display to capture
GUI applications.

| Field                  | Type                                   | Default       | Description                                    |
|------------------------|----------------------------------------|---------------|------------------------------------------------|
| `display`              | `DisplayConfig`                        | See below     | Virtual display settings.                      |
| `window_manager`       | `"openbox" \| "fluxbox" \| "none"`     | `"openbox"`   | Window manager to run inside the virtual display. |
| `window_manager_theme` | `string`                               | `"Nightmare"` | Window manager theme.                          |
| `screenshot_method`    | `"maim" \| "scrot" \| "xdotool"`      | `"maim"`      | Tool used to take screenshots.                 |
| `screenshot_target`    | `"window" \| "screen" \| "region"`     | `"window"`    | What to capture: active window, full screen, or region. |
| `webview_debug_port`   | `int \| null`                          | `null`        | Chrome DevTools debug port for webview-based apps. |

**DisplayConfig:**

| Field        | Type     | Default        | Description                  |
|--------------|----------|----------------|------------------------------|
| `resolution` | `string` | `"1920x1080"`  | Display resolution.          |
| `depth`      | `int`    | `24`           | Color depth in bits.         |
| `dpi`        | `int`    | `96`           | Display DPI.                 |

```yaml
desktop:
  display:
    resolution: 1920x1080
    depth: 24
    dpi: 96
  window_manager: openbox
  window_manager_theme: Nightmare
  screenshot_method: maim
  screenshot_target: window
  webview_debug_port: 9222
```

---

## director

Configuration for the AI-powered director that can autonomously explore the application
and suggest captures.

| Field                    | Type     | Default                      | Description                                  |
|--------------------------|----------|------------------------------|----------------------------------------------|
| `enabled`                | `bool`   | `false`                      | Enable the AI director.                      |
| `model`                  | `string` | `"claude-sonnet-4-20250514"` | AI model identifier to use.                  |
| `explore`                | `bool`   | `true`                       | Allow the director to explore the app autonomously. |
| `auto_caption`           | `bool`   | `true`                       | Automatically generate alt text and descriptions. |
| `suggest_captures`       | `bool`   | `true`                       | Suggest new captures based on exploration.   |
| `max_exploration_steps`  | `int`    | `50`                         | Maximum exploration steps. Must be > 0.      |
| `max_tokens`             | `int`    | `500000`                     | Maximum token budget for the director. Must be > 0. |

```yaml
director:
  enabled: true
  model: claude-sonnet-4-20250514
  explore: true
  auto_caption: true
  suggest_captures: true
  max_exploration_steps: 50
  max_tokens: 500000
```

---

## groups

Named groups of capture IDs for selective execution. Each key is a group name and each
value is a list of capture IDs. All referenced IDs must exist in `captures`.

```yaml
groups:
  onboarding:
    - welcome-screen
    - signup-form
    - email-verification
  dashboard:
    - dashboard-overview
    - dashboard-analytics
    - dashboard-settings
```

---

## Full Examples

### Web Application

A complete manifest for a web application using the `web` runner.

```yaml
phantom: "1"
project: acme-web
name: Acme Web App
description: Screenshot automation for the Acme web application

setup:
  type: web
  requires:
    - node
    - npm
  build:
    - npm ci
    - npm run build
  run:
    command: npm run preview -- --port 4173
    env:
      NODE_ENV: production
    ready_check:
      type: http
      url: http://localhost:4173
      timeout: 60
  teardown:
    - rm -rf .cache
  runner_timeout: 600

fixtures:
  - name: seed-database
    type: script
    run: npx prisma db seed
    timeout: 30
  - name: upload-avatars
    type: file_copy
    source: tests/fixtures/avatars
    destination: public/avatars

capture_defaults:
  viewport:
    width: 1280
    height: 800
  theme: dark
  device_scale: 2
  full_page: false
  wait_after_actions: 500
  timeout: 15
  retry:
    max_attempts: 3
    backoff_ms: 1000

captures:
  - id: landing-page
    name: Landing Page
    description: Marketing landing page with hero section
    route: /
    wait_for: ".hero-section"
    output: docs/images/landing.png
    readme_target: "<!-- phantom:landing -->"
    alt_text: Acme landing page
    actions:
      - type: wait_for_network
        state: idle
        timeout: 10
      - type: evaluate
        js: "document.querySelector('.cookie-banner')?.remove()"

  - id: login-form
    name: Login Form
    description: Authentication page with login form
    route: /login
    wait_for: "#login-form"
    output: docs/images/login.png
    readme_target: "<!-- phantom:login -->"
    viewport:
      width: 800
      height: 600

  - id: dashboard
    name: Dashboard
    description: Main dashboard after login
    route: /dashboard
    wait_for: ".dashboard-grid"
    output: docs/images/dashboard.png
    readme_target: "<!-- phantom:dashboard -->"
    depends_on: login-form
    actions:
      - type: set_cookie
        name: session
        value: test-session-abc123
      - type: navigate
        url: http://localhost:4173/dashboard
      - type: wait_for
        selector: ".data-loaded"
        state: visible
        timeout: 15

  - id: dashboard-mobile
    name: Dashboard (Mobile)
    description: Responsive mobile dashboard view
    route: /dashboard
    output: docs/images/dashboard-mobile.png
    viewport:
      width: 375
      height: 812
    device_scale: 3
    depends_on: dashboard
    actions:
      - type: set_cookie
        name: session
        value: test-session-abc123

  - id: settings
    name: Settings Page
    description: User settings panel
    route: /settings
    output: docs/images/settings.png
    parallel: true
    actions:
      - type: set_cookie
        name: session
        value: test-session-abc123
      - type: click
        selector: "#theme-toggle"
      - type: wait
        ms: 300

  - id: settings-light
    name: Settings (Light Mode)
    description: Settings in light theme
    route: /settings
    output: docs/images/settings-light.png
    theme: light
    parallel: true
    actions:
      - type: set_cookie
        name: session
        value: test-session-abc123

processing:
  format: png
  optimize: true
  max_width: 2800
  border:
    style: drop-shadow
    shadow_color: "rgba(0,0,0,0.3)"
    shadow_offset:
      x: 0
      y: 8
    shadow_blur: 24
    padding: 32
    background: transparent
    corner_radius: 8
  diff:
    enabled: true
    threshold: 0.95
    algorithm: ssim
    ignore_regions:
      - x: 1100
        y: 10
        width: 180
        height: 30

publishing:
  branch: main
  commit_author:
    name: Phantom Bot
    email: phantom@noreply
  ci_skip_tag: "[skip ci]"
  commit_message: "docs(screenshots): update via Phantom"
  strategy: direct
  readme_update: true
  cleanup_stale: true

triggers:
  - type: release
  - type: schedule
    cron: "0 3 * * 1"
  - type: push
    branches:
      - main
    paths:
      - "src/**"

groups:
  auth:
    - login-form
  main:
    - landing-page
    - dashboard
    - dashboard-mobile
  settings:
    - settings
    - settings-light
```

### TUI Application

A complete manifest for a terminal-based application using the `tui` runner.

```yaml
phantom: "1"
project: acme-cli
name: Acme CLI Tool
description: Screenshot automation for the Acme TUI

setup:
  type: tui
  requires:
    - cargo
    - silicon
  build:
    - cargo build --release
  run:
    command: ./target/release/acme-cli
    env:
      TERM: xterm-256color
      NO_COLOR: ""
    ready_check:
      type: screen_stable
      stability_window: 1000
      check_interval: 200
      timeout: 15
  runner_timeout: 120

tui:
  terminal:
    width: 100
    height: 35
  renderer: silicon
  renderer_config:
    font: JetBrains Mono
    font_size: 14
    theme: Catppuccin Mocha
    line_numbers: false
    padding: 20
    background: "#1e1e2e"
    window_controls: true
    corner_radius: 8

capture_defaults:
  viewport:
    width: 1200
    height: 800
  theme: dark
  device_scale: 2
  wait_after_actions: 300
  timeout: 10

captures:
  - id: main-menu
    name: Main Menu
    description: Application main menu on startup
    output: docs/images/main-menu.png
    readme_target: "<!-- phantom:main-menu -->"
    alt_text: Acme CLI main menu

  - id: file-browser
    name: File Browser
    description: Navigating files with the built-in browser
    output: docs/images/file-browser.png
    readme_target: "<!-- phantom:file-browser -->"
    depends_on: main-menu
    actions:
      - type: keystroke
        key: tab
      - type: keystroke
        key: enter
      - type: wait
        ms: 500

  - id: search-results
    name: Search Results
    description: Fuzzy search for files
    output: docs/images/search.png
    depends_on: main-menu
    actions:
      - type: keyboard_shortcut
        keys: Control+f
      - type: type_text
        text: "main.rs"
        delay: 60
      - type: wait
        ms: 800

  - id: help-screen
    name: Help Screen
    description: Keyboard shortcut reference
    output: docs/images/help.png
    actions:
      - type: keystroke
        key: "?"
      - type: wait
        ms: 300

processing:
  format: png
  optimize: true
  max_width: 2400
  border:
    style: rounded
    padding: 0
    corner_radius: 8
    background: "#1e1e2e"
  diff:
    enabled: true
    threshold: 0.90
    algorithm: ssim

publishing:
  branch: main
  strategy: direct
  readme_update: true
  cleanup_stale: true

triggers:
  - type: release
  - type: push
    branches:
      - main
    paths:
      - "src/**"

groups:
  navigation:
    - main-menu
    - file-browser
    - search-results
  reference:
    - help-screen
```

### Docker Compose Application

A complete manifest for a multi-service application using the `docker-compose` runner.

```yaml
phantom: "1"
project: acme-platform
name: Acme Platform
description: Screenshot automation for the Acme microservices platform

setup:
  type: docker-compose
  compose_file: docker-compose.screenshots.yml
  compose_profiles:
    - screenshots
  services:
    - web
    - api
    - db
  build:
    - docker compose -f docker-compose.screenshots.yml build
  run:
    command: docker compose -f docker-compose.screenshots.yml up
    env:
      COMPOSE_PROJECT_NAME: acme-phantom
      DATABASE_URL: postgres://acme:acme@db:5432/acme
    ready_check:
      type: http
      url: http://localhost:8080/health
      status_code: 200
      timeout: 120
      interval: 5
  teardown:
    - docker compose -f docker-compose.screenshots.yml down -v
  runner_timeout: 900

fixtures:
  - name: run-migrations
    type: script
    run: docker compose exec api python manage.py migrate
    timeout: 60
  - name: seed-data
    type: http
    url: http://localhost:8080/api/v1/seed
    method: POST
    headers:
      X-Admin-Key: phantom-seed-key
    body: '{"dataset": "demo", "users": 10}'
    expected_status: 200
    timeout: 30

capture_defaults:
  viewport:
    width: 1440
    height: 900
  theme: dark
  device_scale: 2
  full_page: false
  wait_after_actions: 1000
  timeout: 30
  retry:
    max_attempts: 5
    backoff_ms: 2000

captures:
  - id: login
    name: Login Page
    description: Platform login page
    route: /auth/login
    wait_for: "#login-form"
    output: docs/images/login.png
    readme_target: "<!-- phantom:login -->"
    actions:
      - type: wait_for_network
        state: idle

  - id: org-dashboard
    name: Organization Dashboard
    description: Multi-tenant organization overview
    route: /org/acme-corp
    wait_for: ".org-metrics"
    output: docs/images/org-dashboard.png
    readme_target: "<!-- phantom:org-dashboard -->"
    full_page: false
    actions:
      - type: set_cookie
        name: auth_token
        value: phantom-test-token
        domain: localhost
      - type: navigate
        url: http://localhost:8080/org/acme-corp
      - type: wait_for
        selector: ".metrics-loaded"
        state: visible
        timeout: 20
      - type: wait
        ms: 1000

  - id: org-dashboard-full
    name: Organization Dashboard (Full Page)
    description: Complete scrollable dashboard
    route: /org/acme-corp
    output: docs/images/org-dashboard-full.png
    full_page: true
    depends_on: org-dashboard
    actions:
      - type: set_cookie
        name: auth_token
        value: phantom-test-token
      - type: navigate
        url: http://localhost:8080/org/acme-corp
      - type: wait_for
        selector: ".metrics-loaded"
        state: visible

  - id: api-docs
    name: API Documentation
    description: Interactive API documentation page
    route: /docs/api
    wait_for: ".swagger-ui"
    output: docs/images/api-docs.png
    parallel: true
    viewport:
      width: 1920
      height: 1080
    actions:
      - type: wait_for_network
        state: idle
        timeout: 15
      - type: scroll_to
        selector: "#operations-users"
        block: start
      - type: click
        selector: "#operations-users .opblock-summary"
      - type: wait
        ms: 800

  - id: monitoring
    name: Monitoring Dashboard
    description: Real-time service monitoring
    route: /admin/monitoring
    wait_for: ".monitoring-grid"
    output: docs/images/monitoring.png
    parallel: true
    actions:
      - type: set_cookie
        name: auth_token
        value: phantom-admin-token
      - type: navigate
        url: http://localhost:8080/admin/monitoring
      - type: wait_for
        selector: ".charts-rendered"
        state: visible
        timeout: 20

processing:
  format: webp
  optimize: true
  max_width: 2800
  border:
    style: drop-shadow
    shadow_color: "rgba(0,0,0,0.4)"
    shadow_offset:
      x: 0
      y: 10
    shadow_blur: 30
    padding: 40
    background: "#f8f9fa"
    corner_radius: 12
  diff:
    enabled: true
    threshold: 0.92
    algorithm: pixelmatch
    ignore_regions:
      - x: 1300
        y: 0
        width: 140
        height: 40

publishing:
  branch: main
  commit_author:
    name: Phantom Bot
    email: screenshots@acme.com
  ci_skip_tag: "[ci skip]"
  commit_message: "docs(platform): update screenshots"
  strategy: pr
  readme_update: true
  cleanup_stale: true
  pr_title: "chore(docs): update platform screenshots"
  pr_labels:
    - documentation
    - automated
    - screenshots
  pr_auto_merge: true

triggers:
  - type: release
  - type: schedule
    cron: "0 4 * * 1,4"
  - type: push
    branches:
      - main
      - staging
    paths:
      - "services/web/**"
      - "services/api/**"
      - "docker-compose*.yml"

director:
  enabled: true
  model: claude-sonnet-4-20250514
  explore: true
  auto_caption: true
  suggest_captures: true
  max_exploration_steps: 30
  max_tokens: 300000

groups:
  auth:
    - login
  dashboards:
    - org-dashboard
    - org-dashboard-full
    - monitoring
  docs:
    - api-docs
```
