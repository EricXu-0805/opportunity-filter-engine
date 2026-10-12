// The Resources page carries Import as a tab (`?tab=import`); /import is only a
// door to it, so bookmarks, shared links and in-app links keep working.

export type ResourcesTab = 'guides' | 'import';

type SearchParams = Record<string, string | string[] | undefined>;

export function parseResourcesTab(value: string | string[] | undefined): ResourcesTab {
  return (Array.isArray(value) ? value[0] : value) === 'import' ? 'import' : 'guides';
}

/** Where /import goes: every incoming query pair kept, the Import tab selected. */
export function importRedirectTarget(params: SearchParams): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (key === 'tab' || value === undefined) continue;
    for (const item of Array.isArray(value) ? value : [value]) query.append(key, item);
  }
  query.set('tab', 'import');
  return `/resources?${query.toString()}`;
}
