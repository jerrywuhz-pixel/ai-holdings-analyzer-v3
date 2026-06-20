import { PageHeader, Panel } from '@/components/p0-ui';
import { requireUser } from '@/lib/supabase';
import ChangePasswordForm from './ChangePasswordForm';

export const dynamic = 'force-dynamic';

export default async function ChangePasswordPage() {
  await requireUser();

  return (
    <div className="space-y-6">
      <PageHeader
        eyebrow="账户安全"
        title="修改登录密码"
        description="使用当前密码验证身份后，可以更新 WebApp 本地登录账号的密码。"
      />

      <div className="max-w-3xl">
        <Panel title="登录密码" description="密码更新后，当前登录状态会继续保留；下次登录请使用新密码。">
          <ChangePasswordForm />
        </Panel>
      </div>
    </div>
  );
}
