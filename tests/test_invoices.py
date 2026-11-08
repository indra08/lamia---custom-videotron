"""Exercise long campaign receipts and text that must not be treated as markup."""
from datetime import date, timedelta
import re

from invoices import render_invoice


def test_long_receipt_paginates_without_layout_errors():
    lines = [{'date':(date(2026,11,10)+timedelta(days=i)).isoformat(),'hours':'24','amount':100000} for i in range(90)]
    order = {
        'order_no':'ORD-EXAMPLE-LONG',
        'company':('PT Contoh & Mitra <Nusantara> '*7)[:200],
        'address':('Alamat panjang & karakter <khusus> tetap terbaca. '*11)[:500],
        'pic':'Tim Contoh', 'email':'test@example.com', 'phone':'+6281234567890', 'npwp_last4':'1234',
        'start_at':'2026-11-10T00:00:00+07:00', 'end_at':'2027-02-08T00:00:00+07:00',
        'paid_at':'2026-11-09T08:00:00+07:00', 'created_at':'2026-11-09T07:00:00+07:00',
        'content_title':('Judul kampanye & teks <b>harus tetap literal</b> '*4)[:150],
        'subtotal':9000000,'tax':990000,'total':9990000,
    }
    screen={'name':'Videotron Tengah Kota','code':'VTR-001','location':'Semarang'}
    for simulated in (False, True):
        result=render_invoice(order,screen,lines,simulated=simulated,
                              confirmation=None if simulated else {'reference':'BANK-TEST-'+'A'*100},
                              issuer={'name':'LAMIA & Partner','email':'support@example.com'})
        assert result.startswith(b'%PDF-')
        assert len(re.findall(rb'/Type\s*/Page\b',result)) > 1
