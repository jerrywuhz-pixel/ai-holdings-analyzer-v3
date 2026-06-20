import { NextResponse } from 'next/server';

export const runtime = 'nodejs';

export async function POST() {
  return NextResponse.json(
    { error: '试用阶段不开放自助注册，请联系管理员为已绑定微信账号分配登录账号。' },
    { status: 410 }
  );
}
