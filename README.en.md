# JumpServer Formal Inspection Report

[中文](README.md)

`jumpserver-inspection-report` is now opinionated toward formal inspection reporting. When the user asks for an inspection report, daily report, monthly report, or legacy report and the required inputs are present, the default path is the official remote `jms-inspect-go` flow that produces a `legacy` HTML formal report.

Template filling, Markdown reports, and analysis are still available, but they are now explicit advanced paths. They should only be used when the user clearly asks for `template/Word/PDF/doc/docx` handling or asks for analysis instead of a formal report.

## Copy/Paste for OpenClaw

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
JMS_OFFICIAL_SSH_USERNAME=root
JMS_OFFICIAL_SSH_PASSWORD=change_me
JMS_REPORT_STYLE=legacy
JMS_LEGACY_PROVIDER=official
JMS_AUTO_INSTALL=true
```

Optional for restricted networks:

```ini
HTTPS_PROXY=http://127.0.0.1:7890
HTTP_PROXY=http://127.0.0.1:7890
PLAYWRIGHT_DOWNLOAD_CONNECTION_TIMEOUT=180000
PLAYWRIGHT_CHROMIUM_DOWNLOAD_HOST=https://storage.googleapis.com/chrome-for-testing-public
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

Validate the official path immediately after installation:

```bash
python3 scripts/jms_inspection.py self-test --profile prod --date 2026-03-20
bin/jms-report prod 2026-03-20 html
```

Success means:

- `official_binary_ready = true`
- `official_ssh_ready = true`
- `official_check_only_ready = true`
- the final artifact is an official HTML formal report, not a Markdown template

## Default Behavior

- Preferred formal report entrypoints:
  - `bin/jms-report <profile> <date> html`
  - `python3 scripts/jms_inspection.py report <profile> <date> html`
- HTML defaults to the `legacy` style
- `legacy` defaults to the `official` provider
- The official path uploads `jms_inspect` to the JumpServer host over SSH and retrieves HTML/JSON/Excel artifacts
- The compatibility `generate` entry now also defaults to `html` so it no longer falls back to Markdown templates by accident
- `modern` is only the lighter control-room brief for mobile or summary use
- Template flows only apply when the user explicitly asks for `template/Word/PDF/doc/docx`
- `analyze` only applies when the user explicitly asks for analysis instead of a formal report

## Shortest Formal Report Path

1. Run `bootstrap`
2. Write the minimum profile config
3. Run `self-test`
4. Generate the formal report

```bash
python3 scripts/jms_inspection.py bootstrap --profile prod
python3 scripts/jms_inspection.py save-config --profile prod JUMPSERVER_URL=https://jumpserver.example.com JUMPSERVER_USERNAME=admin JUMPSERVER_PASSWORD=change_me JumpServer_IP=10.1.12.46 JMS_EXEC_ACCOUNT_NAME=root JMS_OFFICIAL_SSH_USERNAME=root JMS_OFFICIAL_SSH_PASSWORD=change_me
python3 scripts/jms_inspection.py self-test --profile prod --date 2026-03-20
bin/jms-report prod 2026-03-20 html
```

## Common Commands

Formal reports:

```bash
bin/jms-report prod 2026-03-20 html
python3 scripts/jms_inspection.py report prod 2026-03-20 html --org-name Production
python3 scripts/jms_inspection.py report prod 2026-03-20 html --all-orgs
python3 scripts/jms_inspection.py report prod 2026-03-20 html --style modern
python3 scripts/jms_inspection.py report prod 2026-03-23 html --from 2026-02-23 --to 2026-03-23
python3 scripts/jms_inspection.py generate --profile prod --date 2026-03-20
```

Analysis:

```bash
python3 scripts/jms_inspection.py analyze --profile prod --from 2026-03-01 --to 2026-03-20 --type login-anomalies --org-name Production
python3 scripts/jms_inspection.py analyze --profile prod --from 2026-03-01 --to 2026-03-20 --type top-users --all-orgs
python3 scripts/jms_inspection.py analyze --profile prod --from 2026-03-20 --to 2026-03-20 --type host-usage --host 10.1.12.46 --org-name Production
```

Explicit template workflows:

```bash
python3 scripts/jms_inspection.py fill-template --profile prod --from 2026-03-01 --to 2026-03-20 --input-file /path/to/report.docx --org-name Production
python3 scripts/jms_inspection.py generate --profile prod --date 2026-03-20 --format markdown --template-file daily
```

Dependencies and diagnostics:

```bash
python3 scripts/jms_inspection.py list-orgs --profile prod
python3 scripts/jms_inspection.py self-test --profile prod --date 2026-03-20
python3 scripts/jms_inspection.py ensure-deps official
python3 scripts/jms_inspection.py ensure-deps all
```

## Dependencies

`requirements.txt` predeclares these Python packages to reduce first-run installation failures:

- `PyMySQL[rsa]`
- `cryptography`
- `playwright`
- `paramiko`
- `python-docx`
- `pypdf`

Notes:

- `bootstrap` installs `db + exec + docx + official` by default
- For fresh installs, prefer `bootstrap` instead of jumping straight to `ensure-deps all`
- If `runtime/.venv` is missing `pip`, the script now recovers it before installing packages
- Playwright browser binaries default to `runtime/.playwright-browsers`
- `exec` prefers a locally installed Chrome/Chromium and only downloads one when necessary
- Official remote execution depends on `paramiko`, and the bundled binary lives at `assets/bin/linux_amd64/jms_inspect`

## Documentation

- Skill routing: `SKILL.md`
- Runtime and environment: `references/runtime.md`
- Intent routing: `references/intent-routing.md`
- Template flows: `references/templates.md`
- Delivery and scheduling: `references/delivery.md`
- Troubleshooting: `references/troubleshooting.md`
- Layout and metadata: `references/metadata/repo-layout.md`
