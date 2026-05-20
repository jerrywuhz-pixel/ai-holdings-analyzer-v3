import LoginForm from './LoginForm';
import { getAuthModeLabel } from '@/lib/supabase';

export default function LoginPage() {
  return (
    <div className="min-h-[calc(100vh-4rem)] bg-gray-50 px-4 py-10">
      <LoginForm authModeLabel={getAuthModeLabel()} />
    </div>
  );
}
