import { PageHeader, Panel, StatusPill } from '@/components/p0-ui';
import { saveProfile } from '@/app/onboarding/actions';
import { getOnboardingState } from '@/lib/onboarding';

export const dynamic = 'force-dynamic';

const inputClass =
  'mt-2 block w-full rounded-xl border border-white/10 bg-black/30 px-3 py-2 text-sm text-white outline-none transition focus:border-red-300/50';
const optionClass =
  'flex items-center gap-2 rounded-xl border border-white/10 bg-white/[0.03] px-3 py-2 text-sm text-slate-200';

export default async function OnboardingProfilePage() {
  const state = await getOnboardingState();
  const settings = state.settings ?? {};
  const markets = new Set<string>(settings.primary_markets ?? ['US']);
  const accountTypes = new Set<string>(settings.account_types ?? ['margin']);

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="注册初始化"
        title="先设定账户口径"
        description="这些设置会作为持仓、期权分析、Sell Put 现金占用和多币种折算的默认口径。"
        actions={<StatusPill tone="muted">1 / 4</StatusPill>}
      />

      <form action={saveProfile} className="grid gap-5 xl:grid-cols-[1fr_0.8fr]">
        <Panel title="基础口径" description="用于后续持仓同步和分析默认值。">
          <div className="grid gap-4 md:grid-cols-2">
            <label className="block">
              <span className="text-sm font-medium text-slate-200">展示币种</span>
              <select name="base_currency" defaultValue={settings.base_currency ?? 'USD'} className={inputClass}>
                <option value="USD">USD</option>
                <option value="HKD">HKD</option>
                <option value="CNY">CNY</option>
              </select>
            </label>
            <label className="block">
              <span className="text-sm font-medium text-slate-200">时区</span>
              <select name="timezone" defaultValue={settings.timezone ?? 'Asia/Shanghai'} className={inputClass}>
                <option value="Asia/Shanghai">Asia/Shanghai</option>
                <option value="America/New_York">America/New_York</option>
                <option value="Asia/Hong_Kong">Asia/Hong_Kong</option>
              </select>
            </label>
          </div>

          <div className="mt-5">
            <p className="text-sm font-medium text-slate-200">主要市场</p>
            <div className="mt-2 grid gap-2 sm:grid-cols-3">
              {[
                ['US', '美股'],
                ['HK', '港股'],
                ['CN', 'A 股'],
              ].map(([value, label]) => (
                <label key={value} className={optionClass}>
                  <input
                    type="checkbox"
                    name="primary_markets"
                    value={value}
                    defaultChecked={markets.has(value)}
                    className="h-4 w-4 accent-red-500"
                  />
                  {label}
                </label>
              ))}
            </div>
          </div>

          <div className="mt-5">
            <p className="text-sm font-medium text-slate-200">账户类型</p>
            <div className="mt-2 grid gap-2 sm:grid-cols-3">
              {[
                ['margin', '保证金'],
                ['cash', '现金'],
                ['options', '期权'],
              ].map(([value, label]) => (
                <label key={value} className={optionClass}>
                  <input
                    type="checkbox"
                    name="account_types"
                    value={value}
                    defaultChecked={accountTypes.has(value)}
                    className="h-4 w-4 accent-red-500"
                  />
                  {label}
                </label>
              ))}
            </div>
          </div>
        </Panel>

        <Panel title="风险默认值" description="控制系统默认展示的分析边界。">
          <div className="space-y-4">
            <label className="block">
              <span className="text-sm font-medium text-slate-200">风险偏好</span>
              <select name="risk_profile" defaultValue={settings.risk_profile ?? 'balanced'} className={inputClass}>
                <option value="conservative">保守</option>
                <option value="balanced">均衡</option>
                <option value="growth">进取</option>
              </select>
            </label>

            <label className={optionClass}>
              <input
                type="checkbox"
                name="sell_put_enabled"
                defaultChecked={settings.sell_put_enabled ?? true}
                className="h-4 w-4 accent-red-500"
              />
              启用 Sell Put 分析
            </label>

            <button
              type="submit"
              className="w-full rounded-xl bg-red-500 px-4 py-2.5 text-sm font-medium text-white transition hover:bg-red-400"
            >
              保存并绑定微信
            </button>
          </div>
        </Panel>
      </form>
    </div>
  );
}
