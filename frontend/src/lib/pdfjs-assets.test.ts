import { afterEach, describe, expect, it } from 'vitest';
import { spawnSync } from 'node:child_process';
import { mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const source = readFileSync(join(__dirname, '../../scripts/prepare-pdfjs-assets.mjs'));
const fixtures: string[] = [];

function fixture() {
  const root = mkdtempSync(join(tmpdir(), 'ofe-pdfjs-assets-test-'));
  fixtures.push(root);
  const packageRoot = join(root, 'node_modules/pdfjs-dist');
  for (const directory of ['scripts', 'node_modules/pdfjs-dist/cmaps', 'node_modules/pdfjs-dist/standard_fonts']) {
    mkdirSync(join(root, directory), { recursive: true });
  }
  writeFileSync(join(root, 'scripts/prepare-pdfjs-assets.mjs'), source);
  writeFileSync(join(packageRoot, 'package.json'), JSON.stringify({ name: 'pdfjs-dist', version: '4.4.168' }));
  writeFileSync(join(root, 'package-lock.json'), JSON.stringify({
    lockfileVersion: 3, packages: { 'node_modules/pdfjs-dist': { version: '4.4.168' } },
  }));
  writeFileSync(join(packageRoot, 'cmaps/Example.bcmap'), Buffer.from([0, 31, 128, 255]));
  writeFileSync(join(packageRoot, 'cmaps/LICENSE'), 'CMap license');
  writeFileSync(join(packageRoot, 'standard_fonts/Example.ttf'), Buffer.from([1, 2, 128, 254]));
  writeFileSync(join(packageRoot, 'standard_fonts/LICENSE_FONT'), 'Font license');
  writeFileSync(join(packageRoot, 'LICENSE'), 'PDF.js license');
  const output = join(root, 'public/pdfjs');
  const run = () => spawnSync(process.execPath, [join(root, 'scripts/prepare-pdfjs-assets.mjs')], {
    // Resolving resources must depend on the script, not the shell's cwd.
    cwd: tmpdir(), encoding: 'utf8',
  });
  return { root, packageRoot, output, run };
}

afterEach(() => {
  for (const root of fixtures.splice(0)) rmSync(root, { recursive: true, force: true });
});

describe('PDF.js local public resources', () => {
  it('copies both resource directories byte-for-byte with their license notices', () => {
    const { packageRoot, output, run } = fixture();
    const result = run();
    expect(result.status, result.stderr).toBe(0);
    for (const file of ['cmaps/Example.bcmap', 'cmaps/LICENSE', 'standard_fonts/Example.ttf', 'standard_fonts/LICENSE_FONT', 'LICENSE']) {
      expect(readFileSync(join(output, file))).toEqual(readFileSync(join(packageRoot, file)));
    }
    expect(readdirSync(output).sort()).toEqual(['LICENSE', 'cmaps', 'standard_fonts']);
  });

  it('replaces stale generated resources when prepared again', () => {
    const { packageRoot, output, run } = fixture();
    expect(run().status).toBe(0);
    writeFileSync(join(output, 'cmaps/removed-in-upgrade.bcmap'), 'stale');
    writeFileSync(join(packageRoot, 'cmaps/Example.bcmap'), 'updated');
    expect(run().status).toBe(0);
    expect(readFileSync(join(output, 'cmaps/Example.bcmap'), 'utf8')).toBe('updated');
    expect(readdirSync(join(output, 'cmaps'))).not.toContain('removed-in-upgrade.bcmap');
  });

  it.each(['cmaps', 'standard_fonts'])('fails before startup when %s is missing', (directory) => {
    const { packageRoot, output, run } = fixture();
    mkdirSync(output, { recursive: true });
    writeFileSync(join(output, 'previous-build'), 'preserve on preparation failure');
    rmSync(join(packageRoot, directory), { recursive: true });
    const result = run();
    expect(result.status).not.toBe(0);
    expect(result.stderr).toContain(directory);
    expect(result.stdout).not.toContain('copied locally');
    expect(readFileSync(join(output, 'previous-build'), 'utf8')).toBe('preserve on preparation failure');
  });

  it('rejects empty resource directories even when their license file exists', () => {
    const { packageRoot, run } = fixture();
    rmSync(join(packageRoot, 'cmaps/Example.bcmap'));
    const result = run();
    expect(result.status).not.toBe(0);
    expect(result.stderr).toContain('contains no resource files');
  });

  it('refuses a package version that differs from the lockfile', () => {
    const { packageRoot, run } = fixture();
    writeFileSync(join(packageRoot, 'package.json'), JSON.stringify({ name: 'pdfjs-dist', version: '0.0.0' }));
    const result = run();
    expect(result.status).not.toBe(0);
    expect(result.stderr).toContain('does not match package-lock.json');
    expect(result.stdout).not.toContain('copied locally');
  });
});
