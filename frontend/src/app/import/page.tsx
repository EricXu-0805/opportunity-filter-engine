import { redirect } from 'next/navigation';
import { importRedirectTarget } from '@/lib/resources-tab';

// Import now lives on the Resources page as a tab. This route stays so old
// links and bookmarks land on it, with their query string intact.
export default async function ImportRedirect({
  searchParams,
}: {
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  redirect(importRedirectTarget(await searchParams));
}
