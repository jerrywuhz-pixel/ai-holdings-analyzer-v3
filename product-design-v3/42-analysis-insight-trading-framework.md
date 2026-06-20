# 分析洞察升级交易框架

> 目标：把外部宏观/交易文章、既有交易纪律、Hermes `AnalysisContextPack v2` 和 Sell Put 规则串成一套可执行的分析框架。本文不是交易建议，而是 Hermes 后续提升持仓分析、机会评估、风险降级和复盘能力的产品/系统契约。

## 1. 本次输入来源

| 来源 | 读取状态 | 对框架的启发 |
| --- | --- | --- |
| [金十：期货交易夜读｜算法时代的隐形之手：AI与人类交易者的共生](https://xnews.jin10.com/webapp/details.html?id=221953&type=news&data_type=0) | 已通过 `reference-api.jin10.com/reference/getOne?id=221953` 读取，发布时间 2026-06-18 22:00 | AI 应作为统计、扫描、执行纪律和情绪锚点；人类保留范式转移、价值判断、风险底线和最终决策权 |
| [培风客：2026H2经济和市场展望 - 全村的希望，The Only Play in Town](https://mp.weixin.qq.com/s/OcwIpDsdeCBOKSrIcgQiww) | 已直接读取微信 HTML 中 `js_content`，Jina Reader 被微信环境验证拦截 | 2026H2 核心矛盾是鹰派联储与 AI Capex 支撑下的 K 型分化；广谱资产环境偏紧，不能把 AI 主线外推成全面牛市 |
| Obsidian 纪要：`2026-06-19_硬科技加速与利润垫交易纪律讨论.md` | 已从本地 `/Users/jerry.wu/Documents/Obsidian Vault/持仓分析系统知识库/2026-06-19/` 读取；GitHub 页面当前不可直接读取 | 需要把“硬科技加速判断”和“全年利润垫”结合：允许有纪律进攻，但必须用利润垫预算、仓位分层和回撤触发线约束 |
| Hermes 既有沉淀 | 已核对 `docs/hermes/*`、`stock_analysis.py`、Sell Put rulebook 和记忆 | 当前系统已有 `market.regime`、`sector.context`、`history_compare`、`discipline_result`、`data_quality` 和 actionability ladder，可直接承接本框架 |

Agent Reach 安装说明已读取，但本机 shell 到 GitHub raw / git clone 当前卡住。本文先使用直接 API/HTML 读取完成资料解析；Agent Reach 后续应作为 URL 读取适配器，而不是阻塞 Hermes 框架设计。

## 2. 核心判断

Hermes 的交易框架不应追求“更会预测”，而应追求 **更会约束预测**：

1. 用 AI 做海量信息扫描、数据归一、历史对照、规则检查和情绪降噪。
2. 用人类判断处理范式转移：AI Capex 是否持续、联储反应函数是否变化、地缘/供应链/政策是否改写历史样本。
3. 用利润垫定义进攻预算：账户已有显著年度利润时，不应继续按亏损账户或单月收益视角执行；应切换为“本金保护 + 利润进攻”。
4. 用交易纪律把叙事压回动作上限：没有数据、没有规则校验、没有仓位余量、没有退出条件，就不能升级到 `trade_draft`。
5. 用复盘把每次判断变成可回放资产：保存当时的宏观环境、数据质量、规则命中、反例和后验结果。

因此，Hermes 后续升级应围绕一个问题设计：

> 在当前市场状态、用户持仓、用户纪律和数据质量下，这个想法最多能走到 `info_only`、`analysis_only`、`suggested_action`、`trade_draft` 还是必须 `blocked`？

补充利润垫视角后，还要继续追问：

> 如果这是一次主线加速，账户允许拿多少已赚利润承受波动？哪些利润必须锁住？哪些亏损会从“合理波动”变成“必须降风险”？

## 3. 市场状态框架

### 3.1 一级状态：宏观流动性

宏观流动性是所有动作上限的第一层背景。它不直接给买卖结论，但会影响仓位、杠杆、期权阈值和复盘重点。

| 状态 | 识别信号 | Hermes 行为 |
| --- | --- | --- |
| `easing_confirmed` | 联储明确转鸽、实际利率下行、美元/美债压力缓和 | 可以提升广谱资产研究优先级，但仍需个股/行业数据确认 |
| `hawkish_hold` | 降息预期消失或推迟，长端利率/美元偏强，财政发债压力存在 | 默认压低行动等级；传统行业、黄金、商品和高估值非 AI 资产需更强证据 |
| `risk_event_forcing_cut` | AI Capex 放缓、信用/新兴市场/就业风险倒逼宽松 | 先输出风险复盘和机会观察，不把“降息”自动等同于“可抄底” |
| `policy_uncertain` | 联储沟通和市场定价冲突，数据分歧大 | 只允许 `analysis_only` 或小仓位观察建议，避免高置信交易草稿 |

### 3.2 二级状态：AI Capex 与 K 型分化

微信文章的关键线索是：AI Capex 像一个大型刺激项，支撑美国经济和市场风险偏好；但它也加剧 K 型分化，使传统行业在高利率下更难修复。

Hermes 应将 `AI Capex` 作为独立主题状态，而不是简单归入科技板块涨跌：

| 状态 | 识别信号 | 对持仓分析的影响 |
| --- | --- | --- |
| `ai_capex_accelerating` | 云厂商 capex 指引上修、订单/电力/半导体链条验证、AI ARR 或 token 使用增长 | AI 链相关持仓可获得主题顺风；同时检查集中度和估值回撤风险 |
| `ai_capex_supported_but_crowded` | AI 主线仍强，但估值、仓位、M7 回报争议升高 | 输出“拥挤但仍是主线”的双结论；不允许只因主线强而忽略止盈/分散 |
| `ai_capex_slowing` | Capex 指引下修、token 价格/需求/ROI 争议恶化 | 触发科技/半导体/电力链风险复盘；传统行业是否受益必须另证 |
| `ai_productivity_breakthrough` | AI 明确提升生产率并推高实际利率 | 对黄金等依赖降息/实际利率下行的资产构成结构性逆风；对铜/电力/算力链条可能仍有支撑 |

### 3.3 三级状态：硬科技加速

Obsidian 纪要把 2026-06-18 的半导体/存储/AI 硬件链共振上涨作为重要输入：MU、INTC、AMD、AVGO、NVDA、SMH、SOXX 同向走强，说明这不是单票孤立异动，而可能是资金重新定价硬科技主线。

Hermes 应把“硬科技加速”从泛泛的 AI 叙事中拆出来，形成单独状态：

| 状态 | 识别信号 | Hermes 行为 |
| --- | --- | --- |
| `hard_tech_watch` | 个别硬科技标的走强，但 ETF、成交量或财报验证不足 | 只做观察和提醒，不提高仓位建议 |
| `hard_tech_acceleration_candidate` | MU/INTC/AMD/NVDA/AVGO 与 SMH/SOXX 多点共振，A 股硬科技也有承接 | 可进入 `suggested_action`，允许建立主线观察清单、复核日和分层仓位计划 |
| `hard_tech_acceleration_confirmed` | 财报/指引、AI Capex、存储/HBM、服务器链数据继续验证，ETF 不破关键趋势 | 在有利润垫和退出条件时，可允许“有纪律的进攻模式” |
| `hard_tech_acceleration_failed` | 财报后高开低走、ETF 放量长阴、AI Capex 指引下修、核心股连续放量下跌 | 停止新增进攻仓，触发降风险或复盘 |

关键窗口不能忽略：

1. MU 财报和电话会验证存储/HBM 景气。
2. 7 月 FOMC 验证利率压力。
3. 7 月下旬到 8 月 Q2 财报季验证 AI Capex、云厂商投入、服务器链和半导体指引。
4. CPI、PCE、就业、ISM 等宏观数据仍会影响美债收益率和科技股估值。

所以判断不是“7、8 月没有风险”，而是：

> 7、8 月没有一个已知必然爆炸的单一风险，但存在一串会验证或证伪硬科技主线的窗口。窗口没有证伪时可以更有耐心；窗口证伪时必须更快降风险。

### 3.4 四级状态：账户利润垫

市场状态只决定机会质量，账户利润垫决定能承受多少波动。纪要中的账户视角是：2026 年港美股账户已有显著全年利润垫，因此策略应从“本金防守”切换为“本金保护 + 利润进攻”。

Hermes 不应把截图或纪要中的金额当作券商事实源；金额必须来自用户明确输入、截图 OCR 或系统资产视图，并标注 source refs。但框架可沉淀为如下原则：

| 利润垫状态 | 判断 | 默认动作 |
| --- | --- | --- |
| `no_profit_cushion` | 年度利润不足或仍在回本 | 只允许小仓观察，优先保护本金 |
| `monthly_profit_cushion_only` | 单月有利润，但全年安全垫不厚 | 以保护月度利润为主，不把单月盈利放大成全年进攻权限 |
| `annual_profit_cushion_significant` | 全年利润显著高于本金或既定目标 | 可使用利润垫的一部分承受主线波动，进入“有纪律的进攻”评估 |
| `profit_cushion_drawdown_warning` | 利润垫回撤接近预设阈值 | 停止新增进攻仓，复核主线是否仍成立 |
| `profit_cushion_protection_required` | 利润垫回撤触及强制保护线 | 降低进攻仓，保护年度胜利 |

### 3.5 五级状态：资产路径拆分

不能把“宏观好/坏”直接映射成统一动作。不同资产在文章中的路径不同：

| 资产/主题 | 顺风路径 | 逆风路径 | Hermes 需要检查 |
| --- | --- | --- | --- |
| AI / 半导体 / 电力链 | AI Capex 继续高增长，盈利兑现或订单验证 | Capex 放缓、估值拥挤、收益率上行压估值 | 主题拥挤度、盈利修正、仓位集中、止盈纪律 |
| 传统周期 / 内需 / 小盘 | 联储转鸽、财政/信贷宽松、需求修复 | 鹰派联储、高利率、K 型分化继续 | 是否已有降息/订单/利润率证据，不能只赌“高低切” |
| 黄金 | 降息预期恢复、赤字压力延续、持仓/ETF 流出企稳 | AI 生产率推高实际利率、降息预期消失、持仓拥挤待消化 | 实际利率、ETF flows、央行买盘、持仓拥挤 |
| 铜 / 铜矿 | AI 数据中心/电力需求，或降息刺激需求 | 高利率进入淡季、全球供给增加、抢关税交易过热 | 铜价季节性、库存、加工费、矿企估值、AI/刺激路径归因 |
| 商品广谱 | 供应链重建、低利率支持产能冗余建设 | 鹰派联储、美元/美债上行、需求不足 | 需求与供给冲击分开解释，避免只看价格突破 |
| 现金 / 短债 | 高利率环境提供等待期收益 | 转鸽后再投资收益下降 | 作为“等待确认”的默认资产，不是消极空仓 |

## 4. 交易决策四层门

### 4.1 第一层：事实门

任何分析先回答事实是否可用：

| 检查 | 通过要求 | 失败动作 |
| --- | --- | --- |
| 行情新鲜度 | 主源 quote 有 `as_of`、freshness 和 source tier | 降级到 `analysis_only`，必要时 `blocked` |
| 持仓/现金/保证金 | 来自系统资产视图或券商只读快照，且 reconcile 无冲突 | 禁止 Sell Put 或高风险仓位建议 |
| 期权链 | DTE、delta、bid/ask、OI、volume、IV/Greeks 足够完整 | 不输出可执行候选，只解释缺口 |
| 新闻/文章/IMA | 保留标题、作者、时间、URL、读取状态 | 只能作为观点来源，不能覆盖市场事实 |
| 历史对比 | 有可回放的历史窗口和版本 | 不能给“历史上通常”这类高置信表达 |

### 4.2 第二层：叙事门

叙事必须被拆成假设，而不是直接变成结论。

每个候选机会需要显式生成：

1. `base_case`：当前最可能路径。
2. `risk_case`：最容易让判断失效的路径。
3. `confirmation_signals`：哪些数据出现后才允许升级行动等级。
4. `invalidation_signals`：哪些数据出现后必须降级或复盘。
5. `time_horizon`：这个判断是日内、1-4 周、季度，还是结构性判断。

示例：

| 叙事 | confirmation | invalidation | 默认动作 |
| --- | --- | --- | --- |
| AI Capex 延续 | 云厂商 capex 指引/订单/收入继续验证 | Capex 指引下修或 ROI 争议扩大 | 观察/持有可继续，但检查集中度和止盈 |
| 硬科技主升加速 | 半导体 ETF 不破趋势，存储/AI 硬件/服务器链财报继续验证，A 股硬科技放量承接 | 财报后高开低走，ETF 放量长阴，核心股连续放量下跌 | 有年度利润垫时可进入分层进攻计划，但必须有预算和防守线 |
| 传统行业见底 | 降息路径确认、信用利差改善、订单/利润率改善 | 利率继续上行、需求数据恶化 | 未确认前不抢高低切 |
| 黄金重新上行 | 降息预期恢复、ETF/持仓企稳、财政赤字压力延续 | 实际利率继续上行、AI 生产率叙事强化 | 未确认前只做观察或分批计划 |
| 铜中期机会 | AI 电力需求或宽松刺激验证 | 淡季价格冲高但需求不跟、供应快速释放 | 低位研究优先于追涨草稿 |

### 4.3 第三层：纪律门

纪律门负责把“看对”变成“能不能做”。它应先于模型措辞。

| 纪律 | 默认处理 |
| --- | --- |
| 不熟悉领域 | 用户明确“不熟悉/没能力判断”的主题，只能 `analysis_only`，除非用户后续建立研究 thesis |
| 单一主题拥挤 | AI/M7/半导体等同主题仓位过高时，建议先做风险雷达和止盈计划 |
| 没有退出条件 | 没有止损、止盈、复核日或失效条件时，不能生成 `trade_draft` |
| 利润垫未分层 | 没有定义锁定利润、进攻预算、高弹性预算和现金防守仓时，不能输出“更大胆”的草稿 |
| 合理波动与失控回撤未区分 | 未定义单日亏损、利润垫回撤和强制保护线时，只能 `analysis_only` |
| 高利率逆风 | `hawkish_hold` 下对传统行业、黄金、商品广谱自动降低一级 actionability |
| 事件窗口 | 财报、FOMC、政策/战争/关税窗口内，除非用户显式接受事件风险，否则期权/加仓草稿降级 |
| Sell Put 接股意愿未知 | 只允许标的分析和期权链观察，不生成卖 put 草稿 |
| 现金/保证金不足或不可验证 | `blocked` |
| hard-block 规则命中 | `blocked`，不能由模型解释绕过 |

### 4.4 第四层：执行门

Hermes 不执行券商订单，只输出动作上限。

| 输出 | 适用场景 |
| --- | --- |
| `info_only` | 事实查询、行情状态、持仓摘要 |
| `analysis_only` | 宏观/文章观点、数据缺失、用户不熟悉领域、事件窗口内观察 |
| `suggested_action` | 可建立关注、提醒、复核日、研究任务、止盈/风险观察 |
| `trade_draft` | 事实门、叙事门、纪律门都通过，且只形成系统内草稿/确认对象 |
| `blocked` | hard block、现金/保证金不可验证、数据冲突、规则服务不可用、高风险越权 |

### 4.5 利润垫进攻门

当账户进入 `annual_profit_cushion_significant`，Hermes 可以从默认防守切换到“有纪律的进攻评估”。但进攻权限来自已定义预算，而不是来自情绪或近期涨幅。

| 层 | 默认原则 | Hermes 输出 |
| --- | --- | --- |
| 已锁定胜利区 | 至少锁住全年利润的一部分，不能把超级胜利打回普通胜利 | 输出年度保护线和不可触碰预算 |
| 主线进攻预算 | 可拿利润垫的一部分承受硬科技/AI/存储/半导体主线波动 | 输出可承受回撤、复核条件和加仓触发 |
| 极端弹性预算 | 期权、杠杆 ETF、高波动小票只能使用利润垫小部分 | 必须有硬止损、到期日、最大亏损和复盘条件 |
| 现金/防守仓 | 保留分歧日再进攻能力，避免被迫卖出 | 输出最低现金比例或现金底线 |

纪要中的参考比例可作为默认模板，但落地时必须从真实资产视图或用户确认金额重算：

| 仓位层 | 参考比例 | 作用 |
| --- | ---: | --- |
| 核心主线仓 | 40%-50% | 吃硬科技主升浪，不因小波动轻易卖飞 |
| 进攻加速仓 | 20%-30% | 突破、放量、财报确认后放大收益 |
| 高弹性仓 | 10%-15% | 期权、杠杆、弹性小票，必须有硬止损 |
| 现金/防守仓 | 15%-25% | 分歧日有子弹，避免被动减仓 |

默认触发条件：

| 类型 | 条件 | 动作 |
| --- | --- | --- |
| 进攻开启 | 硬科技确认条件满足 4 条中的 3 条：ETF 不破趋势、MU/存储财报不证伪、A 股硬科技放量承接、账户月收益仍为正或处于高位 | 允许提高主线持仓耐心和分层进攻预算 |
| 停止新增 | 当日账户亏损超过 3%、半导体 ETF 放量长阴、MU 财报后高开低走、美债收益率快速上冲、A 股硬科技冲高回落、利润垫回撤超过预设警戒 | 停止新增进攻仓，保留观察 |
| 降风险 | 年度利润垫回撤约 20%、主线核心股连续两天放量下跌、财报季指引低于预期、用户出现“靠一笔赚回来”的情绪 | 降低进攻仓，进入复盘 |
| 强制保护 | 年度利润垫回撤约 30% 或触及用户确认的年度保护线 | 进入强制防守，保护年度胜利 |

## 5. Hermes 分析模板

### 5.1 单标的/持仓分析

```text
结论：
行动等级：
当前市场状态：
持仓影响：
关键证据：
叙事假设：
利润垫状态：
仓位预算：
反例/失效条件：
纪律命中：
数据质量：
下一步口令：
来源与时间：
```

### 5.2 机会研究

```text
机会类型：AI 主线 / 高低切 / 黄金 / 铜 / 商品 / 现金等待 / 其他
base_case：
risk_case：
需要验证的 3 个信号：
利润垫可用预算：
仓位前置条件：
退出/复核条件：
可执行上限：
建议沉淀对象：follow_view / alert_rule / research_artifact / discipline_check
```

### 5.3 Sell Put 分析

Sell Put 继续沿用现有两层规则，但增加宏观/主题 overlay：

1. 先判断标的是否处于 `willing_to_assign` 或可接受接股池。
2. 再检查 `market_state`：`hawkish_hold` 或 `risk_off` 下收紧 delta、DTE、spread、集中度阈值。
3. 对 AI 热门标的增加拥挤/财报/估值回撤风险说明。
4. 对传统行业标的要求看到降息或基本面修复证据，不能只因跌多而卖 put。
5. 若卖 put 用于硬科技主线进攻，必须检查 assignment 后是否会放大主题集中度。
6. 高弹性期权预算不能和 cash secured put 现金占用混用；前者是亏损预算，后者是潜在接股预算。
7. 候选合约必须保留 `strategy_model_version`、source lineage 和 `do_not_trade_if`。

## 6. Context Pack 升级建议

当前 `AnalysisContextPack v2` 已包含 quote、position、history、news、sector、active rules、previous signals、data quality。建议升级为 `analysis_context_v2_1`，增加以下 overlay，不破坏现有字段：

```json
{
  "macro_regime": {
    "fed_stance": "hawkish_hold",
    "rate_pressure": "high",
    "usd_pressure": "neutral_to_high",
    "liquidity_note": "Treasury issuance and real-rate pressure require higher evidence threshold",
    "as_of": "2026-06-19",
    "source_refs": []
  },
  "theme_regime": {
    "ai_capex": "supported_but_crowded",
    "hard_tech_acceleration": "acceleration_candidate",
    "k_shape": "intensifying",
    "theme_crowding": "high",
    "confirmation_signals": [],
    "invalidation_signals": []
  },
  "profit_cushion": {
    "status": "annual_profit_cushion_significant",
    "source": "user_confirmed | broker_snapshot | screenshot_ocr | memo_reference",
    "year_to_date_profit": null,
    "locked_victory_floor": null,
    "mainline_attack_budget": null,
    "high_beta_budget": null,
    "cash_defense_floor": null,
    "drawdown_warning_line": null,
    "forced_protection_line": null,
    "as_of": "2026-06-19"
  },
  "asset_playbook": {
    "asset_class": "equity | option | commodity | cash",
    "playbook_key": "ai_capex | hard_tech_acceleration | traditional_recovery | gold_real_rate | copper_dual_path | sell_put",
    "default_actionability_cap": "analysis_only"
  },
  "human_judgment_flags": {
    "requires_paradigm_judgment": true,
    "user_familiarity": "low | medium | high",
    "do_not_upgrade_without_user_thesis": true
  }
}
```

### 6.1 新增工具建议

| Tool | 权限 | 作用 |
| --- | --- | --- |
| `macro.regime` | read | 汇总联储、利率、美元、美债、VIX、市场宽度和流动性状态 |
| `theme.ai_capex` | read | 汇总 AI Capex、云厂商指引、半导体/电力链验证和拥挤度 |
| `theme.hard_tech_acceleration` | read | 汇总 MU/INTC/AMD/NVDA/AVGO、SMH/SOXX、A 股硬科技和财报窗口验证状态 |
| `portfolio.profit_cushion` | read | 从资产视图、用户确认或截图 OCR 计算年度利润垫、保护线、进攻预算和回撤阈值 |
| `asset.playbook.resolve` | read | 根据宏观/主题/资产类别给出默认 actionability cap 和检查清单 |
| `reference.article.extract` | read | 读取网页/微信文章，输出标题、作者、时间、正文摘要和 source refs |
| `discipline.framework_check` | read | 在现有 `trading_rules` 上增加熟悉度、退出条件、事件窗口、叙事拥挤度检查 |

### 6.2 规则建议

新增或显式化以下 `trading_rules` / discipline checks：

| 规则 | action_on_violation | 说明 |
| --- | --- | --- |
| `must_have_exit_condition` | `block_trade_draft` | 没有退出/复核条件，不允许生成交易草稿 |
| `unfamiliar_domain_cap` | `cap_analysis_only` | 用户标记不熟悉的领域，只做分析/研究，不做草稿 |
| `hawkish_macro_discount` | `cap_suggested_action` | 鹰派流动性下，非强基本面机会不直接给草稿 |
| `theme_concentration_limit` | `require_confirmation` | AI/半导体等主题集中度过高时，必须要求确认或降级 |
| `article_reference_only` | `cap_analysis_only` | 文章观点只能作为参考源，不可直接触发交易动作 |
| `profit_cushion_budget_required` | `cap_analysis_only` | 没有利润垫分层预算时，不能输出“更大胆/加仓”的交易草稿 |
| `single_day_loss_guardrail` | `require_review` | 单日亏损超过用户定义阈值时，停止新增进攻仓并触发复盘 |
| `profit_cushion_drawdown_guardrail` | `block_trade_draft` | 年度利润垫回撤超过强制保护线时，阻断新增高风险草稿 |
| `revenge_trade_guardrail` | `block_trade_draft` | 出现“靠一笔赚回来”或情绪化加仓意图时，阻断高风险动作 |

## 7. 工作流

### 7.1 盘前

1. 更新 `macro.regime` 和 `theme.ai_capex`。
2. 更新 `theme.hard_tech_acceleration`：半导体 ETF、存储/AI 硬件链、A 股硬科技、财报/宏观窗口。
3. 更新 `portfolio.profit_cushion`：年度利润垫、锁定胜利线、主线进攻预算、高弹性预算、现金防守线。
4. 对持仓生成风险雷达：集中度、事件、期权 DTE、现金/保证金、纪律冲突。
5. 输出当日 actionability ceiling：哪些主题只能观察，哪些可设提醒，哪些可生成草稿。

### 7.2 盘中

1. 只处理高优先级异常：价格穿越、成交量、期权风险、纪律冲突、新闻/政策突发、单日亏损阈值。
2. 对宏观文章或微信链接只生成研究摘要和 source refs，不直接升级动作。
3. 若用户追问“能不能做”，先跑四层门和利润垫进攻门，再给 actionability。
4. 若触发“停止新增/降风险/强制保护”条件，优先输出复盘和风险处理，而不是继续找进攻理由。

### 7.3 盘后

1. 复盘当日判断：哪些信号被确认，哪些被否定。
2. 更新 `decision_signal_reviews` 和 `discipline_checks`。
3. 复盘利润垫变化：当日盈亏、主线仓贡献、高弹性仓亏损、现金防守是否充足。
4. 把值得沉淀的经验写成 memory candidate，而不是写入持仓事实。

### 7.4 周度

1. 重新评估 AI Capex、联储、黄金/铜/商品、现金等待收益。
2. 重新评估硬科技是否仍在加速：财报、指引、ETF 趋势、A 股承接、拥挤度。
3. 更新用户熟悉度、“不做清单”和利润垫分层预算。
4. 汇总本周违反纪律最多的模式和下一周的默认防守规则。

## 8. 对文章和纪要的落地转换

| 输入观点 | Hermes 中的落地 |
| --- | --- |
| AI 与人类交易者是共生关系 | Hermes 负责扫描、归一、纪律检查和情绪锚点；用户负责最终判断和范式变化 |
| AI 擅长既有规则内优化，但对范式转移有盲点 | 对宏观 regime 变化、地缘、政策和 AI 生产率突破标记 `requires_paradigm_judgment=true` |
| 深度注意力和独立判断比信息本身更稀缺 | 输出短结论 + 证据 + 反例 + 下一步口令，减少噪音 |
| 2026H2 可能是鹰派联储 + AI Capex 支撑的 K 型分化 | `macro.regime=hawkish_hold` 时，不追传统行业高低切；AI 主线也要检查拥挤和集中度 |
| 黄金需要降息预期、赤字/持仓企稳等重新确认 | 黄金 playbook 不把结构性叙事直接转成买入，先看实际利率和 flows |
| 铜有 AI 成功和降息刺激两条路径 | 铜 playbook 强制标注当前上涨来自哪条路径，避免追逐不坚实交易 |
| 广谱资产在鹰派联储下不友善 | 现金/短债等待成为默认可接受状态，避免为了“有动作”而交易 |
| 硬科技/AI/存储/半导体可能进入主升加速 | 增加 `theme.hard_tech_acceleration`，把硬科技加速拆成 watch、candidate、confirmed、failed 四态 |
| 账户已有显著年度利润垫 | 增加 `portfolio.profit_cushion`，用利润垫分层决定进攻预算，而不是只按单月盈亏或情绪判断 |
| 更大胆应该体现在敢拿主线、敢加确认、敢承受合理波动 | 增加“利润垫进攻门”：核心主线仓、进攻加速仓、高弹性仓、现金防守仓分层 |
| 更大胆不等于接受失控回撤 | 增加 `single_day_loss_guardrail`、`profit_cushion_drawdown_guardrail` 和强制保护线 |
| 7-8 月没有单一必爆风险，但有验证窗口 | 盘前/周度流程必须列出 MU 财报、FOMC、Q2 财报季、CPI/PCE/就业/ISM 等验证窗口 |

## 9. P0 实施顺序

1. **先做文档和模板落地**：把本文模板加入 Hermes 报告/微信回复规范，短期不改交易逻辑。
2. **扩展 context pack**：增加 `macro_regime`、`theme_regime`、`asset_playbook`、`human_judgment_flags`。
3. **扩展利润垫上下文**：增加 `profit_cushion`，从资产视图、用户确认或截图 OCR 计算年度利润垫、锁定胜利线、进攻预算和强制保护线。
4. **增加 article reference extractor**：优先支持网页/微信 HTML 直读，Agent Reach 可用后作为增强通道。
5. **增加硬科技加速检查器**：每日汇总 MU/INTC/AMD/NVDA/AVGO、SMH/SOXX、A 股硬科技和财报/宏观窗口。
6. **扩展 discipline checks**：加入熟悉度、退出条件、主题集中度、文章参考源限制、单日亏损、利润垫回撤和情绪化加仓拦截。
7. **接入回放评估**：用历史 `decision_signals` / `discipline_checks` 检查新框架是否减少过度行动，而不是只看报告是否更长。

## 10. 验收标准

1. 任意单标的分析都能说明：宏观状态、主题状态、持仓影响、纪律命中、数据质量和 actionability。
2. 微信文章或网页链接进入 Hermes 后，必须成为 `source_refs`，并被标注为参考观点而非事实源。
3. `hawkish_hold`、`risk_off`、`policy_uncertain` 下，高风险动作默认降级，除非明确通过纪律和数据门。
4. Sell Put 输出必须同时检查接股意愿、现金/保证金、期权链质量、事件窗口、宏观状态和用户纪律。
5. 硬科技主线分析必须输出：加速状态、确认信号、证伪信号、未来风险窗口和拥挤度。
6. 当输出“更大胆/进攻/加仓/持有更久”时，必须同时输出利润垫状态、可用预算、停止新增条件、降风险条件和强制保护线。
7. 每个 `suggested_action` 或 `trade_draft` 都必须有失效条件和下一次复核时间。
8. 复盘能回答：当时为什么允许/阻断这个动作，哪些信号后来被验证或证伪，利润垫是否被按预算使用。
