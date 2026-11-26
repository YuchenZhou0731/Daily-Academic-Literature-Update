# Sources and protected keys

| Source | Baseline access | Evidence boundary |
|---|---|---|
| Crossref | Public metadata; optional contact email | Abstracts may be absent; record creation/indexing is not publication |
| arXiv | Public API | Preprints; submission date is not a journal publication date |
| OpenAlex | User's API key | Metadata/available abstracts; collection checks the reported daily allowance |
| Scopus | User's Elsevier key and permitted search access | STANDARD metadata, often title/first author only; cover date is not first-online |

These capabilities are implemented directly. No separate paper-search MCP server, browser registration automation, publisher password, email password or model API key is bundled. An API may restrict or reject access; registration is not proof of entitlement. Live availability and quotas must be checked for each user.

## Add an optional key

The user runs this themselves in an interactive local terminal after initializing a workspace:

```text
python -I -B scripts/workspace.py --workspace "xxx" credential xxx
```

The input is hidden. Never ask for a key in chat, a command argument, a screenshot or a committed profile. The import verifies storage, not API authentication. Run `doctor --credentials`, followed by a bounded collection, to test actual access.

- Windows: Windows CurrentUser DPAPI, encrypted files under the private workspace's `.credentials/`. The runtime must be able to use that Windows account; a sandbox identity can fail decryption.
- macOS: install `requirements-keyring.txt`; use the system Keychain backend.
- Linux desktop: install `requirements-keyring.txt`; an unlocked Secret Service keyring is required. Headless environments without it cannot use this backend.

There is no plaintext, environment-variable or silent anonymous fallback. Moving a workspace may require reimporting keys: system-keyring entries are scoped to its resolved path, and DPAPI is bound to the Windows user. Crossref/arXiv can still run without optional keys.

Credentials are attached only to the exact official HTTPS API host. Authenticated redirects are blocked; cached success/error responses are redacted. OpenAlex uses the reported daily allowance and a configurable per-run cap, ignoring prepaid balance; the script never purchases credits. Fill the request budgets and page sizes in place of `xxx` after checking the account's access tier. Test the chosen settings before using them unattended.

Crossref cursors and Scopus offsets resume frozen windows. Changing query wording or effective page size changes checkpoint identity; old records remain stored. Scopus offset retrieval stops at 5,000 and reports incomplete coverage. A cap, API error or source cooldown is not a confirmed zero-result search.

The daily collector does not download full text. Full-text work remains an explicit selected-paper action described in `reading.md`.
