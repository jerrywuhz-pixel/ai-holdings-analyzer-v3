import { NextRequest, NextResponse } from 'next/server';
import { ensureUserAccount } from '@/lib/account-store';
import { requireUser } from '@/lib/supabase';
import {
  createTradingRuleForTenant,
  getTradingRulesDashboard,
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
  return [];
}

export async function GET() {
  const session = await requireUser();
  const account = await ensureUserAccount(session.user);
  const dashboard = await getTradingRulesDashboard(account.tenantId);
  return NextResponse.json(dashboard);
}

export async function POST(request: NextRequest) {
  const session = await requireUser();
  const account = await ensureUserAccount(session.user);
  const body = await request.json().catch(() => null);

  try {
    const rule = await createTradingRuleForTenant(account.tenantId, {
      name: String(body?.name || ''),
      ruleKey: body?.ruleKey ? String(body.ruleKey) : undefined,
      ruleType: body?.ruleType ? String(body.ruleType) : undefined,
      scopes: parseStringArray(body?.scopes),
      markets: parseStringArray(body?.markets),
      instruments: parseStringArray(body?.instruments),
      condition: typeof body?.condition === 'object' && body.condition !== null ? body.condition : {},
      message: body?.message ? String(body.message) : undefined,
      actionOnViolation: body?.actionOnViolation as TradingRuleAction | undefined,
      priority: Number(body?.priority),
      source: body?.source ? String(body.source) : undefined,
    });

    return NextResponse.json({ status: 'created', rule });
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : '规则创建失败' },
      { status: 400 }
    );
  }
}
