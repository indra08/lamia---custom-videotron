import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {parseEnv} from 'node:util';

const config = JSON.parse(await readFile(new URL('../config.local.json',import.meta.url),'utf8'));
const secrets = JSON.parse(await readFile(new URL('../.secrets.json',import.meta.url),'utf8'));
const source = process.argv.includes('--source-env')?parseEnv(await readFile(new URL('../../.env',import.meta.url),'utf8')):null;
if(source)assert.ok(source.ADMIN_USERNAME && source.ADMIN_PASSWORD,'Source .env admin credentials must be configured');
const base = config.vars.PUBLIC_BASE_URL;
const get = async path => fetch(base+path,{redirect:'manual',signal:AbortSignal.timeout(20000)});
assert.equal((await get('/')).status,200);
assert.equal((await get('/static/app.js')).status,200);
assert.equal((await get('/icon/logo.webp')).status,200);
const health = await (await get('/api/v1/health')).json(); assert.equal(health.ok,true);
const screens = await (await get('/api/v1/screens')).json(); assert.ok(screens.length);
assert.equal((await get('/api/v1/admin/orders')).status,401);
assert.equal((await get('/player')).status,303);
assert.equal((await get('/static/player.html')).status,303);
const start = new Date(Date.now()+3*86400000).toISOString(), end = new Date(Date.now()+4*86400000).toISOString();
const price = await get('/api/v1/screens/'+screens[0].id+'/quote?'+new URLSearchParams({start_at:start,end_at:end}));
assert.equal(price.status,200); assert.ok((await price.json()).total>0);
const login = await fetch(base+'/api/v1/admin/auth/login',{method:'POST',headers:{'Content-Type':'application/json',Origin:base},
  body:JSON.stringify({username:source?.ADMIN_USERNAME || config.vars.ADMIN_USERNAME || 'admin',password:source?.ADMIN_PASSWORD || secrets.ADMIN_PASSWORD}),signal:AbortSignal.timeout(20000)});
assert.equal(login.status,200,'Admin login should succeed');
const session = await login.json(), cookie = login.headers.get('Set-Cookie').split(';')[0];
assert.ok(session.csrf_token);
const auth = {Cookie:cookie,'X-CSRF-Token':session.csrf_token,Origin:base};
for (const path of ['/admin','/player','/api/v1/admin/orders','/api/v1/admin/summary','/api/v1/admin/schedule']) {
  const response = await fetch(base+path,{headers:auth,redirect:'manual',signal:AbortSignal.timeout(20000)});
  assert.equal(response.status,200,path);
}
assert.equal((await fetch(base+'/api/v1/admin/auth/logout',{method:'POST',headers:auth,signal:AbortSignal.timeout(20000)})).status,200);
assert.equal((await fetch(base+'/api/v1/admin/orders',{headers:auth,signal:AbortSignal.timeout(20000)})).status,401);
console.log('PASS: live static assets, health, catalog, quote, private routes, admin login/schedule/logout.');
console.log('URL: '+base);
if(source)console.log('Admin login verified using credentials read directly from the source .env.');
