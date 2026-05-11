# WebApp 站点层级与高保真原型

## 参考风格提炼

附件参考图的关键风格不是单纯暗色，而是“专业交易终端”的信息组织方式：

1. 黑色浏览器/终端窗口作为整体容器。
2. 左侧控制台承载输入、授权、数据源和快捷动作。
3. 右侧主工作台承载核心结论、图表、候选/持仓列表。
4. 当前确认主色改为红色系，用于品牌、选中态、主动作和关键实时数字；告警仍用琥珀色，辅助模块保留少量青色/紫色区分信息域。
5. 所有卡片边界清晰，圆角克制，文本密度较高。
6. 图表和数字来自结构化数据，而不是装饰性视觉。
7. Dashboard 的主工作区优先展示持仓和 Sell Put 资金占用，趋势图下移；富途同步不作为主界面核心功能点，只作为数据 freshness 状态出现。

3.0 WebApp 可以继承这套气质，但业务上要从“单点期权扫描器”升级成“多账户持仓工作台”。

## 站点层级图

![AI 持仓系统 3.0 WebApp 站点层级](/Users/jerry.wu/Documents/vibecodingapp/ai-holdings-analyzer-v2/product-design-v3/prototypes/webapp-site-map-red.png)

设计结论：

| 层级 | 设计 |
| --- | --- |
| 移动端主导航 | 总览、持仓、关注、研究、我的 |
| 桌面端扩展导航 | 总览、持仓、关注、清仓、研究、确认/消息、数据/账户、规则/纪律、设置 |
| 确认中心 | 不占移动端底部 Tab，使用全局 badge 和深链进入 |
| WebApp Shell | 负责 Supabase Auth、tenant context、当前 `portfolio_view`、数据新鲜度和市场状态 |
| 绑定/授权/同步 | 只在 WebApp 完成，不在微信对话内完成 |

## 高保真原型

![AI 持仓系统 3.0 WebApp 高保真原型](/Users/jerry.wu/Documents/vibecodingapp/ai-holdings-analyzer-v2/product-design-v3/prototypes/webapp-dashboard-terminal-prototype-red.png)

原型选择的是桌面端 Dashboard，因为它最能代表整个 WebApp 的信息架构和视觉语言。

## 移动端适配原型

![AI 持仓系统 3.0 WebApp 移动端原型](/Users/jerry.wu/Documents/vibecodingapp/ai-holdings-analyzer-v2/product-design-v3/prototypes/webapp-dashboard-mobile-red.png)

移动端采用 5 个主 Tab：总览、持仓、关注、研究、我的。确认中心不占底部导航位，而是通过待处理数字、全局 badge 和消息深链进入。

移动端首屏只保留：

1. 当前 `portfolio_view` 和数据新鲜度。
2. 四个最关键指标：总资产、今日盈亏、现金/保证金、待处理。
3. 今日结论摘要。
4. 重点持仓摘要。
5. Sell Put 资金占用摘要。
6. 组合净值小图。

### 页面结构

| 区域 | 内容 |
| --- | --- |
| 顶部窗口/导航 | 类浏览器窗口、当前路径、主导航、LIVE ACCOUNT 状态 |
| 左侧控制台 | 资产信息、当前 `portfolio_view`、Supabase 登录态、微信绑定、数据 freshness、快捷操作、交易纪律 |
| 主工作台第一层 | 今日持仓结论、股票/ETF 持仓、Sell Put 监控和资金占用 |
| 今日结论 | 组合状态、数据源状态、sell put 风险、今日行动 |
| 图表区 | 组合净值、期权风险/DTE/现金占用，放在持仓信息之后 |
| 数据同步入口 | 不在 Dashboard 强展示；进入“我的 / 数据”里的券商连接页触发 |

### 视觉规范草案

| 项 | 规范 |
| --- | --- |
| 背景 | `#050606` / `#0b0d0e` 终端黑 |
| 面板 | `#141619`，1px 冷灰描边 |
| 主色 | 红色系 `#ff1f3d` / `#ff4357`，用于品牌、选中态、主动作、关键实时数字 |
| 辅色 | 青色表示持仓/数据，紫色表示关注，琥珀表示研究/注意和风险提示 |
| 圆角 | 4px-8px，保持工具感 |
| 字体 | 中文优先系统无衬线；数字/代码用等宽字体 |
| 图表 | 确定性 SVG/Canvas 渲染，不使用生成式图片表达财务事实 |

## 站点层级 Mermaid 源

```mermaid
flowchart TB
  Shell["WebApp Shell<br/>Supabase Auth / Tenant Context / Top Status"]

  Shell --> Dashboard["总览 Dashboard<br/>资产摘要 / 风险雷达 / 今日行动"]
  Shell --> Portfolio["持仓 Portfolio<br/>多 portfolio_view / 股票ETF / 期权"]
  Shell --> Follow["关注 Follow<br/>机会池 / sell put 候选 / 提醒"]
  Shell --> Research["研究 Research<br/>Hermes 长任务 / 报告归档"]
  Shell --> Mine["我的 / 数据<br/>绑定 / 授权 / 同步 / 规则"]

  Dashboard --> Inbox["确认 / 消息中心<br/>全局 badge / 深链"]
  Portfolio --> TradeImport["交易与导入<br/>手工 / OCR / CSV"]
  Portfolio --> Closed["清仓 List Views<br/>复盘 / 二次买入"]
  Research --> Artifacts["报告 Artifact<br/>图表 / lineage / 微信摘要跳转"]
  Mine --> Settings["设置 Settings<br/>账号 / 通知 / 隐私"]
```

## 本轮产物文件

| 文件 | 说明 |
| --- | --- |
| `prototypes/webapp-site-map-red.png` | 红色主色站点层级渲染图 |
| `prototypes/webapp-site-map-red.svg` | 红色主色站点层级 SVG 源 |
| `prototypes/webapp-dashboard-terminal-prototype-red.png` | 红色主色桌面 Dashboard 原型 |
| `prototypes/webapp-dashboard-terminal-prototype-red.svg` | 红色主色桌面原型 SVG 源 |
| `prototypes/webapp-dashboard-mobile-red.png` | 红色主色移动端 Dashboard 原型 |
| `prototypes/webapp-dashboard-mobile-red.svg` | 红色主色移动端 SVG 源 |
| `prototypes/webapp-site-map.png` | 绿色参考版站点层级渲染图 |
| `prototypes/webapp-dashboard-terminal-prototype.png` | 绿色参考版 Dashboard 原型 |
| `prototypes/render-webapp-prototype.js` | 原型渲染脚本 |
