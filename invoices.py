"""Branded A4 receipts using persisted booking and payment amounts."""
import io
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from xml.sax.saxutils import escape
from zoneinfo import ZoneInfo

import reportlab
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import KeepTogether, LongTable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

ROOT = Path(__file__).parent
WIB = ZoneInfo('Asia/Jakarta')
INK = colors.HexColor('#183d30')
GREEN = colors.HexColor('#14594b')
MUTED = colors.HexColor('#78877a')
LINE = colors.HexColor('#e3e9df')
PALE = colors.HexColor('#f3f7ee')
AMBER = colors.HexColor('#926e28')
MONTHS = ('Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu', 'Sep', 'Okt', 'Nov', 'Des')
FONT = Path(reportlab.__file__).parent / 'fonts'
pdfmetrics.registerFont(TTFont('Lamia', str(FONT / 'Vera.ttf')))
pdfmetrics.registerFont(TTFont('LamiaBold', str(FONT / 'VeraBd.ttf')))
pdfmetrics.registerFontFamily('Lamia', normal='Lamia', bold='LamiaBold', italic='Lamia', boldItalic='LamiaBold')

STYLES = {
    'body': ParagraphStyle('body', fontName='Lamia', fontSize=8.5, leading=13, textColor=INK, splitLongWords=True),
    'bold': ParagraphStyle('bold', fontName='LamiaBold', fontSize=9, leading=14, textColor=INK),
    'label': ParagraphStyle('label', fontName='LamiaBold', fontSize=6.5, leading=10, textColor=MUTED, spaceAfter=4),
    'small': ParagraphStyle('small', fontName='Lamia', fontSize=7, leading=11, textColor=MUTED),
    'right': ParagraphStyle('right', fontName='Lamia', fontSize=8.5, leading=13, alignment=TA_RIGHT, textColor=INK),
    'rightbold': ParagraphStyle('rightbold', fontName='LamiaBold', fontSize=9, leading=14, alignment=TA_RIGHT, textColor=INK),
    'white': ParagraphStyle('white', fontName='LamiaBold', fontSize=9, leading=14, textColor=colors.white),
    'whiteright': ParagraphStyle('whiteright', fontName='LamiaBold', fontSize=11, leading=15, alignment=TA_RIGHT, textColor=colors.white),
    'heading': ParagraphStyle('heading', fontName='LamiaBold', fontSize=9, leading=14, textColor=GREEN, spaceAfter=9),
}


def text(value):
    """Treat customer-provided names and addresses as text, never PDF markup."""
    return escape(''.join(c for c in str(value or '') if ord(c) >= 32 or c in '\n\t')).replace('\n', '<br/>')


def paragraph(value, style='body'):
    return Paragraph(text(value), STYLES[style])


def money(amount):
    return 'Rp ' + f'{int(amount):,}'.replace(',', '.')


def hours(value):
    return format(Decimal(str(value)).normalize(), 'f').replace('.', ',') + ' jam'


def date(value, with_time=True):
    stamp = datetime.fromisoformat(str(value).replace('Z', '+00:00')).astimezone(WIB)
    result = f'{stamp.day:02d} {MONTHS[stamp.month - 1]} {stamp.year}'
    return result + (f' · {stamp:%H.%M} WIB' if with_time else '')


def label_value(label, value, style='body'):
    return [paragraph(label, 'label'), paragraph(value, style)]


def render_invoice(order, screen, price_lines, confirmation=None, simulated=False, issuer=None):
    issuer = issuer or {}
    invoice_number = 'INV-' + order['order_no']
    output = io.BytesIO()
    width = A4[0] - 92
    document = SimpleDocTemplate(output, pagesize=A4, leftMargin=46, rightMargin=46,
                                 topMargin=124, bottomMargin=58, title=f'{invoice_number} | LAMIA',
                                 author='LAMIA', subject='Bukti pembayaran kampanye videotron')
    logo = ImageReader(str(ROOT / 'icon' / 'logo.webp'))

    def decorate(canvas, doc):
        canvas.saveState()
        page_width, page_height = A4
        canvas.setFillColor(GREEN)
        canvas.rect(0, page_height - 5, page_width, 5, stroke=0, fill=1)
        canvas.drawImage(logo, 46, page_height - 77, width=43, height=43, mask='auto')
        canvas.setFont('LamiaBold', 19)
        canvas.setFillColor(INK)
        canvas.drawString(100, page_height - 53, 'LAMIA')
        canvas.setFont('Lamia', 6.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(101, page_height - 69, 'OUTDOOR ADVERTISING')
        canvas.setFont('LamiaBold', 25)
        canvas.setFillColor(INK)
        canvas.drawRightString(page_width - 46, page_height - 54, 'INVOICE')
        canvas.setFont('Lamia', 7)
        canvas.setFillColor(MUTED)
        canvas.drawRightString(page_width - 46, page_height - 70, 'Bukti pembayaran kampanye')
        badge = 'SIMULASI' if simulated else 'LUNAS'
        badge_width = 68
        canvas.setFillColor(colors.HexColor('#faf2df') if simulated else colors.HexColor('#e7f2e4'))
        canvas.roundRect(page_width - 46 - badge_width, page_height - 99, badge_width, 17, 4, stroke=0, fill=1)
        canvas.setFont('LamiaBold', 7)
        canvas.setFillColor(AMBER if simulated else GREEN)
        canvas.drawCentredString(page_width - 46 - badge_width / 2, page_height - 93, badge)
        canvas.setStrokeColor(LINE)
        canvas.line(46, 43, page_width - 46, 43)
        canvas.setFont('Lamia', 6)
        canvas.setFillColor(MUTED)
        canvas.drawString(46, 29, 'LAMIA  /  ' + invoice_number)
        canvas.drawRightString(page_width - 46, 29, f'Halaman {doc.page}')
        canvas.restoreState()

    story = []
    metadata = Table([[label_value('NOMOR INVOICE', invoice_number, 'bold'),
                       label_value('TANGGAL PEMBAYARAN', date(order['paid_at'] or order['created_at']))]],
                     colWidths=[width * .59, width * .41])
    metadata.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, -1), PALE),
                                  ('BOX', (0, 0), (-1, -1), .5, LINE),
                                  ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                                  ('LEFTPADDING', (0, 0), (-1, -1), 12),
                                  ('RIGHTPADDING', (0, 0), (-1, -1), 12),
                                  ('TOPPADDING', (0, 0), (-1, -1), 10),
                                  ('BOTTOMPADDING', (0, 0), (-1, -1), 10)]))
    story.extend([metadata, Spacer(1, 18)])
    sender = label_value('DITERBITKAN OLEH', issuer.get('name') or 'LAMIA', 'bold')
    for field in ('address', 'email'):
        if issuer.get(field): sender.append(paragraph(issuer[field]))
    recipient = label_value('DITAGIHKAN KEPADA', order['company'], 'bold')
    recipient.extend(paragraph(value) for value in (order['address'], f"PIC: {order['pic']}", order['email'], order['phone'], f"NPWP: **** {order['npwp_last4']}"))
    parties = Table([[sender, recipient]], colWidths=[width * .44, width * .56])
    parties.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'),
                                 ('LEFTPADDING', (0, 0), (-1, -1), 0),
                                 ('RIGHTPADDING', (0, 0), (-1, -1), 16),
                                 ('TOPPADDING', (0, 0), (-1, -1), 0),
                                 ('BOTTOMPADDING', (0, 0), (-1, -1), 0)]))
    story.extend([parties, Spacer(1, 20)])
    campaign = [paragraph('RINCIAN KAMPANYE', 'heading'),
                paragraph(f"{screen['name']} · {screen['code']}", 'bold'),
                paragraph(screen['location'], 'small')]
    if order.get('content_title'):
        campaign.append(paragraph(order['content_title']))
    campaign.append(Spacer(1, 9))
    period = Table([[label_value('MULAI TAYANG', date(order['start_at'])),
                     label_value('SELESAI TAYANG', date(order['end_at']))]], colWidths=[width / 2] * 2)
    period.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'),
                                ('LEFTPADDING', (0, 0), (-1, -1), 0),
                                ('RIGHTPADDING', (0, 0), (-1, -1), 8),
                                ('TOPPADDING', (0, 0), (-1, -1), 0),
                                ('BOTTOMPADDING', (0, 0), (-1, -1), 10)]))
    campaign.append(period)
    story.append(KeepTogether(campaign))
    rows = [[paragraph('PENAYANGAN / TANGGAL', 'label'), paragraph('DURASI', 'label'), paragraph('BIAYA (IDR)', 'rightbold')]]
    if price_lines:
        for line in price_lines:
            # Billing dates are already persisted as Jakarta calendar dates.
            day = datetime.fromisoformat(line['date'])
            day_label = f'{day.day:02d} {MONTHS[day.month - 1]} {day.year}'
            rows.append([paragraph(day_label), paragraph(hours(line['hours'])), paragraph(money(line['amount']), 'right')])
    else:
        duration = (datetime.fromisoformat(order['end_at']) - datetime.fromisoformat(order['start_at'])).total_seconds() / 3600
        rows.append([paragraph('Penayangan iklan videotron'), paragraph(hours(duration)), paragraph(money(order['subtotal']), 'right')])
    billing = LongTable(rows, colWidths=[width * .48, width * .20, width * .32], repeatRows=1, hAlign='LEFT')
    billing.setStyle(TableStyle([('BACKGROUND', (0, 0), (-1, 0), PALE),
                                 ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                                 ('LINEBELOW', (0, 0), (-1, 0), .6, LINE),
                                 ('LINEBELOW', (0, 1), (-1, -1), .35, LINE),
                                 ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#fcfdfb')]),
                                 ('LEFTPADDING', (0, 0), (-1, -1), 12),
                                 ('RIGHTPADDING', (0, 0), (-1, -1), 12),
                                 ('TOPPADDING', (0, 0), (-1, -1), 8),
                                 ('BOTTOMPADDING', (0, 0), (-1, -1), 8)]))
    story.extend([billing, Spacer(1, 14)])
    totals = Table([[paragraph('Subtotal'), paragraph(money(order['subtotal']), 'right')],
                    [paragraph('Pajak'), paragraph(money(order['tax']), 'right')],
                    [paragraph('TOTAL SIMULASI' if simulated else 'TOTAL DIBAYAR', 'white'), paragraph(money(order['total']), 'whiteright')]],
                   colWidths=[width * .29, width * .27])
    totals.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
                                ('TOPPADDING', (0, 0), (-1, -1), 7), ('BOTTOMPADDING', (0, 0), (-1, -1), 7),
                                ('LEFTPADDING', (0, 0), (-1, -1), 11), ('RIGHTPADDING', (0, 0), (-1, -1), 11),
                                ('BACKGROUND', (0, 2), (-1, 2), GREEN)]))
    method = 'Simulasi lokal — bukan transaksi riil' if simulated else 'Transfer bank · diverifikasi operator' if confirmation else 'Pembayaran tercatat'
    receipt = label_value('METODE PEMBAYARAN', method)
    if confirmation:
        receipt.extend(label_value('REFERENSI BANK', confirmation['reference']))
    receipt.extend(label_value('NOMOR PESANAN', order['order_no'], 'small'))
    summary = Table([[receipt, totals]], colWidths=[width * .44, width * .56])
    summary.setStyle(TableStyle([('VALIGN', (0, 0), (-1, -1), 'TOP'),
                                 ('LEFTPADDING', (0, 0), (-1, -1), 0), ('RIGHTPADDING', (0, 0), (-1, -1), 0),
                                 ('TOPPADDING', (0, 0), (-1, -1), 0), ('BOTTOMPADDING', (0, 0), (-1, -1), 0),
                                 ('RIGHTPADDING', (0, 0), (0, 0), 20)]))
    notes = [summary, Spacer(1, 20), paragraph('Terima kasih telah memilih LAMIA.', 'bold'),
             paragraph('Simpan invoice ini dan nomor pesanan Anda sebagai referensi layanan. Dokumen diterbitkan secara elektronik.', 'small'),
             Spacer(1, 5), paragraph('DOKUMEN SIMULASI — BUKAN BUKTI TRANSAKSI RIIL / BUKAN FAKTUR PAJAK' if simulated else 'BUKTI PEMBAYARAN — BUKAN FAKTUR PAJAK', 'small')]
    story.append(KeepTogether(notes))
    document.build(story, onFirstPage=decorate, onLaterPages=decorate)
    return output.getvalue()
