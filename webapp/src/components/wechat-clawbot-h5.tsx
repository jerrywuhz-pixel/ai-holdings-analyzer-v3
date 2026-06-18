import Link from 'next/link';

const bindingUrl = 'https://www.11office.top/binding';
const primaryCta = bindingUrl;
const registerCta = '/login?mode=register&entry=wechat-clawbot';

const heroChecks = ['微信对话式操作，简单自然', 'AI 分析与投资建议，清晰可执行', '多端数据同步，安全可控'];

const chatMessages = [
  { side: 'bot', text: '你好，我是 ClawBot。你的 AI 持仓助手，有什么可以帮你？' },
  { side: 'user', text: '帮我绑定账户' },
  { side: 'bot', text: '好的，请先访问 www.11office.top/binding 生成绑定二维码，再用微信扫码完成绑定。' },
  { side: 'user', text: '我买入了腾讯 100 股，价格 310' },
  { side: 'bot', text: '已记录新持仓：腾讯控股 00700.HK，买入 100 股 @310。' },
  { side: 'user', text: '分析一下腾讯' },
  { side: 'bot', text: '腾讯控股分析摘要：基本面优秀，估值合理，趋势中期上升，建议关注 300 支撑。' },
  { side: 'user', text: '帮我设置纪律：单只不超过 20%' },
  { side: 'bot', text: '已创建交易纪律。后续持仓占比超过 20% 时会提醒你。' },
];

const bindSteps = [
  ['访问绑定页', '打开 www.11office.top/binding。'],
  ['生成二维码', '页面生成你的专属绑定二维码。'],
  ['微信扫码', '用微信扫码完成身份绑定。'],
  ['绑定完成', '回到 ClawBot 对话，开始管理你的持仓。'],
];

const featureSections = [
  {
    number: '02',
    title: '创建你的第一个持仓',
    summary: '支持文本输入和截图识别，快速记录股票、ETF、期权和现金线索。',
    panels: [
      ['文本输入示例', '买入腾讯 100 股，价格 310', '系统会解析标的、数量、价格和时间。'],
      ['截图识别示例', '持仓截图或成交截图', '低置信字段会提示补充，不会静默写入。'],
    ],
  },
  {
    number: '03',
    title: '买入 / 卖出自动同步',
    summary: '把成交消息转发给 ClawBot，系统解析后更新持仓记录，并保留来源与回执。',
    panels: [
      ['买入记录', '买入 AAPL 10 股 180', '写入系统交易记录，不代表自动下单。'],
      ['卖出记录', '卖出 TSLA 5 股 250', '清仓后可以继续生成复盘和二次买入条件。'],
    ],
  },
  {
    number: '04',
    title: '分析一只股票',
    summary: '输入股票名称或代码，Hermes 会结合行情、持仓成本、规则和数据质量给出摘要。',
    panels: [
      ['分析内容', '基本面、估值、趋势、风险提示', '输出行动等级：只读、观察、建议、草稿或阻断。'],
      ['继续操作', '加入观察、设置提醒、发起深研', '复杂研究会进入 Hermes 长任务，完成后推送摘要。'],
    ],
  },
  {
    number: '05',
    title: '加入观察清单与价格提醒',
    summary: '把可能买入或 Sell Put 的标的先放入观察区，记录理由、价位和复核时间。',
    panels: [
      ['我的自选股', '腾讯控股、美团、比亚迪', '每个标的保留观察理由和触发条件。'],
      ['价格提醒', '跌破 300 提醒我', '命中后只提示观察和后续口令，不变成下单建议。'],
    ],
  },
  {
    number: '06',
    title: '建立交易纪律',
    summary: '预设规则，AI 监督，帮助你更自律地执行投资计划。',
    panels: [
      ['纪律示例', '单只持仓不超过总资产 20%', '超过阈值时，系统会提示集中度风险。'],
      ['规则命中', '止损、财报窗口、Sell Put 现金上限', 'hard block 类型规则不会被模型自动覆盖。'],
    ],
  },
];

const safetyItems = [
  ['不代下单', 'ClawBot 不执行任何交易指令，所有操作由你自主完成。'],
  ['数据安全', '采用加密传输与存储，你的数据仅你可见。'],
  ['可溯数据源', '接入权威数据源与实时行情，保留分析客观准确。'],
  ['多重确认', '重要操作先提醒和确认，避免误操作与遗漏。'],
];

function Icon({
  name,
  className = 'h-5 w-5',
}: {
  name: 'check' | 'shield' | 'qr' | 'bell' | 'lock' | 'database' | 'chart' | 'message';
  className?: string;
}) {
  const common = {
    className,
    viewBox: '0 0 24 24',
    fill: 'none',
    stroke: 'currentColor',
    strokeWidth: 1.9,
    strokeLinecap: 'round' as const,
    strokeLinejoin: 'round' as const,
    'aria-hidden': true,
  };

  if (name === 'check') {
    return (
      <svg {...common}>
        <path d="M20 6 9 17l-5-5" />
      </svg>
    );
  }
  if (name === 'qr') {
    return (
      <svg {...common}>
        <path d="M4 4h6v6H4zM14 4h6v6h-6zM4 14h6v6H4z" />
        <path d="M14 14h2v2h-2zM18 14h2v6h-4v-2h2zM14 18h2v2h-2z" />
      </svg>
    );
  }
  if (name === 'bell') {
    return (
      <svg {...common}>
        <path d="M18 8a6 6 0 0 0-12 0c0 7-3 6-3 9h18c0-3-3-2-3-9" />
        <path d="M10 21h4" />
      </svg>
    );
  }
  if (name === 'lock') {
    return (
      <svg {...common}>
        <path d="M7 10V8a5 5 0 0 1 10 0v2" />
        <path d="M5 10h14v10H5z" />
      </svg>
    );
  }
  if (name === 'database') {
    return (
      <svg {...common}>
        <path d="M4 6c0-2 16-2 16 0s-16 2-16 0" />
        <path d="M4 6v6c0 2 16 2 16 0V6" />
        <path d="M4 12v6c0 2 16 2 16 0v-6" />
      </svg>
    );
  }
  if (name === 'chart') {
    return (
      <svg {...common}>
        <path d="M4 19V5" />
        <path d="M4 19h16" />
        <path d="m7 15 4-5 3 3 5-7" />
      </svg>
    );
  }
  if (name === 'message') {
    return (
      <svg {...common}>
        <path d="M5 5h14v10H8l-3 4z" />
      </svg>
    );
  }
  return (
    <svg {...common}>
      <path d="M12 3 20 7v5c0 5-3.4 8.2-8 9-4.6-.8-8-4-8-9V7z" />
      <path d="m9 12 2 2 4-5" />
    </svg>
  );
}

function H5Button({
  href,
  children,
  secondary = false,
}: {
  href: string;
  children: React.ReactNode;
  secondary?: boolean;
}) {
  const className = [
    'inline-flex min-h-11 items-center justify-center rounded-lg px-5 py-3 text-sm font-black transition',
    secondary
      ? 'border border-[#e2e2e2] bg-white text-[#191719] hover:border-[#cfcfcf]'
      : 'bg-[#d71920] text-white shadow-[0_18px_34px_rgba(215,25,32,0.22)] hover:bg-[#bd151b]',
  ].join(' ');

  if (href.startsWith('http')) {
    return (
      <a href={href} className={className}>
        {children}
      </a>
    );
  }

  return (
    <Link href={href} className={className}>
      {children}
    </Link>
  );
}

function PhoneChat() {
  return (
    <div className="mx-auto w-full max-w-[350px] rounded-[34px] border-[8px] border-[#1b1b1d] bg-[#f5f5f5] shadow-[0_28px_80px_rgba(0,0,0,0.22)]">
      <div className="rounded-[26px] border border-black/10 bg-white">
        <div className="flex h-14 items-center justify-between border-b border-[#ececec] px-4 text-[#191719]">
          <span className="text-xl">‹</span>
          <div className="text-center">
            <p className="text-sm font-black">ClawBot</p>
            <p className="text-[10px] text-[#858585]">Hermes 持仓助手</p>
          </div>
          <span className="text-xl">···</span>
        </div>
        <div className="h-[620px] space-y-3 overflow-hidden bg-[#f6f6f6] px-3 py-4">
          {chatMessages.map((message, index) => (
            <div key={`${message.side}-${index}`} className={message.side === 'user' ? 'flex justify-end' : 'flex justify-start gap-2'}>
              {message.side === 'bot' ? (
                <span className="mt-1 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-white text-[#d71920] shadow-sm">
                  <Icon name="message" className="h-4 w-4" />
                </span>
              ) : null}
              <div
                className={[
                  'max-w-[235px] rounded-lg px-3 py-2 text-xs leading-5 shadow-sm',
                  message.side === 'user' ? 'bg-[#bce7a8] text-[#17310f]' : 'bg-white text-[#333]',
                ].join(' ')}
              >
                {message.text}
              </div>
            </div>
          ))}
        </div>
        <div className="flex h-12 items-center gap-2 border-t border-[#ececec] px-3">
          <span className="h-7 w-7 rounded-full border border-[#d9d9d9]" />
          <span className="h-8 flex-1 rounded-lg bg-[#f4f4f4]" />
          <span className="h-7 w-7 rounded-full border border-[#d9d9d9]" />
        </div>
      </div>
    </div>
  );
}

function SectionCard({
  number,
  title,
  summary,
  children,
}: {
  number: string;
  title: string;
  summary: string;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-lg border border-[#e8e8e8] bg-white p-5 shadow-[0_18px_44px_rgba(25,23,25,0.05)] md:p-7">
      <div className="mb-5">
        <div className="flex items-baseline gap-3">
          <span className="text-3xl font-black text-[#d71920]">{number}</span>
          <h2 className="text-2xl font-black leading-tight text-[#191719]">{title}</h2>
        </div>
        <p className="mt-2 text-sm leading-6 text-[#6d6669]">{summary}</p>
      </div>
      {children}
    </section>
  );
}

function FeaturePanel({ title, value, detail }: { title: string; value: string; detail: string }) {
  return (
    <div className="rounded-lg border border-[#eeeeee] bg-[#fbfbfb] p-4">
      <p className="text-sm font-black text-[#191719]">{title}</p>
      <p className="mt-3 rounded-lg bg-[#e8f6df] px-3 py-2 text-sm font-bold text-[#285b1e]">{value}</p>
      <p className="mt-3 text-xs leading-5 text-[#6d6669]">{detail}</p>
    </div>
  );
}

export function WechatClawbotH5Page() {
  return (
    <div className="min-h-screen bg-[#f7f7f7] text-[#191719]">
      <header className="sticky top-0 z-40 border-b border-[#e9e9e9] bg-white/92 backdrop-blur">
        <nav className="mx-auto flex min-h-14 w-[min(1120px,calc(100%_-_28px))] items-center justify-between gap-3">
          <Link href="/" className="flex min-w-0 items-center gap-2 font-black text-[#191719]">
            <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-[#d71920] text-white">
              <Icon name="shield" className="h-5 w-5" />
            </span>
            <span className="truncate">AI 持仓系统</span>
          </Link>
          <H5Button href={primaryCta}>开始绑定</H5Button>
        </nav>
      </header>

      <main>
        <section className="mx-auto grid w-[min(1120px,calc(100%_-_28px))] gap-10 py-10 md:grid-cols-[minmax(0,0.88fr)_minmax(330px,0.72fr)] md:items-center md:py-16">
          <div className="max-w-xl">
            <h1 className="text-4xl font-black leading-[1.08] tracking-[-0.01em] text-[#191719] md:text-[58px]">
              从<span className="text-[#d71920]">微信</span>开始
              <br />
              管理你的持仓
            </h1>
            <p className="mt-5 text-base leading-8 text-[#5d575a] md:text-lg">
              访问绑定页生成二维码，再用微信扫码绑定 ClawBot。绑定后，你可以随时记录、同步、分析持仓，让 Hermes 把股票、观察清单、交易纪律和提醒串成一个可追踪的投资工作流。
            </p>
            <div className="mt-7 flex flex-col gap-3 sm:flex-row">
              <H5Button href={primaryCta}>生成绑定二维码</H5Button>
              <H5Button href={registerCta} secondary>
                先创建账号
              </H5Button>
            </div>
            <div className="mt-7 grid gap-3">
              {heroChecks.map((item) => (
                <div key={item} className="flex items-center gap-3 text-sm font-semibold text-[#514b4e]">
                  <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full border border-[#ffb3b6] bg-[#fff1f1] text-[#d71920]">
                    <Icon name="check" className="h-4 w-4" />
                  </span>
                  {item}
                </div>
              ))}
            </div>
            <div className="mt-7 rounded-lg border border-[#e8e8e8] bg-white p-4 shadow-[0_12px_32px_rgba(25,23,25,0.04)]">
              <p className="text-xs font-black text-[#6d6669]">访问绑定页面</p>
              <p className="mt-2 rounded-lg bg-[#f4f4f4] px-3 py-2 font-mono text-sm font-bold text-[#191719]">
                www.11office.top/binding
              </p>
              <p className="mt-2 text-xs leading-5 text-[#8a8587]">页面会生成专属二维码，使用微信扫码后完成绑定。</p>
            </div>
            <p className="mt-4 flex items-center gap-2 text-xs font-semibold text-[#8a8587]">
              <Icon name="shield" className="h-4 w-4" />
              安全、私密、不代下单
            </p>
          </div>
          <PhoneChat />
        </section>

        <div className="mx-auto grid w-[min(1120px,calc(100%_-_28px))] gap-5 pb-10 md:gap-6 md:pb-16">
          <SectionCard number="01" title="绑定 ClawBot" summary="三步完成绑定，立即开启持仓管理。">
            <div className="grid gap-3 md:grid-cols-4">
              {bindSteps.map(([title, detail], index) => (
                <div key={title} className="rounded-lg border border-[#eeeeee] bg-[#fbfbfb] p-4">
                  <div className="mb-4 flex items-center justify-between">
                    <span className="flex h-12 w-12 items-center justify-center rounded-lg bg-white text-[#d71920] shadow-sm">
                      <Icon name={index === 0 ? 'message' : index === 1 ? 'qr' : index === 2 ? 'shield' : 'check'} className="h-6 w-6" />
                    </span>
                    <span className="text-xs font-black text-[#c7c1c4]">0{index + 1}</span>
                  </div>
                  <p className="text-sm font-black text-[#191719]">{title}</p>
                  <p className="mt-2 text-xs leading-5 text-[#6d6669]">{detail}</p>
                </div>
              ))}
            </div>
          </SectionCard>

          {featureSections.map((section) => (
            <SectionCard key={section.number} number={section.number} title={section.title} summary={section.summary}>
              <div className="grid gap-3 md:grid-cols-2">
                {section.panels.map(([title, value, detail]) => (
                  <FeaturePanel key={title} title={title} value={value} detail={detail} />
                ))}
              </div>
            </SectionCard>
          ))}

          <SectionCard number="07" title="安全承诺" summary="你的资金安全，是系统设计的底线。">
            <div className="grid gap-3 md:grid-cols-4">
              {safetyItems.map(([title, detail], index) => (
                <div key={title} className="rounded-lg border border-[#eeeeee] bg-[#fbfbfb] p-4">
                  <span className="mb-4 flex h-11 w-11 items-center justify-center rounded-lg bg-white text-[#d71920] shadow-sm">
                    <Icon name={index === 0 ? 'shield' : index === 1 ? 'lock' : index === 2 ? 'database' : 'check'} className="h-6 w-6" />
                  </span>
                  <p className="text-sm font-black text-[#191719]">{title}</p>
                  <p className="mt-2 text-xs leading-5 text-[#6d6669]">{detail}</p>
                </div>
              ))}
            </div>
          </SectionCard>

          <section className="rounded-lg bg-[#d71920] px-5 py-8 text-center text-white shadow-[0_18px_44px_rgba(215,25,32,0.22)]">
            <h2 className="text-2xl font-black">开始绑定 ClawBot</h2>
            <p className="mx-auto mt-3 max-w-xl text-sm leading-6 text-white/85">
              打开 www.11office.top/binding 生成绑定二维码，并使用微信扫码。完成后，你就可以用微信新建持仓、同步买卖、分析股票、设置观察和建立交易纪律。
            </p>
            <div className="mt-6 flex flex-col justify-center gap-3 sm:flex-row">
              <Link
                href={primaryCta}
                className="inline-flex min-h-16 w-full items-center justify-center rounded-lg bg-white px-7 py-5 text-lg font-black text-[#d71920] shadow-[0_16px_30px_rgba(84,0,0,0.18)] transition hover:bg-[#fff4f4] sm:w-auto sm:min-w-[320px]"
              >
                生成绑定二维码
              </Link>
              <Link
                href="/features"
                className="inline-flex min-h-11 items-center justify-center rounded-lg border border-white/35 px-5 py-3 text-sm font-black text-white transition hover:bg-white/10"
              >
                查看完整功能
              </Link>
            </div>
          </section>
        </div>
      </main>
    </div>
  );
}
