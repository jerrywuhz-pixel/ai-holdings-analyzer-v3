# Hermes Workflow Templates

This file defines the default task entry templates and child-agent slots for
Hermes holdings-system work. It keeps repeated Codex sessions from rebuilding
context and verification structure from scratch.

## Default Evidence Contract

Every non-trivial Hermes task should close with these proof layers:

1. service health
2. route truth
3. persistence truth
4. delivery truth
5. user-surface truth
6. remaining risks

Use these local helpers when applicable:

- `python3 scripts/hermes_evidence_pack.py`
- `python3 scripts/hermes_wechat_trace_bundle.py`
- `python3 scripts/hermes_swas_runbook.py`
- `python3 scripts/hermes_explain_routing.py`

## Entry Template: New Feature

Use when adding or changing product behavior.

- Goal: user-visible outcome and exact entry surface.
- Boundary: read-only, confirmation-first, no automatic broker order.
- Context to load: `README.md`, `docs/hermes/agents.md`, relevant PRD/system-analysis doc, and current code owner files.
- Required design notes: user entry, write boundary, data/source requirements, rollback/disable path.
- Suggested agent slots: `explore`, `product-doc`, `executor`, `verifier`.
- Completion evidence: tests, route truth, persistence truth, and user-surface proof when applicable.

## Entry Template: Cloud Operations

Use for Aliyun lightweight-server checks, deployment issues, cron incidents, and live runtime doubts.

- Goal: exact claim being proved or disproved.
- Boundary: read-only unless the user explicitly asks to fix or deploy.
- Context to load: `docs/LIGHTWEIGHT_SERVER_DEPLOY.md`, `.omx/state`, recent `.omx/logs`, and prior evidence packs.
- Required checks: SWAS instance, Cloud Assistant, Docker/systemd, WebApp/data-service/domain-tools, cron, WeChat bridge, DB evidence.
- Suggested agent slots: `ops-runtime`, `verifier`; add `executor` only after diagnosis.
- Completion evidence: `scripts/hermes_swas_runbook.py` output plus a `hermes_evidence_pack`.

## Entry Template: Verification Closure

Use when the implementation is already done and the question is whether it truly works.

- Goal: claim and pass/fail threshold.
- Boundary: verify first; avoid design changes until the failing layer is known.
- Context to load: changed files, tests, deploy smoke, DB tables, and user-visible surface.
- Required checks: local green, cloud deployed, path live, user visible.
- Suggested agent slots: `verifier`, with `ops-runtime` for cloud or WeChat claims.
- Completion evidence: PASS/PARTIAL/FAIL/UNKNOWN verdict with Gap and Next.

## Entry Template: Product/Docs Sync

Use when user decisions need to land in Obsidian or repo docs.

- Goal: preserve confirmed decisions in implementation-ready Markdown.
- Boundary: keep source notes intact; do not invent policy.
- Context to load: current Obsidian note or repo doc, recent user confirmations, and `docs/hermes/agents.md`.
- Required sections: user entry and boundary, data/write contract, verification loop, open questions.
- Suggested agent slots: `product-doc`, `verifier`.
- Completion evidence: changed files plus captured decisions and unresolved ambiguity.

## Default Child-Agent Slots

- `explore`: maps files, symbols, tables, and existing tests.
- `ops-runtime`: proves cloud, cron, WeChat, route, and DB state.
- `product-doc`: turns confirmed decisions into concise docs/spec deltas.
- `executor`: owns bounded implementation with a disjoint write set.
- `verifier`: independently checks the claim and produces final evidence.

Rules:

- Do not spawn all slots by default; choose only the useful ones.
- Implementation and verification should be separate for cloud, WeChat, cron, and persistence work.
- The final verifier owns the user-surface truth check and remaining-risk statement.
- Existing user changes are never reverted unless explicitly requested.
