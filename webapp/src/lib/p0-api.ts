const DEFAULT_DATA_SERVICE_BASE_URL = 'http://127.0.0.1:8000';
const DEFAULT_P0_TENANT_ID = '00000000-0000-0000-0000-000000000000';
const REQUEST_TIMEOUT_MS = 2500;

type ApiResultMode = 'live' | 'partial' | 'fallback';
type ConnectionStatus = 'connected' | 'degraded' | 'disconnected';
type SyncStatus = 'success' | 'warning' | 'failed' | 'running';
export type P0QualityFreshness = 'fresh' | 'degraded' | 'stale' | 'missing' | 'unknown';
export type P0QualityActionability = 'trade_draft' | 'analysis_only' | 'blocked';

interface CandidateFetchResult {
  path: string;
  data: unknown;
}

export interface P0ApiOverview {
  currency: string;
  baseCurrency: string;
  currencies: string[];
  totalAssetValue?: number;
  cashAvailable?: number;
  marginUsed?: number;
  cashSecured?: number;
  holdingsCount?: number;
  equityCount?: number;
  optionCount?: number;
  equityMarketValue?: number;
  optionMarketValue?: number;
  grossMarketValue?: number;
  updatedAt?: string;
  fxSource?: string;
  sourceQuality?: string;
  usesEstimatedFx?: boolean;
}

export interface P0ApiEquityPosition {
  id: string;
  symbol: string;
  name: string;
  market: string;
  currency: string;
  baseCurrency: string;
  quantity?: number;
  marketValue?: number;
  originalMarketValue?: number;
  baseMarketValue?: number;
  averageCost?: number;
  originalAverageCost?: number;
  baseAverageCost?: number;
  marketPrice?: number;
  originalMarketPrice?: number;
  baseMarketPrice?: number;
  unrealizedPnlPct?: number;
  updatedAt?: string;
  source: string;
  fxSource?: string;
  sourceQuality?: string;
}

export interface P0ApiOptionPosition {
  id: string;
  underlying: string;
  contract: string;
  currency: string;
  baseCurrency: string;
  quantity?: number;
  marketValue?: number;
  originalMarketValue?: number;
  baseMarketValue?: number;
  marketPrice?: number;
  originalMarketPrice?: number;
  baseMarketPrice?: number;
  averageCost?: number;
  originalAverageCost?: number;
  baseAverageCost?: number;
  strike?: number;
  expiry?: string;
  daysToExpiry?: number;
  delta?: number;
  impliedVolatility?: number;
  optionType?: string;
  cashRequired?: number;
  originalCashRequired?: number;
  baseCashRequired?: number;
  marginRequired?: number;
  originalMarginRequired?: number;
  baseMarginRequired?: number;
  updatedAt?: string;
  source: string;
  fxSource?: string;
  sourceQuality?: string;
}

export interface P0ApiConnection {
  id: string;
  provider: string;
  accountLabel: string;
  authStatus: ConnectionStatus;
  permissionScope: string;
  lastSync?: string;
  updatedAt?: string;
  detail?: string;
}

export interface P0ApiSyncEvent {
  id: string;
  title: string;
  status: SyncStatus;
  startedAt?: string;
  detail: string;
}

export interface P0ApiAssetSource {
  id: string;
  label: string;
  type: string;
  priority: string;
  confidence: string;
  freshness: string;
  lineage: string;
}

export interface P0QualityDisplay {
  schemaVersion: 'quality_display_v1';
  source: string;
  asOf?: string;
  freshness: P0QualityFreshness;
  freshnessLabel: string;
  actionability: P0QualityActionability;
  actionabilityLabel: string;
  degradeReason?: string;
  degradeReasonLabel: string;
  summary: string;
}

export interface P0ApiDataState {
  mode: ApiResultMode;
  label: string;
  detail: string;
  updatedAt?: string;
  baseUrl: string;
  sourcePath?: string;
  error?: string;
  baseCurrency?: string;
  fxSource?: string;
  usesEstimatedFx?: boolean;
  valuationDetail?: string;
}

export interface P0ApiSnapshot {
  dataState: P0ApiDataState;
  overview?: P0ApiOverview;
  equityPositions: P0ApiEquityPosition[];
  optionPositions: P0ApiOptionPosition[];
  connections: P0ApiConnection[];
  syncEvents: P0ApiSyncEvent[];
  assetSources: P0ApiAssetSource[];
}

export interface FetchP0ApiSnapshotOptions {
  tenantId?: string;
}

export function getDataServiceBaseUrl() {
  return (
    process.env.NEXT_PUBLIC_DATA_SERVICE_URL ||
    process.env.DATA_SERVICE_URL ||
    DEFAULT_DATA_SERVICE_BASE_URL
  ).replace(/\/+$/, '');
}

export function getP0TenantId(tenantId?: string) {
  const requestedTenantId = tenantId?.trim();
  if (requestedTenantId) {
    return requestedTenantId;
  }

  return (
    process.env.NEXT_PUBLIC_P0_TENANT_ID ||
    process.env.P0_TENANT_ID ||
    DEFAULT_P0_TENANT_ID
  );
}

export function normalizeQualityDisplay(payload: unknown): P0QualityDisplay {
  const quality = findQualityDisplayRecord(payload);
  const dataQuality = findDataQualityRecord(payload);
  const source =
    getString(quality, ['source', 'source_key', 'sourceKey']) ||
    getString(dataQuality, ['source', 'quote_source', 'quoteSource', 'source_key', 'sourceKey']) ||
    'unknown';
  const asOf =
    getString(quality, ['as_of', 'asOf']) ||
    getString(dataQuality, ['as_of', 'asOf', 'quote_as_of', 'quoteAsOf', 'updated_at', 'updatedAt']);
  const freshness = normalizeQualityFreshness(
    getString(quality, ['freshness']) ||
      getString(asRecord(quality?.freshness), ['status']) ||
      getString(dataQuality, ['freshness']) ||
      getString(asRecord(dataQuality?.freshness), ['status']),
    getNumber(dataQuality, ['freshness_seconds', 'freshnessSeconds']),
    Boolean(asOf || source !== 'unknown')
  );
  const actionability = normalizeQualityActionability(
    getString(quality, ['actionability']) ||
      getString(dataQuality, ['actionability', 'actionability_cap', 'actionabilityCap', 'quote_actionability', 'quoteActionability'])
  );
  const degradeReason =
    getString(quality, ['degrade_reason', 'degradeReason']) ||
    getString(dataQuality, ['degrade_reason', 'degradeReason']) ||
    inferQualityDegradeReason({
      freshness,
      actionability,
      portfolioContext: getString(dataQuality, ['portfolio_context', 'portfolioContext']),
      missing: getStringArray(dataQuality, ['missing']),
    });
  const freshnessLabel =
    getString(quality, ['freshness_label', 'freshnessLabel']) || qualityFreshnessLabel(freshness);
  const actionabilityLabel =
    getString(quality, ['actionability_label', 'actionabilityLabel']) ||
    qualityActionabilityLabel(actionability);
  const degradeReasonLabel =
    getString(quality, ['degrade_reason_label', 'degradeReasonLabel']) ||
    qualityDegradeReasonLabel(degradeReason);
  const summary =
    getString(quality, ['summary']) ||
    qualityDisplaySummary({
      source,
      freshnessLabel,
      actionabilityLabel,
      degradeReason,
      degradeReasonLabel,
    });

  return {
    schemaVersion: 'quality_display_v1',
    source,
    asOf,
    freshness,
    freshnessLabel,
    actionability,
    actionabilityLabel,
    degradeReason,
    degradeReasonLabel,
    summary,
  };
}

export async function fetchP0ApiSnapshot(options: FetchP0ApiSnapshotOptions = {}): Promise<P0ApiSnapshot> {
  const baseUrl = getDataServiceBaseUrl();
  const errors: string[] = [];

  const [overviewResult, positionsResult, statusResult, healthResult, capabilitiesResult] =
    await Promise.all([
      fetchCandidate(baseUrl, OVERVIEW_PATHS, errors, options.tenantId),
      fetchCandidate(baseUrl, POSITIONS_PATHS, errors, options.tenantId),
      fetchCandidate(baseUrl, STATUS_PATHS, errors, options.tenantId),
      fetchCandidate(baseUrl, HEALTH_PATHS, errors, options.tenantId),
      fetchCandidate(baseUrl, CAPABILITY_PATHS, errors, options.tenantId),
    ]);

  const overview = normalizeOverview(overviewResult?.data);
  const positions = normalizePositions(positionsResult?.data);
  const status = normalizeStatus(
    statusResult?.data,
    healthResult?.data,
    capabilitiesResult?.data,
    overview?.updatedAt || positions.updatedAt
  );

  const derivedOverview = deriveOverview(overview, positions);
  const valuation = summarizeValuation(derivedOverview, positions);
  const updatedAt =
    derivedOverview?.updatedAt ||
    positions.updatedAt ||
    status.connections[0]?.lastSync ||
    status.connections[0]?.updatedAt;

  const hasOverview = Boolean(derivedOverview);
  const hasPositions = positions.equity.length > 0 || positions.options.length > 0;
  const hasStatus =
    status.connections.length > 0 ||
    status.syncEvents.length > 0 ||
    status.assetSources.length > 0;

  if (!hasOverview && !hasPositions && !hasStatus) {
    return {
      dataState: {
        mode: 'fallback',
        label: '当前显示参考视图',
        detail: errors[0]
          ? `暂时还没拿到最新账户数据，当前先展示参考数据。${errors[0]}`
          : '暂时还没拿到最新账户数据，当前先展示参考数据。',
        baseUrl,
        error: errors[0],
      },
      equityPositions: [],
      optionPositions: [],
      connections: [],
      syncEvents: [],
      assetSources: [],
    };
  }

  const mode: ApiResultMode =
    hasOverview && hasPositions ? 'live' : 'partial';
  const detailSegments = [
    mode === 'live'
      ? '页面优先展示最新账户数据；少量尚未补齐的区块会继续明确标记。'
      : '已接到部分真实数据，其余字段会明确标记为待补全，避免把参考数据误读成真实账户数据。',
  ];

  if (valuation.valuationDetail) {
    detailSegments.push(valuation.valuationDetail);
  }

  return {
    dataState: {
      mode,
      label: mode === 'live' ? '实时数据已接入' : '部分实时数据已接入',
      detail: detailSegments.join(' '),
      updatedAt,
      baseUrl,
      sourcePath:
        overviewResult?.path ||
        positionsResult?.path ||
        statusResult?.path ||
        healthResult?.path ||
        capabilitiesResult?.path,
      error: errors[0],
      baseCurrency: valuation.baseCurrency,
      fxSource: valuation.fxSource,
      usesEstimatedFx: valuation.usesEstimatedFx,
      valuationDetail: valuation.valuationDetail,
    },
    overview: derivedOverview,
    equityPositions: positions.equity,
    optionPositions: positions.options,
    connections: status.connections,
    syncEvents: status.syncEvents,
    assetSources: status.assetSources,
  };
}

const OVERVIEW_PATHS = [
  '/api/v3/portfolio/overview',
  '/api/v1/portfolio/overview',
  '/api/v1/overview',
  '/api/portfolio/overview',
  '/api/v1/p0/overview',
];

const POSITIONS_PATHS = [
  '/api/v3/portfolio/positions',
  '/api/v1/portfolio/positions',
  '/api/v1/positions',
  '/api/portfolio/positions',
  '/api/v1/p0/positions',
];

const STATUS_PATHS = [
  '/api/v1/portfolio/status',
  '/api/v1/portfolio/connections',
  '/api/v1/data/status',
  '/api/v1/connection-status',
];

const HEALTH_PATHS = ['/health'];
const CAPABILITY_PATHS = ['/api/v3/broker/futu/capabilities'];

async function fetchCandidate(
  baseUrl: string,
  paths: string[],
  errors: string[],
  tenantId?: string
): Promise<CandidateFetchResult | undefined> {
  for (const path of paths) {
    try {
      const data = await fetchJson(baseUrl, path, tenantId);
      return { path, data };
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      errors.push(`${path}: ${message}`);
    }
  }
  return undefined;
}

async function fetchJson(baseUrl: string, path: string, tenantId?: string) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS);

  try {
    const url = new URL(path, `${baseUrl}/`);
    const resolvedTenantId = getP0TenantId(tenantId);
    if (needsTenantId(url) && !url.searchParams.has('tenant_id')) {
      url.searchParams.set('tenant_id', resolvedTenantId);
    }

    const headers: Record<string, string> = {
      Accept: 'application/json',
    };
    if (process.env.DATA_SERVICE_INTERNAL_TOKEN && tenantId) {
      headers['X-Data-Service-Token'] = process.env.DATA_SERVICE_INTERNAL_TOKEN;
      headers['X-Data-Service-Tenant-Id'] = resolvedTenantId;
    }

    const response = await fetch(url.toString(), {
      method: 'GET',
      cache: 'no-store',
      signal: controller.signal,
      headers,
    });

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    return response.json();
  } finally {
    clearTimeout(timeout);
  }
}

function needsTenantId(url: URL) {
  return url.pathname.startsWith('/api/v3/portfolio/');
}

function unwrapPayload<T>(payload: T): unknown {
  if (payload && typeof payload === 'object' && 'data' in (payload as Record<string, unknown>)) {
    return (payload as Record<string, unknown>).data;
  }
  return payload;
}

function normalizeOverview(payload: unknown): P0ApiOverview | undefined {
  const data = asRecord(unwrapPayload(payload));
  if (!data) return undefined;

  const freshness = asRecord(data.freshness);
  const currencies = getStringArray(data, ['currencies']);
  const baseCurrency =
    getString(data, ['base_currency', 'baseCurrency']) ||
    getString(data, ['currency']) ||
    currencies[0] ||
    'USD';
  const cashBalances = getArray(data, ['cash_balances', 'cashBalances']);
  const grossMarketValue = getNumber(data, ['gross_market_value', 'grossMarketValue']);
  const fxSource = getString(data, ['fx_source', 'fxSource']);
  const sourceQuality = getString(data, ['source_quality', 'sourceQuality']);

  const overview: P0ApiOverview = {
    currency: baseCurrency,
    baseCurrency,
    currencies,
    totalAssetValue: getNumber(data, [
      'base_total_asset_value',
      'baseTotalAssetValue',
      'base_total_assets',
      'baseTotalAssets',
      'base_portfolio_value',
      'basePortfolioValue',
      'base_total_value',
      'baseTotalValue',
      'base_net_liquidation',
      'baseNetLiquidation',
      'total_assets',
      'totalAssets',
      'portfolio_value',
      'portfolioValue',
      'total_value',
      'totalValue',
      'net_liquidation',
      'netLiquidation',
    ]),
    cashAvailable:
      getNumber(data, [
        'base_cash_available',
        'baseCashAvailable',
        'base_available_cash',
        'baseAvailableCash',
        'base_cash',
        'baseCash',
        'cash_available',
        'cashAvailable',
        'available_cash',
        'availableCash',
        'cash',
      ]) ??
      sumNumbers(cashBalances, ['available_cash', 'availableCash']),
    marginUsed: getNumber(data, [
      'base_margin_used',
      'baseMarginUsed',
      'base_margin_requirement',
      'baseMarginRequirement',
      'margin_used',
      'marginUsed',
      'margin_requirement',
      'marginRequirement',
      'initial_margin',
      'initialMargin',
    ]),
    cashSecured:
      getNumber(data, [
        'base_cash_secured',
        'baseCashSecured',
        'base_cash_secured_requirement',
        'baseCashSecuredRequirement',
        'cash_secured',
        'cashSecured',
        'cash_secured_requirement',
        'cashSecuredRequirement',
        'cash_secured_reserve',
        'cashSecuredReserve',
      ]) ??
      sumNumbers(cashBalances, ['cash_secured_reserve', 'cashSecuredReserve']),
    holdingsCount: getNumber(data, ['positions_count', 'positionsCount', 'holdings_count', 'holdingsCount']),
    equityCount: getNumber(data, [
      'equity_positions_count',
      'equityPositionsCount',
      'stock_positions_count',
      'stockPositionsCount',
    ]),
    optionCount: getNumber(data, [
      'option_positions_count',
      'optionPositionsCount',
      'options_count',
      'optionsCount',
    ]),
    equityMarketValue: getNumber(data, [
      'base_equity_market_value',
      'baseEquityMarketValue',
      'base_stock_market_value',
      'baseStockMarketValue',
      'equity_market_value',
      'equityMarketValue',
      'stock_market_value',
      'stockMarketValue',
    ]),
    optionMarketValue: getNumber(data, [
      'base_option_market_value',
      'baseOptionMarketValue',
      'option_market_value',
      'optionMarketValue',
    ]),
    grossMarketValue,
    updatedAt:
      getString(freshness, ['as_of', 'asOf', 'received_at', 'receivedAt']) ||
      getString(data, [
      'updated_at',
      'updatedAt',
      'as_of',
      'asOf',
      'data_timestamp',
      'dataTimestamp',
      'last_synced_at',
      'lastSyncedAt',
      ]),
    fxSource,
    sourceQuality,
    usesEstimatedFx: isEstimatedFxSource(fxSource),
  };

  return hasAnyDefinedValue(overview) ? overview : undefined;
}

function normalizePositions(payload: unknown) {
  const data = unwrapPayload(payload);
  const topLevel = asRecord(data);
  const freshness = asRecord(topLevel?.freshness);
  const defaultBaseCurrency =
    getString(topLevel, ['base_currency', 'baseCurrency']) ||
    getString(freshness, ['base_currency', 'baseCurrency']) ||
    'USD';
  const defaultFxSource =
    getString(topLevel, ['fx_source', 'fxSource']) ||
    getString(freshness, ['fx_source', 'fxSource']);
  const defaultSourceQuality = getString(topLevel, ['source_quality', 'sourceQuality']);
  const updatedAt =
    getString(freshness, ['as_of', 'asOf', 'received_at', 'receivedAt']) ||
    getString(topLevel, ['updated_at', 'updatedAt', 'as_of', 'asOf']) ||
    undefined;

  const explicitEquity = topLevel
    ? getArray(topLevel, [
        'equity_positions',
        'equityPositions',
        'equity',
        'equities',
        'stock_positions',
        'stockPositions',
      ])
    : [];
  const explicitOptions = topLevel
    ? getArray(topLevel, [
        'option_positions',
        'optionPositions',
        'options',
        'option_positions',
      ])
    : [];
  const rawAll =
    Array.isArray(data)
      ? data
      : topLevel
        ? getArray(topLevel, ['positions', 'items'])
        : [];

  const partitioned = rawAll.reduce(
    (acc, item) => {
      const type = getInstrumentType(item);
      if (type === 'option') {
        acc.options.push(item);
      } else {
        acc.equity.push(item);
      }
      return acc;
    },
    { equity: [] as unknown[], options: [] as unknown[] }
  );

  const equitySource = explicitEquity.length ? explicitEquity : partitioned.equity;
  const optionSource = explicitOptions.length ? explicitOptions : partitioned.options;

  return {
    equity: equitySource
      .map((item: unknown, index: number) =>
        normalizeEquityPosition(item, index, {
          updatedAt,
          baseCurrency: defaultBaseCurrency,
          fxSource: defaultFxSource,
          sourceQuality: defaultSourceQuality,
        })
      )
      .filter(Boolean) as P0ApiEquityPosition[],
    options: optionSource
      .map((item: unknown, index: number) =>
        normalizeOptionPosition(item, index, {
          updatedAt,
          baseCurrency: defaultBaseCurrency,
          fxSource: defaultFxSource,
          sourceQuality: defaultSourceQuality,
        })
      )
      .filter(Boolean) as P0ApiOptionPosition[],
    updatedAt,
  };
}

function normalizeEquityPosition(
  payload: unknown,
  index: number,
  defaults: {
    updatedAt?: string;
    baseCurrency: string;
    fxSource?: string;
    sourceQuality?: string;
  }
): P0ApiEquityPosition | undefined {
  const data = asRecord(payload);
  if (!data) return undefined;

  const symbol = getString(data, ['symbol', 'ticker', 'provider_symbol']);
  if (!symbol) return undefined;

  const currency = getString(data, ['currency']) || defaults.baseCurrency;
  const baseCurrency = getString(data, ['base_currency', 'baseCurrency']) || defaults.baseCurrency || currency;
  const originalMarketValue =
    getNumber(data, ['market_value', 'marketValue']) ??
    computePositionMarketValue(data, 1);
  const baseMarketValue = getNumber(data, ['base_market_value', 'baseMarketValue']);
  const originalAverageCost = getNumber(data, ['average_cost', 'averageCost', 'cost_basis', 'costBasis']);
  const baseAverageCost = getNumber(data, [
    'base_average_cost',
    'baseAverageCost',
    'base_cost_basis',
    'baseCostBasis',
  ]);
  const originalMarketPrice = getNumber(data, ['market_price', 'marketPrice', 'price', 'last_price', 'lastPrice']);
  const baseMarketPrice = getNumber(data, ['base_market_price', 'baseMarketPrice']);
  const fxSource = getString(data, ['fx_source', 'fxSource']) || defaults.fxSource;
  const sourceQuality = getString(data, ['source_quality', 'sourceQuality']) || defaults.sourceQuality;

  return {
    id: getString(data, ['id']) || `equity-${symbol}-${index}`,
    symbol,
    name: getString(data, ['name', 'display_name', 'displayName']) || symbol,
    market: getString(data, ['market', 'exchange']) || 'US',
    currency,
    baseCurrency,
    quantity: getNumber(data, ['quantity', 'qty']),
    marketValue: baseMarketValue ?? originalMarketValue,
    originalMarketValue,
    baseMarketValue: baseMarketValue ?? (baseCurrency === currency ? originalMarketValue : undefined),
    averageCost: baseAverageCost ?? originalAverageCost,
    originalAverageCost,
    baseAverageCost: baseAverageCost ?? (baseCurrency === currency ? originalAverageCost : undefined),
    marketPrice: baseMarketPrice ?? originalMarketPrice,
    originalMarketPrice,
    baseMarketPrice: baseMarketPrice ?? (baseCurrency === currency ? originalMarketPrice : undefined),
    unrealizedPnlPct:
      getNumber(data, ['unrealized_pnl_pct', 'unrealizedPnlPct', 'pnl_pct', 'pnlPct']) ??
      computeUnrealizedPnlPct(originalMarketPrice, originalAverageCost),
    updatedAt:
      getString(data, ['updated_at', 'updatedAt', 'as_of', 'asOf']) || defaults.updatedAt,
    source: getString(data, ['source', 'provider', 'source_key', 'sourceKey']) || '用户确认持仓',
    fxSource,
    sourceQuality,
  };
}

function normalizeOptionPosition(
  payload: unknown,
  index: number,
  defaults: {
    updatedAt?: string;
    baseCurrency: string;
    fxSource?: string;
    sourceQuality?: string;
  }
): P0ApiOptionPosition | undefined {
  const data = asRecord(payload);
  if (!data) return undefined;

  const contract =
    getString(data, ['contract', 'contract_symbol', 'contractSymbol', 'symbol', 'provider_symbol']) ||
    undefined;
  if (!contract) return undefined;

  const quantity = getNumber(data, ['quantity', 'qty']);
  const multiplier = getNumber(data, ['contract_size', 'contractSize']) || 100;
  const currency = getString(data, ['currency']) || defaults.baseCurrency;
  const baseCurrency = getString(data, ['base_currency', 'baseCurrency']) || defaults.baseCurrency || currency;
  const originalMarketPrice = getNumber(data, ['market_price', 'marketPrice', 'price', 'last_price', 'lastPrice']);
  const baseMarketPrice = getNumber(data, ['base_market_price', 'baseMarketPrice']);
  const originalMarketValue =
    getNumber(data, ['market_value', 'marketValue']) ??
    computePositionMarketValue(data, multiplier);
  const baseMarketValue = getNumber(data, ['base_market_value', 'baseMarketValue']);
  const strike = getNumber(data, ['strike', 'strike_price', 'strikePrice']);
  const expiry = getString(data, ['expiry', 'expiration', 'expiry_date', 'expiryDate']) || undefined;
  const originalAverageCost = getNumber(data, ['average_cost', 'averageCost', 'cost_basis', 'costBasis']);
  const baseAverageCost = getNumber(data, [
    'base_average_cost',
    'baseAverageCost',
    'base_cost_basis',
    'baseCostBasis',
  ]);
  const originalCashRequired =
    getNumber(data, ['cash_required', 'cashRequired']) ??
    computeCashRequired(quantity, strike, multiplier);
  const baseCashRequired = getNumber(data, ['base_cash_required', 'baseCashRequired']);
  const originalMarginRequired = getNumber(data, ['margin_required', 'marginRequired']);
  const baseMarginRequired = getNumber(data, ['base_margin_required', 'baseMarginRequired']);
  const fxSource = getString(data, ['fx_source', 'fxSource']) || defaults.fxSource;
  const sourceQuality = getString(data, ['source_quality', 'sourceQuality']) || defaults.sourceQuality;

  return {
    id: getString(data, ['id']) || `option-${contract}-${index}`,
    underlying:
      getString(data, ['underlying', 'underlying_symbol', 'underlyingSymbol']) ||
      inferUnderlyingSymbol(contract),
    contract,
    currency,
    baseCurrency,
    quantity,
    marketValue: baseMarketValue ?? originalMarketValue,
    originalMarketValue,
    baseMarketValue: baseMarketValue ?? (baseCurrency === currency ? originalMarketValue : undefined),
    marketPrice: baseMarketPrice ?? originalMarketPrice,
    originalMarketPrice,
    baseMarketPrice: baseMarketPrice ?? (baseCurrency === currency ? originalMarketPrice : undefined),
    averageCost: baseAverageCost ?? originalAverageCost,
    originalAverageCost,
    baseAverageCost: baseAverageCost ?? (baseCurrency === currency ? originalAverageCost : undefined),
    strike,
    expiry,
    daysToExpiry:
      getNumber(data, ['days_to_expiry', 'daysToExpiry', 'dte']) ??
      computeDaysToExpiry(expiry),
    delta: getNumber(data, ['delta']),
    impliedVolatility:
      getNumber(data, ['implied_volatility', 'impliedVolatility', 'iv']),
    optionType: getString(data, ['option_type', 'optionType']),
    cashRequired: baseCashRequired ?? originalCashRequired,
    originalCashRequired,
    baseCashRequired: baseCashRequired ?? (baseCurrency === currency ? originalCashRequired : undefined),
    marginRequired: baseMarginRequired ?? originalMarginRequired,
    originalMarginRequired,
    baseMarginRequired: baseMarginRequired ?? (baseCurrency === currency ? originalMarginRequired : undefined),
    updatedAt:
      getString(data, ['updated_at', 'updatedAt', 'as_of', 'asOf']) || defaults.updatedAt,
    source: getString(data, ['source', 'provider', 'source_key', 'sourceKey']) || '用户确认期权持仓',
    fxSource,
    sourceQuality,
  };
}

function normalizeStatus(
  payload: unknown,
  healthPayload: unknown,
  capabilitiesPayload: unknown,
  updatedAt?: string
) {
  const data = asRecord(unwrapPayload(payload));
  const health = asRecord(healthPayload);
  const capabilities = asRecord(unwrapPayload(capabilitiesPayload));

  const connections = normalizeConnections(data, capabilities, updatedAt);
  const syncEvents = normalizeSyncEvents(data, health, updatedAt);
  const assetSources = normalizeAssetSources(data, health, capabilities, updatedAt);

  return { connections, syncEvents, assetSources };
}

function normalizeConnections(
  statusData?: Record<string, unknown> | null,
  capabilities?: Record<string, unknown> | null,
  updatedAt?: string
): P0ApiConnection[] {
  const rawConnections = statusData
    ? [
        ...getArray(statusData, ['connections', 'brokers', 'accounts']),
        ...getArray(statusData, ['connection']).filter((item: unknown) => Boolean(item)),
      ]
    : [];

  if (rawConnections.length) {
    return rawConnections
      .map((item: unknown, index: number) => {
        const data = asRecord(item);
        if (!data) return undefined;
        const status =
          getString(data, ['auth_status', 'authStatus', 'status', 'connection_status', 'connectionStatus']) ||
          'connected';
        return {
          id: getString(data, ['id', 'broker_connection_id', 'brokerConnectionId']) || `connection-${index}`,
          provider: getString(data, ['provider', 'broker']) || '系统行情源',
          accountLabel:
            getString(data, ['account_label', 'accountLabel', 'label', 'name']) || `账户 ${index + 1}`,
          authStatus: mapConnectionStatus(status),
          permissionScope:
            getString(data, ['permission_scope', 'permissionScope']) || '管理员只读行情 / 期权链',
          lastSync:
            getString(data, ['last_sync', 'lastSync', 'last_synced_at', 'lastSyncedAt']) || updatedAt,
          updatedAt:
            getString(data, ['updated_at', 'updatedAt', 'as_of', 'asOf']) || updatedAt,
          detail:
            getString(data, ['detail', 'message', 'degradation', 'reason']) || undefined,
        };
      })
      .filter(Boolean) as P0ApiConnection[];
  }

  if (!capabilities) return [];

  const connectorMode = getString(capabilities, ['connector_mode', 'connectorMode']) || 'unknown';
  const supports = asRecord(capabilities.supports);
  const permissionScope =
    getString(capabilities, ['permission_scope', 'permissionScope']) || '管理员只读行情 / 期权链';
  const notes = Array.isArray(capabilities.notes)
    ? capabilities.notes.filter((item): item is string => typeof item === 'string')
    : [];
  const isConnected = supports && supports.positions === true;

  return [
    {
      id: 'futu-capability',
      provider: '系统 Futu 行情源',
      accountLabel: isConnected ? '管理员侧行情源' : '等待系统行情源',
      authStatus: isConnected ? 'connected' : 'degraded',
      permissionScope,
      lastSync: updatedAt,
      updatedAt,
      detail: normalizeUserFacingNote(notes[0]),
    },
  ];
}

function normalizeSyncEvents(
  statusData?: Record<string, unknown> | null,
  health?: Record<string, unknown> | null,
  updatedAt?: string
): P0ApiSyncEvent[] {
  const rawEvents = statusData
    ? getArray(statusData, ['sync_events', 'syncEvents', 'events', 'recent_syncs', 'recentSyncs'])
    : [];

  if (rawEvents.length) {
    return rawEvents
      .map((item: unknown, index: number) => {
        const data = asRecord(item);
        if (!data) return undefined;
        const status =
          getString(data, ['status', 'sync_status', 'syncStatus']) || 'success';
        return {
          id: getString(data, ['id']) || `sync-${index}`,
          title: getString(data, ['title', 'label', 'name']) || '最近同步',
          status: mapSyncStatus(status),
          startedAt:
            getString(data, ['started_at', 'startedAt', 'updated_at', 'updatedAt', 'as_of', 'asOf']) ||
            updatedAt,
          detail:
            getString(data, ['detail', 'message', 'reason']) || '最近一次同步已记录。',
        };
      })
      .filter(Boolean) as P0ApiSyncEvent[];
  }

  if (!health) return [];

  const gateway = asRecord(health.gateway);
  const gatewayStatus =
    getString(gateway, ['status', 'state']) || getString(health, ['status']) || 'unknown';

  return [
    {
      id: 'health-check',
      title: '系统行情源',
      status: gatewayStatus === 'ok' ? 'success' : 'warning',
      startedAt: updatedAt,
      detail:
        gatewayStatus === 'ok'
          ? '系统行情源可访问，页面会优先尝试读取最新行情数据。'
          : '系统行情源可访问，但尚未返回完整更新状态。',
    },
  ];
}

function normalizeAssetSources(
  statusData?: Record<string, unknown> | null,
  health?: Record<string, unknown> | null,
  capabilities?: Record<string, unknown> | null,
  updatedAt?: string
): P0ApiAssetSource[] {
  const rawSources = statusData
    ? getArray(statusData, ['asset_sources', 'assetSources', 'sources'])
    : [];

  if (rawSources.length) {
    return rawSources
      .map((item: unknown, index: number) => {
        const data = asRecord(item);
        if (!data) return undefined;
        return {
          id: getString(data, ['id']) || `source-${index}`,
          label: getString(data, ['label', 'name', 'provider']) || `来源 ${index + 1}`,
          type: getString(data, ['type', 'kind']) || '账户更新',
          priority: getString(data, ['priority']) || '主要',
          confidence: formatConfidence(getNumber(data, ['confidence'])),
          freshness:
            getString(data, ['freshness', 'freshness_label', 'freshnessLabel']) ||
            formatFreshness(updatedAt),
          lineage: normalizeUserFacingLineage(
            getString(data, ['lineage', 'detail', 'description']) || '由资产汇总结果生成'
          ),
        };
      })
      .filter(Boolean) as P0ApiAssetSource[];
  }

  if (!capabilities && !health) return [];

  const connectorMode =
    getString(capabilities, ['connector_mode', 'connectorMode']) || 'auto';
  const supports = asRecord(capabilities?.supports);
  const isConnected = connectorMode === 'local_connector' || supports?.positions === true;

  return [
    {
      id: 'source-futu',
      label: '系统 Futu 行情源',
      type: '系统行情',
      priority: '行情参考',
      confidence: '0.95',
      freshness: formatFreshness(updatedAt),
      lineage:
        isConnected
          ? '通过管理员侧 OpenD 读取行情和期权链；不会同步普通用户个人账户。'
          : '等待系统行情源返回行情；当前仅展示可用的参考数据。',
    },
  ];
}

function normalizeUserFacingNote(note?: string): string | undefined {
  if (!note) return undefined;
  const lower = note.toLowerCase();
  if (
    lower.includes('p0') ||
    lower.includes('read-only local connector') ||
    lower.includes('connector boundaries') ||
    lower.includes('sidecar')
  ) {
    return '当前连接只会读取持仓、现金与期权链，不会触发下单。';
  }
  return normalizeUserFacingLineage(note);
}

function normalizeUserFacingLineage(value: string): string {
  return value
    .replaceAll('data-service', '资产汇总结果')
    .replaceAll('fallback', '参考数据')
    .replaceAll('sidecar', '本机连接服务')
    .replaceAll('broker sync', '数据来源更新')
    .replaceAll('broker', '数据来源')
    .replaceAll('tenant', '账户空间');
}

function deriveOverview(
  overview: P0ApiOverview | undefined,
  positions: {
    equity: P0ApiEquityPosition[];
    options: P0ApiOptionPosition[];
    updatedAt?: string;
  }
): P0ApiOverview | undefined {
  const equityMarketValue = positions.equity.reduce(
    (sum, item) => sum + (item.marketValue ?? 0),
    0
  );
  const optionMarketValue = positions.options.reduce(
    (sum, item) => sum + (item.marketValue ?? 0),
    0
  );

  const derived: P0ApiOverview = {
    currency: overview?.currency || overview?.baseCurrency || inferCurrencyFromPositions(positions) || 'USD',
    baseCurrency:
      overview?.baseCurrency || overview?.currency || inferCurrencyFromPositions(positions) || 'USD',
    currencies: overview?.currencies || inferCurrenciesFromPositions(positions),
    totalAssetValue:
      overview?.totalAssetValue ??
      ((overview?.cashAvailable ?? 0) + equityMarketValue + optionMarketValue || undefined),
    cashAvailable: overview?.cashAvailable,
    marginUsed: overview?.marginUsed,
    cashSecured: overview?.cashSecured,
    holdingsCount:
      overview?.holdingsCount ??
      (positions.equity.length || positions.options.length
        ? positions.equity.length + positions.options.length
        : undefined),
    equityCount:
      overview?.equityCount ??
      (positions.equity.length ? positions.equity.length : undefined),
    optionCount:
      overview?.optionCount ??
      (positions.options.length ? positions.options.length : undefined),
    equityMarketValue:
      overview?.equityMarketValue ??
      (positions.equity.length ? equityMarketValue : undefined),
    optionMarketValue:
      overview?.optionMarketValue ??
      (positions.options.length ? optionMarketValue : undefined),
    grossMarketValue: overview?.grossMarketValue ?? (positions.equity.length || positions.options.length
      ? positions.equity.reduce((sum, item) => sum + Math.abs(item.marketValue ?? 0), 0) +
        positions.options.reduce((sum, item) => sum + Math.abs(item.marketValue ?? 0), 0)
      : undefined),
    updatedAt: overview?.updatedAt || positions.updatedAt,
    fxSource: overview?.fxSource || positions.equity[0]?.fxSource || positions.options[0]?.fxSource,
    sourceQuality:
      overview?.sourceQuality || positions.equity[0]?.sourceQuality || positions.options[0]?.sourceQuality,
    usesEstimatedFx:
      overview?.usesEstimatedFx ||
      positions.equity.some((item) => isEstimatedFxSource(item.fxSource)) ||
      positions.options.some((item) => isEstimatedFxSource(item.fxSource)),
  };

  return hasAnyDefinedValue(derived) ? derived : undefined;
}

function findQualityDisplayRecord(payload: unknown): Record<string, unknown> | undefined {
  const data = asRecord(payload);
  if (!data) return undefined;
  const direct = asRecord(data.quality_display) || asRecord(data.qualityDisplay);
  if (direct) return direct;

  for (const key of ['analysis', 'data', 'result', 'artifact_metadata', 'artifactMetadata', 'data_quality_summary', 'dataQualitySummary']) {
    const nested = asRecord(data[key]);
    const found = findQualityDisplayRecord(nested);
    if (found) return found;
  }
  return undefined;
}

function findDataQualityRecord(payload: unknown): Record<string, unknown> | undefined {
  const data = asRecord(payload);
  if (!data) return undefined;
  const direct = asRecord(data.data_quality) || asRecord(data.dataQuality) || asRecord(data.data_quality_summary) || asRecord(data.dataQualitySummary);
  if (direct) return direct;

  for (const key of ['analysis', 'data', 'result', 'artifact_metadata', 'artifactMetadata']) {
    const nested = asRecord(data[key]);
    const found = findDataQualityRecord(nested);
    if (found) return found;
  }
  return undefined;
}

function normalizeQualityFreshness(
  value: string | undefined,
  freshnessSeconds: number | undefined,
  hasAnyData: boolean
): P0QualityFreshness {
  const normalized = value?.trim().toLowerCase();
  if (normalized === 'fresh' || normalized === 'ok' || normalized === 'complete') return 'fresh';
  if (normalized === 'degraded' || normalized === 'partial' || normalized === 'limited') return 'degraded';
  if (normalized === 'stale' || normalized === 'expired' || normalized === 'blocked') return 'stale';
  if (normalized === 'missing' || normalized === 'unavailable' || normalized === 'not_available') return 'missing';
  if (freshnessSeconds !== undefined) {
    if (freshnessSeconds > 15 * 60) return 'stale';
    if (freshnessSeconds > 5 * 60) return 'degraded';
    return 'fresh';
  }
  return hasAnyData ? 'unknown' : 'missing';
}

function normalizeQualityActionability(value: string | undefined): P0QualityActionability {
  const normalized = value?.trim().toLowerCase();
  if (normalized === 'trade_draft' || normalized === 'ready' || normalized === 'actionable') return 'trade_draft';
  if (normalized === 'blocked' || normalized === 'not_actionable') return 'blocked';
  return 'analysis_only';
}

function inferQualityDegradeReason(input: {
  freshness: P0QualityFreshness;
  actionability: P0QualityActionability;
  portfolioContext?: string;
  missing: string[];
}): string | undefined {
  if (input.freshness === 'missing') return 'quote_unavailable';
  if (input.freshness === 'stale') return 'data_stale';
  if (input.missing.includes('positions')) return 'no_portfolio_context';
  if (input.portfolioContext === 'not_held_or_unavailable') return 'no_position_context';
  if (input.actionability === 'blocked') return 'action_blocked';
  if (input.actionability === 'analysis_only') return 'analysis_only';
  if (input.freshness === 'degraded' || input.freshness === 'unknown') return 'freshness_uncertain';
  return undefined;
}

function qualityFreshnessLabel(value: P0QualityFreshness) {
  if (value === 'fresh') return '数据新鲜';
  if (value === 'degraded') return '数据降级';
  if (value === 'stale') return '数据过期';
  if (value === 'missing') return '数据缺失';
  return '新鲜度未知';
}

function qualityActionabilityLabel(value: P0QualityActionability) {
  if (value === 'trade_draft') return '可行动';
  if (value === 'blocked') return '不可行动';
  return '只能观察';
}

function qualityDegradeReasonLabel(value?: string) {
  if (!value) return '无降级';
  if (value === 'quote_unavailable') return '行情不可用';
  if (value === 'data_stale') return '数据过期';
  if (value === 'no_portfolio_context' || value === 'no_position_context') return '无持仓上下文';
  if (value === 'action_blocked') return '纪律或数据阻断';
  if (value === 'analysis_only') return '只能观察';
  if (value === 'freshness_uncertain') return '新鲜度待复核';
  return value;
}

function qualityDisplaySummary(input: {
  source: string;
  freshnessLabel: string;
  actionabilityLabel: string;
  degradeReason?: string;
  degradeReasonLabel: string;
}) {
  const parts = [input.actionabilityLabel, input.freshnessLabel];
  if (input.degradeReason && !parts.includes(input.degradeReasonLabel)) {
    parts.push(input.degradeReasonLabel);
  }
  parts.push(`来源 ${input.source || 'unknown'}`);
  return parts.join(' / ');
}

function asRecord(value: unknown): Record<string, unknown> | undefined {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return undefined;
  return value as Record<string, unknown>;
}

function getString(
  source: Record<string, unknown> | null | undefined,
  keys: string[]
): string | undefined {
  if (!source) return undefined;
  for (const key of keys) {
    const value = source[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return undefined;
}

function getNumber(
  source: Record<string, unknown> | null | undefined,
  keys: string[]
): number | undefined {
  if (!source) return undefined;
  for (const key of keys) {
    const value = source[key];
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    if (typeof value === 'string' && value.trim()) {
      const parsed = Number(value);
      if (Number.isFinite(parsed)) return parsed;
    }
  }
  return undefined;
}

function getArray(
  source: Record<string, unknown> | null | undefined,
  keys: string[]
): unknown[] {
  if (!source) return [];
  for (const key of keys) {
    const value = source[key];
    if (Array.isArray(value)) return value;
  }
  return [];
}

function getStringArray(
  source: Record<string, unknown> | null | undefined,
  keys: string[]
): string[] {
  if (!source) return [];
  for (const key of keys) {
    const value = source[key];
    if (!Array.isArray(value)) continue;
    const strings = value
      .map((item) => (typeof item === 'string' ? item.trim() : ''))
      .filter(Boolean);
    if (strings.length) return strings;
  }
  return [];
}

function sumNumbers(items: unknown[], keys: string[]): number | undefined {
  const total = items.reduce<number>((sum, item: unknown) => {
    const value = getNumber(asRecord(item), keys);
    return sum + (value ?? 0);
  }, 0);
  return total || undefined;
}

function hasAnyDefinedValue(source: object): boolean {
  return Object.values(source as Record<string, unknown>).some(
    (value) => value !== undefined && value !== null && value !== ''
  );
}

function getInstrumentType(payload: unknown) {
  const data = asRecord(payload);
  const raw =
    getString(data, ['instrument_type', 'instrumentType', 'asset_type', 'assetType', 'type']) ||
    '';
  const normalized = raw.toLowerCase();
  if (normalized.includes('option')) return 'option';
  return 'equity';
}

function computePositionMarketValue(
  data: Record<string, unknown>,
  multiplier: number
): number | undefined {
  const quantity = getNumber(data, ['quantity', 'qty']);
  const marketPrice = getNumber(data, ['market_price', 'marketPrice', 'price', 'last_price', 'lastPrice']);
  if (quantity === undefined || marketPrice === undefined) return undefined;
  return quantity * marketPrice * multiplier;
}

function computeUnrealizedPnlPct(
  marketPrice?: number,
  averageCost?: number
): number | undefined {
  if (marketPrice === undefined || averageCost === undefined || averageCost === 0) {
    return undefined;
  }
  return ((marketPrice - averageCost) / averageCost) * 100;
}

function computeCashRequired(
  quantity?: number,
  strike?: number,
  multiplier = 100
): number | undefined {
  if (quantity === undefined || strike === undefined || quantity >= 0) return undefined;
  return Math.abs(quantity) * strike * multiplier;
}

function computeDaysToExpiry(expiry?: string): number | undefined {
  if (!expiry) return undefined;
  const expiryTime = Date.parse(expiry);
  if (Number.isNaN(expiryTime)) return undefined;
  const diff = expiryTime - Date.now();
  return Math.max(0, Math.ceil(diff / (24 * 60 * 60 * 1000)));
}

function inferUnderlyingSymbol(contract: string) {
  const matched = contract.match(/^[A-Z.]+/);
  return matched?.[0] || contract;
}

function inferCurrencyFromPositions(positions: {
  equity: P0ApiEquityPosition[];
  options: P0ApiOptionPosition[];
}): string | undefined {
  const currencies = inferCurrenciesFromPositions(positions);
  return currencies[0];
}

function inferCurrenciesFromPositions(positions: {
  equity: P0ApiEquityPosition[];
  options: P0ApiOptionPosition[];
}): string[] {
  const values = [
    ...positions.equity.map((item) => item.baseCurrency || item.currency),
    ...positions.options.map((item) => item.baseCurrency || item.currency),
  ].filter(Boolean);
  return Array.from(new Set(values));
}

function isEstimatedFxSource(value?: string) {
  const normalized = value?.trim().toLowerCase();
  return normalized === 'estimated_fx' || normalized === 'fallback_estimate';
}

function summarizeValuation(
  overview: P0ApiOverview | undefined,
  positions: {
    equity: P0ApiEquityPosition[];
    options: P0ApiOptionPosition[];
  }
) {
  const baseCurrency =
    overview?.baseCurrency ||
    overview?.currency ||
    inferCurrencyFromPositions(positions);
  const fxSource =
    overview?.fxSource ||
    positions.equity.find((item) => item.fxSource)?.fxSource ||
    positions.options.find((item) => item.fxSource)?.fxSource;
  const currencies = new Set<string>([
    ...(overview?.currencies ?? []),
    ...positions.equity.map((item) => item.currency),
    ...positions.options.map((item) => item.currency),
  ]);
  const usesEstimatedFx =
    overview?.usesEstimatedFx ||
    isEstimatedFxSource(fxSource) ||
    positions.equity.some((item) => isEstimatedFxSource(item.fxSource)) ||
    positions.options.some((item) => isEstimatedFxSource(item.fxSource)) ||
    false;

  let valuationDetail: string | undefined;
  if (usesEstimatedFx && baseCurrency) {
    valuationDetail = `多币种资产当前按 ${baseCurrency} 估算汇率折算，仅供参考。`;
  } else if (baseCurrency && currencies.size > 1) {
    valuationDetail = `多币种资产按 ${baseCurrency} 统一折算展示，原币金额请以持仓页为准。`;
  } else if (baseCurrency) {
    valuationDetail = `页面当前按 ${baseCurrency} 口径展示，用于巡检与对比。`;
  }

  return {
    baseCurrency,
    fxSource,
    usesEstimatedFx,
    valuationDetail,
  };
}

function mapConnectionStatus(status: string): ConnectionStatus {
  const normalized = status.toLowerCase();
  if (['connected', 'ok', 'healthy', 'success', 'complete', 'ready'].includes(normalized)) {
    return 'connected';
  }
  if (['warning', 'partial', 'degraded', 'stale', 'limited'].includes(normalized)) {
    return 'degraded';
  }
  return 'disconnected';
}

function mapSyncStatus(status: string): SyncStatus {
  const normalized = status.toLowerCase();
  if (['success', 'ok', 'healthy', 'complete', 'completed'].includes(normalized)) {
    return 'success';
  }
  if (['warning', 'partial', 'degraded', 'stale'].includes(normalized)) {
    return 'warning';
  }
  if (['running', 'syncing', 'pending', 'queued'].includes(normalized)) {
    return 'running';
  }
  return 'failed';
}

function formatFreshness(updatedAt?: string) {
  if (!updatedAt) return '等待首次同步';
  const time = Date.parse(updatedAt);
  if (Number.isNaN(time)) return updatedAt;
  const diffSeconds = Math.max(0, Math.floor((Date.now() - time) / 1000));
  if (diffSeconds < 60) return `${diffSeconds}s`;
  const diffMinutes = Math.floor(diffSeconds / 60);
  if (diffMinutes < 60) return `${diffMinutes}m`;
  const diffHours = Math.floor(diffMinutes / 60);
  return `${diffHours}h`;
}

function formatConfidence(value?: number) {
  if (value === undefined) return '--';
  return value.toFixed(2);
}
