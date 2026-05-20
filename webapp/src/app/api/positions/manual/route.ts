import { NextRequest, NextResponse } from 'next/server';
import { upsertManualPosition } from '@/lib/account-store';
import { requireUser } from '@/lib/supabase';

export const runtime = 'nodejs';

function parseNullableNumber(value: unknown) {
  if (value === null || value === undefined || value === '') return null;
  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? numberValue : null;
}

export async function POST(request: NextRequest) {
  const session = await requireUser();
  const body = await request.json().catch(() => null);

  try {
    const quantity = Number(body?.quantity);
    const result = await upsertManualPosition(session.user, {
      instrumentType: body?.instrumentType,
      symbol: String(body?.symbol || ''),
      name: String(body?.name || ''),
      market: String(body?.market || 'US'),
      exchange: String(body?.exchange || ''),
      quantity,
      averageCost: parseNullableNumber(body?.averageCost),
      marketPrice: parseNullableNumber(body?.marketPrice),
      marketValue: parseNullableNumber(body?.marketValue),
      currency: String(body?.currency || ''),
      note: String(body?.note || ''),
    });

    return NextResponse.json({
      status: 'saved',
      position: result.position,
      snapshotId: result.snapshotId,
      message: '持仓已记录，并已刷新当前账户的持仓快照。',
    });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : '持仓录入失败' },
      { status: 400 }
    );
  }
}
