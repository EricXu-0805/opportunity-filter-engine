/** Loopback-only browser fixture. Never rewrites corpus or calls a provider.
 * Playwright webServer owns its lifecycle; Next's runtime BACKEND_URL uses it.
 * Browser
 * detail routes use the same endpoint; other traffic reaches the local backend.
 */
import { createServer, request as httpRequest } from 'node:http';
import { pipeline } from 'node:stream/promises';
import { createHash } from 'node:crypto';
import { pathToFileURL } from 'node:url';

const TARGET = 'uiuc-siebel-ugresearch';
const canonical = value => Array.isArray(value) ? `[${value.map(canonical).join(',')}]`
  : value !== null && typeof value === 'object' ? `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonical(value[key])}`).join(',')}}` : JSON.stringify(value);
function loopback(value) {
  const url = new URL(value);
  if (url.protocol !== 'http:' || url.hostname !== '127.0.0.1' || !url.port || url.username || url.password || url.search || url.hash || url.pathname !== '/') throw Error('loopback_base_required');
  return url.origin;
}
const sha = value => createHash('sha256').update(canonical(value)).digest('hex');
const send = (res, status, value) => { res.writeHead(status, { 'Content-Type': 'application/json', 'Cache-Control': 'no-store' }); res.end(JSON.stringify(value)); };
async function body(req, limit) {
  const chunks = []; let size = 0;
  for await (const chunk of req) { size += chunk.length; if (size > limit) throw Error('fixture_body_too_large'); chunks.push(chunk); }
  return Buffer.concat(chunks);
}
export function createResearchDetailProxy(upstream = 'http://127.0.0.1:8200') {
  const base = loopback(upstream); let material = null; let reads = [];
  return createServer(async (req, res) => {
    try {
      if (!req.url?.startsWith('/') || req.url.startsWith('//')) return send(res, 400, { error: 'relative_path_required' });
      const url = new URL(req.url, 'http://127.0.0.1');
      if (url.pathname === '/__fixture/health') return send(res, 200, { fixture: 'research-detail-proxy', upstream: base });
      if (url.pathname === `/__fixture/research/${TARGET}`) {
        if (req.method === 'DELETE') { material = null; reads = []; return send(res, 200, { cleared: true }); }
        if (req.method === 'GET') return send(res, 200, { research_context: material, detail_reads: reads });
        if (req.method !== 'POST') return send(res, 405, { error: 'method_not_allowed' });
        const input = JSON.parse((await body(req, 65536)).toString('utf8'));
        if (!input || Object.keys(input).join() !== 'research_context') return send(res, 400, { error: 'fixture_shape' });
        const value = input.research_context; const snapshot = value?.snapshot;
        if (value?.version !== 1 || !['available', 'stale'].includes(value.status) || !snapshot) return send(res, 400, { error: 'fixture_shape' });
        const { snapshot_version, ...stored } = snapshot;
        if (snapshot_version !== 'rs1:' + sha(stored)) return send(res, 400, { error: 'fixture_hash' });
        material = structuredClone(value); reads = []; return send(res, 200, { research_context: material });
      }
      if (url.pathname.startsWith('/__fixture/')) return send(res, 404, { error: 'unknown_fixture' });
      const headers = { ...req.headers, host: new URL(base).host, 'accept-encoding': 'identity' };
      delete headers.connection;
      const currentMaterial = material;
      await new Promise((resolve, reject) => {
        const forwarded = httpRequest(base + url.pathname + url.search, { method: req.method, headers }, response => {
          void (async () => {
            if (currentMaterial && req.method === 'GET' && url.pathname === `/api/opportunities/${TARGET}` && response.statusCode === 200) {
              const value = JSON.parse((await body(response, 3 * 1024 * 1024)).toString('utf8'));
              if (value.id !== TARGET) { send(res, 502, { error: 'unexpected_fixture_target' }); return; }
              value.research_context = structuredClone(currentMaterial);
              const target = Object.fromEntries(Object.entries(value).filter(([key]) => !['writing_target_version', 'contact_email_status', 'contact_email', 'pi_email', 'professor_id'].includes(key)));
              value.writing_target_version = 'wt1:' + sha(target);
              reads.push({ method: req.method, path: url.pathname, status: currentMaterial.status, snapshot_version: currentMaterial.snapshot.snapshot_version });
              send(res, 200, value); return;
            }
            // Transparent streaming preserves large PDF uploads, SSE, exact
            // response bytes/status and redirects without fetching elsewhere.
            res.writeHead(response.statusCode ?? 502, response.headers);
            await pipeline(response, res);
          })().then(resolve, reject);
        });
        forwarded.setTimeout(120000, () => forwarded.destroy(Error('fixture_upstream_timeout')));
        forwarded.on('error', reject);
        void pipeline(req, forwarded).catch(reject);
      });
    } catch (error) { if (res.headersSent) { res.destroy(); return; } send(res, 502, { error: error instanceof Error && error.message === 'fixture_body_too_large' ? 'fixture_body_too_large' : 'fixture_proxy_failure' }); }
  });
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const backendPort = Number(process.env.E2E_BACKEND_PORT ?? 8100);
  if (!Number.isInteger(backendPort) || backendPort < 1024 || backendPort > 65534) throw Error('invalid_backend_port');
  const port = Number(process.env.E2E_RESEARCH_PROXY_PORT ?? backendPort + 1);
  if (!Number.isInteger(port) || port < 1024 || port > 65535) throw Error('invalid_fixture_port');
  if (port === backendPort) throw Error('fixture_port_conflict');
  createResearchDetailProxy(`http://127.0.0.1:${backendPort}`).listen(port, '127.0.0.1', () => process.stdout.write(`Research fixture proxy ready on 127.0.0.1:${port}; upstream 127.0.0.1:${backendPort}\n`));
}
