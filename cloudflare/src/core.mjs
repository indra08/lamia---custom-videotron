export class HttpError extends Error {constructor(status,message){super(message);this.status=status;}}
export const fail=(status,message)=>{throw new HttpError(status,message);};
export const uid=()=>crypto.randomUUID();
export const now=()=>new Date().toISOString();
export const json=(data,status=200,headers={})=>new Response(JSON.stringify(data),{status,headers:{'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store',...headers}});
export const parse=value=>{if(typeof value!=='string'||!/(Z|[+-]\d{2}:\d{2})$/.test(value)||!Number.isFinite(Date.parse(value)))fail(422,'Tanggal harus ISO 8601 dengan zona waktu');return new Date(value).toISOString();};
export const stamp=value=>Date.parse(value);
export const hex=bytes=>Array.from(new Uint8Array(bytes),n=>n.toString(16).padStart(2,'0')).join('');
export async function digest(secret,value){const key=await crypto.subtle.importKey('raw',new TextEncoder().encode(secret),{name:'HMAC',hash:'SHA-256'},false,['sign']);return hex(await crypto.subtle.sign('HMAC',key,new TextEncoder().encode(value)));}
export function equal(a,b){if(typeof a!=='string'||typeof b!=='string')return false;let different=a.length^b.length;for(let i=0;i<Math.max(a.length,b.length);i++)different|=(a.charCodeAt(i)||0)^(b.charCodeAt(i)||0);return different===0;}
const b64=value=>btoa(String.fromCharCode(...new TextEncoder().encode(value))).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,'');
export async function capability(secret,scope,order,seconds){const body=b64(JSON.stringify({scope,order,expires:Date.now()+seconds*1000}));return body+'.'+await digest(secret,body);}
export async function verify(secret,token,scope){try{const [body,signature]=token.split('.');if(!equal(signature,await digest(secret,body)))throw Error();const decoded=JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(body.replace(/-/g,'+').replace(/_/g,'/')),c=>c.charCodeAt(0))));if(decoded.scope!==scope||decoded.expires<=Date.now()||!decoded.order)throw Error();return decoded.order;}catch{fail(401,'Sesi atau tautan tidak valid atau kedaluwarsa');}}
export function randomToken(){return hex(crypto.getRandomValues(new Uint8Array(32)));}
export function policy(){return {immediate_start:false,minimum_lead_minutes:1440,minimum_duration_minutes:1440,start_grace_seconds:0};}
export function validateSchedule(start,end){const s=stamp(start),e=stamp(end);if(s<Date.now()+86400000)fail(422,'Mulai tayang Cloudflare minimal 24 jam dari sekarang');if(e-s<86400000)fail(422,'Durasi minimal 24 jam');if(e-s>366*86400000)fail(422,'Durasi maksimal 366 hari per pesanan');}
export function publicConfig(env){return {terms_version:'2026-11-08',operator:env.OPERATOR_NAME||'LAMIA',support_email:env.SUPPORT_EMAIL||'',legal_configured:!!(env.OPERATOR_NAME&&env.SUPPORT_EMAIL),demo_otp:false,demo_payments:false,email_delivery:'smtp',booking_policy:policy(),bank:{name:env.BANK_NAME||'',account:env.BANK_ACCOUNT||'',holder:env.BANK_HOLDER||''}};}
const rounded=(n,d)=>(2n*n+d)/(2n*d);
export function quote(start,end,monthly,taxRate){const s=stamp(parse(start)),e=stamp(parse(end));if(e<=s||e-s>366*86400000)fail(422,'Rentang jadwal tidak valid atau melebihi 366 hari');if(!Number.isSafeInteger(Number(monthly))||Number(monthly)<0)fail(422,'Tarif tidak valid');let cursor=s,subtotal=0n;const lines=[];while(cursor<e){const local=new Date(cursor+25200000),y=local.getUTCFullYear(),m=local.getUTCMonth(),day=local.getUTCDate(),days=new Date(Date.UTC(y,m+1,0)).getUTCDate();const until=Math.min(e,Date.UTC(y,m,day+1)-25200000);const amount=rounded(BigInt(monthly)*BigInt(until-cursor),BigInt(days)*86400000n);subtotal+=amount;lines.push({date:local.toISOString().slice(0,10),hours:String(Number(((until-cursor)/3600000).toFixed(8))),amount:Number(amount)});cursor=until;}const rate=String(taxRate);if(!/^\d+(\.\d{1,6})?$/.test(rate))fail(422,'Pajak tidak valid');const scale=10n**BigInt((rate.split('.')[1]||'').length);const tax=rounded(subtotal*BigInt(rate.replace('.','')),scale);if(subtotal+tax>BigInt(Number.MAX_SAFE_INTEGER))fail(422,'Nilai pesanan melebihi batas');return {lines,subtotal:Number(subtotal),tax:Number(tax),total:Number(subtotal+tax),hours:String((e-s)/3600000)};}
export async function boundedBytes(request,maximum){
  if(Number(request.headers.get('Content-Length')||0)>maximum)fail(413,'Permintaan terlalu besar');
  if(!request.body)return new Uint8Array();
  const reader=request.body.getReader(),chunks=[];let size=0;
  while(true){const {value,done}=await reader.read();if(done)break;size+=value.byteLength;
    if(size>maximum){await reader.cancel();fail(413,'Permintaan terlalu besar');}chunks.push(value);}
  const bytes=new Uint8Array(size);let at=0;for(const chunk of chunks){bytes.set(chunk,at);at+=chunk.byteLength;}return bytes;
}
export async function body(request){try{const data=JSON.parse(new TextDecoder().decode(await boundedBytes(request,65536)));if(!data||typeof data!=='object'||Array.isArray(data))throw Error();return data;}catch(error){if(error instanceof HttpError)throw error;fail(422,'Data JSON tidak valid');}}
export const clean=(value,max=200)=>typeof value==='string'?value.trim().slice(0,max):'';
export function csrfOrigin(request,env){const supplied=request.headers.get('Origin');const expected=env.PUBLIC_BASE_URL?new URL(env.PUBLIC_BASE_URL).origin:new URL(request.url).origin;if(supplied&&supplied!==expected)fail(403,'Asal permintaan tidak diizinkan');}
export const statement=(env,sql,...args)=>env.DB.prepare(sql).bind(...args);
export const first=(env,sql,...args)=>statement(env,sql,...args).first();
export async function all(env,sql,...args){return (await statement(env,sql,...args).all()).results;}
export async function run(env,sql,...args){return statement(env,sql,...args).run();}
export async function batch(env,items){try{return await env.DB.batch(items);}catch(error){if(/SLOT_CONFLICT|lamia_guard|UNIQUE constraint|CHECK constraint/.test(String(error)))fail(409,'Status atau ketersediaan berubah. Periksa pesanan kembali.');throw error;}}
export const guard=(env,condition,...args)=>statement(env,'INSERT INTO tx_guards(id) SELECT 0 WHERE NOT ('+condition+')',...args);
export const audit=(env,action,id,detail='')=>statement(env,'INSERT INTO audit VALUES(?,?,?,?,?)',uid(),action,id,detail,now());
export const history=(env,id,status)=>statement(env,'INSERT INTO history(order_id,to_status,created_at) VALUES(?,?,?)',id,status,now());
export async function getOrder(env,id){return await first(env,'SELECT * FROM orders WHERE id=?',id)||fail(404,'Pesanan tidak ditemukan');}
export async function overlaps(env,screen,start,end,id=''){return !!(await first(env,"SELECT id FROM orders WHERE screen_id=? AND id!=? AND start_at<? AND end_at>? AND (status IN ('PAID','SCHEDULED','LIVE') OR (status='AWAITING_PAYMENT' AND hold_expires>?)) LIMIT 1",screen,id,end,start,now())||await first(env,'SELECT id FROM blackouts WHERE screen_id=? AND start_at<? AND end_at>? LIMIT 1',screen,end,start));}
export async function reconcile(env){const t=now();await batch(env,[statement(env,"INSERT INTO history(order_id,from_status,to_status,created_at) SELECT id,status,'EXPIRED',? FROM orders WHERE status='AWAITING_PAYMENT' AND hold_expires<=?",t,t),statement(env,"UPDATE orders SET status='EXPIRED',updated_at=? WHERE status='AWAITING_PAYMENT' AND hold_expires<=?",t,t),statement(env,"UPDATE payments SET status='EXPIRED' WHERE status='PENDING' AND order_id IN(SELECT id FROM orders WHERE status='EXPIRED')"),statement(env,"INSERT INTO history(order_id,from_status,to_status,created_at) SELECT id,status,'COMPLETED',? FROM orders WHERE status IN ('SCHEDULED','LIVE') AND end_at<=?",t,t),statement(env,"UPDATE orders SET status='COMPLETED',updated_at=? WHERE status IN ('SCHEDULED','LIVE') AND end_at<=?",t,t),statement(env,"INSERT INTO history(order_id,from_status,to_status,created_at) SELECT id,status,'LIVE',? FROM orders WHERE status='SCHEDULED' AND start_at<=? AND end_at>?",t,t,t),statement(env,"UPDATE orders SET status='LIVE',updated_at=? WHERE status='SCHEDULED' AND start_at<=? AND end_at>?",t,t,t),statement(env,'INSERT OR REPLACE INTO scheduler_state VALUES(1,?)',t)]);}
