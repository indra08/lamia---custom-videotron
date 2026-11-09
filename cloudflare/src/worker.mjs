import {
  HttpError, fail, uid, now, json, parse, stamp, digest, equal, capability, verify,
  randomToken, publicConfig, validateSchedule, quote, body, boundedBytes, clean, statement,
  first, all, run, batch, guard, audit, history, getOrder, overlaps, reconcile
} from './core.mjs';
import {Auth} from './auth.mjs';
import {inspectMedia} from './media.mjs';
import {deliverEmail, emailTemplate} from './mail.mjs';
import {enqueue, processOutbox, issuer} from './outbox.mjs';
import qrcode from 'qrcode-generator';
import {putMedia, deleteMedia, readMedia, sliceStream} from './storage.mjs';

const editable = ['CONTENT_PENDING','CONTENT_REJECTED','APPROVED'];
const protectedPages = new Map([
  ['/admin','admin'], ['/schedule','schedule'], ['/player','player'], ['/static/player.html','player']
]);

function checkSecrets(env) {
  const passwordMinimum = env.ADMIN_PASSWORD_MIN_LENGTH === '10'?10:12;
  if (!env.APP_SECRET || env.APP_SECRET.length < 32 || env.APP_SECRET.startsWith('replace-') ||
      !env.ADMIN_PASSWORD || env.ADMIN_PASSWORD.length < passwordMinimum || env.ADMIN_PASSWORD.startsWith('replace-')) {
    fail(503, 'Secrets Cloudflare belum dikonfigurasi');
  }
}

async function owner(request, env, order, auth) {
  const header = request.headers.get('Authorization');
  if (header) {
    const id = await verify(env.APP_SECRET, header.replace(/^Bearer\s+/i, ''), 'order');
    if (id !== order.id) fail(403, 'Tidak memiliki akses');
  } else await auth.admin();
}

async function device(request, env, screenId) {
  const token = request.headers.get('X-Device-Token');
  if (!token) fail(401, 'Token perangkat wajib diisi');
  const d = await first(env, 'SELECT id,screen_id FROM devices WHERE token_digest=? AND revoked_at IS NULL',
    await digest(env.APP_SECRET, token));
  if (!d) fail(401, 'Token perangkat salah atau sudah dicabut');
  if (screenId && d.screen_id !== screenId) fail(403, 'Token tidak diizinkan untuk layar ini');
  return d;
}

async function screen(env, id) {
  return await first(env, 'SELECT * FROM screens WHERE id=? AND status=?', id, 'ACTIVE') ||
    fail(404, 'Layar tidak ditemukan');
}

function optimistic(env, order, statuses = [order.status]) {
  return guard(env, `EXISTS(SELECT 1 FROM orders WHERE id=? AND content_version=? AND status IN (${statuses.map(()=>'?').join(',')}))`,
    order.id, order.content_version, ...statuses);
}

async function orderDetails(env, order) {
  const result = {...order};
  delete result.npwp_hash;
  result.verified_channels = (await all(env, 'SELECT channel FROM otp WHERE order_id=? AND verified=1', order.id)).map(r=>r.channel);
  result.history = await all(env, 'SELECT to_status,created_at FROM history WHERE order_id=? ORDER BY id', order.id);
  result.terms_version = (await first(env, 'SELECT version FROM consents WHERE order_id=?', order.id))?.version || null;
  result.review_notes = await all(env, "SELECT detail,created_at FROM audit WHERE entity=? AND action='ADMIN_MODERATION_REJECT' ORDER BY created_at DESC", order.id);
  result.payment = await first(env, 'SELECT * FROM payments WHERE order_id=? ORDER BY created_at DESC LIMIT 1', order.id);
  result.price_lines = await all(env, 'SELECT date,hours,amount FROM price_lines WHERE order_id=? ORDER BY date', order.id);
  return result;
}

async function createOrder(request, env) {
  const b = await body(request), company = b.company || {}, contact = b.contact || {}, schedule = b.schedule || {};
  const npwp = typeof company.npwp === 'string' ? company.npwp : '';
  const digits = npwp.replace(/\D/g, '');
  if (!/^[0-9 .-]+$/.test(npwp) || ![15,16].includes(digits.length) || npwp.length > 30) fail(422, 'NPWP harus 15 atau 16 digit');
  const name = clean(company.legal_name, 201), address = clean(company.address, 501), pic = clean(contact.full_name, 151);
  const email = clean(contact.email, 255);
  if (!name || name.length > 200 || !address || address.length > 500 || !pic || pic.length > 150 || b.consent !== true) fail(422, 'Data PT, alamat, PIC, dan persetujuan wajib diisi');
  if (email.length > 254 || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) fail(422, 'Email tidak valid');
  let phone = clean(contact.phone, 26).replace(/\D/g, '');
  if (phone.startsWith('0')) phone = '62'+phone.slice(1);
  if (!/^62\d{8,13}$/.test(phone)) fail(422, 'Nomor HP Indonesia tidak valid');
  if (b.terms_version !== publicConfig(env).terms_version) fail(422, 'Baca dan setujui versi syarat terbaru');
  const start = parse(schedule.start_at), end = parse(schedule.end_at);
  validateSchedule(start, end);
  const s = await screen(env, clean(b.screen_id));
  if (await overlaps(env, s.id, start, end)) fail(409, 'Slot sudah terisi');
  const q = quote(start, end, s.monthly_price, s.tax_rate), id = uid(), t = now();
  const orderNo = 'ORD-'+t.slice(0,10).replace(/-/g,'')+'-'+id.slice(0,8).toUpperCase();
  const lineStatements = [];
  // D1 Free permits 50 queries/request and 100 SQL parameters/query.
  for (let at=0; at<q.lines.length; at+=20) {
    const group = q.lines.slice(at,at+20);
    lineStatements.push(statement(env, 'INSERT INTO price_lines VALUES '+group.map(()=>'(?,?,?,?)').join(','),
      ...group.flatMap(line=>[id,line.date,line.hours,line.amount])));
  }
  await batch(env, [
    statement(env, `INSERT INTO orders(id,order_no,screen_id,company,npwp_hash,npwp_last4,pic,email,phone,address,
      start_at,end_at,status,subtotal,tax,total,created_at,updated_at,consent_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)`,
    id, orderNo, s.id, name, await digest(env.APP_SECRET, digits), digits.slice(-4), pic, email, '+'+phone,
    address, start, end, 'DRAFT', q.subtotal, q.tax, q.total, t, t, t),
    ...lineStatements,
    statement(env, 'INSERT INTO consents VALUES(?,?,?)', id, b.terms_version, t), audit(env, 'ORDER_CREATED', id)
  ]);
  return {id, order_no:orderNo, token:await capability(env.APP_SECRET, 'order', id, 86400), quote:q};
}

async function otp(request, env, auth, action) {
  const b = await body(request), id = clean(b.order_id), channel = b.channel;
  if (!['EMAIL','PHONE'].includes(channel)) fail(422, 'Channel salah');
  const order = await getOrder(env, id);
  await owner(request, env, order, auth);
  const current = await first(env, 'SELECT * FROM otp WHERE order_id=? AND channel=?', id, channel);
  if (action === 'send') {
    if (current?.verified) return {message:'Kontak sudah terverifikasi', verified:true};
    if (current && stamp(current.expires_at) > Date.now()+240000) fail(429, 'Tunggu sebelum meminta OTP lagi');
    const codeBytes = crypto.getRandomValues(new Uint32Array(1));
    const code = String(codeBytes[0] % 1000000).padStart(6, '0');
    const codeHash = await digest(env.APP_SECRET, `${id}:${channel}:${code}`);
    const expires = new Date(Date.now()+300000).toISOString();
    await batch(env, [
      guard(env, "NOT EXISTS(SELECT 1 FROM otp WHERE order_id=? AND channel=? AND (verified=1 OR expires_at>?))", id, channel, new Date(Date.now()+240000).toISOString()),
      statement(env, 'INSERT OR REPLACE INTO otp VALUES(?,?,?,?,0,0)', id, channel, codeHash, expires)
    ]);
    try {
      if (channel === 'EMAIL') {
        if (!env.SMTP_HOST || !env.SMTP_FROM) fail(503, 'SMTP belum dikonfigurasi');
        await deliverEmail(env, order.email, emailTemplate('OTP', {code, issuer:issuer(env)}));
      } else {
        if (!env.PHONE_OTP_WEBHOOK_URL?.startsWith('https://') || !env.PHONE_OTP_WEBHOOK_TOKEN) fail(503, 'Adapter OTP ponsel belum dikonfigurasi');
        const response = await fetch(env.PHONE_OTP_WEBHOOK_URL, {
          method:'POST', headers:{'Content-Type':'application/json', Authorization:'Bearer '+env.PHONE_OTP_WEBHOOK_TOKEN},
          body:JSON.stringify({to:order.phone, code, expires_in:300}), signal:AbortSignal.timeout(15000), redirect:'error'
        });
        if (!response.ok) throw Error('PhoneDeliveryFailed');
      }
    } catch {
      await run(env, 'DELETE FROM otp WHERE order_id=? AND channel=? AND code_hash=? AND verified=0', id, channel, codeHash);
      fail(503, 'Pengiriman kode gagal. Hubungi operator atau coba lagi.');
    }
    return {message:'Kode verifikasi terkirim', expires_in:300, resend_after:60};
  }
  const t = now();
  const claimed = await statement(env, `UPDATE otp SET attempts=attempts+1 WHERE order_id=? AND channel=?
    AND verified=0 AND expires_at>? AND attempts<5 RETURNING *`, id, channel, t).first();
  if (!claimed) {
    if (current?.verified) return {verified:true};
    fail(400, 'OTP kedaluwarsa atau percobaan habis');
  }
  const expected = await digest(env.APP_SECRET, `${id}:${channel}:${String(b.code ?? '')}`);
  if (!equal(expected, claimed.code_hash)) fail(400, 'Kode OTP salah');
  await batch(env, [
    guard(env, 'EXISTS(SELECT 1 FROM otp WHERE order_id=? AND channel=? AND code_hash=? AND expires_at>?)', id, channel, expected, now()),
    statement(env, 'UPDATE otp SET verified=1 WHERE order_id=? AND channel=?', id, channel),
    statement(env, `INSERT INTO history(order_id,from_status,to_status,created_at) SELECT id,status,'CONTENT_PENDING',?
      FROM orders WHERE id=? AND status='DRAFT' AND (SELECT COUNT(*) FROM otp WHERE order_id=? AND verified=1)=2`, t, id, id),
    statement(env, `UPDATE orders SET status='CONTENT_PENDING',updated_at=? WHERE id=? AND status='DRAFT'
      AND (SELECT COUNT(*) FROM otp WHERE order_id=? AND verified=1)=2`, t, id, id)
  ]);
  return {verified:true};
}

async function submitMaterial(request, env, auth, order, upload, ctx) {
  await owner(request, env, order, auth);
  if (!editable.includes(order.status)) fail(409, 'Status tidak mengizinkan perubahan konten');
  let title, text = '', key = null, mime = null, status = 'NEEDS_REVIEW', reason = 'Perlu peninjauan manusia sebelum pembayaran';
  if (upload) {
    const length = Number(request.headers.get('Content-Length') || 0);
    if (length > 21*1048576) fail(413, 'Ukuran file maksimal 20 MB');
    const uploadBytes = await boundedBytes(request,21*1048576);
    let form;
    try {form = await new Request(request.url,{method:'POST',headers:request.headers,body:uploadBytes}).formData();}
    catch {fail(422,'Upload harus memakai multipart/form-data yang valid');}
    const file = form.get('file');
    if (!file || typeof file.arrayBuffer !== 'function') fail(422, 'File wajib diisi');
    if (file.size > 20*1048576) fail(413, 'Ukuran file maksimal 20 MB');
    const bytes = new Uint8Array(await file.arrayBuffer()), s = await screen(env, order.screen_id);
    try {mime = inspectMedia(bytes, s.width, s.height).mime;}
    catch (error) {if(error instanceof HttpError)throw error;fail(422,'Struktur file media tidak valid');}
    key = `${order.id}/${uid()}`;
    title = clean(file.name, 150) || 'Materi iklan';
    await putMedia(env,key,bytes,mime);
  } else {
    const b = await body(request);
    title = clean(b.title, 150); text = clean(b.text, 2000);
    if (b.source !== 'AI_TEMPLATE' || !title || !text) fail(422, 'Judul dan teks template wajib diisi');
    if (['judi online','slot gacor','pornografi','narkoba','senjata ilegal'].some(w=>(title+' '+text).toLowerCase().includes(w))) {
      status = 'CONTENT_REJECTED'; reason = 'Konten mengandung istilah yang dilarang';
    }
  }
  const updated = {...order, content_source:upload?'UPLOAD':'AI_TEMPLATE', content_title:title, content_text:text,
    content_file:key, content_mime:mime, content_version:order.content_version+1, approved_version:null,
    status, moderation:status === 'CONTENT_REJECTED'?'REJECTED':'NEEDS_REVIEW', updated_at:now()};
  try {
    const notification = await enqueue(env, updated, status === 'CONTENT_REJECTED'?'MATERIAL_REJECTED':'MATERIAL_PENDING',
      `material:${order.id}:${updated.content_version}:${status}`, {review_reason:status === 'CONTENT_REJECTED'?reason:''});
    await batch(env, [optimistic(env, order, editable),
      statement(env, `UPDATE orders SET content_source=?,content_title=?,content_text=?,content_file=?,content_mime=?,
        content_version=?,approved_version=NULL,status=?,moderation=?,updated_at=? WHERE id=?`,
      updated.content_source, title, text, key, mime, updated.content_version, status, updated.moderation, updated.updated_at, order.id),
      history(env, order.id, status), audit(env, upload?'UPLOAD_PENDING_MANUAL_REVIEW':'MODERATION_SCREENING', order.id,
        upload?'Pemeriksaan metadata; decoding, antivirus, dan transcoding belum tersedia':updated.moderation), notification
    ]);
  } catch (error) {
    if (key) await deleteMedia(env,key);
    throw error;
  }
  if (order.content_file) ctx.waitUntil(deleteMedia(env,order.content_file));
  ctx.waitUntil(processOutbox(env));
  return {status, reason, message:'Materi masuk antrean pemeriksaan operator.'};
}

async function checkout(request, env, auth, order, ctx) {
  await owner(request, env, order, auth);
  if (!env.BANK_ACCOUNT) fail(503, 'Instruksi pembayaran belum dikonfigurasi operator');
  const key = clean(request.headers.get('Idempotency-Key'), 200) || uid();
  const existing = await first(env, 'SELECT * FROM payments WHERE idempotency_key=?', key);
  if (existing) {
    if (existing.order_id !== order.id) fail(409, 'Kunci pembayaran telah digunakan');
    return {...existing, expires_at:order.hold_expires, demo:false, instructions:publicConfig(env).bank};
  }
  if (order.status !== 'APPROVED' || order.approved_version !== order.content_version) fail(409, 'Konten belum disetujui');
  if (stamp(order.start_at) <= Date.now()) fail(409, 'Jadwal sudah berlalu; buat pesanan baru');
  const t = now(), hold = new Date(Date.now()+900000).toISOString();
  const payment = {id:uid(), order_id:order.id, idempotency_key:key, status:'PENDING', amount:order.total, created_at:t};
  const notification = await enqueue(env, {...order,status:'AWAITING_PAYMENT',hold_expires:hold}, 'BILL_CREATED', 'bill:'+payment.id);
  try {
    await batch(env, [optimistic(env, order, ['APPROVED']),
      guard(env, '(SELECT COUNT(*) FROM otp WHERE order_id=? AND verified=1)=2', order.id),
      guard(env, 'EXISTS(SELECT 1 FROM orders WHERE id=? AND approved_version=content_version AND start_at>?)', order.id, t),
      statement(env, "UPDATE orders SET status='AWAITING_PAYMENT',hold_expires=?,updated_at=? WHERE id=?", hold, t, order.id),
      statement(env, 'INSERT INTO payments VALUES(?,?,?,?,?,?)', ...Object.values(payment)),
      history(env, order.id, 'AWAITING_PAYMENT'), audit(env, 'CHECKOUT', order.id), notification
    ]);
  } catch (error) {
    // Concurrent retries with the same idempotency key return the first payment.
    const prior = await first(env, 'SELECT * FROM payments WHERE idempotency_key=? AND order_id=?', key, order.id);
    if (!prior) throw error;
    const current = await getOrder(env, order.id);
    return {...prior, expires_at:current.hold_expires, demo:false, instructions:publicConfig(env).bank};
  }
  ctx.waitUntil(processOutbox(env));
  return {...payment, expires_at:hold, demo:false, instructions:publicConfig(env).bank};
}

async function asset(request, env, order) {
  if (!order.content_file) fail(404, 'Tidak ada file');
  const object = await readMedia(env,order.content_file);
  if (!object.value) fail(503, 'Materi sedang disinkronkan. Coba lagi setelah satu menit.');
  const metadata = object.metadata;
  if (!metadata || !Number.isSafeInteger(metadata.size)) fail(503,'Metadata materi tidak tersedia');
  const headers = new Headers({'Cache-Control':'no-store', 'Content-Type':order.content_mime,
    'X-Content-Type-Options':'nosniff', 'Accept-Ranges':'bytes', ETag:'"'+order.content_file+'"'});
  let offset = 0, length = metadata.size, status = 200;
  const range = request.headers.get('Range');
  if (range) {
    const match = /^bytes=(\d*)-(\d*)$/.exec(range);
    const invalid = async () => {await object.value.cancel();return new Response(null, {status:416,headers:{...Object.fromEntries(headers),'Content-Range':`bytes */${metadata.size}`}});};
    if (!match || (!match[1] && !match[2]) || !metadata.size) return invalid();
    if (!match[1]) {length = Math.min(Number(match[2]), metadata.size); offset = metadata.size-length;}
    else {offset = Number(match[1]); length = (match[2]?Math.min(Number(match[2]),metadata.size-1):metadata.size-1)-offset+1;}
    if (offset >= metadata.size || length <= 0) return invalid();
    headers.set('Content-Range', `bytes ${offset}-${offset+length-1}/${metadata.size}`); status = 206;
  }
  headers.set('Content-Length', String(length));
  if (request.method === 'HEAD') {await object.value.cancel();return new Response(null, {status,headers});}
  return new Response(status === 206?sliceStream(object.value,offset,length):object.value, {status,headers});
}

async function adminRoutes(request, env, auth, path, ctx) {
  const method = request.method;
  if (path === '/admin/auth/login' && method === 'POST') {
    const result = await auth.login(await body(request));
    return json(result.data, 200, {'Set-Cookie':result.cookie});
  }
  const session = await auth.admin();
  if (path === '/admin/auth/session' && method === 'GET') return session;
  if (path === '/admin/auth/logout' && method === 'POST') return json({ok:true}, 200, {'Set-Cookie':await auth.logout()});
  if (method === 'GET' && path === '/admin/orders') return all(env, 'SELECT id,order_no,company,pic,start_at,end_at,status,total,moderation,content_title,screen_id FROM orders ORDER BY created_at DESC LIMIT 200');
  if (method === 'GET' && path === '/admin/screens') return all(env, 'SELECT * FROM screens');
  if (method === 'GET' && path === '/admin/audit') return all(env, 'SELECT * FROM audit ORDER BY created_at DESC LIMIT 100');
  if (method === 'GET' && path === '/admin/playback') return all(env, 'SELECT * FROM playback ORDER BY started_at DESC LIMIT 100');
  if (method === 'GET' && path === '/admin/summary') return first(env, `SELECT
    (SELECT COUNT(*) FROM orders) orders,
    (SELECT COALESCE(SUM(total),0) FROM orders WHERE status IN ('PAID','SCHEDULED','LIVE','COMPLETED')) revenue,
    (SELECT COUNT(*) FROM orders WHERE status='NEEDS_REVIEW') reviews,
    (SELECT COUNT(*) FROM screens) screens`);
  if (method === 'GET' && path === '/admin/schedule') {
    const value = new URL(request.url).searchParams.get('date') || new Date(Date.now()+25200000).toISOString().slice(0,10);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(value) || !Number.isFinite(Date.parse(value))) fail(422, 'Tanggal tidak valid');
    const start = new Date(Date.parse(value+'T00:00:00+07:00')).toISOString(), end = new Date(stamp(start)+7*86400000).toISOString();
    return {start,end,
      orders:await all(env, "SELECT id,order_no,company,screen_id,start_at,end_at,status,content_title FROM orders WHERE start_at<? AND end_at>? AND status IN ('AWAITING_PAYMENT','SCHEDULED','LIVE','COMPLETED') ORDER BY start_at", end,start),
      screens:(await all(env, 'SELECT s.*,h.reported_at last_seen FROM screens s LEFT JOIN heartbeats h ON s.id=h.screen_id')).map(s=>({...s,online:!!s.last_seen && Date.now()-stamp(s.last_seen)<60000})),
      blackouts:await all(env, 'SELECT * FROM blackouts WHERE start_at<? AND end_at>?',end,start),
      scheduler:await first(env, 'SELECT * FROM scheduler_state WHERE id=1') || {last_tick:now()}
    };
  }
  if (path === '/admin/devices' && method === 'GET') return all(env, 'SELECT id,screen_id,name,created_at,revoked_at FROM devices ORDER BY created_at DESC');
  if (path === '/admin/devices' && method === 'POST') {
    const b = await body(request), name = clean(b.name, 121);
    if (!name || name.length > 120) fail(422, 'Nama perangkat wajib diisi (maksimal 120 karakter)');
    await screen(env, clean(b.screen_id));
    const id = uid(), token = randomToken();
    await batch(env, [statement(env, 'INSERT INTO devices VALUES(?,?,?,?,?,NULL)',id,b.screen_id,name,await digest(env.APP_SECRET,token),now()), audit(env,'DEVICE_ENROLLED',id,name)]);
    return {id,token,screen_id:b.screen_id,name};
  }
  let match = /^\/admin\/devices\/([^/]+)$/.exec(path);
  if (match && method === 'DELETE') {
    const id = match[1];
    if (!await first(env, 'SELECT id FROM devices WHERE id=?',id)) fail(404,'Perangkat tidak ditemukan');
    await batch(env, [statement(env,'UPDATE devices SET revoked_at=? WHERE id=?',now(),id),audit(env,'DEVICE_REVOKED',id)]);
    return {ok:true};
  }
  if (path === '/admin/blackouts' && method === 'POST') {
    const b = await body(request), start = parse(b.start_at), end = parse(b.end_at), reason = clean(b.reason,500);
    if (end <= start || !reason) fail(422,'Rentang waktu dan alasan wajib diisi');
    await screen(env,clean(b.screen_id));
    const id = uid();
    await batch(env,[statement(env,'INSERT INTO blackouts VALUES(?,?,?,?,?)',id,b.screen_id,start,end,reason),audit(env,'BLACKOUT_CREATED',id,reason)]);
    return {id};
  }
  match = /^\/admin\/blackouts\/([^/]+)$/.exec(path);
  if (match && method === 'DELETE') {
    const id = match[1];
    if (!await first(env,'SELECT id FROM blackouts WHERE id=?',id)) fail(404,'Blackout tidak ditemukan');
    await batch(env,[statement(env,'DELETE FROM blackouts WHERE id=?',id),audit(env,'BLACKOUT_REMOVED',id)]);
    return {ok:true};
  }
  match = /^\/admin\/moderation\/([^/]+)\/decision$/.exec(path);
  if (match && method === 'POST') {
    const b = await body(request), order = await getOrder(env,match[1]), reason = clean(b.reason,1000);
    if (!['APPROVE','REJECT'].includes(b.decision) || (b.decision === 'REJECT' && !reason)) fail(422,'Keputusan dan alasan revisi wajib diisi');
    if (order.status !== 'NEEDS_REVIEW') fail(409,'Tidak sedang direview');
    const status = b.decision === 'APPROVE'?'APPROVED':'CONTENT_REJECTED';
    const updated = {...order,status,approved_version:b.decision === 'APPROVE'?order.content_version:null};
    const notification = await enqueue(env,updated,b.decision === 'APPROVE'?'MATERIAL_APPROVED':'MATERIAL_REJECTED',`material:${order.id}:${order.content_version}:${status}`,{review_reason:reason});
    await batch(env,[optimistic(env,order,['NEEDS_REVIEW']),
      statement(env,'UPDATE orders SET status=?,approved_version=?,moderation=?,updated_at=? WHERE id=?',status,updated.approved_version,b.decision === 'APPROVE'?'APPROVED':'REJECTED',now(),order.id),
      history(env,order.id,status),audit(env,'ADMIN_MODERATION_'+b.decision,order.id,reason),notification]);
    ctx.waitUntil(processOutbox(env));
    return {status};
  }
  match = /^\/admin\/orders\/([^/]+)\/(confirm-payment|takedown)$/.exec(path);
  if (match && method === 'POST') {
    const b = await body(request), order = await getOrder(env,match[1]);
    if (match[2] === 'takedown') {
      const reason = clean(b.reason,1000);
      if (!reason) fail(422,'Alasan wajib');
      if (!['SCHEDULED','LIVE'].includes(order.status)) fail(409,'Pesanan tidak sedang dijadwalkan atau tayang');
      await batch(env,[optimistic(env,order,['SCHEDULED','LIVE']),statement(env,"UPDATE orders SET status='TAKEN_DOWN',updated_at=? WHERE id=?",now(),order.id),history(env,order.id,'TAKEN_DOWN'),audit(env,'TAKEDOWN',order.id,reason)]);
      return {status:'TAKEN_DOWN'};
    }
    const reference = clean(b.reference,121), t = now();
    if (reference.length < 6 || reference.length > 120) fail(422,'Referensi bank harus 6–120 karakter');
    if (b.amount !== order.total) fail(422,'Nominal penerimaan harus sama dengan tagihan');
    if (order.status !== 'AWAITING_PAYMENT' || order.hold_expires <= t || order.start_at <= t) fail(409,'Tagihan atau jadwal tidak aktif');
    const updated = {...order,status:'SCHEDULED',paid_at:t};
    const notification = await enqueue(env,updated,'PAYMENT_CONFIRMED','paid:'+order.id,{confirmation:{order_id:order.id,reference,confirmed_at:t}});
    await batch(env,[optimistic(env,order,['AWAITING_PAYMENT']),
      guard(env,'EXISTS(SELECT 1 FROM orders WHERE id=? AND hold_expires>? AND start_at>? AND approved_version=content_version)',order.id,t,t),
      statement(env,'INSERT INTO payment_confirmations VALUES(?,?,?)',order.id,reference,t),
      statement(env,"UPDATE payments SET status='PAID' WHERE order_id=? AND status='PENDING'",order.id),
      statement(env,"UPDATE orders SET status='SCHEDULED',paid_at=?,updated_at=? WHERE id=?",t,t,order.id),
      history(env,order.id,'PAID'),history(env,order.id,'SCHEDULED'),audit(env,'BANK_PAYMENT_CONFIRMED',order.id,reference),notification]);
    ctx.waitUntil(processOutbox(env));
    return {status:'SCHEDULED'};
  }
  fail(404,'Endpoint tidak ditemukan');
}

async function playerRoutes(request, env, path) {
  const method = request.method, url = new URL(request.url);
  const d = await device(request,env);
  if (path === '/player/manifest' && method === 'GET') {
    const id = url.searchParams.get('screen_id');
    if (d.screen_id !== id) fail(403,'Token tidak diizinkan untuk layar ini');
    await screen(env,id);
    const t = now(), future = new Date(Date.now()+48*3600000).toISOString();
    const items = await all(env, `SELECT id order_id,start_at,end_at,content_title title,content_text text,
      CASE WHEN content_file IS NOT NULL THEN '/api/v1/player/assets/'||id ELSE NULL END asset_url,
      content_source source,content_mime mime FROM orders WHERE screen_id=? AND status IN ('SCHEDULED','LIVE')
      AND start_at<? AND end_at>? AND approved_version=content_version ORDER BY start_at LIMIT 100`,id,future,t);
    return {server_time:t,items,refresh_seconds:10,lease_seconds:30};
  }
  const match = /^\/player\/assets\/([^/]+)$/.exec(path);
  if (match && ['GET','HEAD'].includes(method)) {
    const order = await getOrder(env,match[1]);
    if (order.screen_id !== d.screen_id || !['SCHEDULED','LIVE'].includes(order.status) || order.approved_version !== order.content_version || order.end_at <= now()) fail(403,'Aset tidak tersedia');
    return asset(request,env,order);
  }
  if (path === '/player/heartbeat' && method === 'POST') {
    const b = await body(request);
    if (b.screen_id !== d.screen_id) fail(403,'Token tidak diizinkan untuk layar ini');
    await screen(env,b.screen_id);
    await run(env,'INSERT OR REPLACE INTO heartbeats VALUES(?,?,?)',b.screen_id,now(),JSON.stringify({app_version:clean(b.app_version,100),order_id:clean(b.order_id,100)}));
    return {ok:true};
  }
  if (path === '/player/playback-logs' && method === 'POST') {
    const b = await body(request);
    if (!Array.isArray(b.logs) || b.logs.length > 20) fail(422,'Maksimal 20 catatan penayangan per permintaan Cloudflare');
    const statements = [];
    for (const entry of b.logs) {
      const order = await getOrder(env,clean(entry.order_id));
      if (order.screen_id !== d.screen_id) fail(403,'Token tidak diizinkan untuk layar ini');
      const start = parse(entry.started_at), end = parse(entry.ended_at);
      if (entry.screen_id !== order.screen_id || end < start || start < order.start_at || stamp(end) > stamp(order.end_at)+2000 || stamp(end) > Date.now()+10000 || !order.paid_at || order.approved_version !== order.content_version) fail(422,'Catatan penayangan tidak sesuai jadwal');
      statements.push(statement(env,'INSERT OR IGNORE INTO playback VALUES(?,?,?,?,?,?)',clean(entry.id,100)||uid(),order.id,order.screen_id,start,end,'PLAYED'));
    }
    if (statements.length) await batch(env,statements);
    return {ok:true};
  }
  fail(404,'Endpoint tidak ditemukan');
}

async function api(request, env, auth, ctx) {
  const url = new URL(request.url), path = url.pathname.slice('/api/v1'.length), method = request.method;
  if (path === '/config' && method === 'GET') return publicConfig(env);
  if (path === '/health' && method === 'GET') {
    await first(env,'SELECT 1 ok');
    return {ok:true,environment:'cloudflare'};
  }
  if (path.startsWith('/admin/')) {
    if (path !== '/admin/auth/login') await auth.admin();
    if (['/admin/orders','/admin/summary','/admin/schedule'].includes(path)) await reconcileIfDue(env);
    return adminRoutes(request,env,auth,path,ctx);
  }
  if (path.startsWith('/player/')) {
    await device(request,env);
    if (path === '/player/manifest') await reconcileIfDue(env);
    return playerRoutes(request,env,path);
  }
  if (path === '/screens' && method === 'GET') return all(env,"SELECT * FROM screens WHERE status='ACTIVE'");
  let match = /^\/screens\/by-token\/([^/]+)$/.exec(path);
  if (match && method === 'GET') return await first(env,"SELECT * FROM screens WHERE token=? AND status='ACTIVE'",match[1]) || fail(404,'QR tidak dikenal');
  match = /^\/screens\/([^/]+)\/(availability|quote|qr)$/.exec(path);
  if (match && method === 'GET') {
    const s = await screen(env,match[1]);
    if (match[2] === 'qr') {
      const code = qrcode(0,'M'); code.addData(url.origin+'/?screen_token='+encodeURIComponent(s.token)); code.make();
      return new Response(code.createSvgTag({cellSize:5,margin:12}),{headers:{'Content-Type':'image/svg+xml','Cache-Control':'no-store'}});
    }
    const start = parse(url.searchParams.get(match[2] === 'quote'?'start_at':'from_at'));
    const end = parse(url.searchParams.get(match[2] === 'quote'?'end_at':'to_at'));
    if (end <= start) fail(422,'Rentang waktu tidak valid');
    const available = !await overlaps(env,s.id,start,end);
    if (match[2] === 'availability') return {available};
    validateSchedule(start,end);
    return {...quote(start,end,s.monthly_price,s.tax_rate),available};
  }
  if (path === '/orders' && method === 'POST') return createOrder(request,env);
  if (path === '/otp/send' && method === 'POST') return otp(request,env,auth,'send');
  if (path === '/otp/verify' && method === 'POST') return otp(request,env,auth,'verify');
  if (path === '/order-status' && method === 'GET') {
    const id = await verify(env.APP_SECRET,request.headers.get('X-Order-Status') || '', 'status');
    await reconcileIfDue(env);
    const order = await getOrder(env,id), s = await screen(env,order.screen_id);
    const note = await first(env,"SELECT detail FROM audit WHERE entity=? AND action='ADMIN_MODERATION_REJECT' ORDER BY created_at DESC LIMIT 1",id);
    return {order_no:order.order_no,status:order.status,content_title:order.content_title,start_at:order.start_at,end_at:order.end_at,
      screen:s.name,review_note:order.status === 'CONTENT_REJECTED'?note?.detail || '':'',
      history:await all(env,'SELECT to_status,created_at FROM history WHERE order_id=? ORDER BY id',id)};
  }
  match = /^\/orders\/([^/]+)(?:\/(quote|content|upload|checkout|creative|invoice))?$/.exec(path);
  if (match) {
    await reconcileIfDue(env);
    const order = await getOrder(env,match[1]);
    await owner(request,env,order,auth);
    if (!match[2] && method === 'GET') return orderDetails(env,order);
    if (match[2] === 'quote' && method === 'POST') {
      const s = await screen(env,order.screen_id);
      return quote(order.start_at,order.end_at,s.monthly_price,s.tax_rate);
    }
    if (['content','upload'].includes(match[2]) && method === 'POST') return submitMaterial(request,env,auth,order,match[2] === 'upload',ctx);
    if (match[2] === 'checkout' && method === 'POST') return checkout(request,env,auth,order,ctx);
    if (match[2] === 'creative' && ['GET','HEAD'].includes(method)) return asset(request,env,order);
    if (match[2] === 'invoice' && method === 'GET') {
      if (!order.paid_at) fail(409,'Invoice tersedia setelah pembayaran');
      // Generate once in the email worker; downloads stream the stored PDF within Free CPU limits.
      const invoice = await readMedia(env,'invoices/'+order.id+'.pdf');
      if (!invoice.value) fail(409,'Invoice sedang disiapkan atau disinkronkan. Coba lagi setelah satu menit.');
      return new Response(invoice.value,{headers:{'Content-Type':'application/pdf','Content-Disposition':`attachment; filename="INV-${order.order_no}.pdf"`,'Cache-Control':'no-store'}});
    }
  }
  fail(404,'Endpoint tidak ditemukan');
}

export async function reconcileIfDue(env) {
  const state = await first(env,'SELECT last_tick FROM scheduler_state WHERE id=1');
  if (!state || Date.now()-stamp(state.last_tick) >= 60000) await reconcile(env);
}

export default {
  async fetch(request, env, ctx) {
    try {
      const url = new URL(request.url), path = url.pathname;
      checkSecrets(env);
      if (env.CANONICAL_REDIRECT === 'true' && env.PUBLIC_BASE_URL && !path.startsWith('/api/') &&
          ['GET','HEAD'].includes(request.method) && url.origin !== new URL(env.PUBLIC_BASE_URL).origin) {
        const target = new URL(env.PUBLIC_BASE_URL);target.pathname=path;target.search=url.search;
        return new Response(null,{status:308,headers:{Location:target.href,'Cache-Control':'no-store'}});
      }
      const auth = new Auth(request,env);
      if (path.startsWith('/api/')) {
        if (!path.startsWith('/api/v1/')) fail(404,'Endpoint tidak ditemukan');
        const length = Number(request.headers.get('Content-Length') || 0);
        if (!path.endsWith('/upload') && length > 65536) fail(413,'Permintaan terlalu besar');
        const result = await api(request,env,auth,ctx);
        const response = result instanceof Response?result:json(result);
        response.headers.set('Cache-Control','no-store');
        response.headers.set('Referrer-Policy','no-referrer');
        response.headers.set('X-Content-Type-Options','nosniff');
        return response;
      }
      if (!['GET','HEAD'].includes(request.method)) fail(405,'Metode tidak diizinkan');
      if (protectedPages.has(path) && !await auth.session()) {
        return new Response(null,{status:303,headers:{Location:'/login?next='+protectedPages.get(path),'Cache-Control':'no-store'}});
      }
      const target = path === '/player' || path === '/static/player.html'?'/static/player.html':
        ['/','/admin','/schedule','/login','/terms','/privacy','/status'].includes(path)?'/index.html':path;
      const response = await env.ASSETS.fetch(new Request(new URL(target,url),request));
      const result = new Response(response.body,response);
      if (protectedPages.has(path) || path === '/login') {
        result.headers.set('Cache-Control','no-store'); result.headers.set('Vary','Cookie');
      }
      return result;
    } catch (error) {
      if (!(error instanceof HttpError)) console.error('Cloudflare request failed:', env.TEST_DIAGNOSTICS?error.stack:error.name);
      return json({detail:error instanceof HttpError?error.message:'Terjadi kesalahan server'},error instanceof HttpError?error.status:500);
    }
  },
  async scheduled(controller, env, ctx) {
    checkSecrets(env);
    await reconcile(env);
    ctx.waitUntil(processOutbox(env));
  }
};
