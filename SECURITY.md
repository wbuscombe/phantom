# Security Policy

## Supported Versions

Phantom is distributed as [`phantom-docs`](https://pypi.org/project/phantom-docs/) on
PyPI. Security fixes are applied to the latest published minor release.

| Version | Supported |
| ------- | --------- |
| 0.4.x   | ✅         |
| < 0.4   | ❌         |

## Reporting a Vulnerability

Please report suspected vulnerabilities **privately** — do not open a public issue with
exploit details.

- **Preferred:** use GitHub's private vulnerability reporting — the **"Report a
  vulnerability"** button on the repository's
  [Security tab](https://github.com/wbuscombe/phantom/security/advisories/new).
- Alternatively, open a minimal public issue asking for a private contact channel (no
  vulnerability details).

You can expect an initial acknowledgement within a few days. Once a fix is available it
is released to PyPI and noted in [`CHANGELOG.md`](CHANGELOG.md).

For Phantom's product security model — webhook HMAC verification, the zero-outbound
network posture, and secret redaction in logs — see
[`docs/SECURITY-PRACTICES.md`](docs/SECURITY-PRACTICES.md).
