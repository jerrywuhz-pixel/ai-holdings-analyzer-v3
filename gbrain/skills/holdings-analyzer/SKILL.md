---
name: holdings-analyzer
description: Use this Hermes skill for portfolio review, single-position analysis, risk attribution, Sell Put readiness, and artifact-ready investment summaries from provided holdings context. It does not ingest WeChat directly, place broker orders, or write portfolio/trade/rule facts directly.
metadata:
  short-description: Analyze holdings, risk, and Sell Put readiness
  runtime-target: hermes
---

# Holdings Analyzer Hermes Skill

## Purpose

This Hermes-side skill/playbook analyzes current portfolio context for deep reviews, equity analysis, Sell Put readiness, and delivery-ready summaries.

It is the Hermes analysis core. It does not ingest WeChat messages directly and does not commit portfolio, trade, or rule facts. Product backend services own business writes, write receipts, modification, and revocation.

## Hermes Contract

| Field | Value |
| --- | --- |
| `skill_id` | `holdings-analyzer` |
| `runtimeTarget` | `hermes` |
| Supported `HermesJobType` | `portfolio_review`, `equity_analysis`, `options_sell_put` |
| Default complexity | `standard` |
| Deep complexity | `deep` for multi-symbol attribution, Sell Put scans, or historical review |
| Primary artifact types | `portfolio_review`, `deep_research_report`, `sell_put_report` |
| Owner agent | `hermes` |
| Business writes | Forbidden for Hermes; product services own fact writes |

## Job Mapping

| Analysis mode | Hermes job type | Artifact type |
| --- | --- | --- |
| Portfolio overview | `portfolio_review` | `portfolio_review` |
| Single equity/ETF detail | `equity_analysis` | `deep_research_report` |
| Risk snapshot | `portfolio_review` | `portfolio_review` |
| Options/Sell Put readiness | `options_sell_put` | `sell_put_report` |

## Input Expectations

The product backend should provide holdings context as structured snippets, source refs, or local skill context, not as mutable DB handles.

```json
{
  "mode": "overview|position_detail|risk_snapshot|options_snapshot|sell_put_readiness",
  "portfolio_view_id": "optional uuid",
  "symbol": "optional symbol",
  "market": "optional market",
  "as_of": "2026-06-10T09:31:20+08:00",
  "requested_sections": ["equities", "options", "cash_margin", "rules", "data_quality"]
}
```

## Required RunContract

```json
{
  "runtimeTarget": "hermes",
  "agentRole": "holdings-analyzer",
  "intent": "portfolio_review|position_detail|risk_snapshot|options_snapshot|sell_put_readiness",
  "jobType": "portfolio_review|equity_analysis|options_sell_put",
  "riskLevel": "low|medium|high",
  "dataScope": {
    "portfolioViewId": "uuid",
    "symbols": ["optional symbols"]
  },
  "toolPolicy": {
    "allowedTools": [
      "portfolio.snapshot.read",
      "market.quote.read",
      "market.batch_quote.read",
      "options.chain.read",
      "rules.snapshot.read",
      "research_artifacts.write"
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

## ContextPack Requirements

| Section | Source ref type | Notes |
| --- | --- | --- |
| Portfolio view summary | `business_fact` | Total value, cash, margin, source quality |
| Equity positions | `business_fact` | Quantity, cost, price, PnL, weight, sector |
| Option positions | `business_fact` | Contract, side, strike, expiry, DTE, Greeks, IV |
| Longbridge market data | `tool_result` | Quote and option-chain snapshot for US/HK assets |
| Trading rules | `business_fact` | Position limits, blacklists, override policy |
| Prior reviews | `artifact` | Last review, prior Sell Put reports, closed-position reviews |
| Tenant memory | `memory` | Preferences and lessons only |

Every source ref used for advice must expose freshness or trust level.

## Analysis Requirements

### Portfolio Overview

Return:

- total market value
- cash and margin status
- equity/ETF count
- option contract count
- top concentration risks
- option maturity and assignment risks
- data quality summary
- actionability level

### Equity/ETF Detail

Return:

- quantity, cost, latest price, market value
- PnL and portfolio weight
- sector/theme exposure
- stop/take-profit observation state
- rule hits
- source refs and freshness

### Options/Sell Put Readiness

Return:

- contract identity, DTE, strike, expiry
- IV, delta, theta, gamma, vega when available
- moneyness and breakeven
- cash secured amount or margin requirement
- assignment risk
- Longbridge option-chain data quality
- reasons for `blocked` or `analysis_only`

## Actionability Levels

Every output must include exactly one:

| Level | Meaning |
| --- | --- |
| `info_only` | Facts and status only |
| `analysis_only` | Safe observation; no actionable suggestion |
| `suggested_action` | Human may evaluate next step |
| `trade_draft` | A system trade draft may be created by product backend; Hermes does not create orders |
| `blocked` | Missing data, rule block, or risk condition prevents actionable output |

`trade_draft` means Hermes may describe a draft that product backend services can persist. It never means broker execution.

`trade_draft` requires:

1. verified system asset view
2. fresh Longbridge quote/option chain when market data matters
3. cash/margin context available
4. no hard-block trading rule
5. explicit statement that no broker order is placed

## Output Artifact Shape

```markdown
# Holdings Analysis

Job: portfolio_review | equity_analysis | options_sell_put
Actionability: info_only | analysis_only | suggested_action | trade_draft | blocked

## Summary

## Current Holdings Context

## Risk Flags

## Cash And Margin

## Options / Sell Put Readiness

## Data Quality

## Source References
```

## Writable Envelope

Allowed:

- `ArtifactRegistryRecord` with `artifactType = portfolio_review | deep_research_report | sell_put_report`
- `MemoryCandidateRecord` for preferences, lessons, research summaries, or task summaries when an external memory store is deployed
- `OptimizationProposalDraft` for report templates or analysis-output improvements

Forbidden:

- direct `trade_events`
- direct `portfolio_positions`
- direct `trading_rules`
- broker orders
- broker credential changes

## Error Handling

| Scenario | Required behavior |
| --- | --- |
| No asset view | Return `blocked`; ask product backend to collect holdings first |
| Symbol not found | Return `info_only` with not-found reason |
| Longbridge quote unavailable | Degrade market-dependent parts to `analysis_only` |
| Option chain missing key fields | Degrade Sell Put to `blocked` or `analysis_only` |
| Cash/margin missing | Do not produce `trade_draft` |
| Rule context unavailable | High-risk suggestions must be `blocked` |

## Validation Checklist

1. Uses only valid `HermesJobType` values.
2. Uses only valid `ArtifactType` values.
3. Requires `RunContract.runtimeTarget = "hermes"`.
4. Declares required context refs and data freshness.
5. Produces artifact-ready markdown.
6. Does not direct-write business facts.
7. Does not rely on OpenClaw skill discovery.
8. Is discoverable through `hermes skills list` when installed under `/root/.hermes/skills/holdings-analyzer`.
