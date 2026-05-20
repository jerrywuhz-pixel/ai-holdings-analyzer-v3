import { NextResponse } from 'next/server';
import { ensureUserAccount } from '@/lib/account-store';
import { requireUser } from '@/lib/supabase';

export const runtime = 'nodejs';

export async function GET() {
  try {
    const session = await requireUser();
    const account = await ensureUserAccount(session.user);
    return NextResponse.json({ account });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : '账户初始化失败' },
      { status: 500 }
    );
  }
}
