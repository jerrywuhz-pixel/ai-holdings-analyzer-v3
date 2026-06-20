import Link from 'next/link';

const marketingLoginHref = '/login?entry=marketing';

const sourceCards = [
  {
    title: '系统行情源',
    detail: '管理员侧行情源补充美港股和期权链，不同步普通用户个人账户。',
    featured: true,
  },
  {
    title: '手工录入',
    detail: '适合刚开始试用，或者只想先记录少量股票、ETF 和现金。',
  },
  {
    title: '买卖消息',
    detail: '通过微信输入买入、卖出、加仓、清仓，系统解析后写入资产来源。',
  },
  {
    title: '截图 OCR',
    detail: '从交易 App 截图快速识别持仓，用于初始化和人工校对。',
  },
  {
    title: '关注清单',
    detail: '把可能买入的标的先放入观察区，记录触发条件和后续提醒。',
  },
];

const modules = [
  ['当前持仓', '展示股票、ETF 和期权的真实持仓、成本、盈亏、来源和更新时间。', '资产视图'],
  ['关注清单', '管理可能买入的标的，保存触发条件、行业、优先级和观察理由。', '持仓前'],
  ['清仓复盘', '记录退出理由、收益路径和二次买入条件，让卖出也进入经验库。', '持仓后'],
  ['交易纪律', '每个账号保存自己的风险偏好和操作禁区，记录操作时自动提醒。', '纪律提醒'],
  ['股票分析', '结合行情、估值、事件和持仓成本，输出可读的风险与机会判断。', '股票模块'],
  ['Sell Put', '先判断股票是否适合，再在期权链中按收益、风险、流动性排序。', '期权模块'],
];

const researchSteps = [
  ['01', '数据进入', '读取系统行情、历史数据、微信公众号资料和用户自己确认的持仓记录。'],
  ['02', '规则约束', '先检查风险偏好、交易纪律、资金占用和禁止动作。'],
  ['03', '工具分析', '股票评分、期权链筛选、Sell Put 打分、历史走势和回测查询。'],
  ['04', '生成报告', '日常任务快速回复，复杂任务进入深度研究报告。'],
  ['05', '微信确认', '高风险动作只生成草稿和确认项，不自动下单。'],
];

const faqs = [
  ['系统会自动下单吗？', '不会。系统只生成分析、提醒、草稿和确认项，交易执行必须由用户自己完成。'],
  ['需要连接自己的富途账号吗？', '不需要。Futu OpenD 只作为管理员侧系统行情源，普通用户持仓来自手工录入、买卖消息、截图 OCR 和确认写入。'],
  ['没有自动账户同步能用吗？', '可以。你可以先用手工录入、买卖消息或截图 OCR 建立资产视图。'],
  ['移动端体验怎么处理？', 'WebApp 会适配移动端，微信负责高频提醒和确认，复杂配置仍建议在 WebApp 中完成。'],
];

function ButtonLink({
  href,
  children,
  secondary = false,
}: {
  href: string;
  children: React.ReactNode;
  secondary?: boolean;
}) {
  return (
    <Link
      href={href}
      className={[
        'inline-flex min-h-10 items-center justify-center rounded-md px-4 py-2 text-sm font-semibold transition',
        secondary
          ? 'border border-[#d8ccc7] bg-transparent text-[#171417] hover:border-[#bcaeaa]'
          : 'bg-[#d71920] text-white shadow-[0_12px_30px_rgba(215,25,32,0.2)] hover:bg-[#bd151b]',
      ].join(' ')}
    >
      {children}
    </Link>
  );
}

function MarketingHeader() {
  return (
    <header className="sticky top-0 z-30 border-b border-[#e5ddd9]/90 bg-[#fafafa]/90 backdrop-blur">
      <nav className="mx-auto flex min-h-16 w-[min(1180px,calc(100%_-_28px))] items-center justify-between gap-3">
        <Link href="/" className="flex min-w-0 items-center gap-3 font-black text-[#171417]">
          <span className="h-8 w-8 shrink-0 rounded-lg bg-[linear-gradient(135deg,#d71920,#f24b4f_55%,#9f1118)] shadow-[0_8px_22px_rgba(215,25,32,0.2)]" />
          <span className="truncate">AI 持仓系统</span>
        </Link>
        <div className="hidden items-center gap-6 text-sm font-semibold text-[#4f494c] md:flex">
          <Link href="/#sources">资产来源</Link>
          <Link href="/#modules">核心功能</Link>
          <Link href="/#research">AI 投研</Link>
          <a href="https://www.11office.top/trading-framework.html">交易框架</a>
        </div>
        <div className="hidden shrink-0 items-center gap-2 sm:flex">
          <ButtonLink href={marketingLoginHref} secondary>
            登录
          </ButtonLink>
          <ButtonLink href={marketingLoginHref}>登录控制台</ButtonLink>
        </div>
        <Link
          href={marketingLoginHref}
          className="inline-flex min-h-10 shrink-0 items-center justify-center rounded-md border border-[#d8ccc7] px-4 py-2 text-sm font-semibold text-[#171417] transition hover:border-[#bcaeaa] sm:hidden"
        >
          登录
        </Link>
      </nav>
    </header>
  );
}

function SectionHead({
  title,
  description,
  light = false,
}: {
  title: string;
  description: string;
  light?: boolean;
}) {
  return (
    <div className="mb-10 grid gap-5 md:grid-cols-[minmax(0,0.78fr)_minmax(260px,0.42fr)] md:items-end">
      <h2 className={['text-3xl font-black leading-tight tracking-tight md:text-[42px]', light ? 'text-white' : 'text-[#171417]'].join(' ')}>
        {title}
      </h2>
      <p className={['text-base leading-7', light ? 'text-[#c9c2c6]' : 'text-[#6f686b]'].join(' ')}>{description}</p>
    </div>
  );
}

function ProductPreview() {
  return (
    <div className="mx-auto w-[min(560px,calc(100%_-_28px))] overflow-hidden rounded-lg border border-[#ded3ce] bg-white shadow-[0_22px_70px_rgba(61,38,32,0.1)] lg:absolute lg:right-[max(40px,calc((100vw-1180px)/2))] lg:top-32 lg:w-[min(560px,42vw)] lg:-rotate-1">
      <div className="flex h-11 items-center justify-between border-b border-[#e5ddd9] px-4 text-xs font-bold text-[#6f686b]">
        <span className="flex gap-1.5">
          <span className="h-2.5 w-2.5 rounded-full bg-[#d71920]" />
          <span className="h-2.5 w-2.5 rounded-full bg-[#e6b144]" />
          <span className="h-2.5 w-2.5 rounded-full bg-[#0f8f5f]" />
        </span>
        <span>portfolio.ai</span>
        <span>今日 09:35</span>
      </div>
      <div className="grid md:grid-cols-[0.9fr_1.1fr]">
        <div className="border-b border-[#e5ddd9] p-5 md:border-b-0 md:border-r">
          <p className="mb-3 text-sm font-black text-[#4b4548]">统一资产视图</p>
          {[
            ['腾讯控股', '0700.HK · 系统行情源 · 股票'],
            ['核心持仓', '按真实账户同步 · 股票 / ETF'],
            ['SPY Sell Put', '期权链 · 资金占用 12%'],
            ['清仓回溯', '清仓列表 · 等待二次买入条件'],
          ].map(([name, detail]) => (
            <div key={name} className="border-b border-[#e5ddd9] py-3 last:border-b-0">
              <p className="text-sm font-black text-[#171417]">{name}</p>
              <p className="mt-1 text-xs text-[#6f686b]">{detail}</p>
            </div>
          ))}
        </div>
        <div className="bg-[#fffaf8] p-5">
          <p className="mb-3 text-sm font-black text-[#4b4548]">今日行动清单</p>
          <div className="mb-4 grid grid-cols-3 gap-2">
            {[
              ['组合风险', '中等'],
              ['待复核', '3 条'],
              ['Sell Put', '2 个候选'],
            ].map(([label, value]) => (
              <div key={label} className="rounded-lg border border-[#e5ddd9] bg-white p-3">
                <p className="text-xs text-[#6f686b]">{label}</p>
                <p className="mt-1 text-lg font-black text-[#d71920]">{value}</p>
              </div>
            ))}
          </div>
          <div className="relative h-32 overflow-hidden rounded-lg border border-[#e5ddd9] bg-[linear-gradient(180deg,rgba(215,25,32,0.13),transparent),repeating-linear-gradient(to_right,transparent,transparent_40px,rgba(38,34,37,0.06)_41px)]">
            <div className="absolute inset-x-4 bottom-5 top-5 border-t-[3px] border-[#d71920] bg-[#d7192055] [clip-path:polygon(0_70%,10%_50%,19%_58%,30%_38%,42%_46%,53%_30%,66%_42%,78%_24%,89%_30%,100%_20%,100%_100%,0_100%)]" />
          </div>
          <div className="mt-4 space-y-3">
            <div className="border-b border-[#e5ddd9] pb-3">
              <p className="text-sm font-black">复核高波动标的期权风险</p>
              <p className="mt-1 text-xs text-[#6f686b]">IV 抬升，Sell Put 候选降级</p>
            </div>
            <div className="border-b border-[#e5ddd9] pb-3">
              <p className="text-sm font-black">确认 0700.HK 纪律提醒</p>
              <p className="mt-1 text-xs text-[#6f686b]">接近止损观察线，暂不自动执行</p>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export function HeroSection({ compact = false }: { compact?: boolean }) {
  return (
    <section className="relative overflow-hidden border-b border-[#e5ddd9] bg-[linear-gradient(90deg,#fafafa_0%,rgba(250,250,250,0.94)_37%,rgba(250,250,250,0.42)_70%,rgba(250,250,250,0.18)_100%),radial-gradient(circle_at_83%_14%,rgba(215,25,32,0.2),transparent_32%),linear-gradient(135deg,#fff,#f7f0ec_58%,#fff)]">
      <div className="mx-auto grid min-h-[680px] w-[min(1180px,calc(100%_-_28px))] items-center py-12 lg:min-h-[740px]">
        <div className="max-w-xl py-10">
          <h1 className="text-4xl font-black leading-[1.08] tracking-tight text-[#171417] md:text-[58px]">
            <span className="block">把真实持仓</span>
            <span className="block">变成清晰行动</span>
          </h1>
          <p className="mt-6 max-w-[550px] text-base leading-8 text-[#514b4e] md:text-lg">
            AI 持仓系统连接你的真实资产、交易纪律和微信提醒，把股票、ETF 和 Sell Put 期权分开分析，帮助你每天知道该观察什么、确认什么、复盘什么。
          </p>
          <div className="mt-8 flex flex-wrap gap-3">
            <ButtonLink href={marketingLoginHref}>登录控制台</ButtonLink>
            <ButtonLink href="/#modules" secondary>
              查看核心功能
            </ButtonLink>
          </div>
          {!compact ? (
            <div className="mt-8 grid max-w-xl gap-3 sm:grid-cols-3">
              {[
                ['多来源', '系统行情、手工、消息、OCR'],
                ['双产品', '股票与期权独立分析'],
                ['微信确认', '高风险动作先确认'],
              ].map(([title, detail]) => (
                <div key={title} className="border-t-2 border-[#d71920] pt-4">
                  <p className="text-xl font-black">{title}</p>
                  <p className="mt-1 text-sm text-[#6f686b]">{detail}</p>
                </div>
              ))}
            </div>
          ) : null}
        </div>
      </div>
      {!compact ? (
        <div className="pb-8 lg:pb-0">
          <ProductPreview />
        </div>
      ) : null}
    </section>
  );
}

export function SourcesSection() {
  return (
    <section id="sources" className="scroll-mt-20 border-y border-[#e5ddd9] bg-[#f6f1ee]">
      <div className="mx-auto w-[min(1180px,calc(100%_-_28px))] py-20 md:py-24">
        <SectionHead
          title="不用等所有系统都连好，先把资产来源记录清楚"
          description="每一笔资产都会保留来源和更新时间。后续分析、推送和复盘都基于账号维度隔离的数据，而不是混在一段聊天记录里。"
        />
        <div className="grid border-l border-t border-[#d8ccc7] md:grid-cols-2 xl:grid-cols-5">
          {sourceCards.map((source) => (
            <article
              key={source.title}
              className={[
                'min-h-40 border-b border-r border-[#d8ccc7] p-5',
                source.featured ? 'bg-[#d71920] text-white' : 'bg-white text-[#171417]',
              ].join(' ')}
            >
              <h3 className="text-lg font-black">{source.title}</h3>
              <p className={['mt-3 text-sm leading-6', source.featured ? 'text-white/85' : 'text-[#6f686b]'].join(' ')}>
                {source.detail}
              </p>
            </article>
          ))}
        </div>
      </div>
    </section>
  );
}

export function OnboardingIntroSection() {
  return (
    <section className="mx-auto grid w-[min(1180px,calc(100%_-_28px))] gap-10 py-20 md:py-24 lg:grid-cols-[minmax(0,0.95fr)_minmax(340px,1.05fr)] lg:items-center">
      <div>
        <h2 className="text-3xl font-black leading-tight tracking-tight md:text-[42px]">
          新用户先完成一件事：建立第一份真实资产视图
        </h2>
        <p className="mt-4 text-base leading-7 text-[#6f686b]">
          系统会按步骤引导你，不要求一开始就接入所有数据源。你可以先录入一笔资产，再逐步绑定微信、设置交易纪律、使用系统行情补充分析。
        </p>
        <div className="mt-8 border-t border-[#e5ddd9]">
          {[
            ['1', '选择资产进入方式', '手工录入、截图 OCR 或买卖消息，任选一种即可开始。'],
            ['2', '设置自己的交易纪律', '例如不买某类股票、盘前盘后不下单、单标的资金占用上限。'],
            ['3', '微信接收提醒', '日报、异动、待复核动作和长任务结果，都可以回到微信处理。'],
          ].map(([num, title, detail]) => (
            <div key={num} className="grid grid-cols-[48px_1fr] gap-4 border-b border-[#e5ddd9] py-5 md:grid-cols-[74px_1fr]">
              <span className="flex h-11 w-11 items-center justify-center rounded-lg bg-[#fff1f0] font-black text-[#d71920]">{num}</span>
              <div>
                <h3 className="text-xl font-black">{title}</h3>
                <p className="mt-2 text-[#6f686b]">{detail}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
      <div className="overflow-hidden rounded-lg border border-[#d8ccc7] bg-white shadow-[0_22px_70px_rgba(61,38,32,0.1)]">
        <div className="flex h-11 items-center justify-between border-b border-[#e5ddd9] px-4 text-xs font-bold text-[#6f686b]">
          <span>新用户引导</span>
          <span>3 分钟</span>
        </div>
        <div className="p-5">
          {[
            ['我想先手工录入', '输入股票代码、成本、数量和来源。'],
            ['我想上传截图', '识别后会标记为 OCR 来源，等待复核。'],
            ['我想看系统行情', '管理员侧行情源用于估值、期权链和实时性校验。'],
            ['我想绑定微信', '后续通过文本、语音和图片补充资产信息。'],
          ].map(([title, detail]) => (
            <div key={title} className="border-b border-[#e5ddd9] py-4 last:border-b-0">
              <p className="font-black">{title}</p>
              <p className="mt-1 text-sm text-[#6f686b]">{detail}</p>
            </div>
          ))}
          <ButtonLink href={marketingLoginHref}>登录控制台</ButtonLink>
        </div>
      </div>
    </section>
  );
}

export function ModulesSection() {
  return (
    <section id="modules" className="scroll-mt-20 border-y border-[#e5ddd9] bg-[#f6f1ee]">
      <div className="mx-auto w-[min(1180px,calc(100%_-_28px))] py-20 md:py-24">
        <SectionHead
          title="股票和期权分开设计，持仓前、中、后都有位置"
          description="用户看到的是清晰的资产工作台，系统背后会把股票、ETF、期权、关注清单和清仓列表分开管理。"
        />
        <div className="grid gap-8 lg:grid-cols-[280px_minmax(0,1fr)]">
          <aside className="grid gap-1 self-start lg:sticky lg:top-24">
            {['当前持仓', '关注清单', '清仓复盘', '交易纪律', '股票分析', 'Sell Put'].map((item, index) => (
              <span key={item} className={['border-b border-[#e5ddd9] py-3 font-black', index === 0 ? 'text-[#d71920]' : 'text-[#50484b]'].join(' ')}>
                {item}
              </span>
            ))}
          </aside>
          <div className="grid gap-4 md:grid-cols-2">
            {modules.map(([title, detail, label]) => (
              <article key={title} className="min-h-56 rounded-lg border border-[#e5ddd9] bg-white p-5">
                <h3 className="text-2xl font-black">{title}</h3>
                <p className="mt-3 leading-7 text-[#6f686b]">{detail}</p>
                <strong className="mt-8 block text-2xl text-[#d71920]">{label}</strong>
              </article>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}

export function ResearchFlowSection() {
  return (
    <section id="research" className="scroll-mt-20 bg-[#19161a] text-white">
      <div className="mx-auto w-[min(1180px,calc(100%_-_28px))] py-20 md:py-24">
        <SectionHead
          light
          title="AI 研究不是一句回答，而是一条可追溯的任务流"
          description="系统会记录数据来源、使用的分析工具、关键假设、风险阈值和最终确认状态。用户看到的是结论，必要时也能回看证据链。"
        />
        <div className="grid border border-white/15 lg:grid-cols-5">
          {researchSteps.map(([num, title, detail]) => (
            <article key={num} className="min-h-52 border-b border-white/15 bg-white/[0.045] p-5 lg:border-b-0 lg:border-r lg:last:border-r-0">
              <b className="text-sm text-[#ff6b72]">{num}</b>
              <h3 className="mt-3 text-xl font-black">{title}</h3>
              <p className="mt-3 text-sm leading-6 text-[#c9c2c6]">{detail}</p>
            </article>
          ))}
        </div>
        <div className="mt-5 overflow-hidden rounded-lg border border-white/15 bg-white/[0.05]">
          {[
            ['高波动标的', '财报前隐含波动率抬升，Sell Put 候选暂时降级。', '来源：期权链 + 财报日历'],
            ['0700.HK', '当前未触发止损纪律，但接近观察线，建议继续跟踪。', '来源：持仓成本 + 行情'],
            ['SPY', '市场状态由谨慎转为中性，Sell Put 默认阈值恢复。', '来源：波动率 + 趋势'],
          ].map(([symbol, summary, source]) => (
            <div key={symbol} className="grid gap-2 border-b border-white/10 p-4 last:border-b-0 md:grid-cols-[132px_1fr_168px] md:items-center">
              <b className="text-[#ff6b72]">{symbol}</b>
              <span className="text-[#d9d2d6]">{summary}</span>
              <small className="text-xs text-[#aaa2a7]">{source}</small>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

export function WeChatSection() {
  return (
    <section className="mx-auto grid w-[min(1180px,calc(100%_-_28px))] gap-10 py-20 md:py-24 lg:grid-cols-[minmax(0,1fr)_390px] lg:items-center">
      <div>
        <h2 className="text-3xl font-black leading-tight tracking-tight md:text-[42px]">微信是提醒、确认和补充资产信息的主路径</h2>
        <p className="mt-4 text-base leading-7 text-[#6f686b]">
          用户不需要一直打开 WebApp。日常报告、异动提醒、高风险确认、买卖消息和截图补充，都可以通过微信渠道完成。
        </p>
        <div className="mt-8 grid gap-3">
          {[
            ['每日持仓报告', '组合风险、今日异动、待复核动作和关注清单变化。', false],
            ['用户口令', '确认低风险提醒、驳回高风险草稿，或用语音补充买卖记录。', true],
            ['失败补偿', '如果推送失败，系统会记录失败原因并进入补偿队列，避免漏掉关键提醒。', false],
          ].map(([title, detail, user]) => (
            <div key={String(title)} className={['rounded-lg border p-4', user ? 'ml-auto border-[#d7192044] bg-[#fff1f0]' : 'border-[#e5ddd9] bg-white'].join(' ')}>
              <p className="font-black">{title}</p>
              <p className="mt-1 text-[#6f686b]">{detail}</p>
            </div>
          ))}
        </div>
      </div>
      <aside className="overflow-hidden rounded-lg border border-[#d8ccc7] bg-white shadow-[0_22px_70px_rgba(61,38,32,0.1)]">
        <div className="bg-[#262225] px-4 py-3 font-black text-white">AI 持仓系统</div>
        <div className="grid gap-3 p-4">
          <div className="rounded-lg bg-[#f1f4f1] p-3 text-sm">今日持仓摘要已生成：组合风险中等，2 个 Sell Put 候选，1 条纪律提醒。</div>
          <div className="rounded-lg border border-[#d7192033] bg-[#fff1f0] p-3 text-sm">请确认：是否把高波动标的 Sell Put 草稿加入观察？回复“确认”或“取消”。</div>
          <div className="rounded-lg bg-[#f1f4f1] p-3 text-sm">支持文本口令、语音口令、持仓截图和 WebURL 转发读取。</div>
        </div>
      </aside>
    </section>
  );
}

export function FaqSection() {
  return (
    <section className="mx-auto w-[min(1180px,calc(100%_-_28px))] py-20 md:py-24">
      <SectionHead title="常见问题" description="把用户最关心的安全、自动下单、数据及时性和移动端体验提前说清楚。" />
      <div className="grid border-t border-[#e5ddd9] md:grid-cols-2 md:gap-x-10">
        {faqs.map(([question, answer]) => (
          <div key={question} className="min-h-28 border-b border-[#e5ddd9] py-6">
            <p className="font-black">{question}</p>
            <p className="mt-2 text-sm leading-6 text-[#6f686b]">{answer}</p>
          </div>
        ))}
      </div>
    </section>
  );
}

export function FinalCta() {
  return (
    <section className="border-t border-[#e5ddd9] bg-[linear-gradient(90deg,rgba(215,25,32,0.1),transparent_42%),#262225] py-20 text-white">
      <div className="mx-auto grid w-[min(1180px,calc(100%_-_28px))] gap-7 md:grid-cols-[minmax(0,1fr)_auto] md:items-center">
        <div>
          <h2 className="max-w-3xl text-3xl font-black leading-tight md:text-[42px]">先建立第一份持仓视图，再让 AI 帮你持续观察</h2>
          <p className="mt-3 max-w-3xl text-[#d8d1d5]">从一笔真实资产开始，逐步接入微信、交易纪律、系统行情和 AI 研究任务。</p>
        </div>
        <ButtonLink href={marketingLoginHref}>登录控制台</ButtonLink>
      </div>
    </section>
  );
}

function MarketingFooter() {
  return (
    <footer className="border-t border-white/10 bg-[#262225] text-[#cfc8cc]">
      <div className="mx-auto flex w-[min(1180px,calc(100%_-_28px))] flex-col gap-2 py-7 text-sm md:flex-row md:justify-between">
        <span>AI 持仓系统 3.0</span>
        <span>持仓分析仅供参考，不构成投资建议。交易决策需由用户自行确认。</span>
      </div>
    </footer>
  );
}

export function MarketingShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen overflow-x-hidden bg-[#fafafa] text-[#171417]">
      <MarketingHeader />
      {children}
      <MarketingFooter />
    </div>
  );
}

export function PreloginHomePage() {
  return (
    <MarketingShell>
      <main>
        <HeroSection />
        <SourcesSection />
        <OnboardingIntroSection />
        <ModulesSection />
        <ResearchFlowSection />
        <WeChatSection />
        <FaqSection />
        <FinalCta />
      </main>
    </MarketingShell>
  );
}

export function FeaturesMarketingPage() {
  return (
    <MarketingShell>
      <main>
        <HeroSection compact />
        <SourcesSection />
        <ModulesSection />
        <ResearchFlowSection />
        <WeChatSection />
        <FinalCta />
      </main>
    </MarketingShell>
  );
}
