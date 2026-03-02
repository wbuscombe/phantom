# Security Practices

> Living document. All contributors (human and AI) must follow these rules.

---

## Claude Code Prompt Rules

### Secrets Handling

1. **Never `echo`, `cat`, `print`, or `printf` secrets to stdout/stderr.** This includes passwords, tokens, API keys, and any value from `.env` files.
2. **Write credentials directly to files** using heredoc redirects, `tee`, or direct file writes. Suppress console output.
3. **Reference secrets by variable name, never by value.** Say "the password from `$DB_PASS`" not the actual string.
4. **Never include real credentials in Claude Code's summary output.** If a step involves credentials, the summary should say "credentials written to .env" not show them.
5. **Never embed secrets in command-line arguments** where they appear in `ps` output or shell history. Use environment variables or file-based input instead.

Example — correct:
```bash
# Generate and write a password without echoing
openssl rand -base64 32 | tr -d '=+/' | head -c 32 > /tmp/.new_pass
# Use the password from file
some_command --password "$(cat /tmp/.new_pass)"
rm -f /tmp/.new_pass
```

Example — wrong:
```bash
# DON'T DO THIS — password visible in terminal output and shell history
echo "Password is: s0m3_p4ssw0rd_h3r3"
some_command --password s0m3_p4ssw0rd_h3r3
```

### Git Safety

6. **Scan before every commit.** Run `gitleaks detect --source . --no-banner` (or `detect-secrets`) before `git add`.
7. **`.gitignore` must cover** at minimum: `.env`, `.env.*`, `*.pem`, `*.key`, and any project-specific secret files (tokens, credentials, keystores).
8. **If a secret is accidentally committed**, treat it as compromised. Rotate the credential immediately. Do not rely on `git filter-branch` or BFG — assume the value has been seen.

### File Permissions

9. **Private keys and password files: `chmod 600`** (owner read/write only).
10. **Public certs: `chmod 644`** (owner write, world read).
11. **`.env` files: `chmod 600`** on deployment targets.

### Logging

12. **No secrets in log output.** Never set debug-level logging for components that handle credentials unless actively troubleshooting, and revert immediately after.
13. **Test scripts must not print credential values** in PASS/FAIL messages.

---

## Conversation Hygiene

When working with AI assistants (Claude, Claude Code, etc.):

- **Never paste credentials into chat.** If an AI tool outputs a credential, note it as a leak and rotate.
- **Screenshots:** Check for visible passwords, tokens, or sensitive URLs before sharing.
- **Prompt files and docs** must never contain real credentials — only variable references like `$API_KEY` or `<your-token-here>`.

---

## Incident Response

If a credential is exposed:

1. **Rotate immediately.** Don't wait. Don't assess severity first.
2. **Check access logs** for unauthorized use.
3. **Update all references** (`.env`, config files, CI/CD, any scripts).
4. **If the credential was committed to git**, it is permanently compromised regardless of history rewrites. Rotate and move on.
