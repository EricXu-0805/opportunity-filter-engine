import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import appState from './global-setup';
export default async function seed() {
  appState();
  const r = await fetch('http://127.0.0.1:54321/auth/v1/signup', { method:'POST',headers:{'content-type':'application/json'},body:'{}' });
  if (!r.ok) throw new Error('loopback synthetic account unavailable');
  const session = await r.json();
  if (!session.user?.id || !session.access_token) throw new Error('invalid synthetic session');
  const path = join(__dirname,'.storage-state.json');
  const state = JSON.parse(readFileSync(path,'utf8'));
  state.origins[0].localStorage.push({ name:'ofe_auth',value:JSON.stringify(session) });
  writeFileSync(path,JSON.stringify(state));
}
