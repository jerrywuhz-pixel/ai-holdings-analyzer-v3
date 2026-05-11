'use client';

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="rounded-2xl border border-red-500/25 bg-red-500/10 p-5">
      <p className="text-sm font-medium text-red-200">页面渲染失败</p>
      <p className="mt-2 text-sm leading-6 text-red-100/85">{error.message}</p>
      <button
        type="button"
        onClick={reset}
        className="mt-4 rounded-xl border border-red-400/20 bg-red-500/10 px-3 py-2 text-sm text-red-100 transition hover:bg-red-500/15"
      >
        重试
      </button>
    </div>
  );
}
