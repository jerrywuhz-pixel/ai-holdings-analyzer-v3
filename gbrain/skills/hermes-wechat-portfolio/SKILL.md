---
name: hermes-wechat-portfolio
description: Use this Hermes skill for WeChat-first portfolio interaction planning, deep research routing, Sell Put analysis routing, task progress summaries, and delivery-ready investment summaries. It does not bind accounts, place broker orders, or write business facts directly.
metadata:
  short-description: WeChat portfolio orchestration for Hermes
  runtime-target: hermes
---

# Hermes WeChat Portfolio Skill

## Purpose

This is a Hermes-side skill/playbook for interpreting WeChat investment requests and shaping Hermes job execution, progress summaries, and delivery-ready artifacts.

It is **not** an OpenClaw gateway skill, **not** a GBrain memory-store deployment, and **not** a synchronous WeChat router. Product backend services remain responsible for direct message ingestion, product writes, receipts, modification, and revocation.

## Hermes Contract

| Field | Value |
| --- | --- |
| `skill_id` | `hermes-wechat-portfolio` |
| `runtimeTarget` | `hermes` |
| Supported `HermesJobType` | `portfolio_review`, `deep_research`, `options_sell_put`, `ops_diagnostic` |
| Default complexity | `standard`; use `deep` for research and Sell Put scans |
| Primary artifact types | `portfolio_review`, `deep_research_report`, `sell_put_report`, `ops_diagnostic` |
| Owner agent | `hermes` |
| Business writes | Forbidden for Hermes; product services may write facts and return receipts |

## Trigger Mapping

The product backend or OpenClaw ingress may create Hermes jobs using this skill when a WeChat message needs asynchronous analysis.

| WeChat intent | Hermes job type | Artifact type | Notes |
| --- | --- | --- | --- |
| `portfolio_query_deep` | `portfolio_review` | `portfolio_review` | Complex attribution, multi-position risk, or end-of-day summary |
| `position_detail_deep` | `equity_analysis` is not supported by this skill; route to `holdings-analyzer` or equity playbook | `deep_research_report` | Use only when analysis exceeds quick reply scope |
| `sell_put_analysis` | `options_sell_put` | `sell_put_report` | Requires Longbridge option-chain source refs and cash/margin context |
| `deep_research` | `deep_research` | `deep_research_report` | Company, sector, event, or opportunity research |
| `closed_review` | `portfolio_review` | `portfolio_review` | Closed-position review and rebuy conditions |
| `task_progress` | `ops_diagnostic` | `ops_diagnostic` | Explain queued/running/failed Hermes task state |
| `delivery_issue` | `ops_diagnostic` | `ops_diagnostic` | Diagnose missed report or failed delivery |

Direct write intents such as `trade_record_input`, `trade_record_modify`, `trade_record_revoke`, `follow_add`, and `rule_update` should be handled by product backend services, not by Hermes. In P0 there is no independent Domain Tools layer and no generic confirmation flow. Hermes may summarize or explain these writes after the product backend has recorded them and supplied a receipt/source ref.

## RunContract Requirements

Every job using this skill must include:

```json
{
  "runtimeTarget": "hermes",
  "agentRole": "hermes-wechat-portfolio",
  "trigger": "wechat_message|wechat_push|cron|repair_job",
  "intent": "portfolio_review|sell_put_analysis|deep_research|closed_review|task_progress|delivery_issue",
  "riskLevel": "low|medium|high",
  "dataScope": {
    "portfolioViewId": "optional uuid",
    "followViewId": "optional uuid",
    "symbols": ["optional symbols"]
  },
  "memoryScope": {
    "tenantId": "uuid",
    "allowedMemoryTypes": ["preference", "lesson", "research_summary", "session_summary", "task_summary"],
    "forbiddenMemoryTypes": ["broker_fact_ref"]
  },
  "toolPolicy": {
    "allowedTools": [
      "market.quote.read",
      "market.batch_quote.read",
      "portfolio.snapshot.read",
      "options.chain.read",
      "research_artifacts.write",
      "delivery.summary.write"
    ],
    "forbiddenTools": [
      "broker.trade.place_order",
      "portfolio_positions.direct_update",
      "trade_events.direct_commit",
      "trading_rules.direct_update",
      "broker_connection.write"
    ]
  }
}
```

The exact tool names may be implemented by product backend services, but the policy semantics must remain: Hermes may read context and write artifacts, analysis drafts, delivery summaries, and optimization proposals. Hermes must not commit financial facts, mutate trading rules, bind broker accounts, or execute orders.

## ContextPack Requirements

The skill expects these context sections when available:

| Section | Source ref type | Required for |
| --- | --- | --- |
| User message | `user_message` | All jobs |
| Current asset view | `business_fact` | `portfolio_review`, `options_sell_put` |
| Longbridge quote/option chain snapshot | `tool_result` | `options_sell_put`, equity/position detail |
| Trading rules snapshot | `business_fact` | high-risk suggestions and Sell Put |
| Follow/list view items | `business_fact` | opportunity, closed review, rebuy conditions |
| Prior Hermes artifacts | `artifact` | follow-up analysis and task progress |
| Tenant memory | `memory` | preferences, lessons, research summaries |

Source refs must include freshness and trust level where possible.

## Processing Steps

1. Classify the WeChat request into a supported Hermes job type.
2. Validate `RunContract` scope and risk level.
3. Build a concise analysis plan for the requested job.
4. Use context refs only within the tenant scope.
5. Produce a delivery-ready summary suitable for WeChat long-summary push.
6. Write only through the Hermes writable envelope:
   - artifact records
   - memory candidates when an external memory store is deployed
   - optimization proposals
7. Never emit direct business fact mutations in the write envelope.

## Output Contract

The model output should be artifact-ready markdown:

```markdown
# <Title>

Job: <job_type>
Actionability: info_only | analysis_only | suggested_action | trade_draft | blocked

## Conclusion

## Key Data

## Risk And Discipline

## Data Quality

## Suggested Next WeChat Commands

## Source References
```

For WeChat delivery, the product backend may shorten the artifact into a long summary. Hermes itself should include enough structure for that shortening to be deterministic.

## Forbidden Outputs

The skill must not output:

1. SQL mutation instructions for `portfolio_positions`, `trade_events`, or `trading_rules`.
2. Any broker order or auto-trading instruction.
3. Cross-tenant memory or user data.
4. Secret values, broker tokens, or raw credentials.
5. Claims that a product write succeeded unless the product backend supplied a source ref proving it.

## Memory Rules

Allowed memory candidates when a memory store is deployed:

- user preferences
- investment lessons
- research summaries
- session summaries
- task summaries

Forbidden memory candidates:

- unverified holdings facts
- broker facts copied as long-term memory
- relaxed trading rules without explicit backend source refs
- cross-tenant observations

## Validation Checklist

Before installing this skill into Hermes Agent:

1. `name` is unique under `/root/.hermes/skills`.
2. All job types are valid `HermesJobType` values.
3. Artifact types are valid `ArtifactType` values.
4. Forbidden tools include direct portfolio/trade/rule writes and order placement.
5. Output contract contains actionability and source refs.
6. The spec does not require OpenClaw skill discovery.
7. The spec is discoverable through `hermes skills list`.
