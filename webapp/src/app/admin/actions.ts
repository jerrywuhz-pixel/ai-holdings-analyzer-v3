'use server';

import { revalidatePath } from 'next/cache';
import { redirect } from 'next/navigation';
import {
  deleteSocialWatchAccount,
  getSocialWatchAccount,
  importSocialWatchAccountsJson,
  normalizeSymbols,
  saveSocialWatchAccount,
} from '@/lib/social-watchlist';
import { requireAdmin } from '@/lib/supabase';

function formValue(formData: FormData, key: string) {
  const value = formData.get(key);
  return typeof value === 'string' ? value.trim() : '';
}

function redirectWithStatus(path: string, key: 'error' | 'success', message: string): never {
  const params = new URLSearchParams({ [key]: message });
  redirect(`${path}?${params.toString()}`);
}

async function assignWechatLoginInternal(formData: FormData) {
  await requireAdmin();

  const tenantId = formValue(formData, 'tenantId');
  const loginName = formValue(formData, 'loginName');
  const password = formValue(formData, 'password');
  const displayName = formValue(formData, 'displayName');
  const roleValue = formValue(formData, 'role');
  const role = roleValue === 'admin' ? 'admin' : 'user';
  const [{ ensureUserAccount }, localAuthStore] = await Promise.all([
    import('@/lib/account-store'),
    import('@/lib/local-auth-store'),
  ]);
  const upsertAssignedLocalUser = (localAuthStore as any).upsertAssignedLocalUser as
    | ((input: {
        tenantId: string;
        loginName: string;
        password: string;
        displayName: string;
        role: 'user' | 'admin';
      }) => Promise<{ id: string; email: string; displayName: string; role: 'user' | 'admin' }>)
    | undefined;
  if (!upsertAssignedLocalUser) {
    throw new Error('当前部署版本暂不支持在此页分配登录账号');
  }

  const user = await upsertAssignedLocalUser({
    tenantId,
    loginName,
    password,
    displayName,
    role,
  });
  await ensureUserAccount({
    id: user.id,
    email: user.email,
    name: user.displayName,
    role: user.role,
    provider: 'local',
  } as any);

  revalidatePath('/admin');
}

export async function assignWechatLogin(formData: FormData) {
  try {
    await assignWechatLoginInternal(formData);
  } catch (error) {
    const message = error instanceof Error ? error.message : '账号分配失败，请稍后重试';
    redirectWithStatus('/admin', 'error', message);
  }
  redirectWithStatus('/admin', 'success', '登录账号已更新');
}

export async function createWebappLoginForWechat(formData: FormData) {
  try {
    await assignWechatLoginInternal(formData);
  } catch (error) {
    const message = error instanceof Error ? error.message : '账号创建失败，请稍后重试';
    redirectWithStatus('/admin/accounts/new', 'error', message);
  }
  revalidatePath('/admin/accounts/new');
  redirectWithStatus('/admin', 'success', 'WebApp 登录账号已创建');
}

export async function saveSocialWatchAccountAction(formData: FormData) {
  try {
    await requireAdmin();
    const id = formValue(formData, 'id');
    const existing = id ? await getSocialWatchAccount(id) : null;
    const xsecToken = formValue(formData, 'xsecToken') || existing?.xsecToken || '';
    await saveSocialWatchAccount({
      id: id || undefined,
      tenantId: formValue(formData, 'tenantId') || null,
      platform: formValue(formData, 'platform'),
      handle: formValue(formData, 'handle'),
      displayName: formValue(formData, 'displayName') || null,
      url: formValue(formData, 'url') || null,
      channelUrl: formValue(formData, 'channelUrl') || null,
      userId: formValue(formData, 'userId') || null,
      xsecToken,
      symbols: normalizeSymbols([formValue(formData, 'symbols')]),
      priority: Number(formValue(formData, 'priority') || 100),
      isActive: formData.get('isActive') === 'on',
      notes: formValue(formData, 'notes') || null,
    });
    revalidatePath('/admin/social-watchlist');
  } catch (error) {
    const message = error instanceof Error ? error.message : '社媒关注账号保存失败';
    redirectWithStatus('/admin/social-watchlist', 'error', message);
  }
  redirectWithStatus('/admin/social-watchlist', 'success', '社媒关注账号已保存');
}

export async function deleteSocialWatchAccountAction(formData: FormData) {
  try {
    await requireAdmin();
    const id = formValue(formData, 'id');
    if (!id) throw new Error('缺少关注账号 id');
    await deleteSocialWatchAccount(id);
    revalidatePath('/admin/social-watchlist');
  } catch (error) {
    const message = error instanceof Error ? error.message : '社媒关注账号删除失败';
    redirectWithStatus('/admin/social-watchlist', 'error', message);
  }
  redirectWithStatus('/admin/social-watchlist', 'success', '社媒关注账号已删除');
}

export async function importSocialWatchAccountsAction(formData: FormData) {
  let importedCount = 0;
  try {
    await requireAdmin();
    const raw = formValue(formData, 'watchlistJson');
    if (!raw) throw new Error('请粘贴 JSON 清单');
    const saved = await importSocialWatchAccountsJson(raw);
    importedCount = saved.length;
    revalidatePath('/admin/social-watchlist');
  } catch (error) {
    const message = error instanceof Error ? error.message : '社媒关注清单导入失败';
    redirectWithStatus('/admin/social-watchlist', 'error', message);
  }
  redirectWithStatus('/admin/social-watchlist', 'success', `已导入 ${importedCount} 个社媒关注账号`);
}
