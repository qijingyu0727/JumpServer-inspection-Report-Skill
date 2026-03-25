# JumpServer Inspection Toolbox

[中文](README.md)

`jumpserver-inspection-report` is a JumpServer inspection toolbox for team use. It covers formal inspection reports, login anomaly and Top N analysis, single-host usage checks, Word/PDF template filling, Feishu payload generation, and local schedule state.

HTML reports now default to `legacy`, which uses the full host-side and database-backed inspection dataset. Use `--style modern` only when you explicitly want the newer dashboard-style HTML.

## Copy/Paste Setup

Install:

```bash
python3 -m pip install -r requirements.txt
python3 -m playwright install chromium
mkdir -p runtime/profiles
cp .env.example runtime/profiles/prod.env
```

Minimum config:

```ini
JUMPSERVER_URL=https://jumpserver.example.com
JUMPSERVER_USERNAME=admin
JUMPSERVER_PASSWORD=change_me
JMS_EXEC_ASSET_NAME=10.1.12.46
JMS_EXEC_ACCOUNT_NAME=root
JMS_REPORT_STYLE=legacy
JMS_AUTO_INSTALL=true
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

## Features

- Formal inspection reports in `html` and `markdown`
- Full `legacy` data path from JumpServer host inspection and database queries
- Analysis workflows for login anomalies, Top users/assets, and host usage
- Template filling for `doc`, `docx`, and `pdf`
- Feishu payload generation and local scheduling helpers
- Profile/env persistence for follow-up prompts and repeated runs

## Installation

1. Install Python dependencies:

```bash
python3 -m pip install -r requirements.txt
```

2. If you need command execution or host usage checks, install the Playwright browser once:

```bash
python3 -m playwright install chromium
```

3. Create a profile:

```bash
mkdir -p runtime/profiles
cp .env.example runtime/profiles/prod.env
```

## Minimum First-Run Config

Edit `runtime/profiles/prod.env` and set at least:

```ini
JUMPSERVER_URL=https://jumpserver.example.com
JUMPSERVER_USERNAME=admin
JUMPSERVER_PASSWORD=change_me
JMS_EXEC_ASSET_NAME=10.1.12.46
JMS_EXEC_ACCOUNT_NAME=root
```

Notes:

- `JMS_EXEC_ASSET_NAME` should point to the JumpServer deployment host asset name or IP
- `JMS_EXEC_ACCOUNT_NAME` is the account used to connect to that host
- The default report style is `legacy`
- Database queries use `PyMySQL[rsa]`; MySQL 8 `caching_sha2_password` / `sha256_password` setups also require `cryptography`

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
python3 scripts/jms_inspection.py save-config --profile prod JMS_DEFAULT_ORG_NAME=Default JMS_EXEC_ASSET_NAME=10.1.12.46 JMS_EXEC_ACCOUNT_NAME=root
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

- `html` is the recommended report output, and `legacy` is the default HTML style
- `legacy` prefers `JMS_SYSTEM_TARGETS`; if absent, it falls back to `JMS_EXEC_ASSET_NAME / JMS_EXEC_ACCOUNT_NAME`
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
- Auto-installed fallback Python packages are placed in `runtime/.venv`
- `.doc` to `.docx` conversion still depends on system-side `libreoffice/soffice`
