"""Revocable admin sessions, CSRF checks, and persistent login throttling."""
import hashlib
import hmac
import json
import secrets
import time
import uuid
from datetime import datetime, timezone
from urllib.parse import urlsplit

from fastapi import HTTPException

COOKIE = 'lamia_admin_session'
LIFETIME = 8 * 3600
IDLE_TIMEOUT = 30 * 60


def init_auth(connection):
    connection.executescript('''
    CREATE TABLE IF NOT EXISTS admin_sessions(
        digest TEXT PRIMARY KEY,username TEXT NOT NULL,version TEXT NOT NULL,
        created_at REAL NOT NULL,last_seen REAL NOT NULL,expires_at REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS admin_login_attempts(
        bucket TEXT PRIMARY KEY,attempts INTEGER NOT NULL,started_at REAL NOT NULL,blocked_until REAL
    );
    ''')


class AdminSessions:
    def __init__(self, db, secret, username, password):
        self.db, self.secret, self.username, self.password = db, secret.encode(), username, password
        self.version = self.digest(json.dumps([username, password]))

    def digest(self, value):
        return hmac.new(self.secret, value.encode(), hashlib.sha256).hexdigest()

    def csrf(self, sid):
        return self.digest('csrf:' + sid)

    def read(self, request):
        sid = request.cookies.get(COOKIE)
        if not sid:
            return None
        timestamp = time.time()
        with self.db() as c:
            row = c.execute('SELECT * FROM admin_sessions WHERE digest=?', (self.digest(sid),)).fetchone()
            if not row:
                return None
            if row['expires_at'] <= timestamp or row['last_seen'] <= timestamp-IDLE_TIMEOUT or not hmac.compare_digest(row['version'], self.version):
                c.execute('DELETE FROM admin_sessions WHERE digest=?', (row['digest'],))
                return None
            if timestamp-row['last_seen'] > 60:
                c.execute('UPDATE admin_sessions SET last_seen=? WHERE digest=?', (timestamp,row['digest']))
        return {'username':row['username'],'csrf_token':self.csrf(sid),'expires_at':datetime.fromtimestamp(row['expires_at'],timezone.utc).isoformat()}

    @staticmethod
    def check_origin(request, public_url=''):
        origin = request.headers.get('origin')
        if not origin:
            return
        configured = urlsplit(public_url)
        expected = f'{configured.scheme}://{configured.netloc}' if configured.scheme in ('http','https') and configured.netloc else str(request.base_url).rstrip('/')
        if origin.rstrip('/') != expected:
            raise HTTPException(403,'Asal permintaan tidak diizinkan')

    def require(self, request, public_url=''):
        session = getattr(request.state,'admin_session',None)
        if not session:
            raise HTTPException(401,'Silakan login admin terlebih dahulu')
        if request.method not in ('GET','HEAD','OPTIONS'):
            self.check_origin(request,public_url)
            supplied = request.headers.get('x-csrf-token','')
            if not hmac.compare_digest(supplied.encode(),session['csrf_token'].encode()):
                raise HTTPException(403,'Sesi permintaan tidak valid. Muat ulang halaman.')
        return session

    def login(self, request, username, password):
        timestamp = time.time()
        bucket = self.digest('login:' + (request.client.host if request.client else 'unknown'))
        failure = None
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            attempt = c.execute('SELECT * FROM admin_login_attempts WHERE bucket=?',(bucket,)).fetchone()
            if attempt and (attempt['blocked_until'] or 0)>timestamp:
                wait = max(1,int(attempt['blocked_until']-timestamp))
                raise HTTPException(429,'Terlalu banyak percobaan login. Coba kembali setelah 15 menit.',headers={'Retry-After':str(wait)})
            valid_user=hmac.compare_digest(username.encode(),self.username.encode())
            valid_password=hmac.compare_digest(password.encode(),self.password.encode())
            if not (valid_user and valid_password):
                count=attempt['attempts']+1 if attempt and timestamp-attempt['started_at']<900 else 1
                started=attempt['started_at'] if attempt and timestamp-attempt['started_at']<900 else timestamp
                blocked=timestamp+900 if count>=5 else None
                c.execute('INSERT OR REPLACE INTO admin_login_attempts VALUES(?,?,?,?)',(bucket,count,started,blocked))
                failure=HTTPException(429 if blocked else 401,'Terlalu banyak percobaan login. Coba kembali setelah 15 menit.' if blocked else 'Nama pengguna atau kata sandi salah',headers={'Retry-After':'900'} if blocked else None)
            else:
                sid=secrets.token_urlsafe(40)
                old=request.cookies.get(COOKIE)
                if old:c.execute('DELETE FROM admin_sessions WHERE digest=?',(self.digest(old),))
                c.execute('DELETE FROM admin_sessions WHERE expires_at<=? OR last_seen<=?',(timestamp,timestamp-IDLE_TIMEOUT))
                c.execute('DELETE FROM admin_login_attempts WHERE bucket=?',(bucket,))
                c.execute('INSERT INTO admin_sessions VALUES(?,?,?,?,?,?)',(self.digest(sid),self.username,self.version,timestamp,timestamp,timestamp+LIFETIME))
                c.execute('INSERT INTO audit VALUES(?,?,?,?,?)',(str(uuid.uuid4()),'ADMIN_LOGIN',self.username,'',datetime.now(timezone.utc).isoformat()))
        # Failed-attempt counters must commit before returning an HTTP error.
        if failure:raise failure
        return sid, {'username':self.username,'csrf_token':self.csrf(sid),'expires_at':datetime.fromtimestamp(timestamp+LIFETIME,timezone.utc).isoformat()}

    def logout(self, request):
        sid=request.cookies.get(COOKIE,'')
        with self.db() as c:
            c.execute('BEGIN IMMEDIATE')
            c.execute('DELETE FROM admin_sessions WHERE digest=?',(self.digest(sid),))
            c.execute('INSERT INTO audit VALUES(?,?,?,?,?)',(str(uuid.uuid4()),'ADMIN_LOGOUT',self.username,'',datetime.now(timezone.utc).isoformat()))
