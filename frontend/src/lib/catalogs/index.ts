/*
 * Per-school college/major catalog loader. Each non-UIUC catalog is a
 * ~10KB data module, so they load via dynamic import() — webpack splits
 * each one into its own chunk instead of shipping all nine in the main
 * bundle. UIUC re-exports the existing colleges.ts data (already in the
 * main bundle via its static importers) through the same interface.
 *
 * i18n note (intentional, not a regression): these catalogs carry the
 * schools' real English college/major names as scraped from official
 * catalogs. Only UIUC's colleges/majors dictionary namespaces have zh
 * entries (home-utils translateKey), so under the zh locale the non-UIUC
 * dropdowns
 * render the English program names verbatim — a deliberate tradeoff
 * (recognizable official names over machine-translated ones). Revisit only
 * if a zh translation pass for the 8 schools is explicitly scoped.
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
