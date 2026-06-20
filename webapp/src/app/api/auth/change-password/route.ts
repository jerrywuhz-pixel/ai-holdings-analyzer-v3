import { NextRequest, NextResponse } from 'next/server';
import { changeLocalUserPassword } from '@/lib/local-auth-store';
import { requireUser } from '@/lib/supabase';

export const runtime = 'nodejs';

export async function POST(request: NextRequest) {
  const session = await requireUser();
  const body = await request.json().catch(() => null);
  const currentPassword = String(body?.currentPassword || '');
  const newPassword = String(body?.newPassword || '');
  const confirmPassword = String(body?.confirmPassword || '');

  if (!currentPassword || !newPassword || !confirmPassword) {
    return NextResponse.json({ error: '请输入当前密码、新密码和确认密码' }, { status: 400 });
  }
  if (newPassword !== confirmPassword) {
    return NextResponse.json({ error: '两次输入的新密码不一致' }, { status: 400 });
  }

  const result = await changeLocalUserPassword({
    userId: session.user.id,
    currentPassword,
    newPassword,
  });
  if (!result.ok) {
    const status = result.error === '当前密码不正确' ? 401 : 400;
    return NextResponse.json({ error: result.error || '密码修改失败' }, { status });
  }

  return NextResponse.json({ ok: true });
}
