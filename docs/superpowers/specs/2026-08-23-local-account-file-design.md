# Local Account File Design

## Goal

Make local multi-account configuration manageable without changing the existing environment-variable configuration used by GitHub Actions.

## Configuration Interface

Local users may set `ANYROUTER_ACCOUNTS_FILE` in `.env` to a path containing the existing account-array JSON format. Relative paths resolve from the process working directory. The recommended file name is `accounts.json`.

Example `.env`:

```dotenv
ANYROUTER_ACCOUNTS_FILE=accounts.json
CHECKIN_PROXY_URL=http://127.0.0.1:7890
```

Example `accounts.json`:

```json
[
  {
    "name": "anyrouter-1",
    "provider": "anyrouter",
    "cookies": {"session": "..."},
    "api_user": "..."
  },
  {
    "name": "agentrouter-1",
    "provider": "agentrouter",
    "cookies": {"session": "..."},
    "api_user": "..."
  }
]
```

The file supports every field currently accepted in `ANYROUTER_ACCOUNTS`, including email/password accounts. The immediate target use case is GitHub OAuth accounts represented by `session` and `api_user` values.

## Loading And Validation

`load_accounts_config` will load `ANYROUTER_ACCOUNTS_FILE` when it is set. A configured file has priority over `ANYROUTER_ACCOUNTS`, so local configuration is deterministic and does not depend on an inherited environment value.

The loader will use the same JSON parsing and per-account validation for both sources. A missing, unreadable, malformed, or non-array file will print a source-specific error and return `None`; the main program will retain its existing non-zero exit behavior. It will not fall back to `ANYROUTER_ACCOUNTS` after a configured file fails, so an operator cannot unknowingly run stale credentials.

When neither source is configured, the error will mention both supported configuration methods.

## Repository Changes

- Add `accounts.json` to `.gitignore` so credentials cannot be accidentally committed.
- Add a tracked, credential-free `accounts.example.json` template that describes seven OAuth account entries: three `anyrouter` and four `agentrouter`.
- Update `.env.example` with `ANYROUTER_ACCOUNTS_FILE` and retain the inline environment-variable example.
- Update the local setup section of the README to prefer `accounts.json`, explain the source priority, and retain the one-line environment-variable option for CI and compatibility.
- Add focused configuration tests for file loading, file priority, missing file, malformed JSON, and current inline-environment compatibility.

## Success Criteria

- A local `accounts.json` with seven accounts loads through the existing account model and validation.
- A configured account-file path overrides a valid `ANYROUTER_ACCOUNTS` environment variable.
- Invalid file paths and JSON result in clear configuration errors and no check-in attempt.
- Existing environment-variable tests and full test suite remain green.
