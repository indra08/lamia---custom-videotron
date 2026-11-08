"""Table-based transactional emails with inline CSS and plain-text alternatives."""
import io
from datetime import datetime
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import formataddr, formatdate, make_msgid, parseaddr
from functools import lru_cache
from html import escape
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from PIL import Image

MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des')


def money(value):
    return 'Rp ' + f'{int(value):,}'.replace(',', '.')


def local_time(value):
    stamp = datetime.fromisoformat(str(value).replace('Z', '+00:00')).astimezone(ZoneInfo('Asia/Jakarta'))
    return f'{stamp.day:02d} {MONTHS[stamp.month-1]} {stamp.year}, {stamp:%H.%M} WIB'


def e(value):
    return escape(str(value or ''), quote=True)


@lru_cache(maxsize=1)
def logo_png():
    output = io.BytesIO()
    with Image.open(Path(__file__).parent / 'icon' / 'logo.webp') as logo:
        logo.thumbnail((128, 128), Image.Resampling.LANCZOS)
        logo.save(output, format='PNG')
    return output.getvalue()


def detail_rows(rows):
    return '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="width:100%;border-collapse:collapse;table-layout:fixed;">' + ''.join(
        f'<tr><td width="40%" valign="top" style="padding:10px 8px 10px 0;border-bottom:1px solid #e4eadf;font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:19px;color:#738267;">{e(label)}</td><td width="60%" align="right" valign="top" style="padding:10px 0 10px 8px;border-bottom:1px solid #e4eadf;font-family:Arial,Helvetica,sans-serif;font-size:13px;line-height:19px;color:#244531;word-break:break-word;overflow-wrap:anywhere;">{e(value)}</td></tr>'
        for label, value in rows) + '</table>'


def callout(text):
    return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;"><tr><td bgcolor="#f8f4e8" style="padding:14px 16px;border-left:3px solid #ba9c57;font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:20px;color:#786237;">{e(text)}</td></tr></table>'


def message(sender, destination, subject, preview, title, lead, body, plain, *, support='', base_url='', message_id=None, cta_label='Buka workspace LAMIA'):
    address = parseaddr(sender)[1]
    domain = address.rsplit('@', 1)[-1] if '@' in address else 'lamia.local'
    logo_id = 'lamia-logo@' + domain
    mail = EmailMessage(policy=SMTP)
    mail['From'] = formataddr(('LAMIA', address))
    mail['To'] = destination
    mail['Subject'] = subject
    mail['Date'] = formatdate(localtime=False)
    mail['Message-ID'] = message_id or make_msgid(domain=domain)
    if support:
        mail['Reply-To'] = support
    mail.set_content(plain, cte='quoted-printable')
    parsed = urlsplit(base_url)
    valid_url = base_url if parsed.scheme in ('https', 'http') and parsed.netloc and not parsed.username else ''
    button = ''
    if valid_url:
        button = f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;margin-top:22px;"><tr><td align="center" bgcolor="#14594b" style="mso-padding-alt:13px 22px;"><a href="{e(valid_url)}" style="display:inline-block;padding:13px 22px;font-family:Arial,Helvetica,sans-serif;font-size:13px;font-weight:bold;line-height:20px;text-decoration:none;color:#ffffff;">{e(cta_label)} &#8594;</a></td></tr></table>'
    contact = f'Pertanyaan? Hubungi <a href="mailto:{e(support)}" style="color:#426b43;text-decoration:underline;">{e(support)}</a>.' if support else 'Simpan nomor pesanan Anda saat menghubungi operator.'
    html = f'''<!doctype html>
<html lang="id" xmlns="http://www.w3.org/1999/xhtml" xmlns:o="urn:schemas-microsoft-com:office:office">
<head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="x-apple-disable-message-reformatting">
<!--[if mso]><xml><o:OfficeDocumentSettings><o:PixelsPerInch>96</o:PixelsPerInch></o:OfficeDocumentSettings></xml><![endif]-->
<title>{e(subject)}</title></head>
<body style="margin:0;padding:0;width:100%;background-color:#f2f5ef;-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%;">
<div style="display:none;font-size:1px;line-height:1px;max-height:0;max-width:0;opacity:0;overflow:hidden;mso-hide:all;">{e(preview)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#f2f5ef" style="width:100%;border-collapse:collapse;mso-table-lspace:0pt;mso-table-rspace:0pt;"><tr><td align="center" style="padding:24px 12px;">
<!--[if mso]><table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0"><tr><td><![endif]-->
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#ffffff" style="width:100%;max-width:600px;border-collapse:collapse;border:1px solid #dfe7d9;mso-table-lspace:0pt;mso-table-rspace:0pt;">
<tr><td bgcolor="#114c3d" style="padding:24px;"><table role="presentation" cellpadding="0" cellspacing="0" border="0" style="border-collapse:collapse;"><tr><td width="44" valign="middle" style="width:44px;padding:0 12px 0 0;"><img src="cid:{logo_id}" width="44" height="44" border="0" alt="LAMIA" style="display:block;width:44px;height:44px;border:0;outline:none;text-decoration:none;"></td><td valign="middle" style="font-family:Arial,Helvetica,sans-serif;font-size:22px;line-height:26px;font-weight:bold;letter-spacing:2px;color:#ffffff;">LAMIA<br><span style="font-size:8px;line-height:15px;font-weight:normal;letter-spacing:1px;color:#c9dcc1;">OUTDOOR ADVERTISING</span></td></tr></table></td></tr>
<tr><td style="padding:28px 24px 12px;font-family:Arial,Helvetica,sans-serif;"><h1 style="margin:0 0 13px;font-family:Arial,Helvetica,sans-serif;font-size:26px;line-height:34px;font-weight:bold;color:#203f2e;">{e(title)}</h1><p style="margin:0;font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:23px;color:#65795c;">{e(lead)}</p></td></tr>
<tr><td style="padding:12px 24px 28px;font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:23px;color:#35553a;">{body}{button}</td></tr>
<tr><td bgcolor="#fafbf7" style="padding:18px 24px;border-top:1px solid #e4eadf;font-family:Arial,Helvetica,sans-serif;"><p style="margin:0 0 9px;font-size:12px;line-height:20px;color:#7b8c6e;">{contact}</p><p style="margin:0;font-size:10px;line-height:18px;color:#8c9b7e;">LAMIA &middot; Make your next impression count.</p></td></tr>
</table><!--[if mso]></td></tr></table><![endif]-->
</td></tr></table></body></html>'''
    mail.add_alternative(html, subtype='html', cte='quoted-printable')
    mail.get_body(preferencelist=('html',)).add_related(logo_png(), maintype='image', subtype='png', cid=f'<{logo_id}>', disposition='inline', filename='lamia.png')
    return mail


def verification_email(sender, destination, code, support=''):
    plain = f'Verifikasi email LAMIA\n\nKode Anda: {code}\nBerlaku selama 5 menit.\nMasukkan kode pada halaman verifikasi LAMIA, lalu pilih Verifikasi email.\nJangan bagikan kode ini. Jika tidak meminta kode, abaikan email ini.'
    body = f'''<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#eef5e7" style="width:100%;border-collapse:collapse;border:1px solid #dbe7cf;"><tr><td align="center" style="padding:20px 8px 8px;font-family:Arial,Helvetica,sans-serif;font-size:10px;line-height:16px;letter-spacing:1px;color:#69835a;">KODE VERIFIKASI</td></tr>
<tr><td align="center" style="padding:0 8px 8px;font-family:Consolas,'Courier New',monospace;font-size:32px;line-height:44px;font-weight:bold;letter-spacing:4px;color:#174d35;white-space:nowrap;">{e(code)}</td></tr>
<tr><td align="center" style="padding:0 8px 20px;font-family:Arial,Helvetica,sans-serif;font-size:12px;line-height:20px;color:#647d56;">Berlaku selama <strong>5 menit</strong></td></tr></table>
<p style="margin:20px 0;font-size:14px;line-height:23px;color:#65795c;">Kembali ke halaman verifikasi LAMIA, masukkan 6 digit kode, lalu pilih <strong>Verifikasi email</strong>.</p>
{callout('Jangan bagikan kode ini kepada siapa pun. Tim LAMIA tidak akan meminta kode verifikasi Anda.')}
<p style="margin:18px 0 0;font-size:12px;line-height:20px;color:#829274;">Tidak meminta kode ini? Anda dapat mengabaikan email ini.</p>'''
    return message(sender, destination, 'Kode verifikasi email Anda — LAMIA', 'Kode verifikasi Anda berlaku 5 menit.', 'Verifikasi email Anda.', 'Gunakan kode berikut untuk mengonfirmasi email pada pesanan Anda.', body, plain, support=support)


def transaction_email(sender, payload, kind, *, invoice_pdf=None, message_id=None):
    order, screen = payload['order'], payload['screen']
    simulated = payload.get('simulated', False)
    issuer, bank = payload.get('issuer', {}), payload.get('bank', {})
    billing = kind == 'BILL_CREATED'
    title = 'Tagihan kampanye Anda siap.' if billing else 'Pembayaran Anda terkonfirmasi.'
    if simulated:
        title = 'Tagihan pengujian dibuat.' if billing else 'Pembayaran simulasi tercatat.'
    status = 'MENUNGGU PEMBAYARAN' if billing else 'SIMULASI' if simulated else 'LUNAS'
    rows = [('Nomor pesanan', order['order_no']), ('Perusahaan', order['company']), ('Layar', screen['name']),
            ('Mulai tayang', local_time(order['start_at'])), ('Selesai tayang', local_time(order['end_at'])),
            ('Subtotal', money(order['subtotal'])), ('Pajak', money(order['tax']))]
    if billing:
        rows.append(('Batas pembayaran', local_time(order['hold_expires'])))
    else:
        rows.append(('Pembayaran tercatat', local_time(order['paid_at'])))
        if payload.get('confirmation'):
            rows.append(('Referensi bank', payload['confirmation']['reference']))
    summary = detail_rows(rows)
    total_label = 'TOTAL TAGIHAN' if billing else 'TOTAL SIMULASI' if simulated else 'TOTAL DIBAYAR'
    total = f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#14594b" style="width:100%;border-collapse:collapse;"><tr><td style="padding:16px;font-family:Arial,Helvetica,sans-serif;color:#ffffff;"><p style="margin:0 0 6px;font-size:10px;font-weight:bold;line-height:17px;letter-spacing:1px;color:#d7e7cc;">{total_label}</p><p style="margin:0;font-size:24px;font-weight:bold;line-height:32px;color:#ffffff;white-space:nowrap;">{money(order['total'])}</p></td></tr></table>'
    bank_rows = [('Bank', bank.get('name')), ('Nomor rekening', bank.get('account')), ('Atas nama', bank.get('holder'))]
    if billing:
        instructions = '<p style="margin:22px 0 5px;font-weight:bold;font-size:14px;">Instruksi transfer</p>'+detail_rows(bank_rows) if bank.get('account') else callout('Instruksi transfer belum tersedia. Hubungi operator sebelum melakukan pembayaran.')
        note = 'Slot ditahan sampai batas pembayaran di atas. Transfer sesuai total tagihan dan hubungi operator dengan nomor pesanan serta bukti transfer agar dana dapat dikonfirmasi sebelum tagihan berakhir. Jika sudah transfer tetapi tagihan kedaluwarsa, hubungi operator sebelum membayar ulang.'
        lead = 'Materi Anda sudah disetujui. Berikut rincian tagihan dan jadwal kampanye Anda.'
    else:
        instructions = '<p style="margin:20px 0;font-size:14px;line-height:23px;color:#65795c;">Invoice PDF terlampir. Kampanye mengikuti jadwal di atas; pantau perkembangannya melalui Pesanan saya pada sesi browser yang sama.</p>'
        note = 'Invoice terlampir merupakan bukti pembayaran, bukan faktur pajak. Simpan nomor pesanan untuk menghubungi operator.'
        lead = 'Terima kasih. Pembayaran telah dicatat dan kampanye Anda sudah masuk jadwal penayangan.'
    body = f'<p style="margin:0 0 14px;font-size:11px;font-weight:bold;letter-spacing:1px;color:#69835a;">{status}</p>{summary}{total}<div style="height:18px;line-height:18px;font-size:1px;">&nbsp;</div>{instructions}<div style="height:16px;line-height:16px;font-size:1px;">&nbsp;</div>{callout(note)}'
    if simulated:
        body += '<p style="margin:18px 0 0;font-size:12px;line-height:20px;color:#936b2d;">MODE PENGUJIAN: email ini bukan bukti transaksi uang sungguhan.</p>'
    plain = f'{title}\nStatus: {status}\n\n'+'\n'.join(f'{label}: {value}' for label,value in rows)+f'\n{total_label}: {money(order["total"])}\n'
    if billing and bank.get('account'):
        plain += '\n'+'\n'.join(f'{label}: {value or "-"}' for label,value in bank_rows)+'\n'
    plain += '\n'+note+'\nBuka Pesanan saya pada browser yang sama untuk memantau status.'
    if simulated:
        plain += '\nSIMULASI: bukan bukti transaksi uang sungguhan.'
    subject = ('Tagihan ' if billing else 'Pembayaran terkonfirmasi ') + order['order_no'] + ' — LAMIA'
    if simulated: subject = '[SIMULASI] ' + subject
    mail = message(sender, order['email'], subject, title, title, lead, body, plain, support=issuer.get('email',''), base_url=payload.get('base_url',''), message_id=message_id)
    if invoice_pdf:
        mail.add_attachment(invoice_pdf, maintype='application', subtype='pdf', filename=f'invoice-LAMIA-{order["order_no"]}.pdf')
    return mail


def review_email(sender,payload,kind,*,message_id=None):
    order,screen=payload['order'],payload['screen']
    approved=kind=='MATERIAL_APPROVED'
    rejected=kind=='MATERIAL_REJECTED'
    status='DISETUJUI' if approved else 'PERLU REVISI' if rejected else 'MENUNGGU REVIEW'
    title='Materi iklan Anda disetujui.' if approved else 'Ada catatan untuk materi Anda.' if rejected else 'Materi Anda sedang ditinjau.'
    lead='Materi telah disetujui operator. Anda dapat melanjutkan ke checkout.' if approved else 'Silakan perbaiki materi sesuai catatan di bawah, kemudian ajukan kembali.' if rejected else 'Materi berhasil kami terima. Operator akan memeriksanya sebelum Anda dapat melanjutkan pembayaran.'
    rows=[('Nomor pesanan',order['order_no']),('Status materi',status),('Materi',order.get('content_title') or 'Materi iklan'),('Layar',screen['name']),('Mulai tayang',local_time(order['start_at'])),('Selesai tayang',local_time(order['end_at']))]
    reason=payload.get('review_reason','')
    note='Persetujuan materi belum mengunci slot. Cek ketersediaan dan buat tagihan melalui Pesanan saya.' if approved else 'Materi belum dapat ditayangkan. Perbaiki dan ajukan kembali melalui detail pesanan.' if rejected else 'Belum perlu melakukan pembayaran. Kami akan mengirim email lagi setelah ada keputusan review.'
    body=f'<p style="margin:0 0 14px;font-size:11px;font-weight:bold;letter-spacing:1px;color:#69835a;">{status}</p>'+detail_rows(rows)
    if reason:
        body+='<p style="margin:20px 0 8px;font-weight:bold;font-size:14px;">Catatan operator</p>'+callout(reason)
    body+='<div style="height:18px;line-height:18px;">&nbsp;</div>'+callout(note)
    body+='<p style="margin:18px 0 0;font-size:12px;line-height:20px;color:#7b8c6e;">Halaman status menampilkan perkembangan terbaru. Untuk mengubah materi atau membayar, lanjutkan melalui Pesanan saya pada sesi pemesanan Anda.</p>'
    plain=title+'\n'+lead+'\n\n'+'\n'.join(f'{key}: {value}' for key,value in rows)
    if reason:plain+='\nCatatan operator: '+reason
    plain+='\n\n'+note
    if payload.get('status_url'):plain+='\nCek status pesanan: '+payload['status_url']
    else:plain+='\nCek perkembangan melalui Pesanan saya di workspace LAMIA.'
    return message(sender,order['email'],title+' '+order['order_no']+' — LAMIA',title,title,lead,body,plain,
                   support=payload.get('issuer',{}).get('email',''),base_url=payload.get('status_url',''),message_id=message_id,cta_label='Cek status pesanan')
