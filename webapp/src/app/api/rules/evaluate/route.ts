import { NextRequest, NextResponse } from 'next/server';
import { ensureUserAccount } from '@/lib/account-store';
import { requireUser } from '@/lib/supabase';
import { evaluateTradingDiscipline } from '@/lib/trading-rules';

export const runtime = 'nodejs';

function asOptionalString(value: unknown) {
  return typeof value === 'string' && value.trim() ? value.trim() : undefined;
}

function asOptionalNumber(value: unknown) {
  if (value === null || value === undefined || value === '') return null;
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

export async function POST(request: NextRequest) {
  const session = await requireUser();
  const account = await ensureUserAccount(session.user);
  const body = await request.json().catch(() => null);

  const actionType = asOptionalString(body?.actionType);
  if (!actionType) {
    return NextResponse.json({ error: '缺少检查场景' }, { status: 400 });
  }

  const result = await evaluateTradingDiscipline(account.tenantId, {
    actionType,
    symbol: asOptionalString(body?.symbol),
    name: asOptionalString(body?.name),
    market: asOptionalString(body?.market),
    instrumentType: asOptionalString(body?.instrumentType),
    sourceTier: asOptionalString(body?.sourceTier),
    sourceActionability: asOptionalString(body?.sourceActionability),
    isExtendedHours: body?.isExtendedHours === true,
    cashBufferPct: asOptionalNumber(body?.cashBufferPct),
    payload: typeof body?.payload === 'object' && body.payload !== null ? body.payload : {},
  });

  return NextResponse.json(result);
}
