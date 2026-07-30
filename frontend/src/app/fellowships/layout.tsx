import { notFound } from 'next/navigation';
import { RELEASE_SCOPE } from '@/lib/release-scope';

export default function FellowshipsReleaseGuard({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  if (!RELEASE_SCOPE.fellowships) notFound();
  return children;
}
