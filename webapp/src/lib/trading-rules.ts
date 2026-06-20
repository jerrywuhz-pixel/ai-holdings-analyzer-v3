import postgres from 'postgres';

declare global {
  // eslint-disable-next-line no-var
  var __aiHoldingsTradingRulesSql: ReturnType<typeof postgres> | undefined;
}

export type TradingRuleAction = 'warn' | 'block' | 'require_confirmation';
export type DisciplineResultStatus = 'passed' | 'warned' | 'blocked' | 'requires_confirmation';
export type TradingRuleSource = 'system' | 'webapp' | 'wechat_channel' | 'user';

export interface TradingRule {
  id: string;
  tenantId: string;
  name: string;
  ruleKey: string;
  ruleType: string;
  scopes: string[];
  markets: string[];
  instruments: string[];
  condition: Record<string, unknown>;
  message: string;
  actionOnViolation: TradingRuleAction;
  priority: number;
  isActive: boolean;
  source: TradingRuleSource;
  lastTriggeredAt: string | null;
  triggerCount: number;
  createdAt: string;
  updatedAt: string;
}

export interface DisciplineCheck {
  id: string;
  symbol: string | null;
  instrumentType: string | null;
  actionType: string;
  result: DisciplineResultStatus;
  highestAction: TradingRuleAction | 'none';
  triggeredRuleIds: string[];
  checkPayload: Record<string, unknown>;
  createdAt: string;
}

export interface DisciplineRuleHit {
  id: string;
  name: string;
  ruleKey: string;
  ruleType: string;
  actionOnViolation: TradingRuleAction;
  message: string;
  priority: number;
}

export interface DisciplineEvaluationInput {
  actionType: string;
  symbol?: string;
  name?: string;
  market?: string;
  instrumentType?: string;
  sourceTier?: string;
  sourceActionability?: string;
  isExtendedHours?: boolean;
  cashBufferPct?: number | null;
  payload?: Record<string, unknown>;
}

export interface DisciplineEvaluationResult {
  checkId: string;
  result: DisciplineResultStatus;
  highestAction: TradingRuleAction | 'none';
  hits: DisciplineRuleHit[];
  message: string;
}

export interface TradingRulesDashboard {
  summary: Array<{ label: string; value: string; hint: string; tone?: 'default' | 'positive' | 'warning' | 'danger' }>;
  rules: TradingRule[];
  recentChecks: DisciplineCheck[];
}

interface TradingRuleRow {
  id: string;
  tenant_id: string;
  name: string;
  rule_key: string;
  rule_type: string;
  scopes: string[] | null;
  markets: string[] | null;
  instruments: string[] | null;
  condition: Record<string, unknown> | null;
  message: string;
  action_on_violation: TradingRuleAction;
  priority: number;
  is_active: boolean;
  source: TradingRuleSource;
  last_triggered_at: string | Date | null;
  trigger_count: string | number;
  created_at: string | Date;
  updated_at: string | Date;
}

interface DisciplineCheckRow {
  id: string;
  symbol: string | null;
  instrument_type: string | null;
  action_type: string;
  result: DisciplineResultStatus;
  highest_action: TradingRuleAction | 'none';
  triggered_rule_ids: string[] | null;
  check_payload: Record<string, unknown> | null;
  created_at: string | Date;
}

interface DefaultTradingRule {
  ruleKey: string;
  name: string;
  ruleType: string;
  scopes: string[];
  markets: string[];
  instruments: string[];
  condition: Record<string, unknown>;
  message: string;
  actionOnViolation: TradingRuleAction;
  priority: number;
}

const ACTION_RANK: Record<TradingRuleAction | 'none', number> = {
  none: 0,
  warn: 1,
  require_confirmation: 2,
  block: 3,
};

const DEFAULT_TRADING_RULES: DefaultTradingRule[] = [
  {
    ruleKey: 'no-china-adr',
    name: '中概股买入提醒',
    ruleType: 'blocklist',
    scopes: ['manual_position', 'trade_draft', 'sell_put', 'stock', 'etf'],
    markets: ['US'],
    instruments: ['stock', 'etf', 'option_contract'],
    condition: {
      symbol_patterns: ['BABA', 'JD', 'PDD', 'BIDU', 'NIO', 'XPEV', 'LI', 'TME', 'BEKE', 'YMM', 'FUTU', 'TIGR'],
      match_name_keywords: ['阿里', '拼多多', '京东', '百度', '蔚来', '小鹏', '理想', '富途', '老虎'],
    },
    message: '这类标的属于中概股或中概相关资产，请确认是否符合你的投资纪律。',
    actionOnViolation: 'warn',
    priority: 20,
  },
  {
    ruleKey: 'avoid-extended-hours',
    name: '盘前盘后不下单',
    ruleType: 'time_window',
    scopes: ['trade_draft', 'sell_put'],
    markets: ['US', 'HK'],
    instruments: ['stock', 'etf', 'option_contract'],
    condition: { forbid_extended_hours: true },
    message: '当前动作发生在盘前/盘后时段，系统会阻止交易执行类动作。',
    actionOnViolation: 'block',
    priority: 10,
  },
  {
    ruleKey: 'sell-put-cash-buffer',
    name: 'Sell Put 保留现金缓冲',
    ruleType: 'risk_budget',
    scopes: ['sell_put'],
    markets: ['US', 'HK'],
    instruments: ['option_contract'],
    condition: { min_cash_buffer_pct: 20 },
    message: 'Sell Put 后现金缓冲低于默认阈值，需要再次确认资金安全边际。',
    actionOnViolation: 'require_confirmation',
    priority: 30,
  },
  {
    ruleKey: 'manual-position-review',
    name: '手工录入后复核',
    ruleType: 'confirmation_required',
    scopes: ['manual_position'],
    markets: [],
    instruments: ['stock', 'etf', 'option_contract'],
    condition: { source_tiers: ['user_confirmed', 'estimated'] },
    message: '这笔持仓来自手工录入，建议后续用截图识别或交易账户结单复核。',
    actionOnViolation: 'warn',
    priority: 80,
  },
];

function databaseUrl() {
  return process.env.WEBAPP_DATABASE_URL || process.env.DATABASE_URL || '';
}

function sqlClient() {
  const url = databaseUrl();
  if (!url) {
    throw new Error('交易纪律需要配置 DATABASE_URL 或 WEBAPP_DATABASE_URL');
  }

  if (!globalThis.__aiHoldingsTradingRulesSql) {
    globalThis.__aiHoldingsTradingRulesSql = postgres(url, {
      max: 4,
      idle_timeout: 20,
      connect_timeout: 10,
      prepare: false,
    });
  }

  return globalThis.__aiHoldingsTradingRulesSql;
}

function serializeDate(value: unknown) {
  if (value instanceof Date) return value.toISOString();
  return value ? String(value) : null;
}

function normalizeText(value?: string) {
  return (value || '').trim();
}

function normalizeUpper(value?: string) {
  return normalizeText(value).toUpperCase();
}

function normalizeArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item).trim()).filter(Boolean);
}

function normalizeAction(value: unknown): TradingRuleAction {
  if (value === 'block' || value === 'require_confirmation' || value === 'warn') return value;
  return 'warn';
}

function normalizeRuleType(value: unknown) {
  const ruleType = normalizeText(String(value || 'custom'));
  if (
    ruleType === 'allowlist' ||
    ruleType === 'blocklist' ||
    ruleType === 'time_window' ||
    ruleType === 'position_limit' ||
    ruleType === 'risk_budget' ||
    ruleType === 'confirmation_required' ||
    ruleType === 'custom'
  ) {
    return ruleType;
  }
  return 'custom';
}

function normalizeRuleSource(value: unknown): TradingRuleSource {
  const source = normalizeText(String(value || '')).toLowerCase();
  if (source === 'system') return 'system';
  if (source === 'wechat' || source === 'wechat_channel') return 'wechat_channel';
  if (source === 'user') return 'user';
  return 'webapp';
}

function slugifyRuleKey(value: string) {
  const slug = value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return slug || `rule-${Date.now()}`;
}

function mapRule(row: TradingRuleRow): TradingRule {
  return {
    id: row.id,
    tenantId: row.tenant_id,
    name: row.name,
    ruleKey: row.rule_key,
    ruleType: row.rule_type,
    scopes: row.scopes ?? [],
    markets: row.markets ?? [],
    instruments: row.instruments ?? [],
    condition: row.condition ?? {},
    message: row.message,
    actionOnViolation: row.action_on_violation,
    priority: Number(row.priority),
    isActive: row.is_active,
    source: normalizeRuleSource(row.source),
    lastTriggeredAt: serializeDate(row.last_triggered_at),
    triggerCount: Number(row.trigger_count) || 0,
    createdAt: serializeDate(row.created_at) || new Date().toISOString(),
    updatedAt: serializeDate(row.updated_at) || new Date().toISOString(),
  };
}

function mapCheck(row: DisciplineCheckRow): DisciplineCheck {
  return {
    id: row.id,
    symbol: row.symbol,
    instrumentType: row.instrument_type,
    actionType: row.action_type,
    result: row.result,
    highestAction: row.highest_action,
    triggeredRuleIds: row.triggered_rule_ids ?? [],
    checkPayload: row.check_payload ?? {},
    createdAt: serializeDate(row.created_at) || new Date().toISOString(),
  };
}

function postgresArrayLiteral(values: string[]) {
  return `{${values
    .map((value) => `"${value.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`)
    .join(',')}}`;
}

function textArraySql(sql: ReturnType<typeof sqlClient>, values: string[]) {
  return sql`${postgresArrayLiteral(values)}::text[]`;
}

function uuidArraySql(sql: ReturnType<typeof sqlClient>, values: string[]) {
  return sql`${postgresArrayLiteral(values)}::uuid[]`;
}

function scopeMatches(rule: TradingRule, input: DisciplineEvaluationInput) {
  if (!rule.scopes.length || rule.scopes.includes('all')) return true;
  const actionType = normalizeText(input.actionType);
  const instrumentType = normalizeText(input.instrumentType);
  return rule.scopes.includes(actionType) || Boolean(instrumentType && rule.scopes.includes(instrumentType));
}

function restrictionMatches(rule: TradingRule, input: DisciplineEvaluationInput) {
  const market = normalizeUpper(input.market);
  const instrumentType = normalizeText(input.instrumentType);
  if (rule.markets.length && market && !rule.markets.map((item) => item.toUpperCase()).includes(market)) {
    return false;
  }
  if (rule.instruments.length && instrumentType && !rule.instruments.includes(instrumentType)) {
    return false;
  }
  return true;
}

function patternMatches(symbol: string, pattern: string) {
  const normalizedSymbol = symbol.toUpperCase();
  const normalizedPattern = pattern.toUpperCase();
  return normalizedSymbol === normalizedPattern || normalizedSymbol.startsWith(`${normalizedPattern}.`) || normalizedSymbol.includes(normalizedPattern);
}

function conditionMatches(rule: TradingRule, input: DisciplineEvaluationInput) {
  if (!scopeMatches(rule, input) || !restrictionMatches(rule, input)) return false;

  const condition = rule.condition ?? {};
  const symbol = normalizeUpper(input.symbol);
  const name = normalizeText(input.name).toLowerCase();
  const sourceTier = normalizeText(input.sourceTier);
  let hasPredicate = false;
  let matched = false;

  const symbolPatterns = normalizeArray(condition.symbol_patterns ?? condition.symbols);
  if (symbolPatterns.length) {
    hasPredicate = true;
    matched = matched || Boolean(symbol && symbolPatterns.some((pattern) => patternMatches(symbol, pattern)));
  }

  const nameKeywords = normalizeArray(condition.match_name_keywords);
  if (nameKeywords.length) {
    hasPredicate = true;
    matched = matched || Boolean(name && nameKeywords.some((keyword) => name.includes(keyword.toLowerCase())));
  }

  const sourceTiers = normalizeArray(condition.source_tiers);
  if (sourceTiers.length) {
    hasPredicate = true;
    matched = matched || Boolean(sourceTier && sourceTiers.includes(sourceTier));
  }

  if (condition.forbid_extended_hours === true) {
    hasPredicate = true;
    matched = matched || input.isExtendedHours === true;
  }

  const minCashBufferPct = Number(condition.min_cash_buffer_pct);
  if (Number.isFinite(minCashBufferPct)) {
    hasPredicate = true;
    matched = matched || (typeof input.cashBufferPct === 'number' && input.cashBufferPct < minCashBufferPct);
  }

  return hasPredicate ? matched : true;
}

function resultForAction(action: TradingRuleAction | 'none'): DisciplineResultStatus {
  if (action === 'block') return 'blocked';
  if (action === 'require_confirmation') return 'requires_confirmation';
  if (action === 'warn') return 'warned';
  return 'passed';
}

function messageForHits(hits: DisciplineRuleHit[]) {
  if (!hits.length) return '纪律规则检查通过。';
  return hits.map((hit) => `${hit.name}：${hit.message}`).join('；');
}

export async function ensureDefaultTradingRules(tenantId: string) {
  const sql = sqlClient();
  for (const rule of DEFAULT_TRADING_RULES) {
    await sql`
      INSERT INTO public.trading_rules (
        tenant_id, name, rule_key, rule_type, scopes, markets, instruments, condition,
        message, action_on_violation, priority, source
      )
      VALUES (
        ${tenantId}, ${rule.name}, ${rule.ruleKey}, ${rule.ruleType},
        ${textArraySql(sql, rule.scopes)}, ${textArraySql(sql, rule.markets)},
        ${textArraySql(sql, rule.instruments)}, ${sql.json(rule.condition as any)},
        ${rule.message}, ${rule.actionOnViolation}, ${rule.priority}, 'system'
      )
      ON CONFLICT (tenant_id, rule_key) DO NOTHING
    `;
  }
}

export async function listTradingRulesForTenant(tenantId: string) {
  const sql = sqlClient();
  const rows = await sql<TradingRuleRow[]>`
    SELECT *
    FROM public.trading_rules
    WHERE tenant_id = ${tenantId}
    ORDER BY is_active DESC, priority ASC, created_at ASC
  `;
  return rows.map(mapRule);
}

export async function listRecentDisciplineChecks(tenantId: string, limit = 20) {
  const sql = sqlClient();
  const rows = await sql<DisciplineCheckRow[]>`
    SELECT id, symbol, instrument_type, action_type, result, highest_action, triggered_rule_ids, check_payload, created_at
    FROM public.discipline_checks
    WHERE tenant_id = ${tenantId}
      AND COALESCE(array_length(triggered_rule_ids, 1), 0) > 0
    ORDER BY created_at DESC
    LIMIT ${limit}
  `;
  return rows.map(mapCheck);
}

export async function getTradingRulesDashboard(tenantId: string): Promise<TradingRulesDashboard> {
  await ensureDefaultTradingRules(tenantId);
  const [rules, recentChecks] = await Promise.all([
    listTradingRulesForTenant(tenantId),
    listRecentDisciplineChecks(tenantId, 12),
  ]);

  const activeRules = rules.filter((rule) => rule.isActive);
  const blockingRules = activeRules.filter((rule) => rule.actionOnViolation === 'block');
  const confirmationRules = activeRules.filter((rule) => rule.actionOnViolation === 'require_confirmation');
  const recentWarnings = recentChecks.filter((check) => check.result !== 'passed');

  return {
    summary: [
      { label: '已启用规则', value: String(activeRules.length), hint: '会参与交易录入、草稿和策略建议前检查', tone: 'positive' },
      { label: '阻断规则', value: String(blockingRules.length), hint: '命中后会阻止对应动作继续执行', tone: blockingRules.length ? 'danger' : 'default' },
      { label: '需确认规则', value: String(confirmationRules.length), hint: '命中后需要确认或留下例外原因', tone: confirmationRules.length ? 'warning' : 'default' },
      { label: '近期提醒', value: String(recentWarnings.length), hint: '最近纪律检查中需要关注的记录', tone: recentWarnings.length ? 'warning' : 'positive' },
    ],
    rules,
    recentChecks,
  };
}

export async function createTradingRuleForTenant(
  tenantId: string,
  input: {
    name: string;
    ruleKey?: string;
    ruleType?: string;
    scopes?: string[];
    markets?: string[];
    instruments?: string[];
    condition?: Record<string, unknown>;
    message?: string;
    actionOnViolation?: TradingRuleAction;
    priority?: number;
    source?: TradingRuleSource | string;
  }
) {
  const sql = sqlClient();
  const name = normalizeText(input.name);
  if (!name) throw new Error('请输入规则名称');
  const ruleKey = slugifyRuleKey(input.ruleKey || name);
  const ruleType = normalizeRuleType(input.ruleType);
  const actionOnViolation = normalizeAction(input.actionOnViolation);
  const scopes = normalizeArray(input.scopes);
  const markets = normalizeArray(input.markets).map((item) => item.toUpperCase());
  const instruments = normalizeArray(input.instruments);
  const priority = Number.isFinite(input.priority) ? Number(input.priority) : 100;
  const message = normalizeText(input.message) || '该动作命中你的交易纪律，请确认后再继续。';
  const source = normalizeRuleSource(input.source);

  const rows = await sql<TradingRuleRow[]>`
    INSERT INTO public.trading_rules (
      tenant_id, name, rule_key, rule_type, scopes, markets, instruments, condition,
      message, action_on_violation, priority, source
    )
    VALUES (
      ${tenantId}, ${name}, ${ruleKey}, ${ruleType},
      ${textArraySql(sql, scopes)}, ${textArraySql(sql, markets)},
      ${textArraySql(sql, instruments)}, ${sql.json((input.condition ?? {}) as any)},
      ${message}, ${actionOnViolation}, ${priority}, ${source}
    )
    ON CONFLICT (tenant_id, rule_key) DO UPDATE SET
      name = EXCLUDED.name,
      rule_type = EXCLUDED.rule_type,
      scopes = EXCLUDED.scopes,
      markets = EXCLUDED.markets,
      instruments = EXCLUDED.instruments,
      condition = EXCLUDED.condition,
      message = EXCLUDED.message,
      action_on_violation = EXCLUDED.action_on_violation,
      priority = EXCLUDED.priority,
      source = EXCLUDED.source,
      is_active = TRUE,
      updated_at = now()
    RETURNING *
  `;
  return mapRule(rows[0]);
}

export async function updateTradingRuleForTenant(
  tenantId: string,
  ruleId: string,
  patch: Partial<{
    name: string;
    ruleType: string;
    scopes: string[];
    markets: string[];
    instruments: string[];
    condition: Record<string, unknown>;
    message: string;
    actionOnViolation: TradingRuleAction;
    priority: number;
    isActive: boolean;
  }>
) {
  const sql = sqlClient();
  const existing = await sql<TradingRuleRow[]>`
    SELECT *
    FROM public.trading_rules
    WHERE tenant_id = ${tenantId} AND id = ${ruleId}
    LIMIT 1
  `;
  if (!existing[0]) throw new Error('规则不存在或不属于当前账户');

  const current = mapRule(existing[0]);
  const rows = await sql<TradingRuleRow[]>`
    UPDATE public.trading_rules
    SET
      name = ${patch.name === undefined ? current.name : normalizeText(patch.name) || current.name},
      rule_type = ${patch.ruleType === undefined ? current.ruleType : normalizeRuleType(patch.ruleType)},
      scopes = ${textArraySql(sql, patch.scopes === undefined ? current.scopes : normalizeArray(patch.scopes))},
      markets = ${textArraySql(sql, patch.markets === undefined ? current.markets : normalizeArray(patch.markets).map((item) => item.toUpperCase()))},
      instruments = ${textArraySql(sql, patch.instruments === undefined ? current.instruments : normalizeArray(patch.instruments))},
      condition = ${sql.json((patch.condition === undefined ? current.condition : patch.condition) as any)},
      message = ${patch.message === undefined ? current.message : normalizeText(patch.message) || current.message},
      action_on_violation = ${patch.actionOnViolation === undefined ? current.actionOnViolation : normalizeAction(patch.actionOnViolation)},
      priority = ${patch.priority === undefined || !Number.isFinite(patch.priority) ? current.priority : Number(patch.priority)},
      is_active = ${patch.isActive === undefined ? current.isActive : Boolean(patch.isActive)},
      updated_at = now()
    WHERE tenant_id = ${tenantId} AND id = ${ruleId}
    RETURNING *
  `;
  return mapRule(rows[0]);
}

export async function deactivateTradingRuleForTenant(tenantId: string, ruleId: string) {
  return updateTradingRuleForTenant(tenantId, ruleId, { isActive: false });
}

export async function evaluateTradingDiscipline(
  tenantId: string,
  input: DisciplineEvaluationInput
): Promise<DisciplineEvaluationResult> {
  await ensureDefaultTradingRules(tenantId);
  const sql = sqlClient();
  const rules = (await listTradingRulesForTenant(tenantId)).filter((rule) => rule.isActive);
  const hits = rules
    .filter((rule) => conditionMatches(rule, input))
    .map<DisciplineRuleHit>((rule) => ({
      id: rule.id,
      name: rule.name,
      ruleKey: rule.ruleKey,
      ruleType: rule.ruleType,
      actionOnViolation: rule.actionOnViolation,
      message: rule.message,
      priority: rule.priority,
    }));

  const highestAction = hits.reduce<TradingRuleAction | 'none'>((current, hit) => {
    return ACTION_RANK[hit.actionOnViolation] > ACTION_RANK[current] ? hit.actionOnViolation : current;
  }, 'none');
  const result = resultForAction(highestAction);
  const triggeredRuleIds = hits.map((hit) => hit.id);
  const triggeredRuleIdsSql = uuidArraySql(sql, triggeredRuleIds);

  const checkRows = await sql<{ id: string }[]>`
    INSERT INTO public.discipline_checks (
      tenant_id, symbol, instrument_type, action_type, result, triggered_rule_ids,
      highest_action, check_payload
    )
    VALUES (
      ${tenantId},
      ${normalizeUpper(input.symbol) || null},
      ${normalizeText(input.instrumentType) || null},
      ${normalizeText(input.actionType) || 'unknown'},
      ${result},
      ${triggeredRuleIdsSql},
      ${highestAction},
      ${sql.json({ input, hits } as any)}
    )
    RETURNING id
  `;

  if (triggeredRuleIds.length) {
    await sql`
      UPDATE public.trading_rules
      SET trigger_count = trigger_count + 1, last_triggered_at = now(), updated_at = now()
      WHERE tenant_id = ${tenantId} AND id = ANY(${uuidArraySql(sql, triggeredRuleIds)})
    `;
  }

  return {
    checkId: checkRows[0].id,
    result,
    highestAction,
    hits,
    message: messageForHits(hits),
  };
}
