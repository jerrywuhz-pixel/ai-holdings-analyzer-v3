import { redirect } from 'next/navigation';
import { getOnboardingState, nextOnboardingPath } from '@/lib/onboarding';

export const dynamic = 'force-dynamic';

export default async function OnboardingPage() {
  const state = await getOnboardingState();
  redirect(nextOnboardingPath(state));
}
