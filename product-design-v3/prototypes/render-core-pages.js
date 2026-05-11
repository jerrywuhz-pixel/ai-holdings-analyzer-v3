const fs = require("fs");
const path = require("path");
const sharp = require(path.join(process.cwd(), "webapp/node_modules/sharp"));

const outDir = path.join(process.cwd(), "product-design-v3/prototypes");

const css = `
  .bg { fill: #050606; }
  .window { fill: #0b0d0e; stroke: #303538; stroke-width: 1.2; }
  .topbar { fill: #111315; stroke: #252a2e; stroke-width: 1; }
  .panel { fill: #141619; stroke: #30353a; stroke-width: 1.1; }
  .panel2 { fill: #101214; stroke: #2a2f34; stroke-width: 1; }
  .soft { fill: #111315; stroke: #242a2d; stroke-width: 1; }
  .active { stroke: #ff4357; stroke-width: 1.8; }
  .title { font: 800 31px "PingFang SC", "Microsoft YaHei", Arial, sans-serif; fill: #f3f6f6; }
  .h1 { font: 800 24px "PingFang SC", "Microsoft YaHei", Arial, sans-serif; fill: #f5f7f7; }
  .h2 { font: 750 18px "PingFang SC", "Microsoft YaHei", Arial, sans-serif; fill: #f1f5f3; }
  .h3 { font: 720 15px "PingFang SC", "Microsoft YaHei", Arial, sans-serif; fill: #dce2e0; }
  .label { font: 650 12px "PingFang SC", "Microsoft YaHei", Arial, sans-serif; fill: #8e9898; }
  .tiny { font: 520 11px "PingFang SC", "Microsoft YaHei", Arial, sans-serif; fill: #788282; }
  .body { font: 540 14px "PingFang SC", "Microsoft YaHei", Arial, sans-serif; fill: #d6ddda; }
  .body2 { font: 520 13px "PingFang SC", "Microsoft YaHei", Arial, sans-serif; fill: #aeb8b5; }
  .red { fill: #ff4357; }
  .red2 { fill: #ff7a88; }
  .amber { fill: #f6c45b; }
  .green { fill: #50d27a; }
  .cyan { fill: #60d2ff; }
  .violet { fill: #a88cff; }
  .mono { font: 680 14px "SFMono-Regular", "Cascadia Mono", Menlo, monospace; fill: #f2f5f2; }
  .monoRed { font: 850 24px "SFMono-Regular", "Cascadia Mono", Menlo, monospace; fill: #ff4357; }
  .monoSmall { font: 650 12px "SFMono-Regular", "Cascadia Mono", Menlo, monospace; fill: #9ba7a3; }
  .chipText { font: 750 12px "PingFang SC", "Microsoft YaHei", Arial, sans-serif; fill: #fff2f3; }
  .darkChipText { font: 750 12px "PingFang SC", "Microsoft YaHei", Arial, sans-serif; fill: #18070a; }
  .lineRed { fill: none; stroke: #ff5263; stroke-width: 3; stroke-linecap: round; stroke-linejoin: round; }
  .lineAmber { fill: none; stroke: #f6c45b; stroke-width: 2.2; stroke-linecap: round; stroke-linejoin: round; stroke-dasharray: 5 6; }
  .divider { stroke: #252b2e; stroke-width: 1; }
`;

function esc(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function text(x, y, value, cls = "body", anchor = "start") {
  return `<text x="${x}" y="${y}" class="${cls}" text-anchor="${anchor}">${esc(value)}</text>`;
}

function rect(x, y, w, h, cls = "panel", rx = 6) {
  return `<rect x="${x}" y="${y}" width="${w}" height="${h}" rx="${rx}" class="${cls}"/>`;
}

function panel(x, y, w, h, title, cls = "panel") {
  return `${rect(x, y, w, h, cls, 6)}${text(x + 16, y + 28, title, "h3")}`;
}

function chip(x, y, value, variant = "outline", w = 90) {
  if (variant === "solid") {
    return `<rect x="${x}" y="${y}" width="${w}" height="26" rx="13" fill="#ff1f3d" stroke="#ff6574"/>${text(x + w / 2, y + 17, value, "darkChipText", "middle")}`;
  }
  const stroke = variant === "amber" ? "#f6c45b" : variant === "cyan" ? "#60d2ff" : "#ff4357";
  const cls = variant === "amber" ? "amber" : variant === "cyan" ? "cyan" : "red2";
  return `<rect x="${x}" y="${y}" width="${w}" height="26" rx="13" fill="#111417" stroke="${stroke}"/>${text(x + w / 2, y + 17, value, cls, "middle")}`;
}

function header(title, subtitle, active = "持仓") {
  const tabs = ["总览", "持仓", "关注", "研究", "确认", "我的"];
  const tabSvg = tabs.map((tab, i) => {
    const x = 520 + i * 94;
    const isActive = tab === active;
    return `<rect x="${x}" y="124" width="78" height="30" rx="15" fill="${isActive ? "#2c1118" : "#111417"}" stroke="${isActive ? "#ff4357" : "#2a3033"}"/>
      ${text(x + 39, 144, tab, isActive ? "red2" : "body2", "middle")}`;
  }).join("");
  return `
    <rect width="1600" height="1000" class="bg"/>
    <rect x="40" y="34" width="1520" height="920" rx="28" class="window"/>
    <rect x="40" y="34" width="1520" height="66" rx="28" class="topbar"/>
    <circle cx="76" cy="66" r="9" fill="#ff5f57"/><circle cx="104" cy="66" r="9" fill="#ffbd2e"/><circle cx="132" cy="66" r="9" fill="#28c840"/>
    <rect x="540" y="50" width="520" height="34" rx="17" fill="#1a1d20" stroke="#33383c"/>
    ${text(800, 72, "holdings.ai / webapp", "body2", "middle")}
    ${text(78, 128, "AI HOLDINGS · FUTU PRIMARY · TENCENT CHECK", "label")}
    ${text(78, 164, title, "title")}
    ${text(78, 193, subtitle, "body2")}
    ${tabSvg}
    <rect x="1360" y="124" width="150" height="58" rx="5" fill="#111416" stroke="#30353a"/>
    <circle cx="1380" cy="144" r="4" fill="#ff4357"/>
    ${text(1394, 147, "ALL_ASSETS", "label")}
    ${text(1380, 173, "fresh 42s", "red2")}
  `;
}

function metric(x, y, w, label, value, sub, cls = "monoRed") {
  return `${rect(x, y, w, 78, "panel2", 5)}
    ${text(x + 14, y + 23, label, "label")}
    ${text(x + 14, y + 52, value, cls)}
    ${text(x + 14, y + 68, sub, "tiny")}`;
}

function spark(points, x, y, w, h) {
  const min = Math.min(...points);
  const max = Math.max(...points);
  const coords = points.map((p, i) => {
    const px = x + (i * w) / (points.length - 1);
    const py = y + h - ((p - min) / Math.max(1, max - min)) * h;
    return [px, py];
  });
  const d = coords.map(([px, py], i) => `${i === 0 ? "M" : "L"} ${px.toFixed(1)} ${py.toFixed(1)}`).join(" ");
  const area = `${d} L ${x + w} ${y + h} L ${x} ${y + h} Z`;
  return `<path d="${area}" fill="#351018" opacity=".78"/><path d="${d}" class="lineRed"/>`;
}

function tableRow(x, y, w, cells, tones = []) {
  const widths = cells.map((_, i) => {
    if (i === 0) return 120;
    if (i === cells.length - 1) return 120;
    return Math.floor((w - 240) / (cells.length - 2));
  });
  let cursor = x + 14;
  const parts = [`<rect x="${x}" y="${y}" width="${w}" height="42" rx="4" fill="#101315" stroke="#252b2e"/>`];
  cells.forEach((cell, i) => {
    const cls = tones[i] || (i === 0 ? "mono" : "body2");
    parts.push(text(cursor, y + 27, cell, cls));
    cursor += widths[i];
  });
  return `<g>${parts.join("")}</g>`;
}

function optionCard(x, y, title, premium, meta, risk, active = false) {
  return `<g>
    <rect x="${x}" y="${y}" width="240" height="104" rx="5" fill="#101315" stroke="${active ? "#ff4357" : "#2a2f34"}" stroke-width="${active ? 1.8 : 1}"/>
    ${text(x + 14, y + 24, title, "mono")}
    ${text(x + 14, y + 48, meta, "tiny")}
    ${text(x + 14, y + 82, premium, "monoRed")}
    ${text(x + 218, y + 82, risk, risk.includes("高") ? "amber" : "body2", "end")}
  </g>`;
}

function renderPortfolioPage() {
  const curve = [31, 35, 37, 33, 41, 46, 48, 44, 55, 60, 63, 69, 66, 72, 78, 75, 84, 88, 92];
  return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1000" viewBox="0 0 1600 1000">
  <style>${css}</style>
  ${header("持仓工作台", "统一资产视图，股票/ETF 与期权分区；所有数字带来源、时点和确认状态。", "持仓")}

  ${panel(78, 226, 310, 650, "视图与筛选")}
  ${text(102, 270, "Portfolio View", "label")}
  ${chip(102, 286, "全部资产", "solid", 92)}${chip(206, 286, "美股账户", "outline", 92)}
  ${chip(102, 326, "期权策略", "outline", 104)}${chip(220, 326, "A股ETF", "outline", 92)}
  ${text(102, 390, "市场", "label")}${text(102, 418, "美股 / 港股 / A股", "body2")}
  ${text(102, 462, "数据来源", "label")}${text(102, 490, "Futu primary · Tencent check", "red2")}
  ${text(102, 534, "持仓状态", "label")}${text(102, 562, "持仓中 23 · 待确认 2 · 异常 0", "body2")}
  ${text(102, 618, "今日优先处理", "h3")}
  ${text(102, 650, "• TSLA 250P 高注意", "body2")}
  ${text(102, 680, "• NVDA 仓位集中", "body2")}
  ${text(102, 710, "• 2 个交易草稿待确认", "body2")}
  <rect x="102" y="806" width="250" height="40" rx="5" fill="#2c1118" stroke="#ff4357"/>
  ${text(227, 832, "管理 portfolio view", "red2", "middle")}

  ${metric(420, 226, 230, "组合市值", "¥1,248,620", "+1.04% today")}
  ${metric(664, 226, 230, "股票/ETF", "72.4%", "18 个标的")}
  ${metric(908, 226, 230, "期权现金占用", "21.6%", "sell put")}
  ${metric(1152, 226, 230, "待处理", "5", "确认 2 · 纪律 3")}

  ${panel(420, 326, 538, 276, "股票 / ETF 持仓")}
  ${tableRow(444, 374, 490, ["NVDA", "NVIDIA · US", "18.4%", "+¥8,420", "高集中"], ["mono", "body2", "monoSmall", "red", "amber"])}
  ${tableRow(444, 424, 490, ["AAPL", "Apple · US", "11.6%", "+¥1,230", "正常"], ["mono", "body2", "monoSmall", "red", "body2"])}
  ${tableRow(444, 474, 490, ["0700.HK", "腾讯控股", "8.1%", "-¥640", "纪律"], ["mono", "body2", "monoSmall", "amber", "amber"])}
  ${tableRow(444, 524, 490, ["510300", "沪深300ETF", "7.4%", "+¥520", "正常"], ["mono", "body2", "monoSmall", "red", "body2"])}

  ${panel(982, 326, 530, 276, "期权持仓")}
  ${optionCard(1006, 374, "AAPL 185P 2026-05-15", "0.92 / 0.95", "DTE 6 · IV 24.2% · cash secured", "低风险", true)}
  ${optionCard(1248, 374, "NVDA 880P 2026-05-22", "8.10 / 8.35", "DTE 13 · IV 42.1%", "中风险")}
  ${optionCard(1006, 488, "TSLA 250P 2026-05-15", "4.20 / 4.40", "DTE 6 · IV 55.8%", "高注意")}
  ${optionCard(1248, 488, "SPY 570P 2026-05-29", "1.28 / 1.31", "DTE 20 · IV 14.7%", "低风险")}

  ${panel(420, 628, 538, 248, "组合趋势")}
  ${spark(curve, 486, 690, 390, 100)}
  ${text(444, 828, "2026-03-10", "tiny")}${text(906, 828, "2026-05-09  +8.7%", "red2", "end")}

  ${panel(982, 628, 530, 248, "风险雷达")}
  ${text(1010, 674, "仓位集中度", "label")}${text(1280, 674, "38.4% 科技", "amber")}
  ${text(1010, 720, "Sell Put 现金占用", "label")}${text(1280, 720, "21.6%", "red2")}
  ${text(1010, 766, "7 天内到期", "label")}${text(1280, 766, "2 张", "amber")}
  ${text(1010, 812, "数据状态", "label")}${text(1280, 812, "Futu fresh 42s", "red2")}
</svg>`;
}

function renderEquityDetailPage() {
  const curve = [62, 58, 66, 71, 74, 70, 82, 78, 88, 91, 86, 96, 104, 99, 110, 116, 122, 119, 128];
  return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1000" viewBox="0 0 1600 1000">
  <style>${css}</style>
  ${header("股票 / ETF 详情", "围绕单个持仓解释收益、风险、交易纪律和下一步动作。", "持仓")}

  ${panel(78, 226, 380, 650, "NVDA · NVIDIA · US")}
  ${text(104, 276, "持仓占比", "label")}${text(382, 276, "18.4%", "monoRed", "end")}
  ${text(104, 326, "市值", "label")}${text(382, 326, "¥229,680", "monoRed", "end")}
  ${text(104, 376, "成本", "label")}${text(382, 376, "$782.40", "mono", "end")}
  ${text(104, 426, "浮盈亏", "label")}${text(382, 426, "+¥8,420", "red2", "end")}
  ${text(104, 476, "数据源", "label")}${text(382, 476, "Futu fresh 42s", "red2", "end")}
  ${text(104, 544, "纪律命中", "h3")}
  ${text(104, 580, "• 科技仓位集中：NVDA + QQQ 38.4%", "body2")}
  ${text(104, 612, "• 财报前不追加高波动仓位", "body2")}
  ${text(104, 644, "• 止盈线：+30% 分批减仓提醒", "body2")}
  <rect x="104" y="788" width="330" height="42" rx="5" fill="#2c1118" stroke="#ff4357"/>
  ${text(269, 815, "生成持仓分析", "red2", "middle")}

  ${panel(486, 226, 640, 272, "价格与收益路径")}
  ${spark(curve, 550, 300, 500, 120)}
  ${text(510, 454, "买入成本 $782.40", "tiny")}${text(1070, 454, "现价 $914.20", "red2", "end")}

  ${panel(1150, 226, 340, 272, "止盈 / 止损策略")}
  ${text(1176, 276, "止盈区", "label")}${text(1394, 276, "$960 / $1020", "red2", "end")}
  ${text(1176, 326, "止损线", "label")}${text(1394, 326, "$820", "amber", "end")}
  ${text(1176, 376, "加仓条件", "label")}${text(1394, 376, "回踩 20MA", "body2", "end")}
  ${text(1176, 426, "动作上限", "label")}${text(1394, 426, "analysis_only", "tiny", "end")}

  ${panel(486, 526, 640, 350, "交易时间线")}
  ${tableRow(510, 578, 590, ["2026-03-12", "买入", "12 股", "$782.4", "manual"], ["tiny", "body2", "monoSmall", "red2", "tiny"])}
  ${tableRow(510, 628, 590, ["2026-04-09", "加仓", "6 股", "$835.1", "Futu"], ["tiny", "body2", "monoSmall", "red2", "tiny"])}
  ${tableRow(510, 678, 590, ["2026-05-03", "规则提醒", "科技仓位", "38.4%", "discipline"], ["tiny", "amber", "body2", "amber", "tiny"])}
  ${tableRow(510, 728, 590, ["2026-05-09", "分析", "止盈区更新", "$960", "AI"], ["tiny", "body2", "body2", "red2", "tiny"])}

  ${panel(1150, 526, 340, 350, "页面内 AI")}
  ${text(1176, 574, "可执行入口", "label")}
  ${text(1176, 610, "• 解释今日变化", "body2")}
  ${text(1176, 642, "• 生成止盈止损建议", "body2")}
  ${text(1176, 674, "• 检查交易纪律", "body2")}
  ${text(1176, 706, "• 发起个股深研", "body2")}
  <rect x="1176" y="792" width="286" height="42" rx="5" fill="#2c1118" stroke="#ff4357"/>
  ${text(1319, 819, "发起 Hermes 深研", "red2", "middle")}
</svg>`;
}

function renderSellPutPage() {
  return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1000" viewBox="0 0 1600 1000">
  <style>${css}</style>
  ${header("Sell Put 工作台", "期权产品单独成页，核心关注现金占用、DTE、IV、assignment risk 和纪律约束。", "持仓")}

  ${metric(78, 226, 250, "现金可用", "¥398,200", "Futu primary")}
  ${metric(346, 226, 250, "Sell Put 占用", "21.6%", "上限 30%")}
  ${metric(614, 226, 250, "7 天内到期", "2 张", "TSLA / AAPL")}
  ${metric(882, 226, 250, "高注意", "1", "TSLA 250P")}
  ${metric(1150, 226, 250, "候选池", "18", "愿接股标的")}

  ${panel(78, 334, 600, 272, "当前 Sell Put 持仓")}
  ${optionCard(104, 382, "AAPL 185P 2026-05-15", "0.92 / 0.95", "DTE 6 · delta -0.22 · cash 18.5k", "低风险", true)}
  ${optionCard(374, 382, "NVDA 880P 2026-05-22", "8.10 / 8.35", "DTE 13 · delta -0.31 · cash 88k", "中风险")}
  ${optionCard(104, 496, "TSLA 250P 2026-05-15", "4.20 / 4.40", "DTE 6 · delta -0.39 · cash 25k", "高注意")}
  ${optionCard(374, 496, "SPY 570P 2026-05-29", "1.28 / 1.31", "DTE 20 · delta -0.18 · cash 57k", "低风险")}

  ${panel(706, 334, 360, 272, "资金占用结构")}
  ${text(732, 382, "现金担保", "label")}${text(1010, 382, "¥188,500", "red2", "end")}
  ${text(732, 430, "保证金占用", "label")}${text(1010, 430, "¥82,100", "red2", "end")}
  ${text(732, 478, "剩余现金", "label")}${text(1010, 478, "¥127,600", "body2", "end")}
  ${text(732, 526, "纪律上限", "label")}${text(1010, 526, "30%", "amber", "end")}
  <rect x="732" y="556" width="278" height="18" rx="9" fill="#241014" stroke="#563039"/>
  <rect x="732" y="556" width="202" height="18" rx="9" fill="#ff1f3d"/>

  ${panel(1094, 334, 396, 272, "到期梯队")}
  ${text(1120, 384, "DTE 0-7", "label")}${text(1410, 384, "2 张 · 高注意", "amber", "end")}
  ${text(1120, 432, "DTE 8-21", "label")}${text(1410, 432, "4 张", "red2", "end")}
  ${text(1120, 480, "DTE 22-45", "label")}${text(1410, 480, "6 张", "body2", "end")}
  ${text(1120, 528, "DTE 45+", "label")}${text(1410, 528, "0 张", "tiny", "end")}
  ${text(1120, 568, "下一个动作：TSLA 250P 到期前确认 roll / 平仓 / 接股。", "body2")}

  ${panel(78, 636, 708, 240, "候选 Strike 对比")}
  ${tableRow(104, 684, 660, ["标的", "Strike", "DTE", "IV", "Premium", "纪律"], ["label", "label", "label", "label", "label", "label"])}
  ${tableRow(104, 734, 660, ["AAPL", "180", "13", "25.2%", "0.62", "通过"], ["mono", "body2", "body2", "red2", "red2", "green"])}
  ${tableRow(104, 784, 660, ["NVDA", "850", "20", "44.8%", "6.20", "集中"], ["mono", "body2", "body2", "red2", "red2", "amber"])}
  ${tableRow(104, 834, 660, ["TSLA", "230", "13", "58.4%", "3.10", "高波动"], ["mono", "body2", "body2", "amber", "red2", "amber"])}

  ${panel(818, 636, 672, 240, "交易纪律与确认")}
  ${text(846, 690, "• 只卖愿意接股的标的：AAPL / SPY 通过，TSLA 需要原因。", "body2")}
  ${text(846, 726, "• 财报前不卖 put：NVDA 进入风险提示，不直接生成执行清单。", "body2")}
  ${text(846, 762, "• 现金占用上限 30%：当前 21.6%，新增候选需模拟占用。", "body2")}
  <rect x="846" y="810" width="280" height="42" rx="5" fill="#2c1118" stroke="#ff4357"/>
  ${text(986, 837, "生成交易草稿", "red2", "middle")}
  <rect x="1148" y="810" width="280" height="42" rx="5" fill="#111417" stroke="#f6c45b"/>
  ${text(1288, 837, "进入确认中心", "amber", "middle")}
</svg>`;
}

function renderConfirmationPage() {
  return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1000" viewBox="0 0 1600 1000">
  <style>${css}</style>
  ${header("确认中心", "所有会改变事实或高风险判断的动作，在这里完成结构化确认和审计留痕。", "确认")}

  ${panel(78, 226, 430, 650, "待处理")}
  ${chip(102, 266, "全部 5", "solid", 74)}${chip(188, 266, "交易", "outline", 74)}${chip(274, 266, "OCR", "outline", 74)}${chip(360, 266, "规则", "amber", 74)}
  <rect x="102" y="322" width="382" height="96" rx="6" fill="#2c1118" stroke="#ff4357"/>
  ${text(122, 352, "TSLA 250P 持有策略确认", "h3")}
  ${text(122, 382, "高注意 · Sell Put · DTE 6", "amber")}
  ${text(122, 404, "来源：期权工作台 / RiskReviewTools", "tiny")}
  <rect x="102" y="432" width="382" height="76" rx="6" fill="#101315" stroke="#2a2f34"/>
  ${text(122, 462, "OCR 交易截图字段修正", "body")}
  ${text(122, 490, "AAPL 买入 10 股 · 价格低置信", "tiny")}
  <rect x="102" y="522" width="382" height="76" rx="6" fill="#101315" stroke="#2a2f34"/>
  ${text(122, 552, "NVDA 加仓草稿", "body")}
  ${text(122, 580, "命中科技仓位集中纪律", "tiny")}
  <rect x="102" y="612" width="382" height="76" rx="6" fill="#101315" stroke="#2a2f34"/>
  ${text(122, 642, "批量导入 12 条成交", "body")}
  ${text(122, 670, "CSV 预览 · 2 条重复候选", "tiny")}

  ${panel(536, 226, 954, 232, "确认对象")}
  ${text(564, 278, "TSLA 250P 2026-05-15 · 继续持有 / roll / 平仓确认", "h2")}
  ${text(564, 318, "对象类型", "label")}${text(674, 318, "option_position_action", "monoSmall")}
  ${text(564, 354, "风险等级", "label")}${text(674, 354, "high_attention", "amber")}
  ${text(564, 390, "状态", "label")}${text(674, 390, "pending_user_confirmation", "red2")}
  ${text(1020, 318, "数据时点", "label")}${text(1140, 318, "Futu fresh 42s", "red2")}
  ${text(1020, 354, "策略纪律", "label")}${text(1140, 354, "高波动 + DTE 6", "amber")}
  ${text(1020, 390, "动作上限", "label")}${text(1140, 390, "生成草稿，不自动下单", "body2")}

  ${panel(536, 484, 454, 392, "结构化明细")}
  ${text(564, 532, "合约", "label")}${text(700, 532, "TSLA260515P00250000", "monoSmall")}
  ${text(564, 578, "持仓", "label")}${text(700, 578, "Short Put · 1 张", "body2")}
  ${text(564, 624, "权利金", "label")}${text(700, 624, "4.20 / 4.40", "red2")}
  ${text(564, 670, "现金占用", "label")}${text(700, 670, "¥25,000", "red2")}
  ${text(564, 716, "建议动作", "label")}${text(700, 716, "评估 roll 或平仓，不建议被动等待", "body2")}
  ${text(564, 762, "用户备注", "label")}
  <rect x="564" y="780" width="390" height="54" rx="5" fill="#0f1112" stroke="#2a3033"/>
  ${text(582, 814, "输入 override 原因或执行备注...", "tiny")}

  ${panel(1020, 484, 470, 392, "证据与审计")}
  ${text(1048, 532, "数据来源", "label")}${text(1180, 532, "Futu option chain + position", "body2")}
  ${text(1048, 578, "规则命中", "label")}${text(1180, 578, "Sell Put 高波动 / DTE 过近", "amber")}
  ${text(1048, 624, "模型", "label")}${text(1180, 624, "MiniMax M2.7 summary", "body2")}
  ${text(1048, 670, "RiskReview", "label")}${text(1180, 670, "required", "red2")}
  <rect x="1048" y="736" width="190" height="44" rx="5" fill="#2c1118" stroke="#ff4357"/>
  ${text(1143, 764, "确认并记录", "red2", "middle")}
  <rect x="1258" y="736" width="190" height="44" rx="5" fill="#111417" stroke="#f6c45b"/>
  ${text(1353, 764, "拒绝 / 退回", "amber", "middle")}
  ${text(1048, 830, "确认只写系统事实和执行清单，不代表自动下单授权。", "tiny")}
</svg>`;
}

async function writePng(name, svg) {
  const svgPath = path.join(outDir, `${name}.svg`);
  const pngPath = path.join(outDir, `${name}.png`);
  fs.writeFileSync(svgPath, svg);
  await sharp(Buffer.from(svg)).png().toFile(pngPath);
  console.log(pngPath);
}

async function main() {
  await writePng("webapp-core-portfolio-red", renderPortfolioPage());
  await writePng("webapp-core-equity-detail-red", renderEquityDetailPage());
  await writePng("webapp-core-sellput-red", renderSellPutPage());
  await writePng("webapp-core-confirmation-red", renderConfirmationPage());
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
