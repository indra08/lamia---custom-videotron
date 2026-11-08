from datetime import timedelta

import app
from services import TERMS_VERSION


def create(client, **changes):
    screen = client.get('/api/v1/screens').json()[0]
    start = app.now() + timedelta(days=3)
    payload = {'screen_id': screen['id'],
               'company': {'legal_name': 'PT Test', 'npwp': '012345678901234', 'address': 'Semarang'},
               'contact': {'full_name': 'Test PIC', 'email': 'test@example.com', 'phone': '081234567890'},
               'schedule': {'start_at': app.iso(start), 'end_at': app.iso(start + timedelta(days=2))},
               'consent': True, 'terms_version': TERMS_VERSION}
    payload.update(changes)
    response = client.post('/api/v1/orders', json=payload)
    assert response.status_code == 200, response.text
    order = response.json()
    return order, {'Authorization': 'Bearer ' + order['token']}


def operator(client):
    response = client.post('/api/v1/admin/auth/login', json={'username': app.os.getenv('ADMIN_USERNAME','admin'),'password': app.ADMIN_PASSWORD})
    assert response.status_code == 200, response.text
    return {'X-CSRF-Token': response.json()['csrf_token']}


def approve(client):
    order, headers = create(client)
    for channel in ('EMAIL', 'PHONE'):
        sent = client.post('/api/v1/otp/send', headers=headers, json={'order_id': order['id'], 'channel': channel})
        assert sent.status_code == 200, sent.text
        verified = client.post('/api/v1/otp/verify', headers=headers,
                               json={'order_id': order['id'], 'channel': channel, 'code': sent.json()['demo_code']})
        assert verified.status_code == 200
    response = client.post(f"/api/v1/orders/{order['id']}/content", headers=headers,
                           json={'source': 'AI_TEMPLATE', 'title': 'Test campaign', 'text': 'Visit our shop'})
    assert response.json()['status'] == 'NEEDS_REVIEW'
    admin = operator(client)
    response = client.post(f"/api/v1/admin/moderation/{order['id']}/decision", headers=admin, json={'decision': 'APPROVE'})
    assert response.status_code == 200
    return order, headers, admin


def test_booking_persists_consent_and_protects_data(client):
    order, headers = create(client)
    url = '/api/v1/orders/' + order['id']
    assert client.get(url,headers={'Cookie':''}).status_code == 401
    saved = client.get(url, headers=headers).json()
    assert saved['terms_version'] == TERMS_VERSION
    assert saved['company'] == 'PT Test'
    assert 'npwp_hash' not in saved
    assert saved['verified_channels'] == []
    with app.db() as c:
        assert c.execute('SELECT COUNT(*) FROM consents').fetchone()[0] == 1


def test_order_validation(client, monkeypatch):
    assert client.post('/api/v1/orders', json={}).status_code == 422
    monkeypatch.setenv('APP_ENV', 'production')
    screen = client.get('/api/v1/screens').json()[0]
    response = client.get(f"/api/v1/screens/{screen['id']}/quote", params={'start_at': app.iso(app.now()), 'end_at': app.iso(app.now()+timedelta(days=2))})
    assert response.status_code == 422


def test_checkout_commit_idempotency_and_conflict(client):
    order, headers, admin = approve(client)
    url = f"/api/v1/orders/{order['id']}/checkout"
    checkout_headers = {**headers, 'Idempotency-Key': 'unique-checkout'}
    first = client.post(url, headers=checkout_headers)
    assert first.status_code == 200, first.text
    assert client.get('/api/v1/orders/'+order['id'], headers=headers).json()['status'] == 'AWAITING_PAYMENT'
    second = client.post(url, headers=checkout_headers)
    assert second.json()['id'] == first.json()['id']
    # Draft creation may not overbook an active checkout hold.
    existing = client.get('/api/v1/orders/'+order['id'], headers=headers).json()
    screen = client.get('/api/v1/screens').json()[0]
    quote = client.get(f"/api/v1/screens/{screen['id']}/quote", params={'start_at': existing['start_at'], 'end_at': existing['end_at']}).json()
    assert quote['available'] is False
    confirmed = client.post(f"/api/v1/admin/orders/{order['id']}/confirm-payment", headers=admin,
                            json={'reference': 'BANK-12345', 'amount': existing['total']})
    assert confirmed.status_code == 200, confirmed.text
    assert client.get('/api/v1/orders/'+order['id'], headers=headers).json()['status'] == 'SCHEDULED'
    assert client.get(f"/api/v1/orders/{order['id']}/invoice", headers=headers).headers['content-type'] == 'application/pdf'


def test_scheduler_boundaries_player_and_takedown(client, monkeypatch):
    order, headers, admin = approve(client)
    client.post(f"/api/v1/orders/{order['id']}/checkout", headers=headers)
    client.post(f"/api/v1/demo/payments/{order['id']}/settle", headers=headers)
    stored = client.get('/api/v1/orders/'+order['id'], headers=headers).json()
    start, end = app.parse(stored['start_at']), app.parse(stored['end_at'])
    device = {'x-device-token': app.DEVICE_TOKEN}
    monkeypatch.setattr(app, 'now', lambda: start)
    app.scheduler_tick()
    assert client.get('/api/v1/orders/'+order['id'], headers=headers).json()['status'] == 'LIVE'
    manifest = client.get('/api/v1/player/manifest', params={'screen_id': stored['screen_id']}, headers=device).json()
    assert manifest['items'][0]['order_id'] == order['id']
    assert manifest['lease_seconds'] == 30
    assert client.get('/api/v1/player/manifest', params={'screen_id': stored['screen_id']}).status_code == 401
    monkeypatch.setattr(app, 'now', lambda: start+timedelta(seconds=30))
    log = {'id': 'segment-1', 'order_id': order['id'], 'screen_id': stored['screen_id'], 'started_at': app.iso(start), 'ended_at': app.iso(start+timedelta(seconds=20))}
    for _ in range(2):
        assert client.post('/api/v1/player/playback-logs', headers=device, json={'logs':[log]}).status_code == 200
    assert len(client.get('/api/v1/admin/playback', headers=admin).json()) == 1
    app.scheduler_tick()
    history = client.get('/api/v1/orders/'+order['id'], headers=headers).json()['history']
    assert sum(event['to_status'] == 'LIVE' for event in history) == 1
    monkeypatch.setattr(app, 'now', lambda: end)
    app.scheduler_tick()
    assert client.get('/api/v1/orders/'+order['id'], headers=headers).json()['status'] == 'COMPLETED'
    assert client.get('/api/v1/player/manifest', params={'screen_id': stored['screen_id']}, headers=device).json()['items'] == []


def test_takedown_removes_manifest(client, monkeypatch):
    order, headers, admin = approve(client)
    client.post(f"/api/v1/orders/{order['id']}/checkout", headers=headers)
    client.post(f"/api/v1/demo/payments/{order['id']}/settle", headers=headers)
    stored = client.get('/api/v1/orders/'+order['id'], headers=headers).json()
    monkeypatch.setattr(app, 'now', lambda: app.parse(stored['start_at']))
    app.scheduler_tick()
    assert client.post(f"/api/v1/admin/orders/{order['id']}/takedown", headers=admin, json={'reason':'Campaign withdrawn'}).status_code == 200
    manifest = client.get('/api/v1/player/manifest', params={'screen_id':stored['screen_id']}, headers={'x-device-token':app.DEVICE_TOKEN})
    assert manifest.json()['items'] == []


def test_expired_payment_cannot_be_confirmed(client, monkeypatch):
    order, headers, admin = approve(client)
    checkout = client.post(f"/api/v1/orders/{order['id']}/checkout", headers=headers).json()
    monkeypatch.setattr(app, 'now', lambda: app.parse(checkout['expires_at'])+timedelta(seconds=1))
    app.scheduler_tick()
    response = client.post(f"/api/v1/admin/orders/{order['id']}/confirm-payment", headers=admin,
                           json={'reference':'BANK-EXPIRED', 'amount':checkout['amount']})
    assert response.status_code == 409
    stored = client.get('/api/v1/orders/'+order['id'], headers=headers).json()
    assert stored['status'] == 'EXPIRED'
    assert stored['payment']['status'] == 'EXPIRED'


def test_demo_endpoints_disabled_in_production(client, monkeypatch):
    order, headers = create(client)
    monkeypatch.setenv('APP_ENV', 'production')
    assert client.get('/api/v1/config').json()['demo_payments'] is False
    assert client.post(f"/api/v1/demo/payments/{order['id']}/settle", headers=headers).status_code == 404


def test_blackout_blocks_quote_and_can_be_removed(client):
    admin = operator(client)
    screen = client.get('/api/v1/screens').json()[0]
    start = app.now()+timedelta(days=3)
    end = start+timedelta(days=2)
    payload = {'screen_id':screen['id'],'start_at':app.iso(start),'end_at':app.iso(end),'reason':'Maintenance'}
    assert client.post('/api/v1/admin/blackouts', json=payload,headers={'Cookie':''}).status_code == 401
    created = client.post('/api/v1/admin/blackouts', json=payload, headers=admin)
    assert created.status_code == 200
    quote = client.get(f"/api/v1/screens/{screen['id']}/quote", params={'start_at':app.iso(start),'end_at':app.iso(end)})
    assert quote.json()['available'] is False
    assert client.delete('/api/v1/admin/blackouts/'+created.json()['id'], headers=admin).status_code == 200


def test_scoped_device_tokens_and_revocation(client, monkeypatch):
    admin = operator(client)
    screens = client.get('/api/v1/screens').json()
    enrolled = client.post('/api/v1/admin/devices', headers=admin, json={'screen_id':screens[0]['id'], 'name':'Lobby display'})
    assert enrolled.status_code == 200
    device = enrolled.json()
    headers = {'x-device-token':device['token']}
    # Production accepts enrolled credentials and refuses the legacy shared token.
    monkeypatch.setenv('APP_ENV', 'production')
    assert client.get('/api/v1/player/manifest', params={'screen_id':screens[0]['id']}, headers=headers).status_code == 200
    assert client.get('/api/v1/player/manifest', params={'screen_id':screens[1]['id']}, headers=headers).status_code == 403
    assert client.post('/api/v1/player/heartbeat', json={'screen_id':screens[1]['id']}, headers=headers).status_code == 403
    assert client.get('/api/v1/player/manifest', params={'screen_id':screens[0]['id']}, headers={'x-device-token':app.DEVICE_TOKEN}).status_code == 401
    devices = client.get('/api/v1/admin/devices', headers=admin).json()
    assert 'token' not in devices[0] and 'token_digest' not in devices[0]
    assert client.delete('/api/v1/admin/devices/'+device['id'], headers=admin).status_code == 200
    assert client.get('/api/v1/player/manifest', params={'screen_id':screens[0]['id']}, headers=headers).status_code == 401


def test_upload_decodes_images_and_requires_correct_aspect(client):
    import io
    from PIL import Image
    order, headers, admin = approve(client)
    # APPROVED permits a replacement, which must invalidate the previous approval.
    url = f"/api/v1/orders/{order['id']}/upload"
    corrupt = client.post(url, headers=headers, files={'file':('fake.png', b'\x89PNG\r\n\x1a\nnot-an-image', 'image/png')})
    assert corrupt.status_code == 422
    portrait = io.BytesIO()
    Image.new('RGB', (360, 640)).save(portrait, format='PNG')
    assert client.post(url, headers=headers, files={'file':('portrait.png', portrait.getvalue(), 'image/png')}).status_code == 422
    valid = io.BytesIO()
    Image.new('RGB', (640, 360), 'green').save(valid, format='PNG')
    uploaded = client.post(url, headers=headers, files={'file':('ad.png', valid.getvalue(), 'image/png')})
    assert uploaded.status_code == 200
    stored = client.get('/api/v1/orders/'+order['id'], headers=headers).json()
    assert stored['status'] == 'NEEDS_REVIEW'
    assert stored['approved_version'] is None
    preview = client.get(f"/api/v1/orders/{order['id']}/creative", headers=admin)
    assert preview.status_code == 200
    assert preview.headers['content-type'] == 'image/png'
    assert client.get(f"/api/v1/orders/{order['id']}/creative",headers={'Cookie':''}).status_code == 401


def test_failed_delivery_does_not_leave_unusable_code(client, monkeypatch):
    order, headers = create(client)
    def unavailable(*args):
        raise RuntimeError('Provider unavailable')
    monkeypatch.setattr(app, 'deliver_otp', unavailable)
    response = client.post('/api/v1/otp/send', headers=headers, json={'order_id':order['id'],'channel':'EMAIL'})
    assert response.status_code == 503
    with app.db() as c:
        assert c.execute('SELECT COUNT(*) FROM otp WHERE order_id=?',(order['id'],)).fetchone()[0] == 0


def test_npwp_validation_reports_digit_count_and_accepts_formatting(client):
    from pydantic import ValidationError
    import pytest
    with pytest.raises(ValidationError) as invalid:
        app.BusinessInput(legal_name='PT Test', npwp='23402348992304', address='Semarang')
    assert 'saat ini 14 digit' in str(invalid.value)
    with pytest.raises(ValidationError):
        app.BusinessInput(legal_name='PT Test', npwp='abc012345678901234', address='Semarang')
    order, headers = create(client, company={'legal_name':'PT Test', 'npwp':'01.234.567.8-901.234', 'address':'Semarang'})
    saved = client.get('/api/v1/orders/'+order['id'], headers=headers).json()
    assert saved['npwp_last4'] == '1234'
    response = client.post('/api/v1/orders', json={
        'screen_id': saved['screen_id'],
        'company': {'legal_name': 'PT Test', 'npwp': '23402348992304', 'address': 'Semarang'},
        'contact': {'full_name': 'Test PIC', 'email': 'test@example.com', 'phone': '081234567890'},
        'schedule': {'start_at': saved['start_at'], 'end_at': saved['end_at']},
        'consent': True, 'terms_version': TERMS_VERSION,
    })
    assert response.status_code == 422
    issue = response.json()['detail'][0]
    assert issue['loc'] == ['body', 'company', 'npwp']
    assert 'saat ini 14 digit' in issue['msg']
    with app.db() as c:
        assert c.execute('SELECT COUNT(*) FROM orders').fetchone()[0] == 1


def test_invoice_access_filename_and_paid_takedown(client):
    import re
    order, headers, admin = approve(client)
    url = f"/api/v1/orders/{order['id']}/invoice"
    assert client.get(url,headers={'Cookie':''}).status_code == 401
    assert client.get(url, headers=headers).status_code == 409
    other, other_headers = create(client)
    assert client.get(url, headers=other_headers).status_code == 403
    client.post(f"/api/v1/orders/{order['id']}/checkout", headers=headers)
    confirmed = client.post(f"/api/v1/admin/orders/{order['id']}/confirm-payment", headers=admin,
                            json={'reference':'BANK-INVOICE-123', 'amount':order['quote']['total']})
    assert confirmed.status_code == 200
    response = client.get(url, headers=headers)
    assert response.status_code == 200
    assert response.content.startswith(b'%PDF-')
    assert response.headers['cache-control'] == 'no-store'
    assert f"invoice-LAMIA-{order['order_no']}.pdf" in response.headers['content-disposition']
    assert len(re.findall(rb'/Type\s*/Page\b',response.content)) == 1
    client.post(f"/api/v1/admin/orders/{order['id']}/takedown", headers=admin, json={'reason':'Requested by advertiser'})
    assert client.get(url, headers=headers).status_code == 200


def test_development_current_time_quote_checkout_and_payment(client, monkeypatch):
    timestamp = app.now().replace(second=30, microsecond=0)
    monkeypatch.setattr(app, 'now', lambda: timestamp)
    start = timestamp.replace(second=0)
    end = start + timedelta(minutes=30)
    screen = client.get('/api/v1/screens').json()[0]
    policy = client.get('/api/v1/config').json()['booking_policy']
    assert policy['immediate_start'] is True
    assert policy['minimum_duration_minutes'] == 24
    quote = client.get(f"/api/v1/screens/{screen['id']}/quote", params={'start_at':app.iso(start),'end_at':app.iso(end)})
    assert quote.status_code == 200
    order, headers = create(client, schedule={'start_at':app.iso(start),'end_at':app.iso(end)})
    for channel in ('EMAIL', 'PHONE'):
        sent=client.post('/api/v1/otp/send',headers=headers,json={'order_id':order['id'],'channel':channel}).json()
        assert client.post('/api/v1/otp/verify',headers=headers,json={'order_id':order['id'],'channel':channel,'code':sent['demo_code']}).status_code == 200
    client.post(f"/api/v1/orders/{order['id']}/content",headers=headers,json={'source':'AI_TEMPLATE','title':'Current time','text':'Development campaign'})
    admin=operator(client)
    client.post(f"/api/v1/admin/moderation/{order['id']}/decision",headers=admin,json={'decision':'APPROVE'})
    monkeypatch.setattr(app, 'now', lambda: timestamp+timedelta(minutes=6))
    assert client.post(f"/api/v1/orders/{order['id']}/checkout",headers=headers).status_code == 200
    paid=client.post(f"/api/v1/admin/orders/{order['id']}/confirm-payment",headers=admin,json={'reference':'DEV-NOW-BANK','amount':order['quote']['total']})
    assert paid.status_code == 200, paid.text
    assert paid.json()['status'] == 'LIVE'
    monkeypatch.setattr(app, 'now', lambda: end)
    app.scheduler_tick()
    assert client.get('/api/v1/orders/'+order['id'],headers=headers).json()['status'] == 'COMPLETED'


def test_production_booking_policy_cannot_use_development_schedule(client, monkeypatch):
    monkeypatch.setenv('APP_ENV', 'production')
    policy=client.get('/api/v1/config').json()['booking_policy']
    assert policy['immediate_start'] is False
    assert policy['minimum_lead_minutes'] == 1440
    assert policy['minimum_duration_minutes'] == 1440
    timestamp=app.now()
    for start,end in [(timestamp,timestamp+timedelta(days=2)),(timestamp+timedelta(days=2),timestamp+timedelta(days=2,minutes=30))]:
        screen=client.get('/api/v1/screens').json()[0]
        assert client.get(f"/api/v1/screens/{screen['id']}/quote",params={'start_at':app.iso(start),'end_at':app.iso(end)}).status_code == 422
