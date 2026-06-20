import { NextResponse } from 'next/server';

export const runtime = 'nodejs';

export async function POST() {
  return NextResponse.json(
    { error: '邮箱验证码流程已下线，请使用管理员分配的账号密码登录。' },
    { status: 410 }
  );
}
