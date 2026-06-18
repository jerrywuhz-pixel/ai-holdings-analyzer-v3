# Hermes Skills

This directory contains Hermes-side skill/playbook contracts for Hermes Agent.

These are not OpenClaw gateway skills and do not require a GBrain memory-store deployment. On the lightweight server they are installed under `/root/.hermes/skills`.

## Integration Rules

Hermes skills must align with Hermes Agent skill discovery and the current product/runtime contracts:

| Requirement | Contract |
| --- | --- |
| Runtime target | `RunContract.runtimeTarget = "hermes"` where structured jobs are used |
| Job types | Use existing `HermesJobType`: `deep_research`, `equity_analysis`, `options_sell_put`, `portfolio_review`, `memory_curate`, `ops_diagnostic` |
| Context | Declare required `ContextPack` sections and `ContextSourceRef` types |
| Output | Produce artifact content, delivery summaries, analysis drafts, memory candidates when deployed, or optimization proposals |
| Business facts | Hermes does not directly write `portfolio_positions`, `trade_events`, `trading_rules`, broker credentials, or order execution |
| Artifacts | Use existing `ArtifactType`: `deep_research_report`, `sell_put_report`, `portfolio_review`, `ops_diagnostic`, `weekly_optimization_confirmation` |
| Data scope | Use `RunContract.dataScope` for `portfolioViewId`, `followViewId`, `brokerConnectionIds`, and `symbols` |
| Tool policy | Only request allowed read/analysis capabilities; forbidden tools must include direct business-fact writes and order placement |

## Skill List

| Skill | Directory | Hermes job types | Main role |
| --- | --- | --- | --- |
| Hermes WeChat Portfolio | `hermes-wechat-portfolio/` | `portfolio_review`, `deep_research`, `options_sell_put`, `ops_diagnostic` | Convert WeChat investment requests into Hermes job plans, progress summaries, and delivery-ready artifacts |
| Holdings Analyzer | `holdings-analyzer/` | `portfolio_review`, `equity_analysis`, `options_sell_put` | Analyze current holdings context, risk, data quality, and Sell Put readiness for Hermes artifacts |
