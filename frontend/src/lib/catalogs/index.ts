/*
 * Per-school college/major catalog loader. Each non-UIUC catalog is a
 * ~10KB data module, so they load via dynamic import() — webpack splits
 * each one into its own chunk instead of shipping all nine in the main
 * bundle. UIUC re-exports the existing colleges.ts data (already in the
 * main bundle via its static importers) through the same interface.
 *
 * i18n: catalogs carry the schools' real English college/major names as
 * scraped from official catalogs; the zh labels live in the dictionaries'
 * colleges/majors namespaces (rendered via home-utils translateKey), so a
 * new catalog name shows up in English until its dictionary entry is added.
 */

type CatalogModule = { COLLEGE_MAJORS: Record<string, string[]> };

const CATALOG_LOADERS: Record<string, () => Promise<CatalogModule>> = {
  uiuc: () => import('@/lib/colleges'),
  ucb: () => import('./ucb'),
  umich: () => import('./umich'),
  gatech: () => import('./gatech'),
  utexas: () => import('./utexas'),
  ucla: () => import('./ucla'),
  ucsd: () => import('./ucsd'),
  uw: () => import('./uw'),
  wisc: () => import('./wisc'),
  stanford: () => import('./stanford'),
  princeton: () => import('./princeton'),
  uchicago: () => import('./uchicago'),
  uci: () => import('./uci'),
  ucsb: () => import('./ucsb'),
  boulder: () => import('./boulder'),
  purdue: () => import('./purdue'),
  duke: () => import('./duke'),
  jhu: () => import('./jhu'),
  northwestern: () => import('./northwestern'),
  upenn: () => import('./upenn'),
  caltech: () => import('./caltech'),
  cornell: () => import('./cornell'),
  brown: () => import('./brown'),
  rice: () => import('./rice'),
  vanderbilt: () => import('./vanderbilt'),
  dartmouth: () => import('./dartmouth'),
  columbia: () => import('./columbia'),
  mit: () => import('./mit'),
  harvard: () => import('./harvard'),
  usc: () => import('./usc'),
  umn: () => import('./umn'),
  osu: () => import('./osu'),
  nd: () => import('./nd'),
  rochester: () => import('./rochester'),
  uf: () => import('./uf'),
  umass: () => import('./umass'),
  yale: () => import('./yale'),
  vt: () => import('./vt'),
  tamu: () => import('./tamu'),
  umd: () => import('./umd'),
  neu: () => import('./neu'),
  sbu: () => import('./sbu'),
  bu: () => import('./bu'),
  washu: () => import('./washu'),
  rutgers: () => import('./rutgers'),
  ncsu: () => import('./ncsu'),
  psu: () => import('./psu'),
  nyu: () => import('./nyu'),
  georgetown: () => import('./georgetown'),
  emory: () => import('./emory'),
  uva: () => import('./uva'),
  tufts: () => import('./tufts'),
  uga: () => import('./uga'),
  bc: () => import('./bc'),
};

export async function loadCatalog(slug: string): Promise<Record<string, string[]> | null> {
  const loader = CATALOG_LOADERS[slug];
  if (!loader) return null;
  const mod = await loader();
  return mod.COLLEGE_MAJORS;
}
