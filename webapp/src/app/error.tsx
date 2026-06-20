'use client';

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="rounded-lg border border-[#efb5b2] bg-[#fff0ef] p-5">
      <p className="text-sm font-medium text-[#d71920]">页面渲染失败</p>
      <p className="mt-2 text-sm leading-6 text-[#a8181e]/85">{error.message}</p>
      <button
        type="button"
        onClick={reset}
        className="mt-4 rounded-lg border border-[#f0c8c5] bg-[#fff0ef] px-3 py-2 text-sm text-[#a8181e] transition hover:bg-[#ffe9e7]"
      >
        重试
      </button>
    </div>
  );
}
