# JumpServer Inspection Toolbox

[中文](README.md)

`jumpserver-inspection-report` is a JumpServer inspection toolbox for team use. It covers formal inspection reports, login anomaly and Top N analysis, single-host usage checks, Word/PDF template filling, Feishu payload generation, and local schedule state.

HTML reports now default to `legacy`, which renders the new full inspection edition with host-side and database-backed data. `modern` provides a lighter control-room brief in the same JumpServer-themed visual system.

## Copy/Paste Setup

Install:

```bash
python3 scripts/jms_inspection.py bootstrap --profile prod
```

Minimum config:

```ini
JUMPSERVER_URL=https://jumpserver.example.com
JUMPSERVER_USERNAME=admin
JUMPSERVER_PASSWORD=change_me
JumpServer_IP=10.1.12.46
JMS_EXEC_ACCOUNT_NAME=root
JMS_REPORT_STYLE=legacy
JMS_AUTO_INSTALL=true
```

Optional for restricted networks:

```ini
HTTPS_PROXY=http://127.0.0.1:7890
HTTP_PROXY=http://127.0.0.1:7890
PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT=180000
```

If you do not want database discovery to rely on remote `/opt/jumpserver/config/config.txt`, also add:

```ini
DB_ENGINE=mysql
DB_HOST=10.1.12.46
DB_PORT=3306
DB_USER=root
DB_PASSWORD=change_me
DB_NAME=jumpserver
```

Smoke test:

```bash
python3 scripts/jms_inspection.py list-orgs --profile prod
python3 scripts/jms_inspection.py self-test --profile prod --date 2026-03-20
bin/jms-report prod 2026-03-20 html
```

Notes:

- `bootstrap` installs `db + exec + docx` by default
- If you also need PDF template filling, run `python3 scripts/jms_inspection.py bootstrap --profile prod --include-pdf`
- This avoids blocking fresh installs on non-core `pdf/libreoffice` dependencies
- `bootstrap` creates `runtime/profiles/prod.env` automatically and stores Chromium under `runtime/.playwright-browsers`
- If Chromium downloads are timing out, add `HTTPS_PROXY/HTTP_PROXY` or `PLAYWRIGHT_DOWNLOAD_HOST` to the profile and rerun `bootstrap`

## Features

- Formal inspection reports in `html` and `markdown`
- Full `legacy` data path from JumpServer host inspection and database queries, now rendered in the new full-report layout
- Analysis workflows for login anomalies, Top users/assets, and host usage
- Template filling for `doc`, `docx`, and `pdf`
- Feishu payload generation and local scheduling helpers
- Profile/env persistence for follow-up prompts and repeated runs

## Installation

1. Install Python dependencies:

```bash
python3 scripts/jms_inspection.py bootstrap --profile prod
```

2. If you also need PDF template filling:

```bash
python3 scripts/jms_inspection.py bootstrap --profile prod --include-pdf
```

## Minimum First-Run Config

Edit `runtime/profiles/prod.env` and set at least:

```ini
JUMPSERVER_URL=https://jumpserver.example.com
JUMPSERVER_USERNAME=admin
JUMPSERVER_PASSWORD=change_me
JumpServer_IP=10.1.12.46
JMS_EXEC_ACCOUNT_NAME=root
```

Notes:

- `JumpServer_IP` should point to the JumpServer deployment host asset name or IP
- `JMS_EXEC_ACCOUNT_NAME` is the account used to connect to that host
- The default report style is `legacy`, which means the full inspection edition
- Database queries use `PyMySQL[rsa]`; MySQL 8 `caching_sha2_password` / `sha256_password` setups also require `cryptography`
- `bootstrap` prints `pending_profile_keys` so the next missing onboarding inputs are explicit
- The old key `JMS_EXEC_ASSET_NAME` is still supported for compatibility, but new setups should prefer `JumpServer_IP`

## Quick Validation

Check organizations and connectivity before generating reports:

```bash
python3 scripts/jms_inspection.py list-orgs --profile prod
python3 scripts/jms_inspection.py self-test --profile prod --date 2026-03-20 --org-name Production
python3 scripts/jms_inspection.py self-test --profile prod --date 2026-03-20
bin/jms-report prod 2026-03-20 html
```

If the tool asks for org, host, or database config, write it back into the profile:

```bash
python3 scripts/jms_inspection.py save-config --profile prod JMS_DEFAULT_ORG_NAME=Default JumpServer_IP=10.1.12.46 JMS_EXEC_ACCOUNT_NAME=root
```

## Common Workflows

Formal HTML reports:

```bash
bin/jms-report prod 2026-03-20 html
python3 scripts/jms_inspection.py report prod 2026-03-20 html --org-name Production
python3 scripts/jms_inspection.py report prod 2026-03-20 html --all-orgs
python3 scripts/jms_inspection.py report prod 2026-03-20 html --style modern
python3 scripts/jms_inspection.py report prod 2026-03-23 html --from 2026-02-23 --to 2026-03-23
```

Analysis:

```bash
python3 scripts/jms_inspection.py analyze --profile prod --from 2026-03-01 --to 2026-03-20 --type login-anomalies --org-name Production
python3 scripts/jms_inspection.py analyze --profile prod --from 2026-03-01 --to 2026-03-20 --type top-users --all-orgs
python3 scripts/jms_inspection.py analyze --profile prod --from 2026-03-20 --to 2026-03-20 --type host-usage --host 10.1.12.46 --org-name Production
```

Template filling:

```bash
python3 scripts/jms_inspection.py fill-template --profile prod --from 2026-03-01 --to 2026-03-20 --input-file /path/to/report.docx --org-name Production
```

Dependencies and scheduling:

```bash
python3 scripts/jms_inspection.py ensure-deps all
python3 scripts/jms_inspection.py setup-daily-push --profile prod --org-name Production --hour 8 --minute 0 --template-file daily
```

## Default Behavior

- `html` is the recommended report output, and `legacy` is the default full-report HTML style
- `legacy` prefers `JMS_SYSTEM_TARGETS`; if absent, it falls back to `JumpServer_IP / JMS_EXEC_ACCOUNT_NAME`
- `modern` is the lighter summary/control brief style for mobile or short-form reporting
- When one IP matches multiple assets, the tool prefers Host/Linux hints, URL hostname hints, account availability, and connectivity
- Multi-org output shows an overall summary first, then per-org details
- `report ... --from ... --to ...` still generates one summary report, not multiple daily splits
- Host “who is using it” checks rely on JumpServer sessions/audit data, and load is taken from `uptime`

## Dependencies

`requirements.txt` now predeclares these Python packages so skill installation is less likely to degrade first-run Q&A:

- `PyMySQL[rsa]`
- `cryptography`
- `playwright`
- `python-docx`
- `pypdf`

Notes:

- If `JMS_AUTO_INSTALL=true` is enabled, the script still attempts automatic recovery for missing dependencies
- Even if OpenClaw does not preinstall dependencies during skill installation, the script now tries to recover `pip` inside `runtime/.venv` before installing them
- Auto-installed fallback Python packages are placed in `runtime/.venv`
- Playwright browser binaries are stored in `runtime/.playwright-browsers`
- Fresh-install dependency recovery now uses retries and longer browser download timeouts to reduce flaky Chromium setup failures
- `.doc` to `.docx` conversion still depends on system-side `libreoffice/soffice`
- For fresh installs, prefer `python3 scripts/jms_inspection.py bootstrap --profile <name>` instead of starting with `ensure-deps all`

## Documentation

- Skill routing: `SKILL.md`
- Runtime and environment: `references/runtime.md`
- Template filling: `references/templates.md`
- Intent routing: `references/intent-routing.md`
- Delivery and scheduling: `references/delivery.md`
- Troubleshooting: `references/troubleshooting.md`
- Layout and metadata: `references/metadata/repo-layout.md`
