import Link from 'next/link';
import { redirect } from 'next/navigation';
import { getOnboardingState, isOnboardingComplete, nextOnboardingPath } from '@/lib/onboarding';

export const dynamic = 'force-dynamic';

const sourceItems = [
  ['手工录入', '先记录少量持仓、现金和成本，适合快速试用。'],
  ['买卖消息', '通过微信发送买入、卖出、加仓、清仓，系统解析后生成待确认记录。'],
  ['截图 OCR', '从交易 App 截图识别资产，用于初始化和人工校对。'],
  ['系统行情源', '管理员侧 Futu OpenD 只提供行情和期权链，不同步普通用户个人账户。'],
];

const setupSteps = [
  ['1', '账户口径', '展示币种、主要市场、风险偏好和 Sell Put 开关。'],
  ['2', '微信绑定', '把当前系统账号绑定到一个微信助手，后续接收提醒和确认指令。'],
  ['3', '完成检查', '确认持仓、消息和分析能力进入同一个账号空间。'],
];

export default async function OnboardingWelcomePage() {
  const state = await getOnboardingState();

  if (isOnboardingComplete(state)) {
    redirect('/dashboard');
  }

  if (state.checks.profile) {
    redirect(nextOnboardingPath(state));
  }

  return (
    <main className="min-h-screen bg-[#fbfaf9] text-[#171417]">
      <section className="relative overflow-hidden border-b border-[#e5ddd9] bg-[radial-gradient(circle_at_85%_10%,rgba(215,25,32,0.18),transparent_34%),linear-gradient(135deg,#fff,#f7f1ee_60%,#fff)]">
        <div className="mx-auto grid min-h-[640px] w-[min(1180px,calc(100%_-_28px))] gap-10 py-12 lg:grid-cols-[minmax(0,0.92fr)_minmax(340px,0.72fr)] lg:items-center">
          <div>
            <Link href="/" className="inline-flex items-center gap-3 text-sm font-black text-[#171417]">
              <span className="h-8 w-8 rounded-lg bg-[linear-gradient(135deg,#d71920,#f25a5f)]" />
              AI 持仓系统
            </Link>
            <h1 className="mt-12 max-w-3xl text-4xl font-black leading-[1.08] tracking-tight md:text-[56px]">
              先把你的资产来源和分析口径整理清楚
            </h1>
            <p className="mt-6 max-w-2xl text-base leading-8 text-[#514b4e] md:text-lg">
              初始化只需要完成三步：设置账户口径、绑定微信助手、完成最终检查。之后所有持仓、关注清单、清仓复盘和对话记忆都会隔离在当前账号下。
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link
                href="/onboarding/profile"
                className="inline-flex min-h-11 items-center justify-center rounded-md bg-[#d71920] px-5 py-2.5 text-sm font-semibold text-white shadow-[0_12px_30px_rgba(215,25,32,0.2)] transition hover:bg-[#bd151b]"
              >
                开始设置账户
              </Link>
              <Link
                href="/dashboard"
                className="inline-flex min-h-11 items-center justify-center rounded-md border border-[#d8ccc7] px-5 py-2.5 text-sm font-semibold text-[#171417] transition hover:border-[#bcaeaa]"
              >
                先进入控制台
              </Link>
            </div>
          </div>

          <div className="rounded-lg border border-[#ded3ce] bg-white p-5 shadow-[0_22px_70px_rgba(61,38,32,0.1)]">
            <div className="flex items-center justify-between border-b border-[#e5ddd9] pb-4">
              <p className="font-black">初始化清单</p>
              <span className="rounded-full bg-[#fff0f0] px-3 py-1 text-xs font-bold text-[#d71920]">待开始</span>
            </div>
            <div className="mt-5 space-y-4">
              {setupSteps.map(([index, title, detail]) => (
                <div key={index} className="grid grid-cols-[34px_minmax(0,1fr)] gap-3">
                  <span className="flex h-8 w-8 items-center justify-center rounded-full bg-[#171417] text-xs font-black text-white">
                    {index}
                  </span>
                  <div className="border-b border-[#eee6e2] pb-4 last:border-b-0 last:pb-0">
                    <p className="text-sm font-black">{title}</p>
                    <p className="mt-1 text-sm leading-6 text-[#6f686b]">{detail}</p>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="mx-auto w-[min(1180px,calc(100%_-_28px))] py-16">
        <div className="grid gap-8 lg:grid-cols-[0.72fr_1fr] lg:items-start">
          <div>
            <h2 className="text-3xl font-black leading-tight md:text-[40px]">资产可以从多个入口进入，但必须保留来源</h2>
            <p className="mt-4 text-base leading-8 text-[#6f686b]">
              系统不会把手工记录、截图识别和系统行情混成一笔模糊数据。每次写入都会保留来源、时间和确认状态，方便后续校对和复盘。
            </p>
          </div>
          <div className="grid border-l border-t border-[#d8ccc7] sm:grid-cols-2">
            {sourceItems.map(([title, detail]) => (
              <article key={title} className="min-h-36 border-b border-r border-[#d8ccc7] bg-white p-5">
                <p className="text-lg font-black">{title}</p>
                <p className="mt-3 text-sm leading-6 text-[#6f686b]">{detail}</p>
              </article>
            ))}
          </div>
        </div>
      </section>
    </main>
  );
}
