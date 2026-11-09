import {after, before, test} from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';
import {build} from 'esbuild';
import {Miniflare} from 'miniflare';
import {digest, capability, quote} from '../src/core.mjs';

const secret = 'cloudflare-test-secret-never-used-for-deployment';
const password = 'cloudflare-test-admin-password';
let mf, db, kv;
let cookie, csrf;
const dates = () => ({start_at:new Date(Date.now()+3*86400000).toISOString(),end_at:new Date(Date.now()+5*86400000).toISOString()});

before(async () => {
  const source = `import worker from './src/worker.mjs';
    import {processOutbox} from './src/outbox.mjs';
    export default { ...worker, async fetch(request,env,ctx) {
      if(new URL(request.url).pathname.startsWith('/__test/env-login')) {
        const configured=new URL(request.url).pathname==='/__test/env-login';
        env={...env,ADMIN_USERNAME:'env-operator',ADMIN_PASSWORD:'test123456',...(configured?{ADMIN_PASSWORD_MIN_LENGTH:'10'}:{})};
        request=new Request(new URL('/api/v1/admin/auth/login',request.url),request);
      }
      if(new URL(request.url).hostname==='old.lamia.test')env={...env,CANONICAL_REDIRECT:'true'};
      if(new URL(request.url).pathname==='/__test/outbox') {
        const count=await processOutbox({...env,SMTP_HOST:'test.invalid',SMTP_FROM:'mail@example.com'},async()=>{});
        return Response.json({count});
      }
      return worker.fetch(request,env,ctx);
    }};`;
  const bundle = await build({stdin:{contents:source,resolveDir:process.cwd(),sourcefile:'test-entry.mjs'},bundle:true,
    format:'esm',platform:'browser',target:'es2022',write:false,loader:{'.png':'binary','.ttf':'binary','.pdf':'binary'},external:['cloudflare:sockets']});
  mf = new Miniflare({modules:true,script:bundle.outputFiles[0].text,compatibilityDate:'2026-07-30',
    d1Databases:['DB'],kvNamespaces:['MEDIA'],bindings:{TEST_DIAGNOSTICS:true,APP_SECRET:secret,ADMIN_PASSWORD:password,
      PUBLIC_BASE_URL:'https://lamia.test',BANK_NAME:'Test Bank',BANK_ACCOUNT:'123',BANK_HOLDER:'Test'},
    serviceBindings:{ASSETS:async request=>new Response('<html>test asset '+new URL(request.url).pathname+'</html>',{headers:{'Content-Type':'text/html'}})}});
  db = await mf.getD1Database('DB'); kv = await mf.getKVNamespace('MEDIA');
  for (const name of ['0001_initial.sql','0002_media_quota.sql']) {
    let sql = (await readFile(new URL('../migrations/'+name,import.meta.url),'utf8')).replace(/--[^\n]*/g,'');
    const triggers = [...sql.matchAll(/CREATE TRIGGER[\s\S]*?\nEND;/g)].map(m=>m[0]);
    for (const trigger of triggers) sql = sql.replace(trigger,'');
    for (const statement of [...sql.split(';').filter(s=>s.trim()),...triggers]) await db.prepare(statement).run();
  }
});
after(async () => {await mf?.dispose();});

async function request(path,method='GET',data,headers={}) {
  const response = await mf.dispatchFetch('https://lamia.test'+path,{method,headers:{...(data?{'Content-Type':'application/json'}:{}),...headers},
    body:data?JSON.stringify(data):undefined,redirect:'manual'});
  return response;
}
async function api(path,method='GET',data,headers={}) {
  const response = await request('/api/v1'+path,method,data,headers);
  const value = await response.json();
  return {response,value};
}
async function create(schedule=dates()) {
  const {response,value} = await api('/orders','POST',{screen_id:'cf-vtr-001',
    company:{legal_name:'PT Test',npwp:'01.234.567.8-901.234',address:'Semarang'},
    contact:{full_name:'Tester',email:'tester@example.com',phone:'081234567890'},schedule,consent:true,terms_version:'2026-11-08'});
  assert.equal(response.status,200,JSON.stringify(value));
  return value;
}
const customer = order => ({Authorization:'Bearer '+order.token});
const admin = () => ({Cookie:cookie,'X-CSRF-Token':csrf});
async function contacts(order) {
  for (const channel of ['EMAIL','PHONE']) {
    const hash = await digest(secret,`${order.id}:${channel}:123456`);
    await db.prepare('INSERT OR REPLACE INTO otp VALUES(?,?,?,?,0,0)').bind(order.id,channel,hash,new Date(Date.now()+300000).toISOString()).run();
    const result = await api('/otp/verify','POST',{order_id:order.id,channel,code:'123456'},customer(order));
    assert.equal(result.response.status,200,JSON.stringify(result.value));
  }
}
async function approved(order) {
  await contacts(order);
  const submit = await api('/orders/'+order.id+'/content','POST',{source:'AI_TEMPLATE',title:'Brand Test',text:'Kampanye uji'},customer(order));
  assert.equal(submit.value.status,'NEEDS_REVIEW');
  const review = await api('/admin/moderation/'+order.id+'/decision','POST',{decision:'APPROVE'},admin());
  assert.equal(review.value.status,'APPROVED',JSON.stringify(review.value));
}

test('WIB pricing preserves daily rounding and month boundaries', () => {
  assert.equal(quote('2026-11-10T18:00:00+07:00','2026-11-12T06:00:00+07:00',100000000,'0.11').subtotal,4999999);
  const q = quote('2026-11-29T00:00:00+07:00','2026-12-03T00:00:00+07:00',100000000,'0.11');
  assert.equal(q.subtotal,13118278); assert.equal(q.tax,1443011); assert.equal(q.lines.length,4);
  assert.equal(quote('2028-02-29T00:00:00+07:00','2028-03-01T00:00:00+07:00',29,'0').subtotal,1);
});

test('catalog/config and administrative access remain isolated',async () => {
  assert.match(await (await request('/')).text(),/test asset \/index.html/);
  assert.equal((await api('/screens')).value.length,3);
  const config = (await api('/config')).value;
  assert.equal(config.demo_otp,false); assert.equal(config.demo_payments,false);
  assert.equal(config.booking_policy.minimum_duration_minutes,1440);
  assert.equal((await api('/admin/orders')).response.status,401);
  assert.equal((await request('/player')).status,303);
  assert.equal((await request('/static/player.html')).status,303);
  assert.equal((await api('/demo/payments/fake/settle','POST',{})).response.status,404);
});

test('admin login checks origin, CSRF, logout, and cookie security',async () => {
  assert.equal((await api('/admin/auth/login','POST',{username:'admin',password},{Origin:'https://evil.test'})).response.status,403);
  const login = await api('/admin/auth/login','POST',{username:'admin',password},{Origin:'https://lamia.test'});
  assert.equal(login.response.status,200);
  const setCookie = login.response.headers.get('Set-Cookie');
  assert.match(setCookie,/HttpOnly/); assert.match(setCookie,/Secure/); assert.match(setCookie,/SameSite=Strict/);
  cookie = setCookie.split(';')[0]; csrf = login.value.csrf_token;
  assert.equal((await api('/admin/devices','POST',{screen_id:'cf-vtr-001',name:'No CSRF'},{Cookie:cookie})).response.status,403);
  assert.equal((await request('/player','GET',undefined,{Cookie:cookie})).status,200);
  assert.equal((await api('/admin/auth/logout','POST',{},admin())).response.status,200);
  assert.equal((await api('/admin/orders','GET',undefined,admin())).response.status,401);
  const again = await api('/admin/auth/login','POST',{username:'admin',password});
  cookie = again.response.headers.get('Set-Cookie').split(';')[0]; csrf = again.value.csrf_token;
});

test('order ownership, OTP transitions, manual review and material version checks',async () => {
  const order = await create();
  const other = await create();
  assert.equal((await api('/orders/'+order.id,'GET',undefined,customer(other))).response.status,403);
  assert.equal((await api('/orders/'+order.id+'/content','POST',{source:'AI_TEMPLATE',title:'Test',text:'Test'},customer(order))).response.status,409);
  await approved(order);
  const detail = (await api('/orders/'+order.id,'GET',undefined,customer(order))).value;
  assert.equal(detail.npwp_hash,undefined); assert.equal(detail.approved_version,detail.content_version);
  assert.deepEqual(detail.verified_channels,['EMAIL','PHONE']);
  await api('/orders/'+order.id+'/content','POST',{source:'AI_TEMPLATE',title:'Changed',text:'Changed'},customer(order));
  assert.equal((await api('/orders/'+order.id+'/checkout','POST',{},customer(order))).response.status,409);
  const token = await capability(secret,'status',order.id,600);
  const readonly = await api('/order-status','GET',undefined,{'X-Order-Status':token});
  assert.equal(readonly.response.status,200); assert.equal(readonly.value.email,undefined);
  assert.equal((await api('/orders/'+order.id,'GET',undefined,{Authorization:'Bearer '+token})).response.status,401);
});

test('concurrent checkout prevents double booking and is idempotent',async () => {
  const schedule = dates(), one = await create(schedule), two = await create(schedule);
  await approved(one); await approved(two);
  const results = await Promise.all([one,two].map((order,i)=>api('/orders/'+order.id+'/checkout','POST',{},
    {...customer(order),'Idempotency-Key':'concurrent-'+i})));
  assert.deepEqual(results.map(r=>r.response.status).sort(),[200,409]);
  const index = results.findIndex(r=>r.response.status === 200), winner = [one,two][index];
  const repeat = await api('/orders/'+winner.id+'/checkout','POST',{},
    {...customer(winner),'Idempotency-Key':'concurrent-'+index});
  assert.equal(repeat.value.id,results[index].value.id);
  const pay = await api('/admin/orders/'+winner.id+'/confirm-payment','POST',{amount:repeat.value.amount,reference:'BANK-TEST-001'},admin());
  assert.equal(pay.value.status,'SCHEDULED',JSON.stringify(pay.value));
  assert.equal((await api('/admin/orders/'+winner.id+'/confirm-payment','POST',{amount:repeat.value.amount,reference:'BANK-TEST-001'},admin())).response.status,409);
  const enrolled = await api('/admin/devices','POST',{screen_id:'cf-vtr-001',name:'Test kiosk'},admin());
  const headers = {'X-Device-Token':enrolled.value.token};
  const manifest = await api('/player/manifest?screen_id=cf-vtr-001','GET',undefined,headers);
  // Campaign begins in three days and is outside the 48 hour manifest window.
  assert.equal(manifest.response.status,200); assert.equal(manifest.value.items.length,0);
  assert.equal((await api('/player/manifest?screen_id=cf-vtr-002','GET',undefined,headers)).response.status,403);
  assert.equal((await api('/player/heartbeat','POST',{screen_id:'cf-vtr-001'},headers)).response.status,200);
  const takedown = await api('/admin/orders/'+winner.id+'/takedown','POST',{reason:'Test takedown'},admin());
  assert.equal(takedown.value.status,'TAKEN_DOWN');
  await api('/admin/devices/'+enrolled.value.id,'DELETE',undefined,admin());
  assert.equal((await api('/player/manifest?screen_id=cf-vtr-001','GET',undefined,headers)).response.status,401);
});

test('KV upload is private, ranges work, quota reservation is rolled back on conflict',async () => {
  const order = await create({...dates(),start_at:new Date(Date.now()+10*86400000).toISOString(),end_at:new Date(Date.now()+11*86400000).toISOString()});
  await contacts(order);
  const bytes = new Uint8Array(33); bytes.set([137,80,78,71,13,10,26,10]);
  bytes.set(new TextEncoder().encode('IHDR'),12);
  const view = new DataView(bytes.buffer); view.setUint32(16,1920); view.setUint32(20,1080);
  const form = new FormData(); form.set('file',new File([bytes],'test.png',{type:'image/png'}));
  const upload = new Request('https://lamia.test/api/v1/orders/'+order.id+'/upload',{method:'POST',headers:customer(order),body:form});
  const response = await mf.dispatchFetch(upload.url,{method:'POST',headers:upload.headers,body:await upload.arrayBuffer()});
  assert.equal(response.status,200,await response.text());
  assert.equal((await api('/orders/'+order.id+'/creative')).response.status,401);
  const range = await request('/api/v1/orders/'+order.id+'/creative','GET',undefined,{...customer(order),Range:'bytes=0-7'});
  assert.equal(range.status,206); assert.equal(range.headers.get('Content-Range'),'bytes 0-7/33');
  assert.deepEqual(new Uint8Array(await range.arrayBuffer()),bytes.slice(0,8));
  const usage = await db.prepare('SELECT SUM(size) size FROM media_objects WHERE key LIKE ?').bind(order.id+'/%').first(); assert.equal(usage.size,33);
  const previousCount = (await db.prepare('SELECT COUNT(*) n FROM media_objects').first()).n;
  const bigKey = 'quota-test';
  await db.prepare('INSERT INTO media_objects VALUES(?,?,?)').bind(bigKey,800*1024*1024,new Date().toISOString()).run();
  const second = new FormData(); second.set('file',new File([bytes],'test2.png'));
  const nextUpload = new Request(upload.url,{method:'POST',headers:customer(order),body:second});
  const denied = await mf.dispatchFetch(nextUpload.url,{method:'POST',headers:nextUpload.headers,body:await nextUpload.arrayBuffer()});
  assert.equal(denied.status,409); assert.equal((await db.prepare('SELECT COUNT(*) n FROM media_objects').first()).n,previousCount+1);
  await db.prepare('DELETE FROM media_objects WHERE key=?').bind(bigKey).run();
});

test('outbox claims a single notification and cancels obsolete material events',async () => {
  await db.prepare("UPDATE email_outbox SET next_attempt_at=0 WHERE status='PENDING'").run();
  const before = await db.prepare("SELECT COUNT(*) n FROM email_outbox WHERE status='SENT'").first();
  for (let i=0;i<20;i++) await request('/__test/outbox','POST');
  const sent = await db.prepare("SELECT COUNT(*) n FROM email_outbox WHERE status='SENT'").first();
  assert.ok(sent.n > before.n);
  assert.ok((await db.prepare("SELECT COUNT(*) n FROM email_outbox WHERE status='CANCELLED'").first()).n > 0);
  const invoice = await kv.get('invoices/'+(await db.prepare('SELECT order_id FROM payment_confirmations LIMIT 1').first()).order_id+'.pdf','arrayBuffer');
  assert.ok(invoice); assert.equal(new TextDecoder().decode(invoice.slice(0,5)),'%PDF-');
});

test('long bookings fit D1 request query limits',async () => {
  const start = Date.now()+30*86400000;
  const order = await create({start_at:new Date(start).toISOString(),end_at:new Date(start+366*86400000).toISOString()});
  assert.ok(order.quote.lines.length >= 366);
});

test('expired holds cannot be paid and reconcile into EXPIRED',async () => {
  const start = Date.now()+20*86400000;
  const order = await create({start_at:new Date(start).toISOString(),end_at:new Date(start+86400000).toISOString()});
  await approved(order);
  const checkout = await api('/orders/'+order.id+'/checkout','POST',{},customer(order));
  assert.equal(checkout.response.status,200);
  await db.prepare('UPDATE orders SET hold_expires=? WHERE id=?').bind(new Date(Date.now()-1000).toISOString(),order.id).run();
  const pay = await api('/admin/orders/'+order.id+'/confirm-payment','POST',{amount:checkout.value.amount,reference:'BANK-EXPIRED'},admin());
  assert.equal(pay.response.status,409);
  await db.prepare('DELETE FROM scheduler_state').run();
  const current = await api('/orders/'+order.id,'GET',undefined,customer(order));
  assert.equal(current.value.status,'EXPIRED'); assert.equal(current.value.payment.status,'EXPIRED');
});

test('blackout conflicts are enforced atomically',async () => {
  const payload = {screen_id:'cf-vtr-002',...dates(),reason:'Maintenance'};
  const one = await api('/admin/blackouts','POST',payload,admin());
  assert.equal(one.response.status,200);
  assert.equal((await api('/admin/blackouts','POST',payload,admin())).response.status,409);
  assert.equal((await api('/screens/cf-vtr-002/availability?from_at='+payload.start_at+'&to_at='+payload.end_at)).value.available,false);
  assert.equal((await api('/admin/blackouts/'+one.value.id,'DELETE',undefined,admin())).response.status,200);
});

test('OTP attempts and admin login attempts have enforceable limits',async () => {
  const order = await create(), channel = 'EMAIL';
  await db.prepare('INSERT INTO otp VALUES(?,?,?,?,0,0)').bind(order.id,channel,await digest(secret,`${order.id}:${channel}:123456`),new Date(Date.now()+300000).toISOString()).run();
  for(let i=0;i<5;i++) assert.equal((await api('/otp/verify','POST',{order_id:order.id,channel,code:'000000'},customer(order))).response.status,400);
  assert.equal((await api('/otp/verify','POST',{order_id:order.id,channel,code:'123456'},customer(order))).response.status,400);
  for(let i=0;i<5;i++) await api('/admin/auth/login','POST',{username:'admin',password:'wrong-password'},{'CF-Connecting-IP':'192.0.2.123'});
  assert.equal((await api('/admin/auth/login','POST',{username:'admin',password},{'CF-Connecting-IP':'192.0.2.123'})).response.status,429);
});

test('payload limits also apply without a Content-Length header',async () => {
  const response = await api('/orders','POST',{padding:'x'.repeat(65537)});
  assert.equal(response.response.status,413);
});

test('the old browser URL redirects to the canonical domain while device APIs remain available',async () => {
  const page=await mf.dispatchFetch('https://old.lamia.test/login?next=player',{redirect:'manual'});
  assert.equal(page.status,308);assert.equal(page.headers.get('Location'),'https://lamia.test/login?next=player');
  const api=await mf.dispatchFetch('https://old.lamia.test/api/v1/health');
  assert.equal(api.status,200);assert.equal((await api.json()).ok,true);
});

test('an imported ten-character admin password works with its explicit Cloudflare setting',async () => {
  const payload={username:'env-operator',password:'test123456'};
  const result=await request('/__test/env-login','POST',payload,{Origin:'https://lamia.test'});
  assert.equal(result.status,200);assert.equal((await result.json()).username,'env-operator');
  const defaults=await request('/__test/env-login-default','POST',payload,{Origin:'https://lamia.test'});
  assert.equal(defaults.status,503);
});
