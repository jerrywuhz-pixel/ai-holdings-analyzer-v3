import {
  fetchP0ApiSnapshot,
  type P0ApiDataState,
  type P0ApiEquityPosition,
  type P0ApiOptionPosition,
  type P0ApiOverview,
  type P0ApiSnapshot,
} from '@/lib/p0-api';
import {
  accountDatabaseConfigured,
  ensureUserAccount,
  getAccountWorkspace,
  listManualPositions,
  type AccountManualPositionSnapshot,
  type AccountWorkspaceContext,
} from '@/lib/account-store';
import { getCurrentSession } from '@/lib/supabase';

export type PageState = 'ready' | 'loading' | 'error' | 'empty' | 'degraded';

export interface ViewOption {
  id: string;
  name: string;
  baseCurrency: string;
  scope: string;
  sourceCount: number;
  highImpactChangePending?: boolean;
}

export interface SourceStatus {
  key: string;
  label: string;
  tier: 'L1' | 'L2' | 'L3';
  status: 'fresh' | 'stale' | 'degraded';
  freshnessLabel: string;
  lastUpdated: string;
  reason?: string;
  actionability: 'ready' | 'analysis_only' | 'blocked';
}

export interface ChromeSnapshot {
  activeViewId: string;
  views: ViewOption[];
  sources: SourceStatus[];
  marketStates: Array<{ market: string; status: string }>;
  pendingConfirmations: number;
  syncIssues: number;
  runningJobs: number;
}

export interface Metric {
  label: string;
  value: string;
  hint: string;
  tone?: 'default' | 'positive' | 'warning' | 'danger';
}

export interface ActionItem {
  id: string;
  title: string;
  detail: string;
  severity: 'critical' | 'warning' | 'normal';
  href: string;
  badge?: string;
}

export interface RiskItem {
  id: string;
  title: string;
  detail: string;
  level: 'high' | 'medium' | 'low';
  badge: string;
}

export interface EquityHolding {
  symbol: string;
  name: string;
  market: string;
  quantity: string;
  marketValue: string;
  marketValueDetail?: string;
  valuationBasis?: string;
  pnl: string;
  concentration: string;
  discipline: 'clear' | 'watch' | 'blocked';
  freshness: string;
  source: string;
}

export interface OptionHolding {
  id: string;
  underlying: string;
  contract: string;
  dte: string;
  delta: string;
  iv: string;
  premium: string;
  optionMarketValue: string;
  optionMarketValueDetail?: string;
  cashRequired: string;
  marginRequired: string;
  valuationBasis?: string;
  risk: 'high' | 'medium' | 'low';
  assignment: string;
  freshness: string;
  source: string;
  actionability: 'ready' | 'analysis_only' | 'blocked';
}

export interface CandidateStrike {
  id: string;
  underlying: string;
  strike: string;
  expiry: string;
  dte: string;
  delta: string;
  iv: string;
  premium: string;
  cashRequired: string;
  result: 'ready' | 'analysis_only' | 'blocked';
  note: string;
}

export interface ThresholdConfig {
  label: string;
  value: string;
  source: string;
  mutableVia: string;
}

export interface BrokerConnection {
  id: string;
  provider: string;
  accountLabel: string;
  authStatus: string;
  permissionScope: string;
  lastSync: string;
  freshness: string;
  degradation?: string;
}

export interface AssetSourceRow {
  id: string;
  label: string;
  type: string;
  priority: string;
  confidence: string;
  freshness: string;
  lineage: string;
}

export interface SyncEvent {
  id: string;
  title: string;
  status: 'success' | 'warning' | 'failed' | 'running';
  startedAt: string;
  detail: string;
}

export interface RuleRow {
  id: string;
  title: string;
  scope: string;
  severity: 'high' | 'medium' | 'low';
  condition: string;
  latestHit: string;
  overrideRequired: boolean;
}

export interface OverrideRow {
  id: string;
  object: string;
  reason: string;
  actor: string;
  createdAt: string;
}

export interface OpsJob {
  id: string;
  lane: string;
  status: 'queued' | 'running' | 'failed' | 'ready';
  updatedAt: string;
  owner: string;
}

export interface DeliveryIssue {
  id: string;
  channel: string;
  reason: string;
  lastAttempt: string;
  recovery: string;
}

export interface ReplayItem {
  id: string;
  objectType: string;
  reason: string;
  status: string;
}

export interface WorkspaceSnapshot {
  chrome: ChromeSnapshot;
  dashboard: {
    metrics: Metric[];
    riskRadar: RiskItem[];
    actions: ActionItem[];
    holdingsPreview: EquityHolding[];
    optionsPreview: OptionHolding[];
  };
  holdings: {
    metrics: Metric[];
    equity: EquityHolding[];
    options: OptionHolding[];
    riskRadar: RiskItem[];
    sources: AssetSourceRow[];
  };
  sellPut: {
    metrics: Metric[];
    ladder: Array<{ bucket: string; contracts: string; exposure: string }>;
    positions: OptionHolding[];
    candidates: CandidateStrike[];
    thresholds: ThresholdConfig[];
  };
  data: {
    summary: Metric[];
    connections: BrokerConnection[];
    assetSources: AssetSourceRow[];
    syncEvents: SyncEvent[];
  };
  rules: {
    summary: Metric[];
    rules: RuleRow[];
    overrides: OverrideRow[];
    thresholdGroups: ThresholdConfig[];
  };
  ops: {
    summary: Metric[];
    jobs: OpsJob[];
    deliveries: DeliveryIssue[];
    brokerSyncs: SyncEvent[];
    replayQueue: ReplayItem[];
  };
}

export interface WorkspaceResponse {
  state: PageState;
  data?: WorkspaceSnapshot;
  errorMessage?: string;
  liveData?: P0ApiDataState;
}

const baseWorkspace: WorkspaceSnapshot = {
  chrome: {
    activeViewId: 'all-assets',
    views: [
      { id: 'all-assets', name: '全部资产', baseCurrency: 'USD', scope: '当前账户空间', sourceCount: 0 },
    ],
    sources: [],
    marketStates: [],
    pendingConfirmations: 0,
    syncIssues: 0,
    runningJobs: 0,
  },
  dashboard: {
    metrics: [
      { label: '总资产', value: '$0', hint: '等待真实账户数据' },
      { label: '可用现金', value: '$0', hint: '等待资金数据' },
      { label: '保证金占用', value: '$0', hint: '等待期权资金数据' },
      { label: '持仓数', value: '0', hint: '等待持仓数据' },
      { label: '股票 / 期权', value: '0 / 0', hint: '等待持仓拆分' },
      { label: '待处理', value: '0', hint: '暂无待处理事项' },
    ],
    riskRadar: [],
    actions: [],
    holdingsPreview: [],
    optionsPreview: [],
  },
  holdings: {
    metrics: [
      { label: '资产视图', value: '全部资产', hint: '当前账户空间' },
      { label: '股票 / ETF', value: '0', hint: '等待持仓数据' },
      { label: '期权持仓', value: '0', hint: '等待期权数据' },
      { label: '数据状态', value: '等待数据', hint: '暂无真实持仓数据', tone: 'warning' },
    ],
    equity: [],
    options: [],
    riskRadar: [],
    sources: [],
  },
  sellPut: {
    metrics: [
      { label: '可用现金', value: '$0', hint: '等待资金数据' },
      { label: '现金担保', value: '$0', hint: '暂无 Sell Put 持仓' },
      { label: '保证金占用', value: '$0', hint: '暂无保证金占用' },
      { label: '7 天内到期', value: '0', hint: '暂无近到期期权' },
      { label: '高注意', value: '0', hint: '暂无高注意合约' },
      { label: '候选池', value: '0', hint: '暂无真实候选数据' },
    ],
    ladder: [
      { bucket: '0-7 天', contracts: '0', exposure: '$0' },
      { bucket: '8-21 天', contracts: '0', exposure: '$0' },
      { bucket: '22-45 天', contracts: '0', exposure: '$0' },
      { bucket: '45 天以上', contracts: '0', exposure: '$0' },
    ],
    positions: [],
    candidates: [],
    thresholds: [
      { label: '最大现金占用比', value: '未配置', source: '账户规则', mutableVia: '交易纪律' },
      { label: '候选最小到期天数', value: '未配置', source: '账户规则', mutableVia: '交易纪律' },
      { label: '候选最大 delta', value: '未配置', source: '账户规则', mutableVia: '交易纪律' },
      { label: '数据更新要求', value: '等待数据', source: '行情设置', mutableVia: '设置' },
    ],
  },
  data: {
    summary: [
      { label: '系统行情源', value: '0', hint: '等待数据源状态' },
      { label: '资产来源', value: '0', hint: '等待账户数据源' },
      { label: '更新异常', value: '0', hint: '暂无异常' },
      { label: '微信绑定', value: '0', hint: '等待账号绑定状态' },
    ],
    connections: [],
    assetSources: [],
    syncEvents: [],
  },
  rules: {
    summary: [
      { label: '纪律规则', value: '0', hint: '等待当前账号规则' },
      { label: '需要例外说明', value: '0', hint: '暂无例外说明' },
      { label: 'Sell Put 阈值', value: '0', hint: '等待规则配置' },
      { label: '最近命中', value: '0', hint: '暂无规则命中' },
    ],
    rules: [],
    overrides: [],
    thresholdGroups: [
      { label: '最大现金占用比', value: '未配置', source: '账户规则', mutableVia: '交易纪律' },
      { label: '最大 delta', value: '未配置', source: '账户规则', mutableVia: '交易纪律' },
      { label: '最小到期天数', value: '未配置', source: '账户规则', mutableVia: '交易纪律' },
    ],
  },
  ops: {
    summary: [
      { label: '进行中事项', value: '0', hint: '暂无进行中事项' },
      { label: '推送失败', value: '0', hint: '暂无失败推送' },
      { label: '账户更新异常', value: '0', hint: '暂无更新异常' },
      { label: '等待继续处理', value: '0', hint: '暂无待处理队列' },
    ],
    jobs: [],
    deliveries: [],
    brokerSyncs: [],
    replayQueue: [],
  },
};

export function resolvePageState(value?: string): PageState {
  if (value === 'loading' || value === 'error' || value === 'empty' || value === 'degraded') {
    return value;
  }
  return 'ready';
}

function withView(workspace: WorkspaceSnapshot, viewId?: string) {
  if (!viewId) return workspace;
  const next = structuredClone(workspace);
  const matched = next.chrome.views.find((view) => view.id === viewId);
  if (matched) {
    next.chrome.activeViewId = matched.id;
    next.holdings.metrics[0] = {
      label: '资产视图',
      value: matched.name,
      hint: `${matched.baseCurrency} · ${matched.scope}`,
    };
  }
  return next;
}

function scopeForPortfolioView(view: AccountWorkspaceContext['portfolioViews'][number]) {
  if (view.slug === 'option-income' || view.viewType === 'options_income') {
    return 'Sell Put 与期权资金占用';
  }
  if (view.slug === 'long-term') {
    return '股票 / ETF 长期账户';
  }
  return 'A 股 / 港股 / 美股 / ETF / 期权';
}

function applyAccountWorkspace(
  workspace: WorkspaceSnapshot,
  account: AccountWorkspaceContext,
  viewId?: string
) {
  const views = account.portfolioViews.length
    ? account.portfolioViews.map((view) => ({
        id: view.id,
        name: view.name,
        baseCurrency: view.baseCurrency,
        scope: scopeForPortfolioView(view),
        sourceCount: view.sourceCount,
        highImpactChangePending: false,
      }))
    : [
        {
          id: account.activePortfolioViewId || account.tenantId,
          name: '全部资产',
          baseCurrency: account.baseCurrency,
          scope: 'A 股 / 港股 / 美股 / ETF / 期权',
          sourceCount: account.assetSources.length,
        },
      ];
  const matchedView =
    account.portfolioViews.find((view) => view.id === viewId || view.slug === viewId) ??
    account.portfolioViews.find((view) => view.isDefault) ??
    account.portfolioViews[0];
  const activeViewId = matchedView?.id || views[0]?.id || account.activePortfolioViewId;

  workspace.chrome.views = views;
  workspace.chrome.activeViewId = activeViewId;
  workspace.holdings.metrics[0] = {
    label: '资产视图',
    value: matchedView?.name || views[0]?.name || '全部资产',
    hint: `${matchedView?.baseCurrency || account.baseCurrency} · ${
      matchedView ? scopeForPortfolioView(matchedView) : '当前账户空间'
    }`,
  };
  workspace.data.summary[0] = {
    label: '账户空间',
    value: account.manualPositionCount ? `${account.manualPositionCount} 条持仓` : '已初始化',
    hint: `account_id ${account.accountId.slice(0, 8)} · tenant_id ${account.tenantId.slice(0, 8)}`,
    tone: account.manualPositionCount ? 'positive' : 'warning',
  };
  workspace.data.summary[1] = {
    label: '资产来源',
    value: String(account.assetSources.length),
    hint: '系统行情、手工、买卖消息、截图和语音来源已按账户隔离',
  };
  workspace.data.summary[3] = {
    label: '清单视图',
    value: `${account.followView?.itemCount ?? 0} / ${account.listView?.itemCount ?? 0}`,
    hint: '关注清单 / 清仓回溯',
  };
}

function hasPortfolioData(live: P0ApiSnapshot) {
  return Boolean(
    live.equityPositions.length > 0 ||
      live.optionPositions.length > 0 ||
      (live.overview &&
        ((live.overview.holdingsCount ?? 0) > 0 ||
          (live.overview.equityCount ?? 0) > 0 ||
          (live.overview.optionCount ?? 0) > 0 ||
          Math.abs(live.overview.totalAssetValue ?? 0) > 0 ||
          Math.abs(live.overview.grossMarketValue ?? 0) > 0))
  );
}

function applyAccountEmptyWorkspace(workspace: WorkspaceSnapshot, account: AccountWorkspaceContext) {
  workspace.dashboard.metrics = [
    { label: '总资产', value: '$0', hint: `当前以 ${account.baseCurrency} 展示，等待录入或同步` },
    { label: '股票 / ETF', value: '0', hint: '尚未记录持仓' },
    { label: '期权持仓', value: '0', hint: 'Sell Put 数据会独立展示' },
    { label: '账户空间', value: '已初始化', hint: `account_id ${account.accountId.slice(0, 8)}` },
    { label: '资产来源', value: String(account.assetSources.length), hint: '手工、消息、OCR、语音和系统行情来源已建好' },
    { label: '待处理', value: '0', hint: '暂无待复核动作' },
  ];
  workspace.dashboard.holdingsPreview = [];
  workspace.dashboard.optionsPreview = [];
  workspace.dashboard.actions = [
    {
      id: 'account-empty-add-position',
      title: '先录入一条持仓',
      detail: '可以从数据与账户页手工录入股票 / ETF，系统会按当前账号生成持仓快照。',
      severity: 'normal',
      href: '/data',
    },
    {
      id: 'account-empty-add-image',
      title: '用截图初始化持仓',
      detail: '普通用户不连接个人 Futu OpenD，可以通过微信发送持仓截图识别后确认写入。',
      severity: 'normal',
      href: '/ops',
    },
  ];
  workspace.dashboard.riskRadar = [
    {
      id: 'account-empty-risk',
      title: '暂无可分析持仓',
      detail: '当前账号空间已经创建，录入或同步后才会生成风险雷达。',
      level: 'low',
      badge: '等待数据',
    },
  ];
  workspace.holdings.metrics = [
    { label: '资产视图', value: workspace.holdings.metrics[0]?.value || '全部资产', hint: workspace.holdings.metrics[0]?.hint || account.baseCurrency },
    { label: '股票 / ETF', value: '0', hint: '没有当前持仓' },
    { label: '期权持仓', value: '0', hint: '没有当前期权仓位' },
    { label: '数据状态', value: '等待录入', hint: '暂无手工、OCR 或微信确认持仓', tone: 'warning' },
  ];
  workspace.holdings.equity = [];
  workspace.holdings.options = [];
  workspace.holdings.riskRadar = workspace.dashboard.riskRadar;
  workspace.holdings.sources = account.assetSources.map((source) => ({
    id: source.id,
    label: sourceDisplayName(source.sourceName, source.sourceType),
    type: sourceLabel(source.sourceType),
    priority: source.isActive ? `优先级 ${source.priority}` : '未启用',
    confidence: source.sourceQuality,
    freshness: source.lastSeenAt ? formatFreshness(source.lastSeenAt) : '等待数据',
    lineage: `${sourceProviderLabel(source.provider)} · ${source.sourceKey}`,
  }));
  workspace.sellPut.metrics = [
    { label: '可用现金', value: '$0', hint: '等待手工资金数据或系统行情补充' },
    { label: '现金担保', value: '$0', hint: '暂无 Sell Put 持仓' },
    { label: '保证金占用', value: '$0', hint: '暂无期权保证金占用' },
    { label: '7 天内到期', value: '0', hint: '暂无近到期期权' },
    { label: '高注意', value: '0', hint: '暂无期权风险项' },
    { label: '候选池', value: '0', hint: '录入关注清单或同步行情后生成候选' },
  ];
  workspace.sellPut.positions = [];
  workspace.sellPut.candidates = [];
  workspace.ops.jobs = [];
  workspace.ops.deliveries = [];
  workspace.ops.replayQueue = [];
}

function sourceLabel(sourceType: string) {
  if (sourceType === 'manual') return '手工录入';
  if (sourceType === 'message_trade_input') return '买卖消息';
  if (sourceType === 'ocr') return '截图识别';
  if (sourceType === 'voice_asr') return '语音识别';
  if (sourceType === 'broker_api') return '系统行情源';
  return sourceType;
}

function sourceDisplayName(sourceName: string, sourceType?: string) {
  if (sourceType === 'broker_api' || sourceName.includes('富途') || sourceName.includes('券商')) {
    return '系统 Futu 行情源';
  }
  return sourceName;
}

function sourceProviderLabel(provider: string) {
  return provider.toLowerCase().includes('futu') ? 'system_market_data' : provider;
}

function buildManualP0Snapshot(
  account: AccountWorkspaceContext,
  manual: AccountManualPositionSnapshot,
  baseUrl: string
): P0ApiSnapshot {
  const baseCurrency = account.baseCurrency || 'USD';
  const positions = manual.positions.map((position, index) => {
    const originalMarketPrice = resolvedManualPrice(position.marketPrice, position.averageCost);
    const originalMarketValue = resolvedManualMarketValue(
      position.marketValue,
      position.quantity,
      originalMarketPrice,
      position.multiplier ?? undefined
    );
    const fxRate = manualFxRate(position.currency, baseCurrency);
    const baseMarketValue =
      originalMarketValue === undefined ? undefined : roundMoney(originalMarketValue * fxRate);
    const baseMarketPrice =
      originalMarketPrice === undefined ? undefined : roundMoney(originalMarketPrice * fxRate);
    const baseAverageCost =
      position.averageCost === null ? undefined : roundMoney(position.averageCost * fxRate);
    const fxSource = position.currency === baseCurrency ? 'manual_cost_basis' : 'fallback_estimate';

    return {
      id: position.id || `manual-${position.symbol}-${index}`,
      symbol: position.symbol,
      name: position.name || position.symbol,
      market: position.market,
      currency: position.currency,
      baseCurrency,
      quantity: position.quantity,
      marketValue: baseMarketValue,
      originalMarketValue,
      baseMarketValue,
      averageCost: baseAverageCost,
      originalAverageCost: position.averageCost ?? undefined,
      baseAverageCost,
      marketPrice: baseMarketPrice,
      originalMarketPrice,
      baseMarketPrice,
      unrealizedPnlPct: position.unrealizedPnlPct ?? resolvedManualPnlPct(originalMarketPrice, position.averageCost),
      updatedAt: position.updatedAt,
      source: '手工录入',
      fxSource,
      sourceQuality: 'user_confirmed',
      instrumentType: position.instrumentType,
      positionSide: position.positionSide,
      optionType: position.optionType,
      strike: position.strike,
      expiry: position.expiry,
      multiplier: position.multiplier,
    };
  });
  const equityPositions = positions.filter((position) => position.instrumentType !== 'option_contract');
  const optionPositions = positions
    .filter((position) => position.instrumentType === 'option_contract')
    .map((position, index) => ({
      id: position.id || `manual-option-${position.symbol}-${index}`,
      underlying: position.symbol,
      contract: formatOptionContract(position.symbol, position.expiry, position.strike, position.optionType),
      currency: position.currency,
      baseCurrency,
      quantity: position.quantity,
      marketValue: position.baseMarketValue,
      originalMarketValue: position.originalMarketValue,
      baseMarketValue: position.baseMarketValue,
      marketPrice: position.baseMarketPrice,
      originalMarketPrice: position.originalMarketPrice,
      baseMarketPrice: position.baseMarketPrice,
      averageCost: position.baseAverageCost,
      originalAverageCost: position.originalAverageCost,
      baseAverageCost: position.baseAverageCost,
      strike: position.strike ?? undefined,
      expiry: position.expiry ?? undefined,
      daysToExpiry: daysToExpiry(position.expiry),
      optionType: position.optionType ?? undefined,
      cashRequired: computeManualOptionCashRequired(position),
      originalCashRequired: computeManualOptionCashRequired(position, false),
      baseCashRequired: computeManualOptionCashRequired(position),
      marginRequired: 0,
      originalMarginRequired: 0,
      baseMarginRequired: 0,
      updatedAt: position.updatedAt,
      source: '手工录入',
      fxSource: position.fxSource,
      sourceQuality: position.sourceQuality,
    }));
  const totalAssetValue = positions.reduce((sum, item) => sum + (item.baseMarketValue ?? 0), 0);
  const grossMarketValue = positions.reduce((sum, item) => sum + Math.abs(item.baseMarketValue ?? 0), 0);
  const updatedAt = manual.updatedAt || new Date().toISOString();

  return {
    dataState: {
      mode: 'live',
      label: '手工持仓已接入',
      detail: '当前页面展示的是本账号手工确认录入的持仓数据；缺少实时行情时按成本价估算市值，仅供巡检和补充行情前使用。',
      updatedAt,
      baseUrl,
      sourcePath: 'webapp_manual_positions',
      baseCurrency,
      fxSource: positions.some((position) => position.fxSource === 'fallback_estimate')
        ? 'fallback_estimate'
        : 'manual_cost_basis',
      usesEstimatedFx: true,
      valuationDetail: `手工录入数据按成本价估算，并按 ${baseCurrency} 页面口径折算；未补充实时行情前仅供参考。`,
    },
    overview: {
      currency: baseCurrency,
      baseCurrency,
      currencies: Array.from(new Set(manual.positions.map((item) => item.currency))),
      totalAssetValue,
      cashAvailable: 0,
      marginUsed: 0,
      cashSecured: 0,
      holdingsCount: manual.positions.length,
      equityCount: equityPositions.length,
      optionCount: optionPositions.length,
      equityMarketValue: equityPositions.reduce((sum, item) => sum + (item.baseMarketValue ?? 0), 0),
      optionMarketValue: optionPositions.reduce((sum, item) => sum + (item.baseMarketValue ?? 0), 0),
      grossMarketValue,
      updatedAt,
      fxSource: positions.some((position) => position.fxSource === 'fallback_estimate')
        ? 'fallback_estimate'
        : 'manual_cost_basis',
      sourceQuality: 'user_confirmed',
      usesEstimatedFx: true,
    },
    equityPositions,
    optionPositions,
    connections: [
      {
        id: 'manual-webapp',
        provider: '手工录入',
        accountLabel: '当前账号手工持仓',
        authStatus: 'connected',
        permissionScope: '用户确认录入',
        lastSync: updatedAt,
        updatedAt,
        detail: '由 WebApp 手工录入生成；缺少系统行情时按成本价估算。',
      },
    ],
    syncEvents: [
      {
        id: 'manual-position-refresh',
        title: '手工持仓已刷新',
        status: 'success',
        startedAt: updatedAt,
        detail: `已记录 ${manual.positions.length} 条手工持仓，并限定在当前账号空间。`,
      },
    ],
    assetSources: account.assetSources.map((source) => ({
      id: source.id,
      label: sourceDisplayName(source.sourceName, source.sourceType),
      type: sourceLabel(source.sourceType),
      priority: source.isActive ? `优先级 ${source.priority}` : '待启用',
      confidence: source.sourceQuality,
      freshness: source.lastSeenAt ? formatFreshness(source.lastSeenAt) : source.sourceKey === 'manual-webapp' ? formatFreshness(updatedAt) : '等待数据',
      lineage: `${sourceProviderLabel(source.provider)} · ${source.sourceKey}`,
    })),
  };
}

const FALLBACK_FX_TO_USD: Record<string, number> = {
  USD: 1,
  HKD: 0.128,
  CNY: 0.138,
};

function resolvedManualPrice(marketPrice: number | null, averageCost: number | null) {
  if (isUsablePositiveNumber(marketPrice)) return marketPrice;
  if (isUsablePositiveNumber(averageCost)) return averageCost;
  return undefined;
}

function resolvedManualMarketValue(
  marketValue: number | null,
  quantity: number,
  marketPrice?: number,
  multiplier = 1
) {
  if (isUsableNumber(marketValue)) return marketValue;
  if (!isUsableNumber(quantity) || marketPrice === undefined) return undefined;
  return roundMoney(quantity * marketPrice * multiplier);
}

function resolvedManualPnlPct(marketPrice: number | undefined, averageCost: number | null) {
  if (marketPrice === undefined || averageCost === null || averageCost <= 0) return undefined;
  return ((marketPrice - averageCost) / averageCost) * 100;
}

function formatOptionContract(
  underlying: string,
  expiry?: string | null,
  strike?: number | null,
  optionType?: string | null
) {
  const normalizedType = optionType?.trim().toUpperCase();
  const typeCode = normalizedType?.startsWith('P') ? 'P' : normalizedType?.startsWith('C') ? 'C' : '';
  const strikeText = strike === null || strike === undefined ? '' : `${strike}`;
  return [underlying, expiry, strikeText && typeCode ? `${strikeText}${typeCode}` : strikeText || typeCode]
    .filter(Boolean)
    .join(' ');
}

function daysToExpiry(expiry?: string | null) {
  if (!expiry) return undefined;
  const expiryTime = Date.parse(expiry);
  if (Number.isNaN(expiryTime)) return undefined;
  return Math.max(0, Math.ceil((expiryTime - Date.now()) / (24 * 60 * 60 * 1000)));
}

function computeManualOptionCashRequired(
  position: {
    quantity?: number;
    strike?: number | null;
    multiplier?: number | null;
    baseCurrency?: string;
    currency?: string;
  },
  convertToBase = true
) {
  if (!position.quantity || position.quantity >= 0 || !position.strike) return undefined;
  const value = Math.abs(position.quantity) * position.strike * (position.multiplier || 100);
  if (!convertToBase) return roundMoney(value);
  return roundMoney(value * manualFxRate(position.currency || 'USD', position.baseCurrency || 'USD'));
}

function manualFxRate(currency: string, baseCurrency: string) {
  const source = currency.toUpperCase();
  const target = baseCurrency.toUpperCase();
  if (source === target) return 1;
  const sourceToUsd = FALLBACK_FX_TO_USD[source];
  const targetToUsd = FALLBACK_FX_TO_USD[target];
  if (!sourceToUsd || !targetToUsd) return 1;
  return sourceToUsd / targetToUsd;
}

function isUsablePositiveNumber(value: number | null | undefined): value is number {
  return isUsableNumber(value) && value > 0;
}

function isUsableNumber(value: number | null | undefined): value is number {
  return typeof value === 'number' && Number.isFinite(value);
}

function roundMoney(value: number) {
  return Number(value.toFixed(2));
}

function applyLiveData(workspace: WorkspaceSnapshot, live: P0ApiSnapshot) {
  const totalAssetValue =
    live.overview?.totalAssetValue ??
    live.equityPositions.reduce((sum, item) => sum + (item.marketValue ?? 0), 0) +
      live.optionPositions.reduce((sum, item) => sum + (item.marketValue ?? 0), 0);
  const equity = live.equityPositions.length
    ? buildEquityHoldings(live.equityPositions, totalAssetValue)
    : [];
  const options = live.optionPositions.length ? buildOptionHoldings(live.optionPositions) : [];

  workspace.chrome.sources = buildChromeSources(live);

  if (live.overview || equity.length || options.length) {
    workspace.dashboard.metrics = buildDashboardMetrics(live.overview, equity, options, live.dataState);
    workspace.dashboard.holdingsPreview = equity.slice(0, 3);
    workspace.dashboard.optionsPreview = options.slice(0, 2);
    workspace.dashboard.riskRadar = buildRiskRadar(live.overview, equity, options, live.dataState);
    workspace.dashboard.actions = buildActionItems(equity, options, live.dataState);

    workspace.holdings.metrics = buildHoldingsMetrics(
      activeViewName(workspace),
      live.overview,
      equity,
      options,
      live.dataState
    );
    workspace.holdings.equity = equity;
    workspace.holdings.options = options;
    workspace.holdings.riskRadar = buildRiskRadar(live.overview, equity, options, live.dataState);
    workspace.holdings.sources = buildHoldingSources(live, equity, options);

    workspace.sellPut.metrics = buildSellPutMetrics(live.overview, options);
    workspace.sellPut.positions = options;
    workspace.sellPut.ladder = buildSellPutLadder(options);
    workspace.sellPut.candidates = [];
  }

  if (live.connections.length || live.syncEvents.length || live.assetSources.length) {
    workspace.data.summary = buildDataSummary(live);
    workspace.data.connections = buildDataConnections(live);
    workspace.data.assetSources = buildDataSources(live);
    workspace.data.syncEvents = buildDataSyncEvents(live);
  }

  return workspace;
}

function activeViewName(workspace: WorkspaceSnapshot) {
  return workspace.chrome.views.find((view) => view.id === workspace.chrome.activeViewId)?.name || '全部资产';
}

function buildDashboardMetrics(
  overview: P0ApiOverview | undefined,
  equity: EquityHolding[],
  options: OptionHolding[],
  liveData: P0ApiDataState
): Metric[] {
  const updatedAt = overview?.updatedAt;
  const valuationHint =
    liveData.valuationDetail ||
    (overview?.baseCurrency ? `页面当前按 ${overview.baseCurrency} 口径展示。` : '优先取实时总览');

  return [
    {
      label: '总资产',
      value: formatCurrency(overview?.totalAssetValue, overview?.currency),
      hint: valuationHint,
    },
    {
      label: '可用现金',
      value: formatCurrency(overview?.cashAvailable, overview?.currency),
      hint: overview?.baseCurrency ? `按 ${overview.baseCurrency} 展示可用现金` : '可用于新增仓位的现金',
    },
    {
      label: '保证金占用',
      value: formatCurrency(overview?.marginUsed, overview?.currency),
      hint: overview?.baseCurrency ? `保证金与现金担保按 ${overview.baseCurrency} 分开展示` : '保证金与现金担保分开展示',
      tone: overview?.marginUsed ? 'warning' : 'default',
    },
    {
      label: '持仓数',
      value: String(
        overview?.holdingsCount ??
          overview?.equityCount ??
          equity.length + (overview?.optionCount ?? options.length)
      ),
      hint: '股票、ETF 与期权合并计数',
    },
    {
      label: '股票 / 期权',
      value: `${overview?.equityCount ?? equity.length} / ${overview?.optionCount ?? options.length}`,
      hint: '拆分查看权益仓与期权仓',
    },
    {
      label: '数据时间',
      value: updatedAt ? formatDateTime(updatedAt) : '等待同步',
      hint: updatedAt
        ? `${liveData.usesEstimatedFx ? '折算仅供参考 · ' : ''}距今 ${formatFreshness(updatedAt)}`
        : '尚未返回最新时间',
      tone: updatedAt ? 'positive' : 'warning',
    },
  ];
}

function buildHoldingsMetrics(
  activeViewName: string,
  overview: P0ApiOverview | undefined,
  equity: EquityHolding[],
  options: OptionHolding[],
  liveData: P0ApiDataState
): Metric[] {
  return [
    {
      label: '资产视图',
      value: activeViewName,
      hint: overview?.baseCurrency ? `按 ${overview.baseCurrency} 统一展示，可切换资产视图` : '当前页面仍支持多视图切换',
    },
    {
      label: '股票 / ETF',
      value: String(overview?.equityCount ?? equity.length),
      hint: '持仓页会同时显示原币种与页面折算口径',
    },
    {
      label: '期权持仓',
      value: String(overview?.optionCount ?? options.length),
      hint: '期权金额用于巡检，不等同交易账户结单',
    },
    {
      label: '数据状态',
      value: liveData.mode === 'live' ? '实时' : liveData.mode === 'partial' ? '部分实时' : '等待数据',
      hint:
        liveData.valuationDetail ||
        (liveData.updatedAt ? `更新 ${formatFreshness(liveData.updatedAt)}` : '等待首次同步'),
      tone: liveData.mode === 'live' ? 'positive' : 'warning',
    },
  ];
}

function buildRiskRadar(
  overview: P0ApiOverview | undefined,
  equity: EquityHolding[],
  options: OptionHolding[],
  liveData: P0ApiDataState
): RiskItem[] {
  const items: RiskItem[] = [];
  const topHolding = equity
    .map((holding) => ({
      holding,
      concentration: Number(holding.concentration.replace('%', '')) || 0,
    }))
    .sort((left, right) => right.concentration - left.concentration)[0];

  if (topHolding && topHolding.concentration >= 20) {
    items.push({
      id: 'live-risk-concentration',
      title: '单标的占比偏高',
      detail: `${topHolding.holding.symbol} 当前约占资产 ${topHolding.holding.concentration}，建议复核集中度。`,
      level: topHolding.concentration >= 30 ? 'high' : 'medium',
      badge: '集中度',
    });
  }

  const nearExpiryCount = options.filter((option) => Number(option.dte) <= 14).length;
  if (nearExpiryCount > 0) {
    items.push({
      id: 'live-risk-expiry',
      title: '近到期期权需要复核',
      detail: `${nearExpiryCount} 份期权合约在 14 天内到期，建议优先检查接股与资金占用。`,
      level: nearExpiryCount >= 2 ? 'high' : 'medium',
      badge: '到期风险',
    });
  }

  if (liveData.usesEstimatedFx) {
    items.push({
      id: 'live-risk-fx-estimate',
      title: '多币种金额按估算汇率折算',
      detail: '当前页面金额按估算汇率折算，仅供参考；请结合原币金额与交易账户结单复核。',
      level: 'medium',
      badge: '折算口径',
    });
  }

  if (liveData.mode !== 'live') {
    items.push({
      id: 'live-risk-data',
      title: '实时数据暂不完整',
      detail: liveData.detail,
      level: 'medium',
      badge: '数据状态',
    });
  }

  if (!items.length) {
    items.push({
      id: 'live-risk-ok',
      title: '当前数据可用于快速巡检',
      detail:
        overview?.updatedAt
          ? `最近数据时间 ${formatDateTime(overview.updatedAt)}，未发现需要立刻处理的持仓级风险。`
          : '当前未发现需要立刻处理的持仓级风险。',
      level: 'low',
      badge: '已检查',
    });
  }

  return items.slice(0, 3);
}

function buildActionItems(
  equity: EquityHolding[],
  options: OptionHolding[],
  liveData: P0ApiDataState
): ActionItem[] {
  const items: ActionItem[] = [];
  const nearExpiry = options.filter((option) => Number(option.dte) <= 14);

  if (nearExpiry.length > 0) {
    items.push({
      id: 'live-action-expiry',
      title: '复核近到期期权',
      detail: `${nearExpiry.length} 份期权接近到期，先检查接股风险和现金占用。`,
      severity: nearExpiry.length >= 2 ? 'critical' : 'warning',
      href: '/holdings',
      badge: nearExpiry.length >= 2 ? '优先处理' : undefined,
    });
  }

  const blockedEquity = equity.find((holding) => holding.discipline === 'blocked');
  if (blockedEquity) {
    items.push({
      id: 'live-action-blocked',
      title: `查看 ${blockedEquity.symbol} 的持仓风险`,
      detail: '该标的当前集中度或盈亏状态需要额外关注。',
      severity: 'warning',
      href: '/holdings',
    });
  }

  if (liveData.mode !== 'live') {
    items.push({
      id: 'live-action-status',
      title: '检查数据连接状态',
      detail: '部分区块暂未拿到真实数据，建议先确认数据连接与最近同步。',
      severity: 'warning',
      href: '/data',
    });
  }

  if (!items.length) {
    items.push({
      id: 'live-action-default',
      title: '查看完整持仓明细',
      detail: '实时总览已接入，下一步建议核对完整持仓与最近同步时间。',
      severity: 'normal',
      href: '/holdings',
    });
  }

  return items.slice(0, 3);
}

function buildHoldingSources(
  live: P0ApiSnapshot,
  equity: EquityHolding[],
  options: OptionHolding[]
): AssetSourceRow[] {
  const valuationRow: AssetSourceRow = {
    id: 'holding-source-valuation',
    label: '页面展示口径',
    type: '折算口径',
    priority: live.dataState.baseCurrency || '当前口径',
    confidence: live.dataState.usesEstimatedFx ? '参考' : '已对齐',
    freshness: live.dataState.updatedAt ? formatFreshness(live.dataState.updatedAt) : '等待同步',
    lineage:
      live.dataState.valuationDetail ||
      `页面按 ${live.dataState.baseCurrency || live.overview?.baseCurrency || '当前币种'} 展示。`,
  };

  if (live.assetSources.length) {
    return [valuationRow, ...live.assetSources.map((source) => ({
      id: source.id,
      label: source.label,
      type: source.type,
      priority: source.priority,
      confidence: source.confidence,
      freshness: source.freshness,
      lineage: source.lineage,
    }))];
  }

  return [
    valuationRow,
    {
      id: 'holding-source-live',
      label: '实时资产数据',
      type: '资产汇总',
      priority: '最高',
      confidence: live.dataState.mode === 'live' ? '0.98' : '0.86',
      freshness: live.dataState.updatedAt ? formatFreshness(live.dataState.updatedAt) : '等待同步',
      lineage: `由资产汇总结果生成概览与持仓；当前股票 ${equity.length} 条，期权 ${options.length} 条。`,
    },
  ];
}

function buildDataSummary(live: P0ApiSnapshot): Metric[] {
  const connectedCount = live.connections.filter((item) => item.authStatus === 'connected').length;
  const latestSync = live.connections
    .map((item) => item.lastSync || item.updatedAt)
    .filter(Boolean)
    .sort()
    .reverse()[0];

  return [
    {
      label: '系统行情源',
      value: String(live.connections.length || 1),
      hint: `${connectedCount} 条系统源状态正常`,
      tone: connectedCount ? 'positive' : 'warning',
    },
    {
      label: '最近同步',
      value: latestSync ? formatDateTime(latestSync) : '等待同步',
      hint: latestSync ? `距今 ${formatFreshness(latestSync)}` : '服务尚未返回同步时间',
    },
    {
      label: '展示币种',
      value: live.dataState.baseCurrency || live.overview?.baseCurrency || '--',
      hint:
        live.dataState.valuationDetail ||
        '多币种资产会统一折算到当前页面展示币种。',
    },
    {
      label: '数据来源',
      value: live.dataState.mode === 'live' ? '实时' : live.dataState.mode === 'partial' ? '部分实时' : '等待数据',
      hint: live.dataState.mode === 'live' ? '页面优先展示最新数据' : '仍有部分区块暂未拿到最新系统数据',
      tone: live.dataState.mode === 'live' ? 'positive' : 'warning',
    },
  ];
}

function buildDataConnections(live: P0ApiSnapshot): BrokerConnection[] {
  if (live.connections.length) {
    return live.connections.map((connection) => ({
      id: connection.id,
      provider: normalizeProviderName(connection.provider),
      accountLabel: connection.accountLabel,
      authStatus: connection.authStatus === 'connected' ? 'connected' : 'degraded',
      permissionScope: normalizePermissionScope(connection.permissionScope),
      lastSync: connection.lastSync ? formatDateTime(connection.lastSync) : '等待同步',
      freshness: connection.lastSync ? formatFreshness(connection.lastSync) : '等待同步',
      degradation: connection.detail,
    }));
  }

  return [
    {
      id: 'fallback-connection',
      provider: '系统行情源',
      accountLabel: '系统数据待补齐',
      authStatus: 'degraded',
      permissionScope: '等待真实数据返回',
      lastSync: '等待同步',
      freshness: '等待同步',
      degradation: live.dataState.detail,
    },
  ];
}

function buildDataSources(live: P0ApiSnapshot): AssetSourceRow[] {
  const valuationRow: AssetSourceRow = {
    id: 'data-source-valuation',
    label: '多币种展示口径',
    type: '折算口径',
    priority: live.dataState.baseCurrency || live.overview?.baseCurrency || '当前口径',
    confidence: live.dataState.usesEstimatedFx ? '参考' : '已对齐',
    freshness: live.dataState.updatedAt ? formatFreshness(live.dataState.updatedAt) : '等待同步',
    lineage:
      live.dataState.valuationDetail ||
      `页面按 ${live.dataState.baseCurrency || live.overview?.baseCurrency || '当前币种'} 展示。`,
  };

  if (live.assetSources.length) {
    return [valuationRow, ...live.assetSources.map((source) => ({
      id: source.id,
      label: source.label,
      type: source.type,
      priority: source.priority,
      confidence: source.confidence,
      freshness: source.freshness,
      lineage: source.lineage,
    }))];
  }

  return [
    valuationRow,
    {
      id: 'fallback-source',
      label: '系统数据待补齐',
      type: '等待数据',
      priority: '待补齐',
      confidence: '--',
      freshness: live.dataState.updatedAt ? formatFreshness(live.dataState.updatedAt) : '等待同步',
      lineage: '实时数据暂不可用时，页面只展示空状态和待补齐说明，不回退到占位资产。',
    },
  ];
}

function buildDataSyncEvents(live: P0ApiSnapshot): SyncEvent[] {
  const events: SyncEvent[] = live.syncEvents.length
    ? live.syncEvents.map((event) => ({
        id: event.id,
        title: event.title,
        status: event.status,
        startedAt: event.startedAt || '',
        detail: event.detail,
      }))
    : [
        {
          id: 'fallback-sync',
          title: '实时数据暂不可用',
          status: live.dataState.mode === 'fallback' ? 'failed' : 'warning',
          startedAt: live.dataState.updatedAt || '',
          detail: live.dataState.detail,
        },
      ];

  return events.map((event: SyncEvent) => ({
    id: event.id,
    title: event.title,
    status: event.status,
    startedAt: event.startedAt ? compactDateTime(event.startedAt) : '刚刚',
    detail: event.detail,
  }));
}

function buildChromeSources(live: P0ApiSnapshot): SourceStatus[] {
  const updatedAt = live.dataState.updatedAt;
  const defaultLastUpdated = updatedAt ? formatDateTime(updatedAt) : '等待同步';
  const defaultFreshness = updatedAt ? formatFreshness(updatedAt) : '等待同步';

  return [
    {
      key: 'portfolio-overview',
      label: '资产总览数据',
      tier: 'L1',
      status: live.overview ? 'fresh' : live.dataState.mode === 'fallback' ? 'degraded' : 'stale',
      freshnessLabel: defaultFreshness,
      lastUpdated: defaultLastUpdated,
      reason: live.overview
        ? live.dataState.usesEstimatedFx
          ? '多币种金额当前按估算汇率折算，仅供参考。'
          : live.dataState.valuationDetail
        : '总览数据暂未完整返回，相关数字会显示为空或待补齐。',
      actionability: live.overview ? 'ready' : 'analysis_only',
    },
    {
      key: 'portfolio-positions',
      label: '持仓数据',
      tier: 'L1',
      status:
        live.equityPositions.length || live.optionPositions.length
          ? 'fresh'
          : live.dataState.mode === 'fallback'
            ? 'degraded'
            : 'stale',
      freshnessLabel: defaultFreshness,
      lastUpdated: defaultLastUpdated,
      reason:
        live.equityPositions.length || live.optionPositions.length
          ? undefined
          : '持仓数据暂未返回，页面不会展示占位标的。',
      actionability: live.equityPositions.length || live.optionPositions.length ? 'ready' : 'analysis_only',
    },
    {
      key: 'system-futu-source',
      label: '系统 Futu 行情源',
      tier: 'L2',
      status:
        live.connections[0]?.authStatus === 'connected'
          ? 'fresh'
          : live.dataState.mode === 'fallback'
            ? 'degraded'
            : 'stale',
      freshnessLabel:
        live.connections[0]?.lastSync ? formatFreshness(live.connections[0].lastSync) : defaultFreshness,
      lastUpdated:
        live.connections[0]?.lastSync ? formatDateTime(live.connections[0].lastSync) : defaultLastUpdated,
      reason: live.connections[0]?.detail,
      actionability: live.connections[0]?.authStatus === 'connected' ? 'ready' : 'analysis_only',
    },
  ];
}

function buildEquityHoldings(
  items: P0ApiEquityPosition[],
  totalAssetValue: number
): EquityHolding[] {
  return items.map((item) => {
    const concentration =
      totalAssetValue > 0 && item.marketValue !== undefined
        ? ((Math.abs(item.marketValue) / totalAssetValue) * 100).toFixed(1)
        : '--';
    const valueMeta = describeValuation({
      originalCurrency: item.currency,
      baseCurrency: item.baseCurrency,
      originalValue: item.originalMarketValue,
      baseValue: item.baseMarketValue ?? item.marketValue,
      usesEstimatedFx: isEstimatePosition(item.fxSource),
    });

    return {
      symbol: item.symbol,
      name: item.name,
      market: item.market,
      quantity: item.quantity !== undefined ? formatQuantity(item.quantity) : '--',
      marketValue: formatCurrency(item.marketValue, item.baseCurrency || item.currency),
      marketValueDetail: valueMeta.detail,
      valuationBasis: valueMeta.basis,
      pnl: formatPercent(item.unrealizedPnlPct),
      concentration: concentration === '--' ? '--' : `${concentration}%`,
      discipline: inferDiscipline(item.unrealizedPnlPct, Number(concentration)),
      freshness: item.updatedAt ? formatFreshness(item.updatedAt) : '等待同步',
      source: normalizeSourceLabel(item.source),
    };
  });
}

function buildOptionHoldings(items: P0ApiOptionPosition[]): OptionHolding[] {
  return items.map((item) => {
    const dte = item.daysToExpiry ?? 0;
    const usesEstimatedFx = isEstimatePosition(item.fxSource);
    const valueMeta = describeValuation({
      originalCurrency: item.currency,
      baseCurrency: item.baseCurrency,
      originalValue: item.originalMarketValue,
      baseValue: item.baseMarketValue ?? item.marketValue,
      usesEstimatedFx,
    });
    return {
      id: item.id,
      underlying: item.underlying,
      contract: item.contract,
      dte: String(dte || '--'),
      delta: item.delta !== undefined ? item.delta.toFixed(2) : '--',
      iv: item.impliedVolatility !== undefined ? `${(item.impliedVolatility * 100).toFixed(0)}%` : '--',
      premium: formatCurrency(item.averageCost, item.baseCurrency || item.currency, true),
      optionMarketValue: formatCurrency(item.marketValue, item.baseCurrency || item.currency, true),
      optionMarketValueDetail: valueMeta.detail,
      cashRequired: formatCurrency(item.cashRequired, item.baseCurrency || item.currency),
      marginRequired: formatCurrency(item.marginRequired ?? 0, item.baseCurrency || item.currency),
      valuationBasis: valueMeta.basis,
      risk: dte <= 7 ? 'high' : dte <= 21 ? 'medium' : 'low',
      assignment: dte <= 7 ? '近到期，建议复核' : dte <= 21 ? '保持跟踪' : '按计划持有',
      freshness: item.updatedAt ? formatFreshness(item.updatedAt) : '等待同步',
      source: normalizeSourceLabel(item.source),
      actionability: dte <= 21 ? 'analysis_only' : 'ready',
    };
  });
}

function buildSellPutMetrics(
  overview: P0ApiOverview | undefined,
  options: OptionHolding[]
): Metric[] {
  const cashSecured = sumCurrency(options.map((option) => option.cashRequired));
  const marginUsed = sumCurrency(options.map((option) => option.marginRequired));
  const nearExpiryCount = options.filter((option) => Number(option.dte) <= 7).length;
  const watchCount = options.filter((option) => option.risk === 'high' || option.actionability !== 'ready').length;

  return [
    {
      label: '可用现金',
      value: formatCurrency(overview?.cashAvailable, overview?.currency),
      hint: '以用户确认资金为准',
    },
    {
      label: '现金担保',
      value: formatCurrency(overview?.cashSecured ?? cashSecured, overview?.currency),
      hint: options.length ? '按真实 Sell Put 持仓估算现金占用' : '当前没有真实 Sell Put 持仓',
    },
    {
      label: '保证金占用',
      value: formatCurrency(overview?.marginUsed ?? marginUsed, overview?.currency),
      hint: '与现金担保分开展示',
      tone: (overview?.marginUsed ?? marginUsed) ? 'warning' : 'default',
    },
    {
      label: '7 天内到期',
      value: String(nearExpiryCount),
      hint: nearExpiryCount ? '近到期合约需要优先复核' : '暂无 7 天内到期合约',
      tone: nearExpiryCount ? 'danger' : 'default',
    },
    {
      label: '高注意',
      value: String(watchCount),
      hint: watchCount ? '价内、近到期或数据字段待补齐' : '当前没有高注意 Sell Put 持仓',
      tone: watchCount ? 'warning' : 'default',
    },
    {
      label: '候选池',
      value: '0',
      hint: '暂无真实候选数据，不展示占位标的',
    },
  ];
}

function buildSellPutLadder(options: OptionHolding[]): Array<{ bucket: string; contracts: string; exposure: string }> {
  const buckets = [
    { bucket: '0-7 天', min: 0, max: 7 },
    { bucket: '8-21 天', min: 8, max: 21 },
    { bucket: '22-45 天', min: 22, max: 45 },
    { bucket: '45 天以上', min: 46, max: Number.POSITIVE_INFINITY },
  ];

  return buckets.map(({ bucket, min, max }) => {
    const matched = options.filter((option) => {
      const dte = Number(option.dte);
      return Number.isFinite(dte) && dte >= min && dte <= max;
    });
    return {
      bucket,
      contracts: String(matched.length),
      exposure: formatCurrency(sumCurrency(matched.map((option) => option.cashRequired)), 'USD'),
    };
  });
}

function sumCurrency(values: Array<string | undefined>) {
  return values.reduce((sum, value) => sum + (parseCurrencyValue(value) ?? 0), 0);
}

function parseCurrencyValue(value?: string) {
  if (!value || value === '--') return undefined;
  const parsed = Number(value.replace(/[^0-9.-]/g, ''));
  return Number.isFinite(parsed) ? parsed : undefined;
}

function normalizeProviderName(value: string) {
  return value.toLowerCase().includes('futu') ? '系统 Futu 行情源' : value;
}

function normalizePermissionScope(value: string) {
  if (value === 'read_only') return '管理员只读行情 / 期权链';
  return value
    .replaceAll('/', ' / ')
    .replaceAll('_', ' ')
    .trim();
}

function normalizeSourceLabel(value: string) {
  const lower = value.toLowerCase();
  if (lower.includes('futu')) return '系统 Futu 行情';
  if (lower.includes('broker')) return '系统行情数据';
  return value;
}

function describeValuation({
  originalCurrency,
  baseCurrency,
  originalValue,
  baseValue,
  usesEstimatedFx,
}: {
  originalCurrency?: string;
  baseCurrency?: string;
  originalValue?: number;
  baseValue?: number;
  usesEstimatedFx?: boolean;
}) {
  const sourceCurrency = originalCurrency || baseCurrency || 'USD';
  const displayCurrency = baseCurrency || sourceCurrency;
  const converted = Boolean(
    sourceCurrency &&
      displayCurrency &&
      sourceCurrency !== displayCurrency &&
      baseValue !== undefined
  );

  return {
    detail:
      converted && originalValue !== undefined
        ? `原币 ${formatCurrency(originalValue, sourceCurrency)}`
        : `原币 ${sourceCurrency}`,
    basis: usesEstimatedFx
      ? `按 ${displayCurrency} 估算汇率折算，仅供参考`
      : converted
        ? `按 ${displayCurrency} 折算展示`
        : `原币 ${sourceCurrency} 展示`,
  };
}

function isEstimatePosition(fxSource?: string) {
  const normalized = fxSource?.trim().toLowerCase();
  return normalized === 'estimated_fx' || normalized === 'fallback_estimate';
}

function inferDiscipline(pnlPct?: number, concentration?: number) {
  if ((concentration ?? 0) >= 25) return 'blocked';
  if ((concentration ?? 0) >= 18 || (pnlPct ?? 0) <= -5) return 'watch';
  return 'clear';
}

function formatCurrency(value?: number, currency = 'USD', signed = false) {
  if (value === undefined || Number.isNaN(value)) return '--';
  const formatter = new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    minimumFractionDigits: Math.abs(value) < 10 ? 2 : 0,
    maximumFractionDigits: Math.abs(value) < 10 ? 2 : 0,
  });
  const absolute = formatter.format(Math.abs(value));
  if (value < 0) return `-${absolute}`;
  if (signed && value > 0) return `+${absolute}`;
  return formatter.format(value);
}

function formatPercent(value?: number) {
  if (value === undefined || Number.isNaN(value)) return '--';
  return `${value > 0 ? '+' : ''}${value.toFixed(1)}%`;
}

function formatQuantity(value: number) {
  if (Number.isInteger(value)) return String(value);
  return value.toFixed(2);
}

function formatDateTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, '0');
  const day = String(date.getDate()).padStart(2, '0');
  const hours = String(date.getHours()).padStart(2, '0');
  const minutes = String(date.getMinutes()).padStart(2, '0');
  return `${year}-${month}-${day} ${hours}:${minutes}`;
}

function compactDateTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const hours = String(date.getHours()).padStart(2, '0');
  const minutes = String(date.getMinutes()).padStart(2, '0');
  return `${hours}:${minutes}`;
}

function formatFreshness(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const diffSeconds = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
  if (diffSeconds < 60) return `${diffSeconds}s`;
  const diffMinutes = Math.floor(diffSeconds / 60);
  if (diffMinutes < 60) return `${diffMinutes}m`;
  const diffHours = Math.floor(diffMinutes / 60);
  if (diffHours < 24) return `${diffHours}h`;
  const diffDays = Math.floor(diffHours / 24);
  return `${diffDays}d`;
}

export async function getWorkspaceSnapshot(options?: { state?: PageState; viewId?: string }): Promise<WorkspaceResponse> {
  const state = options?.state ?? 'ready';

  if (state === 'loading') return { state };

  if (state === 'error') {
    return {
      state,
      errorMessage: '页面数据暂时不可用，请稍后重试或检查数据连接状态。',
    };
  }

  const session = await getCurrentSession();
  const account = session && accountDatabaseConfigured() ? await ensureUserAccount(session.user) : null;
  const workspace = withView(structuredClone(baseWorkspace), options?.viewId);
  if (account) {
    applyAccountWorkspace(workspace, account, options?.viewId);
  }

  if (state === 'empty') {
    workspace.dashboard.metrics = workspace.dashboard.metrics.map((metric) =>
      metric.label === '待处理'
        ? { ...metric, value: '0', hint: '暂无待处理项' }
        : metric.label === '总资产'
          ? { ...metric, value: '$0', hint: '等待首次同步或录入' }
          : metric
    );
    workspace.dashboard.holdingsPreview = [];
    workspace.dashboard.optionsPreview = [];
    workspace.dashboard.actions = [];
    workspace.holdings.equity = [];
    workspace.holdings.options = [];
    workspace.sellPut.positions = [];
    workspace.sellPut.candidates = [];
    workspace.data.connections = [];
    workspace.ops.jobs = [];
    workspace.ops.deliveries = [];
    workspace.ops.replayQueue = [];
  }

  let liveData: P0ApiDataState | undefined;

  if (state === 'ready' || state === 'degraded') {
    const live = await fetchP0ApiSnapshot({ tenantId: account?.tenantId });
    let effectiveLive = live;
    if (account && !hasPortfolioData(live)) {
      const manual = await listManualPositions(account);
      if (manual.positions.length > 0) {
        effectiveLive = buildManualP0Snapshot(account, manual, live.dataState.baseUrl);
      }
    }
    liveData = effectiveLive.dataState;
    applyLiveData(workspace, effectiveLive);
    if (account && !hasPortfolioData(effectiveLive)) {
      applyAccountEmptyWorkspace(workspace, account);
    }
  }

  if (state === 'degraded') {
    workspace.chrome.sources = workspace.chrome.sources.map((source) =>
      source.key === 'option-chain' || source.key === 'portfolio-positions'
        ? {
            ...source,
            status: 'degraded',
            freshnessLabel: '92s',
            reason: '期权链更新超出交易建议要求，候选只提供观察结论。',
            actionability: 'analysis_only',
          }
        : source
    );
    workspace.sellPut.metrics[5] = {
      label: '候选池',
      value: '4',
      hint: '当前全部仅供参考',
      tone: 'warning',
    };
    workspace.sellPut.positions = workspace.sellPut.positions.map((position) => ({
      ...position,
      actionability: 'analysis_only',
      source: position.source === '系统期权链' ? '系统行情更新延迟' : position.source,
      freshness: position.freshness === '44s' ? '92s' : position.freshness,
    }));
    workspace.sellPut.candidates = workspace.sellPut.candidates.map((candidate) => ({
      ...candidate,
      result: candidate.result === 'blocked' ? 'blocked' : 'analysis_only',
      note:
        candidate.result === 'blocked'
          ? candidate.note
          : '数据更新不满足交易建议要求，只输出观察结论。',
    }));
  }

  return { state, data: workspace, liveData };
}

export async function getChromeSnapshot(): Promise<ChromeSnapshot> {
  const session = await getCurrentSession();
  const workspace = structuredClone(baseWorkspace);
  if (session && accountDatabaseConfigured()) {
    try {
      const account = await getAccountWorkspace(session.user);
      applyAccountWorkspace(workspace, account);
      const live = await fetchP0ApiSnapshot({ tenantId: account.tenantId });
      applyLiveData(workspace, live);
    } catch {
      // Chrome should not block page rendering if the account workspace is not initialized yet.
    }
  }
  return workspace.chrome;
}

export function findEquityBySymbol(workspace: WorkspaceSnapshot, symbol: string) {
  return workspace.holdings.equity.find((holding) => holding.symbol === symbol);
}
