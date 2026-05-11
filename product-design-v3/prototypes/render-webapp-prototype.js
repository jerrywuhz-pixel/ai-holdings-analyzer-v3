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
  .mutedPanel { fill: #0f1213; stroke: #242a2d; stroke-width: 1; }
  .active { stroke: #33f24f; stroke-width: 1.8; }
  .greenFill { fill: #102415; }
  .title { font: 700 32px "PingFang SC", "Microsoft YaHei", Arial, sans-serif; fill: #f3f6f6; }
  .h1 { font: 700 25px "PingFang SC", "Microsoft YaHei", Arial, sans-serif; fill: #f5f7f7; }
  .h2 { font: 700 18px "PingFang SC", "Microsoft YaHei", Arial, sans-serif; fill: #f1f5f3; }
  .h3 { font: 700 15px "PingFang SC", "Microsoft YaHei", Arial, sans-serif; fill: #dce2e0; }
  .label { font: 650 12px "PingFang SC", "Microsoft YaHei", Arial, sans-serif; fill: #8e9898; }
  .tiny { font: 500 11px "PingFang SC", "Microsoft YaHei", Arial, sans-serif; fill: #788282; }
  .body { font: 500 14px "PingFang SC", "Microsoft YaHei", Arial, sans-serif; fill: #d6ddda; }
  .body2 { font: 500 13px "PingFang SC", "Microsoft YaHei", Arial, sans-serif; fill: #aeb8b5; }
  .green { fill: #48f25f; }
  .green2 { fill: #78ff83; }
  .amber { fill: #f6c45b; }
  .red { fill: #ff6666; }
  .cyan { fill: #60d2ff; }
  .violet { fill: #a88cff; }
  .lineGreen { fill: none; stroke: #67f06c; stroke-width: 3; stroke-linecap: round; stroke-linejoin: round; }
  .lineCyan { fill: none; stroke: #60d2ff; stroke-width: 2.4; stroke-linecap: round; stroke-linejoin: round; }
  .dash { fill: none; stroke: #8d865c; stroke-width: 1.4; stroke-dasharray: 6 7; opacity: .9; }
  .divider { stroke: #252b2e; stroke-width: 1; }
  .mono { font: 650 14px "SFMono-Regular", "Cascadia Mono", Menlo, monospace; fill: #f2f5f2; }
  .monoGreen { font: 800 24px "SFMono-Regular", "Cascadia Mono", Menlo, monospace; fill: #48f25f; }
  .monoSmall { font: 650 12px "SFMono-Regular", "Cascadia Mono", Menlo, monospace; fill: #9ba7a3; }
  .chipText { font: 700 12px "PingFang SC", "Microsoft YaHei", Arial, sans-serif; fill: #071007; }
  .nodeTitle { font: 800 18px "PingFang SC", "Microsoft YaHei", Arial, sans-serif; fill: #f2f6f5; }
  .nodeItem { font: 550 13px "PingFang SC", "Microsoft YaHei", Arial, sans-serif; fill: #aeb8b5; }
  .nodeMeta { font: 700 11px "PingFang SC", "Microsoft YaHei", Arial, sans-serif; fill: #48f25f; }
`;

const redCss = css + `
  .active { stroke: #ff4357; stroke-width: 1.8; }
  .green { fill: #ff4357; }
  .green2 { fill: #ff7a88; }
  .lineGreen { fill: none; stroke: #ff5263; stroke-width: 3; stroke-linecap: round; stroke-linejoin: round; }
  .monoGreen { font: 800 24px "SFMono-Regular", "Cascadia Mono", Menlo, monospace; fill: #ff4357; }
  .nodeMeta { font: 700 11px "PingFang SC", "Microsoft YaHei", Arial, sans-serif; fill: #ff4357; }
`;

function applyRedTheme(svg) {
  return svg
    .replace(`<style>${css}</style>`, `<style>${redCss}</style>`)
    .replaceAll("#48f25f", "#ff4357")
    .replaceAll("#78ff83", "#ff7a88")
    .replaceAll("#67f06c", "#ff5263")
    .replaceAll("#34f253", "#ff4357")
    .replaceAll("#132016", "#2a1016")
    .replaceAll("#172b19", "#2c1118")
    .replaceAll("#102415", "#261018")
    .replaceAll("#11391c", "#351018")
    .replaceAll("#0df525", "#ff1f3d")
    .replaceAll("#3cff62", "#ff6574")
    .replaceAll("#304036", "#563039")
    .replaceAll("#354138", "#58323b");
}

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

function chip(x, y, value, color = "#48f25f", w = 84) {
  return `<rect x="${x}" y="${y}" width="${w}" height="24" rx="12" fill="${color}"/>${text(x + w / 2, y + 16, value, "chipText", "middle")}`;
}

function panel(x, y, w, h, title, cls = "panel") {
  return `${rect(x, y, w, h, cls, 5)}${text(x + 16, y + 26, title, "h3")}`;
}

function spark(points, x, y, w, h, cls = "lineGreen", fill = true) {
  const xs = points.map((_, i) => x + (i * w) / (points.length - 1));
  const min = Math.min(...points);
  const max = Math.max(...points);
  const ys = points.map((p) => y + h - ((p - min) / Math.max(1, max - min)) * h);
  const d = points.map((_, i) => `${i === 0 ? "M" : "L"} ${xs[i].toFixed(1)} ${ys[i].toFixed(1)}`).join(" ");
  const area = `${d} L ${x + w} ${y + h} L ${x} ${y + h} Z`;
  return `${fill ? `<path d="${area}" fill="#11391c" opacity=".62"/>` : ""}<path d="${d}" class="${cls}"/>`;
}

function navPill(x, label, active = false) {
  const fill = active ? "#172b19" : "#111417";
  const stroke = active ? "#34f253" : "#2a3033";
  const colorClass = active ? "green2" : "body2";
  return `<rect x="${x}" y="132" width="86" height="30" rx="15" fill="${fill}" stroke="${stroke}"/>${text(x + 43, 152, label, colorClass, "middle")}`;
}

function metricCard(x, y, w, label, value, sub, accent = "green") {
  return `${rect(x, y, w, 92, "panel", 4)}
    ${text(x + 16, y + 24, label, "label")}
    ${text(x + 16, y + 57, value, "monoGreen")}
    ${text(x + 16, y + 78, sub, "tiny")}`;
}

function optionCard(x, y, idx, title, strike, dte, premium, risk, active = false) {
  return `<g>
    <rect x="${x}" y="${y}" width="278" height="108" rx="4" class="${active ? "panel active" : "panel2"}"/>
    ${text(x + 14, y + 22, `#${idx}`, "green")}
    ${text(x + 244, y + 22, "PUT", "green", "end")}
    ${text(x + 14, y + 45, title, "mono")}
    ${text(x + 14, y + 66, dte, "tiny")}
    ${text(x + 244, y + 66, strike, "tiny", "end")}
    ${text(x + 14, y + 92, premium, "monoGreen")}
    ${text(x + 244, y + 92, risk, risk.includes("高") ? "amber" : "body2", "end")}
  </g>`;
}

function row(x, y, symbol, name, pos, pnl, risk, color = "green") {
  return `<g>
    <rect x="${x}" y="${y}" width="540" height="43" rx="4" fill="#101315" stroke="#252b2e"/>
    ${text(x + 14, y + 27, symbol, "mono")}
    ${text(x + 116, y + 27, name, "body2")}
    ${text(x + 284, y + 27, pos, "monoSmall", "end")}
    ${text(x + 390, y + 27, pnl, color, "end")}
    ${text(x + 522, y + 27, risk, "tiny", "end")}
  </g>`;
}

function renderPrototypeSvg() {
  const curve1 = [28, 36, 33, 41, 39, 44, 47, 51, 46, 58, 62, 59, 64, 68, 70, 67, 74, 78, 75, 83, 86, 91, 88, 94, 97];
  const curve2 = [76, 72, 66, 55, 49, 44, 46, 52, 48, 55, 64, 70, 73, 69, 76, 80, 77, 83, 86, 90, 88, 85, 89, 84, 81];
  const dash = [55, 55, 54, 53, 53, 54, 55, 57, 58, 59, 60, 60, 61, 62, 62, 63, 64, 64, 65, 66];

  return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="1800" height="1100" viewBox="0 0 1800 1100">
  <style>${css}</style>
  <rect width="1800" height="1100" class="bg"/>
  <rect x="44" y="38" width="1712" height="1024" rx="30" class="window"/>
  <rect x="44" y="38" width="1712" height="66" rx="30" class="topbar"/>
  <circle cx="78" cy="70" r="9" fill="#ff5f57"/><circle cx="108" cy="70" r="9" fill="#ffbd2e"/><circle cx="138" cy="70" r="9" fill="#28c840"/>
  <rect x="190" y="53" width="84" height="34" rx="17" fill="#1b1e21" stroke="#2d3337"/>
  ${text(232, 76, "◀  ▶", "tiny", "middle")}
  <rect x="562" y="51" width="676" height="36" rx="18" fill="#1a1d20" stroke="#33383c"/>
  ${text(900, 75, "holdings.ai / dashboard", "body2", "middle")}
  <rect x="1570" y="51" width="120" height="36" rx="18" fill="#1a1d20" stroke="#33383c"/>
  ${text(1630, 75, "share  +", "tiny", "middle")}

  ${text(82, 132, "AI HOLDINGS · FUTU PRIMARY · TENCENT CHECK", "label")}
  ${text(82, 166, "AI 持仓系统 3.0", "title")}
  ${text(82, 194, "移动端优先的投资工作台：多 portfolio view、股票/ETF 持仓、期权 sell put 资金占用、确认中心。", "body2")}
  ${navPill(540, "总览", true)}
  ${navPill(636, "持仓")}
  ${navPill(732, "关注")}
  ${navPill(828, "研究")}
  ${navPill(924, "确认")}
  ${navPill(1020, "我的")}
  <rect x="1536" y="126" width="170" height="66" rx="4" fill="#111416" stroke="#30353a"/>
  <circle cx="1558" cy="148" r="4" fill="#48f25f"/>
  ${text(1570, 150, "LIVE ACCOUNT", "label")}
  ${text(1554, 176, "ALL ASSETS", "monoGreen")}

  ${panel(82, 226, 430, 244, "资产信息")}
  ${text(104, 264, "当前视图", "label")}${text(104, 292, "全部资产 / ALL_ASSETS", "mono")}
  ${text(104, 326, "总资产", "label")}${text(490, 326, "¥1,248,620", "monoGreen", "end")}
  ${text(104, 360, "今日盈亏", "label")}${text(250, 360, "+¥12,840", "green", "end")}${text(270, 360, "equity +9.2k / options +3.6k", "tiny")}
  ${text(104, 394, "现金/保证金", "label")}${text(250, 394, "31.8%", "monoGreen", "end")}${text(270, 394, "sell put cash secured", "tiny")}
  ${text(104, 428, "待处理", "label")}${text(250, 428, "5", "amber", "end")}${text(270, 428, "确认 2 · 纪律 3", "tiny")}

  ${panel(82, 486, 430, 138, "账户与数据状态")}
  ${text(104, 524, "登录", "label")}${text(160, 524, "Supabase Auth · jerry@***", "body2")}
  ${text(104, 556, "微信", "label")}${chip(160, 538, "BOUND", "#48f25f", 76)}${text(250, 556, "openclaw-weixin / 主账号", "body2")}
  ${text(104, 590, "数据", "label")}${text(160, 590, "Futu fresh 42s · Tencent check ok", "green")}

  ${panel(82, 640, 430, 114, "快捷操作")}
  <rect x="104" y="680" width="178" height="38" rx="4" fill="#101315" stroke="#304036"/>${text(193, 704, "录入交易", "body", "middle")}
  <rect x="292" y="680" width="178" height="38" rx="4" fill="#101315" stroke="#304036"/>${text(381, 704, "发起深研", "body", "middle")}
  ${text(104, 738, "富途同步从数据/账户页进入，主界面只展示 freshness。", "tiny")}

  ${panel(82, 768, 430, 250, "交易纪律 / 风险偏好")}
  ${text(104, 807, "规则命中", "label")}${text(190, 807, "3", "amber")}${text(216, 807, "条需关注", "body2")}
  ${text(104, 841, "· 不买中概股：命中 BABA 关注项", "body2")}
  ${text(104, 873, "· 盘前盘后不下单：当前美股盘前", "body2")}
  ${text(104, 905, "· Sell Put 现金占用不得超过 12%", "body2")}
  <rect x="104" y="940" width="386" height="46" rx="4" fill="#101315" stroke="#304036"/>
  ${text(124, 968, "打开规则管理", "green")}
  ${text(472, 968, "→", "green", "end")}

  ${panel(536, 226, 1178, 154, "今日持仓结论")}
  ${text(560, 270, "组合状态：风险可控，但 NVDA 与 QQQ 暴露合计 38.4%，本周不建议继续放大科技仓位。", "h2")}
  ${text(560, 306, "• 核心持仓优先检查：科技仓位集中、TSLA 250P 接近纪律阈值、7 天内到期期权 2 张。", "body")}
  ${text(560, 338, "• 数据状态仅作为底层信号展示：Futu fresh 42s，Tencent check ok；同步入口移至数据/账户页。", "body")}

  ${panel(536, 398, 574, 280, "股票 / ETF 持仓")}
  ${row(558, 440, "NVDA", "NVIDIA · US", "18.4%", "+¥8,420", "高集中", "green")}
  ${row(558, 488, "AAPL", "Apple · US", "11.6%", "+¥1,230", "正常", "green")}
  ${row(558, 536, "0700.HK", "腾讯控股 · HK", "8.1%", "-¥640", "纪律关注", "amber")}
  ${row(558, 584, "510300", "沪深300ETF · A", "7.4%", "+¥520", "正常", "green")}
  <rect x="558" y="632" width="540" height="30" rx="4" fill="#101315" stroke="#252b2e"/>
  ${text(578, 652, "查看全部持仓和来源明细", "green")}
  ${text(1078, 652, "→", "green", "end")}

  ${panel(1130, 398, 584, 280, "Sell Put 监控 / 资金占用")}
  ${optionCard(1152, 440, 1, "AAPL260515P00185000", "Strike 185", "DTE 6 · IV 24.2%", "0.92 / 0.95", "低风险", true)}
  ${optionCard(1440, 440, 2, "NVDA260522P00880000", "Strike 880", "DTE 13 · IV 42.1%", "8.10 / 8.35", "中风险")}
  ${optionCard(1152, 556, 3, "TSLA260515P00250000", "Strike 250", "DTE 6 · IV 55.8%", "4.20 / 4.40", "高注意")}
  ${optionCard(1440, 556, 4, "SPY260529P00570000", "Strike 570", "DTE 20 · IV 14.7%", "1.28 / 1.31", "低风险")}

  ${panel(536, 700, 574, 226, "组合净值 / 近 60 日")}
  ${spark(curve1, 610, 760, 420, 118)}
  ${text(562, 900, "2026-03-10", "tiny")}${text(1036, 900, "2026-05-09", "tiny", "end")}
  ${text(562, 738, "portfolio NAV", "tiny")}${text(1036, 738, "+8.7%", "green", "end")}

  ${panel(1130, 700, 584, 226, "期权风险 / DTE 与现金占用")}
  ${spark(curve2, 1200, 760, 420, 118, "lineGreen")}
  ${spark(dash, 1200, 778, 420, 90, "dash", false)}
  ${text(1156, 738, "sell put exposure", "tiny")}${text(1620, 738, "cash used 21.6%", "amber", "end")}
  ${text(1156, 900, "DTE 0-7", "tiny")}${text(1620, 900, "DTE 30+", "tiny", "end")}
</svg>`;
}

function node(x, y, w, h, title, meta, items, accent = "#48f25f") {
  const itemLines = items.map((item, idx) => text(x + 22, y + 66 + idx * 24, `• ${item}`, "nodeItem")).join("");
  return `<g>
    <rect x="${x}" y="${y}" width="${w}" height="${h}" rx="8" fill="#121518" stroke="#30373a" stroke-width="1.2"/>
    <rect x="${x}" y="${y}" width="6" height="${h}" rx="3" fill="${accent}"/>
    ${text(x + 22, y + 30, title, "nodeTitle")}
    ${text(x + 22, y + 50, meta, "nodeMeta")}
    ${itemLines}
  </g>`;
}

function connector(x1, y1, x2, y2) {
  return `<path d="M ${x1} ${y1} C ${x1} ${Math.round((y1 + y2) / 2)}, ${x2} ${Math.round((y1 + y2) / 2)}, ${x2} ${y2}" fill="none" stroke="#344045" stroke-width="1.4"/>`;
}

function renderSiteMapSvg() {
  return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="1050" viewBox="0 0 1600 1050">
  <style>${css}</style>
  <rect width="1600" height="1050" fill="#050606"/>
  <rect x="42" y="36" width="1516" height="978" rx="28" fill="#0b0d0e" stroke="#303538"/>
  ${text(82, 92, "AI 持仓系统 3.0 WebApp 站点层级", "title")}
  ${text(82, 124, "移动端 5 个主 Tab；桌面端扩展为侧边导航。绑定、授权、同步、复杂确认均在 WebApp 完成。", "body2")}
  <rect x="604" y="160" width="392" height="78" rx="10" fill="#132016" stroke="#48f25f" stroke-width="1.6"/>
  ${text(800, 191, "WebApp Shell", "nodeTitle", "middle")}
  ${text(800, 216, "Supabase Auth · Tenant Context · Top Status Bar", "nodeItem", "middle")}

  ${connector(800, 238, 225, 300)}
  ${connector(800, 238, 520, 300)}
  ${connector(800, 238, 815, 300)}
  ${connector(800, 238, 1110, 300)}
  ${connector(800, 238, 1405, 300)}

  ${node(82, 300, 286, 190, "总览 Dashboard", "P0 · 首屏", [
    "资产摘要 / 今日盈亏",
    "数据新鲜度 / 市场状态",
    "风险雷达 / 今日行动",
    "页面内 AI 解释入口"
  ])}
  ${node(377, 300, 286, 190, "持仓 Portfolio", "P0 · 核心工作台", [
    "多 portfolio_view",
    "股票/ETF 持仓",
    "期权 sell put 持仓",
    "来源 / 时间线 / 明细"
  ], "#60d2ff")}
  ${node(672, 300, 286, 190, "关注 Follow", "P0 · 机会池", [
    "可能买入标的",
    "sell put 候选条件",
    "价格 / IV / 事件提醒",
    "转换为持仓或归档"
  ], "#a88cff")}
  ${node(967, 300, 286, 190, "研究 Research", "P0 · Hermes 长任务", [
    "个股深研",
    "期权策略研究",
    "清仓复盘报告",
    "任务进度与历史归档"
  ], "#f6c45b")}
  ${node(1262, 300, 286, 190, "我的 / 数据", "P0 · 控制台", [
    "微信 claw 绑定",
    "富途授权与同步",
    "数据来源与质量",
    "规则纪律 / 通知策略"
  ], "#ff6b6b")}

  ${connector(520, 490, 520, 565)}
  ${connector(1405, 490, 1210, 565)}
  ${connector(815, 490, 815, 565)}
  ${connector(1110, 490, 1110, 565)}
  ${connector(225, 490, 390, 565)}

  ${node(82, 565, 286, 190, "确认 / 消息中心", "P0 · 全局 Badge", [
    "交易草稿确认",
    "OCR 多字段修正",
    "批量导入预览",
    "数据冲突 / 风险 override"
  ], "#48f25f")}
  ${node(377, 565, 286, 190, "交易与导入", "P0/P1", [
    "手工交易录入",
    "自然语言结构化预览",
    "图片 OCR",
    "CSV / 对账单导入"
  ], "#60d2ff")}
  ${node(672, 565, 286, 190, "清仓 List Views", "P0/P1 · 复盘", [
    "历史持仓查询",
    "已实现盈亏",
    "退出原因 / 复盘标签",
    "二次买入条件"
  ], "#a88cff")}
  ${node(967, 565, 286, 190, "报告 Artifact", "P0 · 深链", [
    "深研报告",
    "策略说明",
    "图表和数据 lineage",
    "微信摘要跳转"
  ], "#f6c45b")}
  ${node(1262, 565, 286, 190, "设置 Settings", "P0/P1", [
    "账号资料 / 安全",
    "Quiet hours",
    "默认 portfolio_view",
    "导出 / 删除 / 隐私"
  ], "#ff6b6b")}

  <rect x="82" y="835" width="1466" height="112" rx="8" fill="#101315" stroke="#2a3235"/>
  ${text(110, 872, "P0 导航约束", "h2")}
  ${text(110, 908, "移动端底部 Tab：总览、持仓、关注、研究、我的。确认中心用全局 badge 和深链进入，不占底部导航位。", "body")}
  ${text(110, 938, "桌面端可展开为：总览、持仓、关注、清仓、研究、确认/消息、数据/账户、规则/纪律、设置。", "body2")}
</svg>`;
}

function mobileMetric(x, y, label, value, sub) {
  return `<g>
    <rect x="${x}" y="${y}" width="184" height="82" rx="8" fill="#141619" stroke="#30353a"/>
    ${text(x + 14, y + 24, label, "label")}
    ${text(x + 14, y + 54, value, "monoGreen")}
    ${text(x + 14, y + 72, sub, "tiny")}
  </g>`;
}

function mobileRow(y, symbol, name, weight, pnl, tone = "green") {
  return `<g>
    <rect x="30" y="${y}" width="370" height="48" rx="7" fill="#101315" stroke="#252b2e"/>
    ${text(46, y + 28, symbol, "mono")}
    ${text(128, y + 28, name, "body2")}
    ${text(300, y + 28, weight, "monoSmall", "end")}
    ${text(384, y + 28, pnl, tone, "end")}
  </g>`;
}

function renderMobileRedSvg() {
  const nav = [28, 108, 188, 268, 348]
    .map((x, i) => {
      const labels = ["总览", "持仓", "关注", "研究", "我的"];
      const active = i === 0;
      return `<g>
        <rect x="${x}" y="860" width="58" height="40" rx="12" fill="${active ? "#2c1118" : "#111417"}" stroke="${active ? "#ff4357" : "#2a3033"}"/>
        ${text(x + 29, 885, labels[i], active ? "green2" : "tiny", "middle")}
      </g>`;
    })
    .join("");

  const curve = [28, 32, 29, 37, 42, 39, 46, 49, 45, 56, 62, 60, 66, 71, 69, 76, 82, 80, 87, 92];

  return `<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="430" height="932" viewBox="0 0 430 932">
  <style>${redCss}</style>
  <rect width="430" height="932" fill="#050606"/>
  <rect x="10" y="10" width="410" height="912" rx="34" fill="#0b0d0e" stroke="#303538"/>
  <rect x="156" y="24" width="118" height="24" rx="12" fill="#050606"/>
  ${text(32, 70, "AI HOLDINGS · FUTU", "label")}
  ${text(32, 104, "AI 持仓系统 3.0", "h1")}
  <rect x="286" y="74" width="112" height="36" rx="18" fill="#2c1118" stroke="#ff4357"/>
  ${text(342, 97, "ALL_ASSETS", "green2", "middle")}

  <rect x="30" y="126" width="370" height="58" rx="10" fill="#141619" stroke="#30353a"/>
  ${text(48, 153, "当前视图", "label")}
  ${text(48, 173, "全部资产 / 美股账户 / 期权策略账户", "body2")}
  ${text(384, 157, "fresh 42s", "green", "end")}

  ${mobileMetric(30, 198, "总资产", "¥1,248,620", "+1.04% today")}
  ${mobileMetric(216, 198, "今日盈亏", "+¥12,840", "权益 +9.2k")}
  ${mobileMetric(30, 290, "现金/保证金", "31.8%", "sell put cash")}
  ${mobileMetric(216, 290, "待处理", "5", "确认 2 · 纪律 3")}

  <rect x="30" y="390" width="370" height="124" rx="10" fill="#141619" stroke="#30353a"/>
  ${text(48, 420, "今日持仓结论", "h3")}
  ${text(48, 448, "组合风险可控，NVDA 与 QQQ 暴露偏高。", "body")}
  ${text(48, 474, "Sell Put 现金占用 21.6%，TSLA 250P", "body2")}
  ${text(48, 498, "接近纪律阈值，需要进入确认中心。", "body2")}
  <rect x="282" y="407" width="94" height="34" rx="6" fill="#2c1118" stroke="#ff4357"/>
  ${text(329, 429, "解释", "green2", "middle")}

  <rect x="30" y="528" width="370" height="122" rx="10" fill="#141619" stroke="#30353a"/>
  ${text(48, 558, "重点持仓", "h3")}
  ${mobileRow(574, "NVDA", "NVIDIA · US", "18.4%", "+¥8,420")}
  ${text(48, 636, "AAPL 11.6%  +¥1,230   ·   0700.HK 纪律关注", "tiny")}

  <rect x="30" y="664" width="370" height="78" rx="10" fill="#141619" stroke="#30353a"/>
  ${text(48, 694, "Sell Put 资金占用", "h3")}
  ${text(48, 722, "现金占用 21.6% · 7 天内到期 2 张 · TSLA 高注意", "body2")}
  ${text(376, 694, "查看", "green", "end")}

  <rect x="30" y="756" width="370" height="90" rx="10" fill="#141619" stroke="#30353a"/>
  ${text(48, 786, "组合净值 / 近 60 日", "h3")}
  ${spark(curve, 74, 806, 278, 30, "lineGreen")}
  ${text(48, 834, "2026-03-10", "tiny")}${text(376, 834, "2026-05-09  +8.7%", "green", "end")}
  <rect x="30" y="854" width="370" height="58" rx="18" fill="#0f1112" stroke="#252b2e"/>
  ${nav}
</svg>`;
}

async function main() {
  const prototypeSvg = renderPrototypeSvg();
  const siteMapSvg = renderSiteMapSvg();
  const prototypeRedSvg = applyRedTheme(prototypeSvg);
  const siteMapRedSvg = applyRedTheme(siteMapSvg);
  const mobileRedSvg = applyRedTheme(renderMobileRedSvg());
  const prototypeSvgPath = path.join(outDir, "webapp-dashboard-terminal-prototype.svg");
  const siteMapSvgPath = path.join(outDir, "webapp-site-map.svg");
  const prototypeRedSvgPath = path.join(outDir, "webapp-dashboard-terminal-prototype-red.svg");
  const siteMapRedSvgPath = path.join(outDir, "webapp-site-map-red.svg");
  const mobileRedSvgPath = path.join(outDir, "webapp-dashboard-mobile-red.svg");
  const prototypePngPath = path.join(outDir, "webapp-dashboard-terminal-prototype.png");
  const siteMapPngPath = path.join(outDir, "webapp-site-map.png");
  const prototypeRedPngPath = path.join(outDir, "webapp-dashboard-terminal-prototype-red.png");
  const siteMapRedPngPath = path.join(outDir, "webapp-site-map-red.png");
  const mobileRedPngPath = path.join(outDir, "webapp-dashboard-mobile-red.png");

  fs.writeFileSync(prototypeSvgPath, prototypeSvg);
  fs.writeFileSync(siteMapSvgPath, siteMapSvg);
  fs.writeFileSync(prototypeRedSvgPath, prototypeRedSvg);
  fs.writeFileSync(siteMapRedSvgPath, siteMapRedSvg);
  fs.writeFileSync(mobileRedSvgPath, mobileRedSvg);

  await sharp(Buffer.from(prototypeSvg)).png().toFile(prototypePngPath);
  await sharp(Buffer.from(siteMapSvg)).png().toFile(siteMapPngPath);
  await sharp(Buffer.from(prototypeRedSvg)).png().toFile(prototypeRedPngPath);
  await sharp(Buffer.from(siteMapRedSvg)).png().toFile(siteMapRedPngPath);
  await sharp(Buffer.from(mobileRedSvg)).png().toFile(mobileRedPngPath);

  console.log(prototypePngPath);
  console.log(siteMapPngPath);
  console.log(prototypeRedPngPath);
  console.log(siteMapRedPngPath);
  console.log(mobileRedPngPath);
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
