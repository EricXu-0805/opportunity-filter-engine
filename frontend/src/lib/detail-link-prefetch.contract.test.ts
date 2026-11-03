import { describe, it, expect } from 'vitest';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

// Static contract, M27: a Link that can lead to a detail page
// (/opportunities/<id>) does not prefetch it. Next prefetches a Link when it
// scrolls into view or is hovered, and a prefetched detail page is rendered on
// the server, which reads the backend detail record. Those reads come from the
// frontend server, so they draw on the same per-client detail budget as the
// pages students actually open; a list of detail links could use it up before
// anyone clicks.
//
// A regex heuristic over the source, like attribution-sites.contract.test.ts.
// An href is followed one level through a `const`/`let` declared in the same
// file; an href passed in as a prop is checked where its literal is written.

const SRC = join(__dirname, '..');

function walk(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) { out.push(...walk(full)); continue; }
    if (/\.tsx$/.test(entry) && !/\.test\.tsx$/.test(entry)) out.push(full);
  }
  return out;
}

const SOURCES = new Map(walk(SRC).map((f) => [f.slice(SRC.length + 1), readFileSync(f, 'utf8')]));
const DETAIL_PATH = /\/opportunities\//;

/** Each `<Link ...>` opening tag in `src`, with its line. */
function linkTags(src: string): { tag: string; line: number }[] {
  return [...src.matchAll(/<Link\b/g)].map((m) => {
    let depth = 0;
    let i = m.index + m[0].length;
    for (; i < src.length; i += 1) {
      if (src[i] === '{') depth += 1;
      else if (src[i] === '}') depth -= 1;
      else if (src[i] === '>' && depth === 0) break;
    }
    return { tag: src.slice(m.index, i + 1), line: src.slice(0, m.index).split('\n').length };
  });
}

/** The href expression of an opening tag: a quoted string or the inside of `{...}`. */
function hrefOf(tag: string): string | null {
  const m = /\shref=(["'{])/.exec(tag);
  if (!m) return null;
  const start = m.index + m[0].length;
  if (m[1] !== '{') return tag.slice(start, tag.indexOf(m[1], start));
  let depth = 1;
  let i = start;
  for (; i < tag.length && depth > 0; i += 1) {
    if (tag[i] === '{') depth += 1;
    else if (tag[i] === '}') depth -= 1;
  }
  return tag.slice(start, i - 1);
}

function canBeDetailHref(src: string, href: string): boolean {
  if (DETAIL_PATH.test(href)) return true;
  return [...href.matchAll(/[A-Za-z_$][\w$]*/g)].some(([name]) => {
    const declared = new RegExp(`\\b(?:const|let)\\s+${name.replace(/\$/g, '\\$')}\\b[^=;]*=([^;]*)`, 'g');
    return [...src.matchAll(declared)].some((d) => DETAIL_PATH.test(d[1]));
  });
}

const DETAIL_LINKS = [...SOURCES].flatMap(([file, src]) => linkTags(src)
  .filter(({ tag }) => {
    const href = hrefOf(tag);
    return href !== null && canBeDetailHref(src, href);
  })
  .map(({ tag, line }) => ({ site: `${file}:${line}`, tag })));

describe('links that can open a detail page do not prefetch it', () => {
  it('every next/link import is named Link, so the scan sees its tags', () => {
    const renamed = [...SOURCES]
      .filter(([, src]) => /from ['"]next\/link['"]/.test(src) && !/import Link from ['"]next\/link['"]/.test(src))
      .map(([file]) => file);
    expect(renamed).toEqual([]);
  });

  it('finds the detail links', () => {
    expect(DETAIL_LINKS.length).toBeGreaterThan(5);
  });

  it('each one sets prefetch={false}', () => {
    expect(DETAIL_LINKS.filter(({ tag }) => !/\sprefetch=\{false\}/.test(tag)).map(({ site }) => site)).toEqual([]);
  });
});
