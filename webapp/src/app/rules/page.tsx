import { ensureUserAccount } from '@/lib/account-store';
import { requireUser } from '@/lib/supabase';
import { getTradingRulesDashboard } from '@/lib/trading-rules';
import { MetricCard, PageHeader, Panel } from '@/components/p0-ui';
import TradingRulesManager from '@/components/trading-rules-manager';

export const dynamic = 'force-dynamic';

export default async function RulesPage() {
  const session = await requireUser();
  const account = await ensureUserAccount(session.user);
  const dashboard = await getTradingRulesDashboard(account.tenantId);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="交易纪律"
        title="把投资纪律变成每次操作前的提醒"
        description="管理禁买/慎买标的、交易时段、Sell Put 资金边界和手工录入复核规则。系统会在记录持仓、生成交易草稿和策略建议前检查这些规则。"
      />

      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
        {dashboard.summary.map((metric) => (
          <MetricCard key={metric.label} metric={metric} />
        ))}
      </div>

      <Panel
        title="规则管理"
        description="启用、停用或调整命中后的动作。阻止类规则会直接拦截对应动作，提醒类规则会保留纪律检查记录。"
      >
        <TradingRulesManager initialRules={dashboard.rules} recentChecks={dashboard.recentChecks} />
      </Panel>
    </div>
  );
}
