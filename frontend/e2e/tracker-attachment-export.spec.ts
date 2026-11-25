import { execFileSync } from 'node:child_process';
import { expect, test } from '@playwright/test';
import { account, seed } from './contact-materials-fixture';
import { en } from '../src/i18n/dictionaries';

test('downloads one independently verifiable ZIP for all legacy Tracker folders after a failed attempt', async ({ page }, info) => {
  const owner = await account(true);
  try {
    await seed(page, owner);
    const uid = owner.session.user.id;
    const files = new Map<string, string>();
    for (let i = 0; i < 101; i++) files.set('retired/' + String(i).padStart(3, '0') + '.pdf', 'fixture ' + i);
    files.set('retired/CV.pdf', 'older contents');
    files.set('other/CV.pdf', 'other contents');
    files.set('other/space #and%.pdf', 'literal punctuation');
    files.set('other/nested/研究.json', '{}');
    const failures = new Set(['other/space #and%.pdf']);
    const offsets: number[] = [];
    let downloads = 0;
    page.on('download', () => downloads++);
    const external: string[] = [];
    await page.context().route('**/*', route => {
      const url = new URL(route.request().url());
      if (!['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)) {
        external.push(url.origin); return route.abort();
      }
      return route.continue();
    });
    await page.route('**/storage/v1/object/list/tracker-attachments', route => {
      const { prefix, offset, limit } = route.request().postDataJSON();
      expect(route.request().headers().authorization).toBe('Bearer ' + owner.session.access_token);
      expect(prefix === uid || prefix.startsWith(uid + '/')).toBeTruthy();
      const folder = prefix === uid ? '' : prefix.slice(uid.length + 1) + '/';
      const names = new Map<string, object>();
      for (const [key, content] of files) {
        if (!key.startsWith(folder)) continue;
        const rest = key.slice(folder.length);
        const [name] = rest.split('/');
        names.set(name, rest.includes('/') ? { name, id: null, metadata: null } : {
          name, id: key, updated_at: '2026-11-25T08:00:00Z', metadata: { size: Buffer.byteLength(content), mimetype: 'application/octet-stream' },
        });
      }
      if (folder === 'retired/') offsets.push(offset);
      const sorted = [...names.keys()].sort().slice(offset, offset + limit);
      return route.fulfill({ json: sorted.map(name => names.get(name)) });
    });
    await page.route('**/storage/v1/object/tracker-attachments/**', route => {
      const path = decodeURIComponent(new URL(route.request().url()).pathname.split('/tracker-attachments/')[1]);
      expect(route.request().method()).toBe('GET');
      expect(route.request().headers().authorization).toBe('Bearer ' + owner.session.access_token);
      expect(path.startsWith(uid + '/')).toBe(true);
      const key = path.slice(uid.length + 1);
      expect(files.has(key)).toBe(true);
      if (failures.delete(key)) return route.fulfill({ status: 503, json: { error: 'controlled fixture error' } });
      return route.fulfill({ body: files.get(key)!, contentType: 'application/octet-stream' });
    });
    await page.goto('/account');
    const copy = en.account.attachmentExport;
    await page.getByRole('button', { name: copy.start }).click();
    await expect(page.getByText(copy.failed)).toBeVisible();
    expect(downloads).toBe(0);
    const finished = page.waitForEvent('download');
    await page.getByRole('button', { name: copy.retry }).click();
    const download = await finished;
    expect(download.suggestedFilename()).toBe('tracker-attachments.zip');
    const path = info.outputPath('synthetic-tracker-attachments.zip');
    await download.saveAs(path);
    const verify = `
import hashlib, json, sys, zipfile
expected = json.load(sys.stdin)
with zipfile.ZipFile(sys.argv[1]) as archive:
    assert archive.testzip() is None
    manifest = json.loads(archive.read("manifest.json"))
    assert manifest["formatVersion"] == 1
    entries = manifest["files"]
    assert len(entries) == len(expected) == 105
    assert {entry["originalPath"] for entry in entries} == set(expected)
    paths = [entry["archivePath"] for entry in entries]
    assert len({path.casefold() for path in paths}) == len(paths)
    assert set(archive.namelist()) == set(paths) | {"manifest.json", "SHA256SUMS"}
    for entry in entries:
        data = archive.read(entry["archivePath"])
        assert data == expected[entry["originalPath"]].encode()
        assert entry["size"] == len(data)
        assert entry["sha256"] == hashlib.sha256(data).hexdigest()
    sums = dict(line.split("  ", 1)[::-1] for line in archive.read("SHA256SUMS").decode().splitlines())
    assert set(sums) == set(paths) | {"manifest.json"}
    assert all(hashlib.sha256(archive.read(p)).hexdigest() == digest for p, digest in sums.items())
`;
    execFileSync('python3', ['-c', verify, path], { input: JSON.stringify(Object.fromEntries(files)) });
    await expect(page.getByText(copy.complete.replace('{count}', '105'))).toBeVisible();
    expect(offsets.filter(offset => offset === 99).length).toBeGreaterThanOrEqual(2);
    expect(downloads).toBe(1);
    expect(external).toEqual([]);
  } finally { await owner.http.dispose(); }
});
