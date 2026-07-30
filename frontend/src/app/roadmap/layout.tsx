import { notFound } from 'next/navigation';
import { RELEASE_SCOPE } from '@/lib/release-scope';

export default function RoadmapReleaseGuard({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  if (!RELEASE_SCOPE.roadmap) notFound();
  return children;
}
