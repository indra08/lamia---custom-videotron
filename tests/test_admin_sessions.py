import time
from fastapi.testclient import TestClient

import app
import admin_sessions
from test_workflows import create, operator


def credentials():
    return {'username':app.os.getenv('ADMIN_USERNAME','admin'),'password':app.ADMIN_PASSWORD}


def test_operations_require_real_login_not_customer_or_legacy_admin_token(client):
    order,headers=create(client)
    legacy={'Authorization':'Bearer '+app.serializer.dumps({'role':'admin'})}
    for path in ('orders','screens','summary','schedule','audit','devices','playback'):
        url='/api/v1/admin/'+path
        assert client.get(url).status_code==401
        assert client.get(url,headers=headers).status_code==401
        assert client.get(url,headers=legacy).status_code==401
    assert client.get('/api/v1/orders/'+order['id'],headers=legacy).status_code==401
    for path in ('/admin','/schedule','/player','/static/player.html'):
        response=client.get(path,follow_redirects=False)
        assert response.status_code==303
        assert response.headers['location'].startswith('/login?next=')


def test_login_cookie_and_csrf_protect_operations_and_logout_revokes_session(client):
    response=client.post('/api/v1/admin/auth/login',json=credentials())
    assert response.status_code==200
    assert 'token' not in response.json()
    assert 'HttpOnly' in response.headers['set-cookie']
    assert 'SameSite=strict' in response.headers['set-cookie']
    csrf=response.json()['csrf_token']
    original=client.cookies.get(admin_sessions.COOKIE)
    assert client.get('/api/v1/admin/orders').status_code==200
    assert client.get('/api/v1/admin/auth/session').json()['username']==credentials()['username']
    assert client.post('/api/v1/admin/devices',json={}).status_code==403
    assert client.post('/api/v1/admin/devices',headers={'X-CSRF-Token':'incorrect'},json={}).status_code==403
    assert client.post('/api/v1/admin/auth/logout',headers={'X-CSRF-Token':csrf,'Origin':'https://evil.example'}).status_code==403
    assert client.post('/api/v1/admin/auth/logout',headers={'X-CSRF-Token':csrf}).status_code==200
    assert client.get('/api/v1/admin/orders').status_code==401
    assert client.get('/api/v1/admin/orders',headers={'Cookie':admin_sessions.COOKIE+'='+original}).status_code==401


def test_login_throttle_is_persisted(client):
    for index in range(5):
        response=client.post('/api/v1/admin/auth/login',json={**credentials(),'password':'wrong-password'})
        assert response.status_code==(429 if index==4 else 401)
    blocked=client.post('/api/v1/admin/auth/login',json=credentials())
    assert blocked.status_code==429
    assert int(blocked.headers['retry-after'])>0
    with app.db() as c:
        row=c.execute('SELECT attempts,blocked_until FROM admin_login_attempts').fetchone()
        assert row['attempts']==5 and row['blocked_until']>time.time()


def test_login_rejects_cross_origin_and_production_uses_secure_cookie(client,monkeypatch):
    monkeypatch.setenv('PUBLIC_BASE_URL','')
    assert client.post('/api/v1/admin/auth/login',headers={'Origin':'https://evil.example'},json=credentials()).status_code==403
    monkeypatch.setenv('APP_ENV','production')
    secure=TestClient(app.app,base_url='https://testserver')
    response=secure.post('/api/v1/admin/auth/login',json=credentials())
    assert response.status_code==200
    assert 'Secure' in response.headers['set-cookie']
    assert secure.get('/api/v1/admin/orders').status_code==200
    secure.close()


def test_idle_expiry_and_password_change_revoke_sessions(client,monkeypatch):
    operator(client)
    timestamp=time.time()
    monkeypatch.setattr(admin_sessions.time,'time',lambda:timestamp+admin_sessions.IDLE_TIMEOUT+1)
    assert client.get('/api/v1/admin/orders').status_code==401
    response=client.post('/api/v1/admin/auth/login',json=credentials())
    assert response.status_code==200
    monkeypatch.setattr(app,'ADMIN_PASSWORD','a-new-admin-password')
    assert client.get('/api/v1/admin/orders').status_code==401


def test_session_rotation_revokes_old_cookie_and_storage_contains_only_digests(client):
    operator(client)
    old=client.cookies.get(admin_sessions.COOKIE)
    operator(client)
    current=client.cookies.get(admin_sessions.COOKIE)
    assert current!=old
    assert client.get('/api/v1/admin/orders',headers={'Cookie':admin_sessions.COOKIE+'='+old}).status_code==401
    with app.db() as c:
        row=c.execute('SELECT * FROM admin_sessions').fetchone()
        assert len(row['digest'])==64 and len(row['version'])==64
        assert row['digest']!=current
        assert app.ADMIN_PASSWORD not in str(dict(row))
