import {uid, now, statement, first, all, batch, audit, capability, publicConfig} from './core.mjs';
import {deliverEmail, emailTemplate} from './mail.mjs';
import {makeInvoice} from './pdf.mjs';
import {putMedia, readMedia} from './storage.mjs';

export const issuer = env => ({name:env.OPERATOR_NAME || 'LAMIA',email:env.SUPPORT_EMAIL || '',address:env.OPERATOR_ADDRESS || ''});

// Return a statement to be committed atomically with the order transition.
export async function enqueue(env, order, kind, key, extra = {}) {
  const snapshot = {...order}; delete snapshot.npwp_hash;
  const screen = await first(env,'SELECT * FROM screens WHERE id=?',order.screen_id);
  delete screen.token;
  const base = (env.PUBLIC_BASE_URL || '').replace(/\/$/,'');
  const statusUrl = kind.startsWith('MATERIAL_') && base.startsWith('https://')?
    base+'/status#access='+encodeURIComponent(await capability(env.APP_SECRET,'status',order.id,7*86400)):'';
  const payload = {order:snapshot,screen,issuer:issuer(env),bank:publicConfig(env).bank,base_url:base,status_url:statusUrl,
    lines:await all(env,'SELECT date,hours,amount FROM price_lines WHERE order_id=? ORDER BY date',order.id),...extra};
  const id = uid(), domain = (env.SMTP_FROM || 'mail@lamia.invalid').split('@')[1];
  return statement(env, `INSERT OR IGNORE INTO email_outbox(id,event_key,order_id,kind,payload,message_id,next_attempt_at,created_at)
    VALUES(?,?,?,?,?,?,?,?)`,id,key,order.id,kind,JSON.stringify(payload),`<${id}@${domain}>`,Date.now()/1000,now());
}

export async function processOutbox(env, send = deliverEmail) {
  // One item per invocation limits CPU and ensures a slow provider does not starve other items.
  const t = Date.now()/1000, claim = uid();
  const item = await statement(env, `UPDATE email_outbox SET status='SENDING',attempts=attempts+1,claim_token=?,claimed_until=?
    WHERE id=(SELECT id FROM email_outbox WHERE attempts<5 AND
      ((status='PENDING' AND next_attempt_at<=?) OR (status='SENDING' AND claimed_until<=?)) ORDER BY created_at,id LIMIT 1)
    AND attempts<5 AND ((status='PENDING' AND next_attempt_at<=?) OR (status='SENDING' AND claimed_until<=?)) RETURNING *`,
  claim,t+120,t,t,t,t).first();
  // Expired leases from the final attempt cannot stay SENDING forever.
  await statement(env, "UPDATE email_outbox SET status='FAILED',last_error='DeliveryLeaseExpired',claimed_until=NULL,claim_token=NULL WHERE status='SENDING' AND attempts>=5 AND claimed_until<=?",t).run();
  if (!item) return 0;
  let status = 'SENT', errorName = null;
  try {
    const payload = JSON.parse(item.payload), order = await first(env,'SELECT status,content_version,hold_expires FROM orders WHERE id=?',item.order_id);
    if (!order || (item.kind === 'BILL_CREATED' && (order.status !== 'AWAITING_PAYMENT' || order.hold_expires <= now())) ||
      (item.kind.startsWith('MATERIAL_') && (order.content_version !== payload.order.content_version ||
        (item.kind === 'MATERIAL_PENDING' && order.status !== 'NEEDS_REVIEW')))) {
      status = 'CANCELLED';
    } else {
      let attachment = null;
      if (item.kind === 'PAYMENT_CONFIRMED') {
        const key = 'invoices/'+item.order_id+'.pdf';
        const stored = await readMedia(env,key,'arrayBuffer');
        const bytes = stored.value?new Uint8Array(stored.value):
          await makeInvoice(payload.order,payload.screen,payload.lines,payload.confirmation,payload.issuer);
        if (!stored.value) {
          // KV may not have propagated a previous successful upload to this location yet.
          const reserved = await first(env,'SELECT key FROM media_objects WHERE key=?',key);
          if (!reserved) await putMedia(env,key,bytes,'application/pdf');
        }
        attachment = {name:'INV-'+payload.order.order_no+'.pdf',bytes};
      }
      if (!env.SMTP_HOST || !env.SMTP_FROM) throw Error('SmtpNotConfigured');
      await send(env,payload.order.email,emailTemplate(item.kind,payload),attachment,item.message_id);
    }
  } catch (error) {
    status = item.attempts >= 5?'FAILED':'PENDING'; errorName = error.name;
  }
  await batch(env,[
    statement(env, `UPDATE email_outbox SET status=?,last_error=?,sent_at=?,next_attempt_at=?,claimed_until=NULL,claim_token=NULL
      WHERE id=? AND claim_token=?`,status,errorName,status === 'SENT'?now():null,
    Date.now()/1000+Math.min(60*2**(item.attempts-1),900),item.id,claim),
    audit(env,'EMAIL_'+(status === 'PENDING'?'RETRY':status),item.order_id,item.kind+(errorName?': '+errorName:''))
  ]);
  return 1;
}
