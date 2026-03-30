# Local Patch Notes

Upstream source snapshot origin:

- Repository: `https://github.com/O-Jiangweidong/jms-inspect-go.git`
- Local import source: `/Users/qixiaoc/Code/skills/jms-inspect-go-0.0.13`

Local changes applied for OpenClaw / non-interactive skill integration:

- Added `-auto-approve` to skip the post-check interactive confirmation.
- Added `-check-only` so `self-test` can validate config and connectivity without generating reports.
- Added `-output-dir` so the Python adapter can control remote output placement and download artifacts reliably.
- Changed config validation failures to exit with a non-zero status instead of logging only.
- In silent or auto-approved runs, missing SSH or privilege passwords now return explicit errors instead of waiting for terminal input.
- Embedded `echarts.min.js` was vendored locally under `pkg/report/templates/` so the binary can be rebuilt without a runtime network fetch.
