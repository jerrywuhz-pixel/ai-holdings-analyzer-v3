import { requireUser } from '@/lib/supabase';

export const dynamic = 'force-dynamic';

/* ------------------------------------------------------------------ */
/*  Types                                                              */
/* ------------------------------------------------------------------ */
interface DailyReport {
  id: string;
  tenant_id: string;
  report_date: string;
  market: string;
  report_type: string;
  content: string;
  summary: string | null;
  created_at: string;
}

/* ------------------------------------------------------------------ */
/*  Helpers                                                            */
/* ------------------------------------------------------------------ */
function marketLabel(market: string): string {
  switch (market) {
    case 'CN': return 'A股';
    case 'US': return '美股';
    case 'HK': return '港股';
    default: return market;
  }
}

function reportTypeLabel(type: string): string {
  switch (type) {
    case 'daily': return '日报';
    case 'weekly': return '周报';
    case 'monthly': return '月报';
    default: return type;
  }
}

/* ------------------------------------------------------------------ */
/*  Page                                                                */
/* ------------------------------------------------------------------ */
export default async function WeeklyPage() {
  const { supabase } = await requireUser();
  /* daily_reports 表可能在 Phase 5 之后才创建，这里做安全降级 */
  let reports: DailyReport[] = [];
  let tableExists = true;

  const { data, error } = await supabase
    .from('daily_reports')
    .select('id, tenant_id, report_date, market, report_type, content, summary, created_at')
    .order('report_date', { ascending: false })
    .limit(50);

  if (error) {
    // Table might not exist yet
    if (error.code === '42P01' || error.message?.includes('does not exist')) {
      tableExists = false;
    }
    // Otherwise just show empty
  } else {
    reports = data ?? [];
  }

  return (
    <div className="mx-auto max-w-4xl">
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-gray-900">投资周报</h1>
        <p className="mt-1 text-sm text-gray-500">
          查看每日/每周投资分析报告。
        </p>
      </div>

      {!tableExists ? (
        /* Table not yet available */
        <div className="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-gray-300 bg-white py-16">
          <svg className="h-12 w-12 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
          <h3 className="mt-4 text-lg font-medium text-gray-900">报告功能即将上线</h3>
          <p className="mt-1 text-sm text-gray-500">
            周报功能将在系统 Phase 5 完成后自动启用，敬请期待。
          </p>
        </div>
      ) : reports.length === 0 ? (
        /* Table exists but no data */
        <div className="flex flex-col items-center justify-center rounded-lg border-2 border-dashed border-gray-300 bg-white py-16">
          <svg className="h-12 w-12 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
          <h3 className="mt-4 text-lg font-medium text-gray-900">暂无报告</h3>
          <p className="mt-1 text-sm text-gray-500">
            系统尚未生成任何投资分析报告。
          </p>
        </div>
      ) : (
        /* Reports list */
        <div className="space-y-4">
          {reports.map((report) => (
            <ReportCard key={report.id} report={report} />
          ))}
        </div>
      )}
    </div>
  );
}

/* ------------------------------------------------------------------ */
/*  Sub-components                                                      */
/* ------------------------------------------------------------------ */

function ReportCard({ report }: { report: DailyReport }) {
  return (
    <details className="group rounded-lg bg-white shadow">
      <summary className="flex cursor-pointer items-center justify-between px-6 py-4 hover:bg-gray-50">
        <div className="flex items-center gap-3">
          <span className="text-sm font-medium text-gray-900">{report.report_date}</span>
          <span className="inline-flex items-center rounded-full bg-blue-100 px-2.5 py-0.5 text-xs font-medium text-blue-800">
            {marketLabel(report.market)}
          </span>
          <span className="inline-flex items-center rounded-full bg-gray-100 px-2.5 py-0.5 text-xs font-medium text-gray-800">
            {reportTypeLabel(report.report_type)}
          </span>
        </div>
        <svg
          className="h-5 w-5 text-gray-400 transition-transform group-open:rotate-180"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={2}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
        </svg>
      </summary>
      <div className="border-t border-gray-200 px-6 py-4">
        {report.summary && (
          <p className="mb-3 text-sm font-medium text-gray-700">{report.summary}</p>
        )}
        <div className="whitespace-pre-wrap text-sm text-gray-600">{report.content}</div>
      </div>
    </details>
  );
}
