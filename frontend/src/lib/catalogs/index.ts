/*
 * Per-school college/major catalog loader. Each non-UIUC catalog is a
 * ~10KB data module, so they load via dynamic import() — webpack splits
 * each one into its own chunk instead of shipping all nine in the main
 * bundle. UIUC re-exports the existing colleges.ts data (already in the
 * main bundle via its static importers) through the same interface.
 */

type CatalogModule = { COLLEGE_MAJORS: Record<string, string[]> };

const CATALOG_LOADERS: Record<string, () => Promise<CatalogModule>> = {
  uiuc: () => import('@/lib/colleges'),
  ucb: () => import('./ucb'),
  umich: () => import('./umich'),
  gatech: () => import('./gatech'),
  utexas: () => import('./utexas'),
  ucla: () => import('./ucla'),
  uw: () => import('./uw'),
  wisc: () => import('./wisc'),
  stanford: () => import('./stanford'),
};

export async function loadCatalog(slug: string): Promise<Record<string, string[]> | null> {
  const loader = CATALOG_LOADERS[slug];
  if (!loader) return null;
  const mod = await loader();
  return mod.COLLEGE_MAJORS;
}
