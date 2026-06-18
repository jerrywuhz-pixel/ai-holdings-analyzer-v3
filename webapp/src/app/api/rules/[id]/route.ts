import { NextRequest, NextResponse } from 'next/server';
import { ensureUserAccount } from '@/lib/account-store';
import { requireUser } from '@/lib/supabase';
import {
  deactivateTradingRuleForTenant,
  updateTradingRuleForTenant,
  type TradingRuleAction,
} from '@/lib/trading-rules';

export const runtime = 'nodejs';

function parseStringArray(value: unknown) {
  if (Array.isArray(value)) return value.map((item) => String(item).trim()).filter(Boolean);
  if (typeof value === 'string') {
    return value
      .split(/[\n,，]/)
      .map((item) => item.trim())
      .filter(Boolean);
  }
  return undefined;
}

export async function PATCH(
  request: NextRequest,
  context: { params: Promise<{ id: string }> }
) {
  const session = await requireUser();
  const account = await ensureUserAccount(session.user);
  const params = await context.params;
  const body = await request.json().catch(() => null);

  try {
    const rule = await updateTradingRuleForTenant(account.tenantId, params.id, {
      name: body?.name === undefined ? undefined : String(body.name),
      ruleType: body?.ruleType === undefined ? undefined : String(body.ruleType),
      scopes: parseStringArray(body?.scopes),
      markets: parseStringArray(body?.markets),
      instruments: parseStringArray(body?.instruments),
      condition: body?.condition === undefined ? undefined : body.condition,
      message: body?.message === undefined ? undefined : String(body.message),
      actionOnViolation: body?.actionOnViolation as TradingRuleAction | undefined,
      priority: body?.priority === undefined ? undefined : Number(body.priority),
      isActive: body?.isActive === undefined ? undefined : Boolean(body.isActive),
    });
    return NextResponse.json({ status: 'updated', rule });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : '规则更新失败' },
      { status: 400 }
    );
  }
}

export async function DELETE(
  _request: NextRequest,
  context: { params: Promise<{ id: string }> }
) {
  const session = await requireUser();
  const account = await ensureUserAccount(session.user);
  const params = await context.params;

  try {
    const rule = await deactivateTradingRuleForTenant(account.tenantId, params.id);
    return NextResponse.json({ status: 'deactivated', rule });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : '规则停用失败' },
      { status: 400 }
    );
  }
}
