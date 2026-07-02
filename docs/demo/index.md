# Demo Docs

Use this section for live demo prep, presentation, and evidence capture.

## Recommended reading order

1. `docs/demo/guide.md` — canonical rerun guide
2. `docs/demo/operator-cheatsheet.md` — fastest command reference on the demo host
3. `docs/demo/presenter-script.md` — presenter talk track and branch handling
4. `docs/demo/report-template.md` — template for recording outcome and evidence
5. `docs/demo/ui-direction.md` — product/design note for the alert-first incident console

## Which file to use

- **Need validated demo truth, GO / NO-GO, or fallback policy?** Use `docs/demo/guide.md`.
- **Need commands during the demo?** Use `docs/demo/operator-cheatsheet.md`.
- **Need wording for the room?** Use `docs/demo/presenter-script.md`.
- **Need to record a run?** Use `docs/demo/report-template.md`.
- **Need UI/product context?** Use `docs/demo/ui-direction.md`.

## Ownership model

- `guide.md` owns validated scenarios, endpoints, run order, GO / NO-GO, and fallback rules.
- `operator-cheatsheet.md` owns exact commands, checks, and blocker triage.
- `presenter-script.md` owns spoken narration only.
- `report-template.md` owns fill-in evidence capture only.
- `ui-direction.md` owns product/UI direction only.

## Scope guardrails

These docs support the validated demo stories only:
- direct Prometheus report-centric path
- live Grafana Loki alert webhook path

They are not broad product-certification docs. For current runtime limits, cross-check `docs/current-rca-runtime-truth-table.md`.
