import { NextRequest, NextResponse } from 'next/server';
import QRCode from 'qrcode';
import { getWechatQrTargetUrl } from '@/lib/wechat-binding';
import { requireUser } from '@/lib/supabase';

export const runtime = 'nodejs';

function svgResponse(svg: string) {
  return new NextResponse(svg, {
    headers: {
      'Content-Type': 'image/svg+xml; charset=utf-8',
      'Cache-Control': 'no-store, max-age=0',
      'X-Content-Type-Options': 'nosniff',
    },
  });
}

function jsonError(error: unknown, status = 400) {
  return NextResponse.json(
    { error: error instanceof Error ? error.message : '微信二维码生成失败' },
    { status }
  );
}

export async function GET(request: NextRequest) {
  const { user } = await requireUser();
  const authSessionId = request.nextUrl.searchParams.get('authSessionId')?.trim();

  if (!authSessionId) {
    return jsonError(new Error('缺少微信绑定会话 ID'));
  }

  try {
    const targetUrl = await getWechatQrTargetUrl(user, authSessionId);
    const svg = await QRCode.toString(targetUrl, {
      type: 'svg',
      width: 244,
      margin: 2,
      errorCorrectionLevel: 'M',
      color: {
        dark: '#020617',
        light: '#ffffff',
      },
    });

    return svgResponse(svg);
  } catch (error) {
    return jsonError(error);
  }
}
