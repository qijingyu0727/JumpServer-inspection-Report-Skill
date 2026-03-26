# Progress

- Inspected skill routing, parser entrypoints, dependency bootstrap, and command execution flow.
- Added a dedicated `bootstrap` entrypoint and changed docs/prompts to prefer it for fresh installs.
- Added `runtime/.venv` pip recovery, dependency-install retries, longer browser download timeouts, and profile-aware install env handling.
- Redirected Playwright browser storage to `runtime/.playwright-browsers`.
- Added bootstrap payload fields for `pending_profile_keys`, dependency-group failures, browser path, and next-step commands.
- Validated syntax, CLI help, bootstrap JSON smoke behavior, and a live bootstrap run that wrote browser state into `runtime/.playwright-browsers`.
