export const WECHAT_ONBOARDING_INIT_VERSION = '2026-06-16-profile-first-v1';

export type WechatOnboardingTemplateKey =
  | 'profile_intro'
  | 'stock_analysis'
  | 'position_create'
  | 'portfolio_analysis'
  | 'watchlist_alert'
  | 'trading_discipline'
  | 'guide_complete';

export type WechatOnboardingTemplate = {
  key: WechatOnboardingTemplateKey;
  title: string;
  text: string;
};

export type WechatSelfIntroductionProfile = {
  displayName?: string;
  primaryMarkets?: string[];
  riskProfile?: 'conservative' | 'balanced' | 'aggressive';
  interests?: string[];
};

function optionalName(displayName?: string | null) {
  const name = displayName?.trim();
  return name ? `${name}，` : '';
}

export function buildWechatBindingInitializationMessage(displayName?: string | null) {
  return [
    `${optionalName(displayName)}绑定完成。`,
    '',
    '我是 ClawBot，你的 Hermes 持仓助手。第一次使用前，我想先认识你一下。',
    '',
    '你可以直接回复：',
    '「叫我 Jerry，主要看美股和港股，风格偏稳健」',
    '或：',
    '「叫我 老吴，我主要做 A 股 ETF 和美股，风险中等」',
    '',
    '我会用这个信息设置你的称呼、默认市场和风险偏好。之后你随时可以修改。',
    '',
    '之后你可以这样用我：',
    '1. 查股票：分析 腾讯 / 300750 / 600519',
    '2. 记持仓：买入 腾讯 100股 价格310',
    '3. 看组合：分析我的持仓',
    '4. 设纪律：单只股票不超过总资产20%',
    '',
    '我会帮你记录、分析、提醒和复盘，但不会自动下单。所有交易决策都由你确认。',
  ].join('\n');
}

export const WECHAT_NEW_USER_GUIDE_TEMPLATES: WechatOnboardingTemplate[] = [
  {
    key: 'profile_intro',
    title: '第一次认识用户',
    text: buildWechatBindingInitializationMessage(),
  },
  {
    key: 'stock_analysis',
    title: '股票查询与分析',
    text: [
      '你可以先试试查一只股票。',
      '',
      '直接发：',
      '「分析 600519」',
      '「分析 腾讯控股」',
      '「分析 300750」',
      '',
      '我会返回结论、行动等级、关键依据、主要风险、数据质量和下一步口令。',
      '这是分析，不是自动交易建议。',
    ].join('\n'),
  },
  {
    key: 'position_create',
    title: '构建第一笔持仓',
    text: [
      '接下来可以建立你的第一笔持仓。',
      '',
      '你可以发：',
      '「买入 腾讯 100股 价格310」',
      '「持有 00700.HK 100股 成本310」',
      '「卖出 600519 10股 价格1700」',
      '',
      '也可以发持仓截图，我会先识别成待复核记录，复核后才写入系统。',
      '这里是记录持仓和交易事实，不会帮你下单。',
    ].join('\n'),
  },
  {
    key: 'portfolio_analysis',
    title: '分析持仓',
    text: [
      '有持仓后，可以让我做组合分析。',
      '',
      '你可以发：',
      '「分析我的持仓」',
      '「看看我的风险」',
      '「今天有什么需要处理」',
      '「哪只仓位太重」',
      '',
      '我会重点看总资产、盈亏、集中度、现金风险、交易纪律和今天最该处理的事项。',
    ].join('\n'),
  },
  {
    key: 'watchlist_alert',
    title: '观察清单与提醒',
    text: [
      '如果暂时不买，也可以先放进观察清单。',
      '',
      '你可以发：',
      '「观察 300750，跌到180提醒我」',
      '「关注 腾讯，原因是估值回落」',
      '「如果 600519 跌破1700提醒」',
      '',
      '触发后我只会提醒你复核，不会自动交易。',
    ].join('\n'),
  },
  {
    key: 'trading_discipline',
    title: '建立交易纪律',
    text: [
      '建议你设置几条交易纪律。纪律会在持仓分析、买卖记录和提醒里自动检查。',
      '',
      '你可以发：',
      '「单只股票不超过总资产20%」',
      '「亏损超过8%提醒我复盘」',
      '「财报前不加仓」',
      '「现金低于15%提醒」',
      '「Sell Put 占用现金不超过30%」',
      '',
      '纪律不是限制你操作，而是在你冲动时帮你多看一眼。',
    ].join('\n'),
  },
  {
    key: 'guide_complete',
    title: '新手引导完成',
    text: [
      '你已经可以用微信完成 Hermes 的核心流程了：',
      '',
      '1. 查股票：分析 600519',
      '2. 记持仓：买入 腾讯 100股 价格310',
      '3. 看组合：分析我的持仓',
      '4. 设提醒：跌破300提醒我',
      '5. 建纪律：单只股票不超过20%',
      '',
      '以后不确定怎么问时，直接发「我能做什么」。',
    ].join('\n'),
  },
];

export function shouldDeliverWechatOnboardingInitialization(metadata: Record<string, unknown> | null | undefined) {
  const onboarding = metadata?.onboarding;
  if (!onboarding || typeof onboarding !== 'object' || Array.isArray(onboarding)) {
    return true;
  }

  const state = onboarding as Record<string, unknown>;
  return state.initialization_version !== WECHAT_ONBOARDING_INIT_VERSION || !state.initialization_sent_at;
}

export function wechatOnboardingInitializationMetadata(status: 'sent' | 'failed', error?: string) {
  return {
    onboarding: {
      initialization_version: WECHAT_ONBOARDING_INIT_VERSION,
      initialization_status: status,
      initialization_sent_at: status === 'sent' ? new Date().toISOString() : null,
      initialization_failed_at: status === 'failed' ? new Date().toISOString() : null,
      initialization_error: error ? error.slice(0, 240) : null,
      profile_step: 'awaiting_self_intro',
      guide_templates: WECHAT_NEW_USER_GUIDE_TEMPLATES.map((template) => template.key),
    },
  };
}

function unique(values: string[]) {
  return Array.from(new Set(values));
}

export function parseWechatSelfIntroduction(text?: string | null): WechatSelfIntroductionProfile | null {
  const source = text?.trim();
  if (!source) return null;

  const displayNameMatch = source.match(/(?:叫我|称呼我|我叫|我是)\s*([A-Za-z0-9_\-\u4e00-\u9fa5]{1,20})/);
  const displayName = displayNameMatch?.[1]?.trim();
  const primaryMarkets = unique([
    ...(/美股|美国|US|U\.S\./i.test(source) ? ['US'] : []),
    ...(/港股|香港|HK/i.test(source) ? ['HK'] : []),
    ...(/A股|沪深|中国|CN|A share/i.test(source) ? ['CN'] : []),
  ]);
  const interests = unique([
    ...(/ETF|指数基金/i.test(source) ? ['ETF'] : []),
    ...(/Sell\s*Put|卖 put|卖沽|现金担保/i.test(source) ? ['Sell Put'] : []),
    ...(/股票|个股/i.test(source) ? ['股票'] : []),
    ...(/期权|option/i.test(source) ? ['期权'] : []),
  ]);

  let riskProfile: WechatSelfIntroductionProfile['riskProfile'];
  if (/保守|稳健|低风险|防守/i.test(source)) {
    riskProfile = 'conservative';
  } else if (/激进|进取|高风险|成长/i.test(source)) {
    riskProfile = 'aggressive';
  } else if (/均衡|中等|平衡|普通/i.test(source)) {
    riskProfile = 'balanced';
  }

  const profile: WechatSelfIntroductionProfile = {};
  if (displayName) profile.displayName = displayName;
  if (primaryMarkets.length) profile.primaryMarkets = primaryMarkets;
  if (riskProfile) profile.riskProfile = riskProfile;
  if (interests.length) profile.interests = interests;

  return Object.keys(profile).length ? profile : null;
}

export function shouldCaptureWechatSelfIntroduction(metadata: Record<string, unknown> | null | undefined) {
  const onboarding = metadata?.onboarding;
  if (!onboarding || typeof onboarding !== 'object' || Array.isArray(onboarding)) {
    return false;
  }

  const state = onboarding as Record<string, unknown>;
  return state.profile_step === 'awaiting_self_intro';
}

export function wechatSelfIntroductionMetadata(profile: WechatSelfIntroductionProfile) {
  return {
    profile_step: 'self_intro_collected',
    profile_collected_at: new Date().toISOString(),
    profile_source: 'wechat_self_intro',
    profile_fields: Object.keys(profile),
    preferred_salutation: profile.displayName || null,
    primary_markets: profile.primaryMarkets || null,
    risk_profile: profile.riskProfile || null,
    interests: profile.interests || null,
  };
}
