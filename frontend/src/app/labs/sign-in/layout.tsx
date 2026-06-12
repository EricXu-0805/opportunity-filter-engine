import type { Metadata } from 'next';

// Labs routes are direct-URL design previews: keep them out of search
// indexes and give the tab a recognizable title.
export const metadata: Metadata = {
  title: 'Labs · Sign-in modal redesign preview',
  robots: { index: false, follow: false },
};

export default function LabsSignInLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
