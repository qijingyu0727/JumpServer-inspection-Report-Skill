# JumpServer Inspection Toolbox

[中文](README.md)

`jumpserver-inspection-report` is now a JumpServer inspection toolbox for teams. It covers formal HTML/Markdown reports, login anomaly and Top N analysis, single-host usage checks, Word/PDF template filling, Feishu payload generation, and local schedule state. HTML reports now default to `legacy` so the full server-side and database-backed inspection dataset is used unless `--style modern` is explicitly requested.

## Quick Start

```bash
python3 -m pip install -r requirements.txt
mkdir -p runtime/profiles
cp .env.example runtime/profiles/prod.env
python3 scripts/jms_inspection.py list-orgs --profile prod
python3 scripts/jms_inspection.py self-test --profile prod --date 2026-03-20 --org-name Production
bin/jms-report prod 2026-03-20 html
```

If you need command execution support, install the Playwright browser once:

```bash
python3 -m playwright install chromium
```

## Common Commands

```bash
python3 scripts/jms_inspection.py analyze --profile prod --from 2026-03-01 --to 2026-03-20 --type login-anomalies --org-name Production
python3 scripts/jms_inspection.py analyze --profile prod --from 2026-03-01 --to 2026-03-20 --type top-users --all-orgs
python3 scripts/jms_inspection.py analyze --profile prod --from 2026-03-20 --to 2026-03-20 --type host-usage --host 10.1.12.46 --org-name Production
python3 scripts/jms_inspection.py fill-template --profile prod --from 2026-03-01 --to 2026-03-20 --input-file /path/to/report.docx --org-name Production
python3 scripts/jms_inspection.py ensure-deps all
```

## Notes

- Formal reports still prefer `html`, and `legacy` is now the default HTML style
- Analysis requests return structured markdown by default
- Organization names are resolved by exact match or unique fuzzy match
- Host "who is using it" checks rely on JumpServer sessions/audit data
- `requirements.txt` now predeclares `PyMySQL[rsa]`, `cryptography`, `playwright`, `python-docx`, and `pypdf`
- MySQL 8 `caching_sha2_password` / `sha256_password` authentication is covered by the RSA dependency path
- Auto-installed fallback Python dependencies are still placed in `runtime/.venv`
