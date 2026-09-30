// PDF.js fetches CMaps and standard fonts at runtime. Serve the resources
// from the same installed package as the parser; never fetch them from a CDN.
// Run before next dev/build, because Next serves public/ from the site root.
import { cp, mkdir, mkdtemp, readFile, readdir, rename, rm } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const frontendRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const require = createRequire(import.meta.url);
let staging;

try {
  const packageRoot = dirname(require.resolve('pdfjs-dist/package.json'));
  const installed = JSON.parse(await readFile(join(packageRoot, 'package.json'), 'utf8'));
  const lock = JSON.parse(await readFile(join(frontendRoot, 'package-lock.json'), 'utf8'));
  const lockedVersion = lock.packages?.['node_modules/pdfjs-dist']?.version;
  if (!lockedVersion || installed.version !== lockedVersion) {
    throw new Error(`pdfjs-dist version ${installed.version} does not match package-lock.json (${lockedVersion ?? 'missing'}). Run npm ci.`);
  }

  const assets = [
    { directory: 'cmaps', extensions: /\.bcmap$/ },
    { directory: 'standard_fonts', extensions: /\.(?:pfb|ttf)$/ },
  ];
  const counts = [];
  // Validate both sources before touching the previously generated resources.
  for (const { directory, extensions } of assets) {
    const files = await readdir(join(packageRoot, directory), { withFileTypes: true });
    const count = files.filter((file) => file.isFile() && extensions.test(file.name)).length;
    if (!count) throw new Error(`pdfjs-dist/${directory} contains no resource files. Run npm ci.`);
    counts.push(`${directory}=${count}`);
  }

  const publicRoot = join(frontendRoot, 'public');
  await mkdir(publicRoot, { recursive: true });
  staging = await mkdtemp(join(publicRoot, '.pdfjs-assets-'));
  for (const { directory } of assets) {
    // Copy the entire directory, including its font/CMap license notices.
    await cp(join(packageRoot, directory), join(staging, directory), { recursive: true });
  }
  await cp(join(packageRoot, 'LICENSE'), join(staging, 'LICENSE'));
  // public/pdfjs is generated-only. Replace it after the complete copy succeeds
  // so dependency upgrades cannot leave removed resources from an older build.
  const destination = join(publicRoot, 'pdfjs');
  await rm(destination, { recursive: true, force: true });
  await rename(staging, destination);
  staging = undefined;
  console.log(`pdfjs-assets: ${installed.version} copied locally (${counts.join(', ')}).`);
} catch (error) {
  console.error(`pdfjs-assets: ${error instanceof Error ? error.message : String(error)}`);
  process.exitCode = 1;
} finally {
  if (staging) await rm(staging, { recursive: true, force: true });
}
