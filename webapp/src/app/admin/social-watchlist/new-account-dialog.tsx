'use client';

import { useRef } from 'react';
import type { ReactNode } from 'react';

export function NewAccountDialog({ children }: { children: ReactNode }) {
  const dialogRef = useRef<HTMLDialogElement>(null);

  return (
    <>
      <button
        type="button"
        className="rounded-md bg-red-500 px-4 py-2 text-sm font-medium text-white transition hover:bg-red-400"
        onClick={() => dialogRef.current?.showModal()}
      >
        新增账号
      </button>
      <dialog
        ref={dialogRef}
        className="w-[min(720px,calc(100vw-32px))] max-h-[calc(100vh-48px)] overflow-y-auto rounded-lg border border-white/10 bg-[#111419] p-0 text-slate-100 shadow-[0_24px_80px_rgba(0,0,0,0.55)] backdrop:bg-black/70"
        onClick={(event) => {
          if (event.target === dialogRef.current) {
            dialogRef.current?.close();
          }
        }}
      >
        <div className="flex items-center justify-between gap-4 border-b border-white/10 px-6 py-4">
          <h2 className="text-lg font-medium text-white">新增账号</h2>
          <button
            type="button"
            className="rounded-md border border-white/15 bg-white/[0.04] px-3 py-1.5 text-sm font-medium text-slate-200 transition hover:bg-white/[0.08]"
            onClick={() => dialogRef.current?.close()}
          >
            关闭
          </button>
        </div>
        {children}
      </dialog>
    </>
  );
}
