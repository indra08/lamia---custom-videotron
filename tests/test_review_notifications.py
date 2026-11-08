from urllib.parse import urlsplit, parse_qs
import re
from datetime import timedelta

import app
import services
from notifications import process_outbox
from test_workflows import create, operator


def ready_order(client):
    order,headers=create(client)
    for channel in ('EMAIL','PHONE'):
        sent=client.post('/api/v1/otp/send',headers=headers,json={'order_id':order['id'],'channel':channel}).json()
        assert client.post('/api/v1/otp/verify',headers=headers,json={'order_id':order['id'],'channel':channel,'code':sent['demo_code']}).status_code==200
    return order,headers


def test_review_emails_and_readonly_status_link_follow_latest_decision(client,monkeypatch):
    monkeypatch.setenv('PUBLIC_BASE_URL','https://lamia.example.test')
    messages=[]
    monkeypatch.setattr(services,'send_email',messages.append)
    order,headers=ready_order(client)
    url='/api/v1/orders/'+order['id']+'/content'
    assert client.post(url,headers=headers,json={'source':'AI_TEMPLATE','title':'Brand Anda','text':'Kunjungi toko kami'}).status_code==200
    assert len(messages)==1
    mail=messages[0]
    assert 'sedang ditinjau' in mail['Subject']
    html=mail.get_body(preferencelist=('html',)).get_content()
    link=re.search(r'href="(https://lamia.example.test/status#[^"]+)"',html).group(1)
    access=parse_qs(urlsplit(link).fragment)['access'][0]
    status_headers={'X-Order-Status':access,'Cookie':''}
    status=client.get('/api/v1/order-status',headers=status_headers)
    assert status.status_code==200
    assert status.json()['status']=='NEEDS_REVIEW'
    for private in ('email','phone','company','npwp_hash','address','total'):
        assert private not in status.json()
    admin=operator(client)
    reason='Perbesar teks & revisi <contoh>'
    response=client.post('/api/v1/admin/moderation/'+order['id']+'/decision',headers=admin,json={'decision':'REJECT','reason':reason})
    assert response.status_code==200
    assert len(messages)==2
    rejected=messages[-1]
    assert reason in rejected.get_body(preferencelist=('plain',)).get_content()
    assert '&lt;contoh&gt;' in rejected.get_body(preferencelist=('html',)).get_content()
    latest=client.get('/api/v1/order-status',headers=status_headers).json()
    assert latest['status']=='CONTENT_REJECTED' and latest['review_note']==reason
    # A status link cannot become an editing credential or an admin login.
    assert client.get('/api/v1/orders/'+order['id'],headers={'Authorization':'Bearer '+access,'Cookie':''}).status_code==401
    assert client.get('/api/v1/admin/orders',headers={'Authorization':'Bearer '+access,'Cookie':''}).status_code==401
    assert client.post(url,headers=headers,json={'source':'AI_TEMPLATE','title':'Brand Baru','text':'Teks yang sudah direvisi'}).status_code==200
    response=client.post('/api/v1/admin/moderation/'+order['id']+'/decision',headers=admin,json={'decision':'APPROVE'})
    assert response.status_code==200
    assert len(messages)==4
    assert 'disetujui' in messages[-1]['Subject']
    assert list(messages[-1].iter_attachments())==[]
    assert client.get('/api/v1/order-status',headers=status_headers).json()['status']=='APPROVED'
    assert client.post('/api/v1/admin/moderation/'+order['id']+'/decision',headers=admin,json={'decision':'APPROVE'}).status_code==409
    assert len(messages)==4
    assert client.get('/api/v1/order-status',headers={'X-Order-Status':access+'changed'}).status_code==401


def test_stale_waiting_email_is_cancelled_after_review_is_decided(client,monkeypatch):
    order,headers=ready_order(client)
    def offline(message):raise RuntimeError('SMTP unavailable')
    monkeypatch.setattr(services,'send_email',offline)
    assert client.post('/api/v1/orders/'+order['id']+'/content',headers=headers,json={'source':'AI_TEMPLATE','title':'Brand','text':'Pesan kampanye'}).status_code==200
    sent=[]
    monkeypatch.setattr(services,'send_email',sent.append)
    admin=operator(client)
    assert client.post('/api/v1/admin/moderation/'+order['id']+'/decision',headers=admin,json={'decision':'APPROVE'}).status_code==200
    assert len(sent)==1 and 'disetujui' in sent[0]['Subject']
    process_outbox(app.DB,clock=lambda:app.now()+timedelta(seconds=61))
    assert len(sent)==1
    with app.db() as c:
        assert c.execute("SELECT status FROM email_outbox WHERE kind='MATERIAL_PENDING'").fetchone()['status']=='CANCELLED'
