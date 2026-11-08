from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
import json
import threading

import app
import services
from notifications import process_outbox
from test_workflows import approve


def messages_for(client, monkeypatch):
    messages=[]
    monkeypatch.setattr(services,'send_email',messages.append)
    order,headers,admin=approve(client)
    messages.clear()
    return order,headers,admin,messages


def test_bill_and_payment_email_are_committed_once_with_receipt(client,monkeypatch):
    order,headers,admin,messages=messages_for(client,monkeypatch)
    url=f"/api/v1/orders/{order['id']}/checkout"
    key={**headers,'Idempotency-Key':'email-idempotency-key'}
    assert client.post(url,headers=key).status_code==200
    assert client.post(url,headers=key).status_code==200
    assert len(messages)==1
    bill=messages[0]
    assert bill['To']=='test@example.com'
    assert order['order_no'] in bill['Subject']
    assert 'Batas pembayaran' in bill.get_body(preferencelist=('plain',)).get_content()
    assert not list(bill.iter_attachments())
    with app.db() as c:
        rows=c.execute('SELECT kind,status,payload FROM email_outbox WHERE kind="BILL_CREATED"').fetchall()
        assert len(rows)==1 and rows[0]['status']=='SENT'
        payload=json.loads(rows[0]['payload'])
        assert 'npwp_hash' not in payload['order']
        assert 'token' not in payload['screen']
    response=client.post(f"/api/v1/admin/orders/{order['id']}/confirm-payment",headers=admin,json={'reference':'BANK-NOTIFY-0001','amount':order['quote']['total']})
    assert response.status_code==200
    assert len(messages)==2
    paid=messages[1]
    assert 'Pembayaran terkonfirmasi' in paid['Subject']
    assert 'LUNAS' in paid.get_body(preferencelist=('plain',)).get_content()
    attachments=list(paid.iter_attachments())
    assert len(attachments)==1
    assert attachments[0].get_content_type()=='application/pdf'
    assert attachments[0].get_payload(decode=True).startswith(b'%PDF-')
    assert order['order_no'] in attachments[0].get_filename()
    assert client.post(f"/api/v1/admin/orders/{order['id']}/confirm-payment",headers=admin,json={'reference':'BANK-NOTIFY-0001','amount':order['quote']['total']}).status_code==409
    assert len(messages)==2


def test_smtp_failure_does_not_rollback_bill_and_retries_same_message_id(client,monkeypatch):
    order,headers,admin,messages=messages_for(client,monkeypatch)
    def offline(message):
        messages.append(message)
        raise RuntimeError('SMTP unavailable')
    monkeypatch.setattr(services,'send_email',offline)
    response=client.post(f"/api/v1/orders/{order['id']}/checkout",headers=headers)
    assert response.status_code==200
    assert client.get('/api/v1/orders/'+order['id'],headers=headers).json()['status']=='AWAITING_PAYMENT'
    with app.db() as c:
        row=c.execute('SELECT * FROM email_outbox WHERE kind="BILL_CREATED"').fetchone()
        assert row['status']=='PENDING' and row['attempts']==1
        assert row['last_error']=='RuntimeError'
    original=messages[0]['Message-ID']
    monkeypatch.setattr(services,'send_email',messages.append)
    assert process_outbox(app.DB,clock=lambda:app.now()+timedelta(seconds=61))==1
    assert messages[-1]['Message-ID']==original
    with app.db() as c:
        assert c.execute('SELECT status FROM email_outbox WHERE kind="BILL_CREATED"').fetchone()['status']=='SENT'


def test_expired_bill_is_not_emailed_on_retry(client,monkeypatch):
    order,headers,admin,messages=messages_for(client,monkeypatch)
    def offline(message):
        raise RuntimeError('SMTP unavailable')
    monkeypatch.setattr(services,'send_email',offline)
    checkout=client.post(f"/api/v1/orders/{order['id']}/checkout",headers=headers).json()
    monkeypatch.setattr(services,'send_email',messages.append)
    clock=lambda:app.parse(checkout['expires_at'])+timedelta(seconds=1)
    assert process_outbox(app.DB,clock=clock)==1
    assert messages==[]
    with app.db() as c:
        assert c.execute('SELECT status FROM email_outbox WHERE kind="BILL_CREATED"').fetchone()['status']=='CANCELLED'


def test_payment_survives_email_failure(client,monkeypatch):
    order,headers,admin,messages=messages_for(client,monkeypatch)
    client.post(f"/api/v1/orders/{order['id']}/checkout",headers=headers)
    def offline(message):
        raise RuntimeError('SMTP unavailable')
    monkeypatch.setattr(services,'send_email',offline)
    response=client.post(f"/api/v1/admin/orders/{order['id']}/confirm-payment",headers=admin,json={'reference':'BANK-EMAIL-FAIL','amount':order['quote']['total']})
    assert response.status_code==200
    assert client.get('/api/v1/orders/'+order['id'],headers=headers).json()['status']=='SCHEDULED'
    with app.db() as c:
        assert c.execute("SELECT status FROM email_outbox WHERE kind='PAYMENT_CONFIRMED'").fetchone()['status']=='PENDING'
        assert c.execute('SELECT reference FROM payment_confirmations').fetchone()['reference']=='BANK-EMAIL-FAIL'


def test_two_workers_cannot_send_the_same_notification_concurrently(client,monkeypatch):
    order,headers,admin,messages=messages_for(client,monkeypatch)
    client.post(f"/api/v1/orders/{order['id']}/checkout",headers=headers)
    messages.clear()
    with app.db() as c:
        c.execute("UPDATE email_outbox SET status='PENDING',attempts=0,next_attempt_at=0,sent_at=NULL WHERE kind='BILL_CREATED'")
    started,release=threading.Event(),threading.Event()
    def hold(message):
        messages.append(message)
        started.set()
        assert release.wait(timeout=5)
    monkeypatch.setattr(services,'send_email',hold)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future=pool.submit(process_outbox,app.DB)
        assert started.wait(timeout=5)
        try:
            assert process_outbox(app.DB)==0
        finally:
            release.set()
        assert future.result(timeout=5)==1
    assert len(messages)==1
