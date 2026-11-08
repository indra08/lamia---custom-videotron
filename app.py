"""Videotron self-service local MVP. External integrations are deliberately simulated."""
import os, sqlite3, uuid, json, hmac, hashlib, secrets, calendar, re, io, asyncio, logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from urllib.parse import urlsplit, quote as url_quote
from zoneinfo import ZoneInfo
from contextlib import contextmanager, asynccontextmanager
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / '.env')
from services import deliver_otp, public_config, TERMS_VERSION, booking_policy
from admin_sessions import AdminSessions, init_auth, COOKIE as ADMIN_COOKIE, LIFETIME as ADMIN_LIFETIME
from media import validate_media
from notifications import init_outbox, enqueue_order_email, process_outbox
from fastapi import FastAPI, Request, HTTPException, UploadFile, File, Header, BackgroundTasks
from pydantic import BaseModel, ConfigDict, Field, field_validator
from fastapi.responses import FileResponse, Response, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from itsdangerous import URLSafeTimedSerializer, BadSignature

ROOT=Path(__file__).parent
DB=Path(os.getenv('DB_PATH',str(ROOT/'videotron.db')))
UPLOAD=ROOT/'uploads'; UPLOAD.mkdir(exist_ok=True)
TZ=ZoneInfo('Asia/Jakarta')
SECRET=os.getenv('APP_SECRET','dev-only-change-this-secret')
ADMIN_PASSWORD=os.getenv('ADMIN_PASSWORD','admin123')
DEVICE_TOKEN=os.getenv('DEVICE_TOKEN','demo-device-token')
serializer=URLSafeTimedSerializer(SECRET)
status_serializer=URLSafeTimedSerializer(SECRET,salt='lamia-readonly-order-status')
@asynccontextmanager
async def lifespan(app):
    if os.getenv('APP_ENV', 'development') == 'production':
        if SECRET == 'dev-only-change-this-secret' or len(SECRET)<32 or SECRET.startswith('replace-') or ADMIN_PASSWORD == 'admin123' or len(ADMIN_PASSWORD)<12 or ADMIN_PASSWORD.startswith('replace-'):
            raise RuntimeError('Set a unique APP_SECRET (32+ characters) and ADMIN_PASSWORD (12+ characters) before production startup')
    async def run_scheduler():
        while True:
            try:
                await asyncio.to_thread(scheduler_tick)
            except Exception:
                logging.exception('Scheduler tick failed')
            await asyncio.sleep(5)
    async def run_notifications():
        while True:
            try:
                await asyncio.to_thread(process_outbox, DB, clock=now)
            except Exception:
                logging.exception('Notification worker failed')
            await asyncio.sleep(5)
    embedded = os.getenv('DISABLE_EMBEDDED_SCHEDULER','false').lower() != 'true'
    tasks = [asyncio.create_task(run_scheduler()),asyncio.create_task(run_notifications())] if embedded else []
    try:
        yield
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

app=FastAPI(title='LAMIA Videotron API',version='0.2.0',lifespan=lifespan)
app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')
app.mount('/icon',StaticFiles(directory=ROOT/'icon'),name='icon')

@contextmanager
def db():
    c=sqlite3.connect(DB,timeout=10,isolation_level=None)
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    try:
        yield c
        if c.in_transaction:
            c.commit()
    except BaseException:
        if c.in_transaction:
            c.rollback()
        raise
    finally:
        c.close()

def now(): return datetime.now(timezone.utc)
def iso(d): return d.isoformat()
def parse(s):
    try:
        d=datetime.fromisoformat(s.replace('Z','+00:00'))
        if d.tzinfo is None: raise ValueError()
        return d.astimezone(timezone.utc)
    except Exception: raise HTTPException(422,'Tanggal harus ISO 8601 dengan zona waktu')
def validate_booking_schedule(start, end):
    policy = booking_policy()
    timestamp = now()
    earliest = timestamp + timedelta(minutes=policy['minimum_lead_minutes']) - timedelta(seconds=policy['start_grace_seconds'])
    if start < earliest:
        message = 'Mode development: mulai tayang harus waktu saat ini (toleransi 5 menit)' if policy['immediate_start'] else 'Mulai tayang minimal 24 jam dari sekarang'
        raise HTTPException(422, message)
    duration = policy['minimum_duration_minutes']
    if end - start < timedelta(minutes=duration):
        raise HTTPException(422, f'Durasi minimal {duration} menit' if duration < 60 else f'Durasi minimal {duration // 60} jam')
    if end <= timestamp:
        raise HTTPException(422, 'Selesai tayang harus setelah waktu sekarang')


def booking_window_open(order):
    return parse(order['end_at']) > now() and (booking_policy()['immediate_start'] or parse(order['start_at']) > now())


def uid(): return str(uuid.uuid4())
def money(x): return int(Decimal(x).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
def row(r): return dict(r) if r else None
def get_order(c,id):
    r=c.execute('SELECT * FROM orders WHERE id=?',(id,)).fetchone()
    if not r: raise HTTPException(404,'Pesanan tidak ditemukan')
    return row(r)
def session_auth():
    return AdminSessions(db,SECRET,os.getenv('ADMIN_USERNAME','admin'),ADMIN_PASSWORD)


def auth(request):
    token=request.headers.get('authorization','').removeprefix('Bearer ').strip()
    try:
        payload=serializer.loads(token,max_age=86400)
        if not isinstance(payload,dict) or payload.get('role') or not payload.get('order'):
            raise BadSignature('Only customer order credentials are accepted')
        return payload
    except BadSignature:
        raise HTTPException(401,'Sesi pesanan tidak valid')


def owner(request,o):
    if request.headers.get('authorization'):
        if auth(request).get('order')!=o['id']:raise HTTPException(403,'Tidak memiliki akses')
    else:
        admin(request)


def admin(request):
    return session_auth().require(request,os.getenv('PUBLIC_BASE_URL',''))

def player(request):
    token = request.headers.get('x-device-token', '')
    if not token:
        raise HTTPException(401, 'Token perangkat wajib diisi')
    digest = hmac.new(SECRET.encode(), token.encode(), hashlib.sha256).hexdigest()
    with db() as c:
        device = c.execute('SELECT id,screen_id FROM devices WHERE token_digest=? AND revoked_at IS NULL', (digest,)).fetchone()
    if device:
        request.state.device_screen = device['screen_id']
        return
    if os.getenv('APP_ENV', 'development') != 'production' and hmac.compare_digest(token, DEVICE_TOKEN):
        request.state.device_screen = None
        return
    raise HTTPException(401, 'Token perangkat salah atau sudah dicabut')

def device_scope(request, screen_id):
    scope = getattr(request.state, 'device_screen', None)
    if scope is not None and scope != screen_id:
        raise HTTPException(403, 'Token tidak diizinkan untuk layar ini')
def audit(c,action,entity,detail=''):
    c.execute('INSERT INTO audit(id,action,entity,detail,created_at) VALUES(?,?,?,?,?)',(uid(),action,entity,detail,iso(now())))
def transition(c,id,to,allowed):
    o=get_order(c,id)
    if o['status'] not in allowed: raise HTTPException(409,f"Transisi {o['status']} → {to} tidak diizinkan")
    c.execute('UPDATE orders SET status=?,updated_at=? WHERE id=?',(to,iso(now()),id))
    c.execute('INSERT INTO history(order_id,from_status,to_status,created_at) VALUES(?,?,?,?)',(id,o['status'],to,iso(now())))

def init():
    DB.parent.mkdir(parents=True,exist_ok=True)
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS screens(id TEXT PRIMARY KEY,code TEXT UNIQUE,name TEXT,location TEXT,width INTEGER,height INTEGER,monthly_price INTEGER,tax_rate TEXT,token TEXT UNIQUE,status TEXT);
        CREATE TABLE IF NOT EXISTS orders(id TEXT PRIMARY KEY,order_no TEXT UNIQUE,screen_id TEXT REFERENCES screens(id),company TEXT,npwp_hash TEXT,npwp_last4 TEXT,pic TEXT,email TEXT,phone TEXT,address TEXT,start_at TEXT,end_at TEXT,status TEXT,content_source TEXT,content_title TEXT,content_text TEXT,content_file TEXT,content_mime TEXT,content_version INTEGER DEFAULT 0,approved_version INTEGER,moderation TEXT,subtotal INTEGER,tax INTEGER,total INTEGER,hold_expires TEXT,paid_at TEXT,created_at TEXT,updated_at TEXT,consent_at TEXT);
        CREATE TABLE IF NOT EXISTS price_lines(order_id TEXT,date TEXT,hours TEXT,amount INTEGER,PRIMARY KEY(order_id,date));
        CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY AUTOINCREMENT,order_id TEXT,from_status TEXT,to_status TEXT,created_at TEXT);
        CREATE TABLE IF NOT EXISTS otp(order_id TEXT,channel TEXT,code_hash TEXT,expires_at TEXT,attempts INTEGER DEFAULT 0,verified INTEGER DEFAULT 0,PRIMARY KEY(order_id,channel));
        CREATE TABLE IF NOT EXISTS payments(id TEXT PRIMARY KEY,order_id TEXT,idempotency_key TEXT UNIQUE,status TEXT,amount INTEGER,created_at TEXT);
        CREATE TABLE IF NOT EXISTS playback(id TEXT PRIMARY KEY,order_id TEXT,screen_id TEXT,started_at TEXT,ended_at TEXT,status TEXT);
        CREATE TABLE IF NOT EXISTS heartbeats(screen_id TEXT PRIMARY KEY,reported_at TEXT,detail TEXT);
        CREATE TABLE IF NOT EXISTS audit(id TEXT PRIMARY KEY,action TEXT,entity TEXT,detail TEXT,created_at TEXT);
        CREATE TABLE IF NOT EXISTS blackouts(id TEXT PRIMARY KEY,screen_id TEXT,start_at TEXT,end_at TEXT,reason TEXT);
        ''')
        c.executescript("""
        CREATE TABLE IF NOT EXISTS consents(order_id TEXT PRIMARY KEY REFERENCES orders(id),version TEXT NOT NULL,accepted_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS payment_confirmations(order_id TEXT PRIMARY KEY REFERENCES orders(id),reference TEXT UNIQUE NOT NULL,confirmed_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS devices(id TEXT PRIMARY KEY,screen_id TEXT NOT NULL REFERENCES screens(id),name TEXT NOT NULL,token_digest TEXT UNIQUE NOT NULL,created_at TEXT NOT NULL,revoked_at TEXT);
        CREATE TABLE IF NOT EXISTS scheduler_state(id INTEGER PRIMARY KEY CHECK(id=1),last_tick TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS orders_screen_schedule ON orders(screen_id,start_at,end_at,status);
        """)
        init_auth(c)
        init_outbox(c)
        if not c.execute('SELECT 1 FROM screens').fetchone():
            for code,name,loc,price in [('VTR-001','Videotron Tengah Kota','Semarang, Jawa Tengah',100000000),('VTR-002','Videotron Kota Lama','Semarang, Jawa Tengah',75000000),('VTR-003','Videotron Alun-Alun','Ungaran, Jawa Tengah',45000000)]:
                c.execute('INSERT INTO screens VALUES(?,?,?,?,?,?,?,?,?,?)',(uid(),code,name,loc,1920,1080,price,'0.11',secrets.token_urlsafe(16),'ACTIVE'))
        c.execute('UPDATE screens SET name=? WHERE code=? AND name=?', ('Videotron Tengah Kota', 'VTR-001', 'Videotron Simpang Lima'))
init()

def quote(start,end,monthly,taxrate):
    s=parse(start).astimezone(TZ); e=parse(end).astimezone(TZ)
    if e<=s: raise HTTPException(422,'Akhir harus setelah awal')
    lines=[]; cursor=s; subtotal=0
    while cursor<e:
        nextday=(cursor+timedelta(days=1)).replace(hour=0,minute=0,second=0,microsecond=0)
        until=min(nextday,e)
        hours=Decimal(str((until-cursor).total_seconds()))/Decimal(3600)
        days=calendar.monthrange(cursor.year,cursor.month)[1]
        amount=money(Decimal(monthly)*hours/(Decimal(days)*24))
        lines.append({'date':cursor.date().isoformat(),'hours':str(hours.normalize()),'amount':amount})
        subtotal+=amount;cursor=until
    tax=money(Decimal(subtotal)*Decimal(str(taxrate)))
    return {'lines':lines,'subtotal':subtotal,'tax':tax,'total':subtotal+tax,'hours':str((Decimal(str((e-s).total_seconds()))/3600).normalize())}

def overlaps(c,screen,start,end,exclude=None):
    t=iso(now())
    q='''SELECT 1 FROM orders WHERE screen_id=? AND start_at<? AND end_at>? AND status IN ('AWAITING_PAYMENT','PAID','SCHEDULED','LIVE') AND (status!='AWAITING_PAYMENT' OR hold_expires>?)'''
    args=[screen,end,start,t]
    if exclude: q+=' AND id!=?';args.append(exclude)
    return bool(c.execute(q+' LIMIT 1',args).fetchone() or c.execute('SELECT 1 FROM blackouts WHERE screen_id=? AND start_at<? AND end_at>? LIMIT 1',(screen,end,start)).fetchone())

def expire(c):
    for r in c.execute("SELECT id FROM orders WHERE status='AWAITING_PAYMENT' AND hold_expires<=?",(iso(now()),)).fetchall(): transition(c,r['id'],'EXPIRED',['AWAITING_PAYMENT'])

def screen_info(r):
    d=row(r);return {k:d[k] for k in ('id','code','name','location','width','height','monthly_price','tax_rate','token','status')}

@app.middleware('http')
async def operations_access(request:Request,call_next):
    manager=session_auth()
    request.state.admin_session=manager.read(request)
    path=request.url.path
    if path.startswith('/api/v1/admin/') and path!='/api/v1/admin/auth/login':
        try:manager.require(request,os.getenv('PUBLIC_BASE_URL',''))
        except HTTPException as error:
            return JSONResponse({'detail':error.detail},status_code=error.status_code,headers={**(error.headers or {}),'Cache-Control':'no-store'})
    if path in ('/admin','/schedule','/player','/static/player.html') and not request.state.admin_session:
        destination={'/admin':'admin','/schedule':'schedule','/player':'player','/static/player.html':'player'}[path]
        return RedirectResponse('/login?next='+destination,status_code=303,headers={'Cache-Control':'no-store'})
    response=await call_next(request)
    if path.startswith('/api/v1/admin/') or path in ('/admin','/schedule','/login','/player','/static/player.html'):
        response.headers['Cache-Control']='no-store'
        response.headers['Vary']='Cookie'
    return response


@app.get('/favicon.ico', include_in_schema=False)
def favicon():
    return FileResponse(ROOT/'icon'/'logo.ico', media_type='image/vnd.microsoft.icon')

@app.get('/')
def home(): return FileResponse(ROOT/'static'/'index.html')
@app.get('/admin')
@app.get('/schedule')
@app.get('/login')
def admin_page(): return FileResponse(ROOT/'static'/'index.html')
@app.get('/player')
def player_page(): return FileResponse(ROOT/'static'/'player.html')
@app.get('/api/v1/screens')
def screens():
    with db() as c:return [screen_info(r) for r in c.execute('SELECT * FROM screens WHERE status="ACTIVE"')]
@app.get('/api/v1/screens/by-token/{token}')
def by_token(token:str):
    with db() as c:
        r=c.execute('SELECT * FROM screens WHERE token=?',(token,)).fetchone()
        if not r:raise HTTPException(404,'QR tidak dikenal')
        return screen_info(r)
@app.get('/api/v1/screens/{screen_id}/availability')
def availability(screen_id:str,from_at:str,to_at:str):
    start,end=iso(parse(from_at)),iso(parse(to_at))
    if parse(end) <= parse(start):raise HTTPException(422,'Rentang waktu tidak valid')
    with db() as c:
        expire(c)
        return {'available':not overlaps(c,screen_id,start,end)}
class BusinessInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    legal_name: str = Field(min_length=1, max_length=200)
    npwp: str = Field(max_length=30)
    address: str = Field(min_length=1, max_length=500)

    @field_validator('npwp')
    @classmethod
    def validate_npwp(cls, value):
        if not re.fullmatch(r'[0-9 .-]+', value):
            raise ValueError('NPWP hanya boleh berisi angka, titik, spasi, atau tanda hubung')
        digits = re.sub(r'\D', '', value)
        if len(digits) not in (15, 16):
            raise ValueError(f'NPWP harus 15 atau 16 digit; saat ini {len(digits)} digit')
        return digits


class ContactInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    full_name: str = Field(min_length=1, max_length=150)
    email: str = Field(min_length=3, max_length=254)
    phone: str = Field(min_length=10, max_length=25)


class ScheduleInput(BaseModel):
    start_at: str
    end_at: str


class OrderInput(BaseModel):
    screen_id: str
    company: BusinessInput
    contact: ContactInput
    schedule: ScheduleInput
    consent: bool
    terms_version: str


@app.post('/api/v1/orders')
async def create_order(payload: OrderInput):
    b=payload.model_dump();company=b['company'];contact=b['contact'];schedule=b['schedule']
    npwp=re.sub(r'\D','',company.get('npwp',''))
    if len(npwp) not in (15,16):raise HTTPException(422,'NPWP harus 15 atau 16 digit')
    if not re.fullmatch(r'[^@\s]+@[^@\s]+\.[^@\s]+',contact.get('email','')):raise HTTPException(422,'Email tidak valid')
    phone=re.sub(r'\D','',contact.get('phone',''))
    if phone.startswith('0'):phone='62'+phone[1:]
    if not phone.startswith('62') or not 10<=len(phone)<=15:raise HTTPException(422,'Nomor HP Indonesia tidak valid')
    if not all([str(company.get('legal_name','')).strip(),str(company.get('address','')).strip(),str(contact.get('full_name','')).strip(),b.get('consent') is True]):raise HTTPException(422,'Data PT, alamat, PIC, dan persetujuan wajib diisi')
    if b.get('terms_version') != TERMS_VERSION:raise HTTPException(422,'Baca dan setujui versi syarat terbaru')
    s=parse(schedule.get('start_at',''));e=parse(schedule.get('end_at',''))
    validate_booking_schedule(s,e)
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        expire(c)
        scr=c.execute('SELECT * FROM screens WHERE id=? AND status="ACTIVE"',(b.get('screen_id'),)).fetchone()
        if not scr:raise HTTPException(404,'Layar tidak ditemukan')
        if overlaps(c,scr['id'],iso(s),iso(e)):raise HTTPException(409,'Slot sudah terisi')
        q=quote(iso(s),iso(e),scr['monthly_price'],scr['tax_rate']);id=uid();ts=iso(now())
        c.execute('''INSERT INTO orders(id,order_no,screen_id,company,npwp_hash,npwp_last4,pic,email,phone,address,start_at,end_at,status,subtotal,tax,total,created_at,updated_at,consent_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(id,'ORD-'+now().strftime('%Y%m%d')+'-'+id[:8].upper(),scr['id'],company['legal_name'],hmac.new(SECRET.encode(),npwp.encode(),hashlib.sha256).hexdigest(),npwp[-4:],contact['full_name'],contact['email'],'+'+phone,company['address'],iso(s),iso(e),'DRAFT',q['subtotal'],q['tax'],q['total'],ts,ts,ts))
        for line in q['lines']:c.execute('INSERT INTO price_lines VALUES(?,?,?,?)',(id,line['date'],line['hours'],line['amount']))
        c.execute('INSERT INTO consents VALUES(?,?,?)',(id,TERMS_VERSION,ts))
        audit(c,'ORDER_CREATED',id)
        return {'id':id,'order_no':get_order(c,id)['order_no'],'token':serializer.dumps({'order':id}),'quote':q}
@app.post('/api/v1/otp/send')
async def otp_send(request:Request):
    b=await request.json();id=b.get('order_id');channel=b.get('channel')
    if channel not in ('EMAIL','PHONE'):raise HTTPException(422,'Channel salah')
    with db() as c:
        o=get_order(c,id);owner(request,o)
        last=c.execute('SELECT expires_at,verified FROM otp WHERE order_id=? AND channel=?',(id,channel)).fetchone()
        if last and last['verified']:return {'message':'Kontak sudah terverifikasi','verified':True}
        if last and parse(last['expires_at'])>now()+timedelta(minutes=4):raise HTTPException(429,'Tunggu sebelum meminta OTP lagi')
        code=f'{secrets.randbelow(1000000):06d}'
        digest=hmac.new(SECRET.encode(),f'{id}:{channel}:{code}'.encode(),hashlib.sha256).hexdigest()
        c.execute('BEGIN IMMEDIATE')
        deadline=now()+timedelta(minutes=5)
        c.execute('INSERT OR REPLACE INTO otp VALUES(?,?,?,?,0,0)',(id,channel,digest,iso(deadline)))
        try:
            result=await asyncio.to_thread(deliver_otp,channel,o['email'] if channel=='EMAIL' else o['phone'],code)
        except Exception:
            c.execute('DELETE FROM otp WHERE order_id=? AND channel=?',(id,channel))
            c.commit()
            raise HTTPException(503,'Pengiriman kode gagal. Hubungi operator atau coba lagi.')
        return {**result,'expires_in':max(0,int((deadline-now()).total_seconds())),'resend_after':60}
@app.post('/api/v1/otp/verify')
async def otp_verify(request:Request):
    b=await request.json();id=b.get('order_id');ch=b.get('channel');code=str(b.get('code',''))
    with db() as c:
        o=get_order(c,id);owner(request,o)
        r=c.execute('SELECT * FROM otp WHERE order_id=? AND channel=?',(id,ch)).fetchone()
        if not r or parse(r['expires_at'])<now() or r['attempts']>=5:raise HTTPException(400,'OTP kedaluwarsa atau percobaan habis')
        digest=hmac.new(SECRET.encode(),f'{id}:{ch}:{code}'.encode(),hashlib.sha256).hexdigest()
        c.execute('UPDATE otp SET attempts=attempts+1 WHERE order_id=? AND channel=?',(id,ch))
        if not hmac.compare_digest(digest,r['code_hash']):raise HTTPException(400,'Kode OTP salah')
        c.execute('UPDATE otp SET verified=1 WHERE order_id=? AND channel=?',(id,ch))
        if c.execute('SELECT COUNT(*) n FROM otp WHERE order_id=? AND verified=1',(id,)).fetchone()['n']==2 and o['status']=='DRAFT':transition(c,id,'CONTENT_PENDING',['DRAFT'])
        return {'verified':True}
@app.get('/api/v1/orders/{id}')
def order(id:str,request:Request):
    with db() as c:
        expire(c);o=get_order(c,id);owner(request,o)
        o.pop('npwp_hash',None)
        o['verified_channels']=[r['channel'] for r in c.execute('SELECT channel FROM otp WHERE order_id=? AND verified=1',(id,))]
        o['history']=[row(r) for r in c.execute('SELECT to_status,created_at FROM history WHERE order_id=? ORDER BY id',(id,))]
        consent=c.execute('SELECT version FROM consents WHERE order_id=?',(id,)).fetchone()
        o['terms_version']=consent['version'] if consent else None
        o['review_notes']=[row(r) for r in c.execute("SELECT detail,created_at FROM audit WHERE entity=? AND action='ADMIN_MODERATION_REJECT' ORDER BY created_at DESC",(id,))]
        o['payment']=row(c.execute('SELECT * FROM payments WHERE order_id=? ORDER BY created_at DESC LIMIT 1',(id,)).fetchone())
        o['price_lines']=[row(r) for r in c.execute('SELECT date,hours,amount FROM price_lines WHERE order_id=?',(id,))]
        return o
@app.post('/api/v1/orders/{id}/quote')
def order_quote(id:str,request:Request):
    with db() as c:
        o=get_order(c,id);owner(request,o)
        s=c.execute('SELECT * FROM screens WHERE id=?',(o['screen_id'],)).fetchone()
        return quote(o['start_at'],o['end_at'],s['monthly_price'],s['tax_rate'])
def material_notification(c,id,request,background_tasks,reason=''):
    order=get_order(c,id)
    kinds={'NEEDS_REVIEW':'MATERIAL_PENDING','APPROVED':'MATERIAL_APPROVED','CONTENT_REJECTED':'MATERIAL_REJECTED'}
    kind=kinds[order['status']]
    base=os.getenv('PUBLIC_BASE_URL','').strip().rstrip('/')
    if not base and os.getenv('APP_ENV','development')=='development' and request.url.hostname in ('localhost','127.0.0.1','::1'):
        base=str(request.base_url).rstrip('/')
    parsed=urlsplit(base)
    status_url=''
    if parsed.scheme in ('https','http') and parsed.netloc and not parsed.username and (parsed.scheme=='https' or os.getenv('APP_ENV','development')!='production'):
        access=status_serializer.dumps({'order':id})
        status_url=base+'/status#access='+url_quote(access,safe='')
    enqueue_order_email(c,order,kind,event_key=f'material:{id}:{order["content_version"]}:{kind}',timestamp=now(),status_url=status_url,review_reason=reason)
    background_tasks.add_task(process_outbox,DB,clock=now,limit=3)


@app.post('/api/v1/orders/{id}/content')
async def content(id:str,request:Request,background_tasks:BackgroundTasks):
    b=await request.json()
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        o=get_order(c,id);owner(request,o)
        if o['status'] not in ('CONTENT_PENDING','CONTENT_REJECTED','APPROVED'):raise HTTPException(409,'Status tidak mengizinkan perubahan konten')
        source=b.get('source');title=str(b.get('title','')).strip()[:150];body=str(b.get('text','')).strip()[:2000]
        if source!='AI_TEMPLATE' or not title or not body:raise HTTPException(422,'Judul dan teks template wajib diisi')
        transition(c,id,'MODERATING',[o['status']])
        c.execute('UPDATE orders SET content_source=?,content_title=?,content_text=?,content_file=NULL,content_mime=NULL,content_version=content_version+1,approved_version=NULL,moderation=? WHERE id=?',(source,title,body,'PENDING',id))
        result=moderate(c,id,title+' '+body)
        material_notification(c,id,request,background_tasks,result.get('reason','') if result['status']=='REJECTED' else '')
        return {**result,'status':get_order(c,id)['status']}
@app.post('/api/v1/orders/{id}/upload')
async def upload(id:str,request:Request,background_tasks:BackgroundTasks,file:UploadFile=File(...)):
    allowed=('CONTENT_PENDING','CONTENT_REJECTED','APPROVED')
    with db() as c:
        original=get_order(c,id);owner(request,original)
        if original['status'] not in allowed:raise HTTPException(409,'Status tidak mengizinkan upload')
        screen=c.execute('SELECT width,height FROM screens WHERE id=?',(original['screen_id'],)).fetchone()
    data=await file.read(20*1024*1024+1)
    if len(data)>20*1024*1024:raise HTTPException(413,'Ukuran file maksimal 20 MB')
    mime=None
    if data[:3]==b'\xff\xd8\xff':mime='image/jpeg'
    elif data[:8]==b'\x89PNG\r\n\x1a\n':mime='image/png'
    elif len(data)>12 and data[4:8]==b'ftyp':mime='video/mp4'
    if not mime:raise HTTPException(415,'Hanya JPG, PNG, atau MP4 valid')
    data=await asyncio.to_thread(validate_media,data,mime,screen['width'],screen['height'])
    path=uid()+('.mp4' if mime=='video/mp4' else '.png' if mime=='image/png' else '.jpg')
    destination=UPLOAD/path
    try:
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            o=get_order(c,id);owner(request,o)
            if o['status'] not in allowed or o['content_version']!=original['content_version']:
                raise HTTPException(409,'Materi atau status pesanan berubah. Muat ulang pesanan sebelum mengunggah.')
            destination.write_bytes(data)
            transition(c,id,'MODERATING',[o['status']])
            c.execute('UPDATE orders SET content_source=?,content_title=?,content_text=?,content_file=?,content_mime=?,content_version=content_version+1,approved_version=NULL,moderation=? WHERE id=?',('UPLOAD',(file.filename or 'Materi iklan')[:150],'',path,mime,'NEEDS_REVIEW',id))
            transition(c,id,'NEEDS_REVIEW',['MODERATING'])
            audit(c,'UPLOAD_PENDING_MANUAL_REVIEW',id,'Antivirus dan AI multimedia belum terintegrasi')
            material_notification(c,id,request,background_tasks)
    except BaseException:
        destination.unlink(missing_ok=True)
        raise
    return {'status':'NEEDS_REVIEW','message':'File tervalidasi dan masuk antrean pemeriksaan operator.'}


def moderate(c,id,text):
    # Conservative local rule screening only. This is NOT AI moderation.
    prohibited=['judi online','slot gacor','pornografi','narkoba','senjata ilegal']
    flagged=[w for w in prohibited if w in text.lower()]
    if flagged:
        transition(c,id,'CONTENT_REJECTED',['MODERATING']);result='REJECTED'
    else:
        transition(c,id,'NEEDS_REVIEW',['MODERATING']);result='NEEDS_REVIEW'
    c.execute('UPDATE orders SET moderation=? WHERE id=?',(result,id))
    audit(c,'MODERATION_SCREENING',id,result)
    return {'status':result,'reason':'Perlu peninjauan manusia sebelum pembayaran' if not flagged else 'Konten mengandung istilah yang dilarang'}
@app.post('/api/v1/orders/{id}/checkout')
async def checkout(id:str,request:Request,background_tasks:BackgroundTasks,idempotency_key:str=Header(default='')):
    if not public_config()['demo_payments'] and not public_config()['bank']['account']:
        raise HTTPException(503,'Instruksi pembayaran belum dikonfigurasi operator')
    with db() as c:
        c.execute('BEGIN IMMEDIATE');expire(c);o=get_order(c,id);owner(request,o)
        existing=c.execute('SELECT * FROM payments WHERE idempotency_key=?',(idempotency_key,)).fetchone() if idempotency_key else None
        if existing:
            if existing['order_id']!=id:raise HTTPException(409,'Kunci pembayaran telah digunakan')
            return {**row(existing),'expires_at':o['hold_expires'],'demo':public_config()['demo_payments'],'instructions':public_config()['bank']}
        if not booking_window_open(o):raise HTTPException(409,'Jadwal sudah berlalu; buat pesanan baru')
        if o['status']!='APPROVED' or o['approved_version']!=o['content_version']:raise HTTPException(409,'Konten belum disetujui')
        if c.execute('SELECT COUNT(*) n FROM otp WHERE order_id=? AND verified=1',(id,)).fetchone()['n']!=2:raise HTTPException(409,'Kontak belum terverifikasi')
        if overlaps(c,o['screen_id'],o['start_at'],o['end_at'],id):raise HTTPException(409,'Slot baru saja diambil pelanggan lain')
        if not idempotency_key:idempotency_key=uid()
        existing=c.execute('SELECT * FROM payments WHERE idempotency_key=?',(idempotency_key,)).fetchone()
        if existing:return row(existing)
        transition(c,id,'AWAITING_PAYMENT',['APPROVED']);hold=iso(now()+timedelta(minutes=15))
        c.execute('UPDATE orders SET hold_expires=? WHERE id=?',(hold,id))
        p={'id':uid(),'order_id':id,'idempotency_key':idempotency_key,'status':'PENDING','amount':o['total'],'created_at':iso(now())}
        c.execute('INSERT INTO payments VALUES(?,?,?,?,?,?)',tuple(p.values()))
        enqueue_order_email(c,get_order(c,id),'BILL_CREATED',event_key='bill:'+p['id'],timestamp=now(),simulated=public_config()['demo_payments'])
        background_tasks.add_task(process_outbox,DB,clock=now)
        return {**p,'expires_at':hold,'demo':public_config()['demo_payments'],'instructions':public_config()['bank']}
@app.post('/api/v1/demo/payments/{id}/settle')
def settle(id:str,request:Request,background_tasks:BackgroundTasks):
    """Explicitly enabled local test path only."""
    if not public_config()['demo_payments']:raise HTTPException(404,'Endpoint tidak tersedia')
    with db() as c:
        c.execute('BEGIN IMMEDIATE');expire(c);o=get_order(c,id);owner(request,o)
        if o['status']!='AWAITING_PAYMENT':raise HTTPException(409,'Pembayaran tidak aktif')
        if parse(o['hold_expires'])<=now():raise HTTPException(409,'Hold habis')
        if not booking_window_open(o):raise HTTPException(409,'Periode tayang sudah berakhir')
        c.execute("UPDATE payments SET status='PAID' WHERE order_id=? AND status='PENDING'",(id,))
        transition(c,id,'PAID',['AWAITING_PAYMENT'])
        c.execute('UPDATE orders SET paid_at=? WHERE id=?',(iso(now()),id))
        transition(c,id,'SCHEDULED',['PAID']);audit(c,'DEMO_PAYMENT_SETTLED',id)
        scheduler_tick(c)
        enqueue_order_email(c,get_order(c,id),'PAYMENT_CONFIRMED',event_key='paid:'+id,timestamp=now(),simulated=True)
        background_tasks.add_task(process_outbox,DB,clock=now)
        return {'status':get_order(c,id)['status'],'demo':True}
@app.get('/api/v1/orders/{id}/invoice')
def invoice(id:str,request:Request):
    from invoices import render_invoice
    with db() as c:
        o=get_order(c,id);owner(request,o)
        if o['status'] not in ('PAID','SCHEDULED','LIVE','COMPLETED','TAKEN_DOWN') or not o['paid_at']:
            raise HTTPException(409,'Invoice belum tersedia')
        simulated=bool(c.execute("SELECT 1 FROM audit WHERE entity=? AND action='DEMO_PAYMENT_SETTLED'",(id,)).fetchone())
        screen=row(c.execute('SELECT * FROM screens WHERE id=?',(o['screen_id'],)).fetchone())
        lines=[row(r) for r in c.execute('SELECT date,hours,amount FROM price_lines WHERE order_id=? ORDER BY date',(id,))]
        confirmation=row(c.execute('SELECT * FROM payment_confirmations WHERE order_id=?',(id,)).fetchone())
    operator=public_config()
    issuer={'name':operator['operator'],'email':operator['support_email'],'address':os.getenv('OPERATOR_ADDRESS','')}
    data=render_invoice(o,screen,lines,confirmation=confirmation,simulated=simulated,issuer=issuer)
    return Response(data,media_type='application/pdf',headers={
        'Content-Disposition':f'attachment; filename="invoice-LAMIA-{o["order_no"]}.pdf"',
        'Cache-Control':'no-store',
    })
class AdminLoginInput(BaseModel):
    username: str = Field(min_length=1,max_length=128)
    password: str = Field(min_length=1,max_length=1024)


@app.post('/api/v1/admin/auth/login')
def login(payload:AdminLoginInput,request:Request,response:Response):
    manager=session_auth()
    manager.check_origin(request,os.getenv('PUBLIC_BASE_URL',''))
    sid,session=manager.login(request,payload.username,payload.password)
    response.set_cookie(ADMIN_COOKIE,sid,max_age=ADMIN_LIFETIME,httponly=True,secure=os.getenv('APP_ENV','development')=='production',samesite='strict',path='/')
    return session


@app.get('/api/v1/admin/auth/session')
def admin_session(request:Request):
    return admin(request)


@app.post('/api/v1/admin/auth/logout')
def admin_logout(request:Request,response:Response):
    admin(request)
    session_auth().logout(request)
    response.delete_cookie(ADMIN_COOKIE,path='/',secure=os.getenv('APP_ENV','development')=='production',httponly=True,samesite='strict')
    return {'logged_out':True}

@app.get('/api/v1/admin/orders')
def admin_orders(request:Request):
    admin(request)
    with db() as c:
        expire(c)
        return [dict(r) for r in c.execute('SELECT id,order_no,company,pic,start_at,end_at,status,total,moderation,content_title,screen_id FROM orders ORDER BY created_at DESC LIMIT 200')]
@app.get('/api/v1/admin/screens')
def admin_screens(request:Request):
    admin(request)
    with db() as c:return [screen_info(r) for r in c.execute('SELECT * FROM screens')]
@app.post('/api/v1/admin/moderation/{id}/decision')
async def decision(id:str,request:Request,background_tasks:BackgroundTasks):
    admin(request);b=await request.json();v=b.get('decision')
    if v not in ('APPROVE','REJECT'):raise HTTPException(422,'Keputusan salah')
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        o=get_order(c,id)
        if o['status']!='NEEDS_REVIEW':raise HTTPException(409,'Tidak sedang direview')
        if v=='APPROVE':
            transition(c,id,'APPROVED',['NEEDS_REVIEW']);c.execute('UPDATE orders SET approved_version=content_version,moderation="APPROVED" WHERE id=?',(id,))
        else:
            if not b.get('reason'):raise HTTPException(422,'Alasan penolakan wajib')
            transition(c,id,'CONTENT_REJECTED',['NEEDS_REVIEW']);c.execute('UPDATE orders SET moderation="REJECTED" WHERE id=?',(id,))
        reason=str(b.get('reason','')).strip()[:1000]
        audit(c,'ADMIN_MODERATION_'+v,id,reason)
        material_notification(c,id,request,background_tasks,reason)
        return {'status':'APPROVED' if v=='APPROVE' else 'CONTENT_REJECTED'}
@app.post('/api/v1/admin/orders/{id}/takedown')
async def takedown(id:str,request:Request):
    admin(request);b=await request.json()
    if not b.get('reason'):raise HTTPException(422,'Alasan wajib')
    with db() as c:
        o=get_order(c,id);transition(c,id,'TAKEN_DOWN',['SCHEDULED','LIVE']);audit(c,'TAKEDOWN',id,b['reason'])
        return {'status':'TAKEN_DOWN'}
@app.get('/api/v1/admin/summary')
def summary(request:Request):
    admin(request)
    with db() as c:
        expire(c)
        return {'orders':c.execute('SELECT COUNT(*) FROM orders').fetchone()[0],'revenue':c.execute("SELECT COALESCE(SUM(total),0) FROM orders WHERE status IN ('PAID','SCHEDULED','LIVE','COMPLETED')").fetchone()[0],'reviews':c.execute("SELECT COUNT(*) FROM orders WHERE status='NEEDS_REVIEW'").fetchone()[0],'screens':c.execute('SELECT COUNT(*) FROM screens').fetchone()[0]}
@app.get('/api/v1/admin/audit')
def audits(request:Request):
    admin(request)
    with db() as c:return [row(r) for r in c.execute('SELECT * FROM audit ORDER BY created_at DESC LIMIT 100')]
@app.get('/api/v1/screens/{id}/qr')
def qr(id:str,request:Request):
    import qrcode
    with db() as c:
        r=c.execute('SELECT token FROM screens WHERE id=?',(id,)).fetchone()
        if not r:raise HTTPException(404,'Layar tidak ada')
    url=str(request.base_url).rstrip('/')+'/?screen_token='+r['token']
    b=io.BytesIO();qrcode.make(url).save(b,format='PNG');return Response(b.getvalue(),media_type='image/png')
@app.get('/api/v1/player/manifest')
def manifest(request:Request):
    player(request);screen_id=request.query_params.get('screen_id')
    device_scope(request,screen_id)
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        if not c.execute('SELECT 1 FROM screens WHERE id=? AND status="ACTIVE"',(screen_id,)).fetchone():raise HTTPException(404,'Layar tidak ditemukan')
        scheduler_tick(c)
        t=iso(now());future=iso(now()+timedelta(hours=48))
        items=[{'order_id':r['id'],'start_at':r['start_at'],'end_at':r['end_at'],'title':r['content_title'],'text':r['content_text'],'asset_url':'/api/v1/player/assets/'+r['id'] if r['content_file'] else None,'source':r['content_source'],'mime':r['content_mime']} for r in c.execute("SELECT * FROM orders WHERE screen_id=? AND status IN ('SCHEDULED','LIVE') AND start_at<? AND end_at>? AND approved_version=content_version ORDER BY start_at",(screen_id,future,t))]
        return {'server_time':t,'items':items,'refresh_seconds':10,'lease_seconds':30}
@app.get('/api/v1/player/assets/{id}')
def player_asset(id:str,request:Request):
    player(request)
    with db() as c:
        o=get_order(c,id)
        device_scope(request,o['screen_id'])
        if parse(o['end_at'])<=now() or o['status'] not in ('SCHEDULED','LIVE') or o['approved_version']!=o['content_version'] or not o['content_file']:raise HTTPException(403,'Aset tidak tersedia')
        return FileResponse(UPLOAD/o['content_file'],media_type=o['content_mime'])
@app.post('/api/v1/player/heartbeat')
async def heartbeat(request:Request):
    player(request);b=await request.json();screen=b.get('screen_id')
    device_scope(request,screen)
    with db() as c:
        if not c.execute('SELECT 1 FROM screens WHERE id=?',(screen,)).fetchone():raise HTTPException(404,'Layar tidak ditemukan')
        c.execute('INSERT OR REPLACE INTO heartbeats VALUES(?,?,?)',(screen,iso(now()),json.dumps(b)))
    return {'ok':True}
@app.post('/api/v1/player/playback-logs')
async def logs(request:Request):
    player(request);b=await request.json()
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        for r in b.get('logs',[])[:100]:
            o=get_order(c,r.get('order_id'))
            device_scope(request,o['screen_id'])
            start,end=parse(r.get('started_at','')),parse(r.get('ended_at',''))
            if r.get('screen_id')!=o['screen_id'] or end<start or start<parse(o['start_at']) or end>parse(o['end_at'])+timedelta(seconds=2) or end>now()+timedelta(seconds=10):
                raise HTTPException(422,'Catatan penayangan tidak sesuai jadwal')
            if o['paid_at'] is None or o['approved_version']!=o['content_version']:
                raise HTTPException(422,'Pesanan belum diizinkan tayang')
            c.execute('INSERT OR IGNORE INTO playback VALUES(?,?,?,?,?,?)',(str(r.get('id',uid()))[:100],o['id'],o['screen_id'],iso(start),iso(end),'PLAYED'))
    return {'ok':True}
@app.get('/api/v1/admin/playback')
def playback(request:Request):
    admin(request)
    with db() as c:return [row(r) for r in c.execute('SELECT * FROM playback ORDER BY started_at DESC LIMIT 100')]


def scheduler_tick(connection=None):
    """Reconcile persisted bookings; safe to repeat or run from multiple workers."""
    if connection is None:
        with db() as c:
            c.execute('BEGIN IMMEDIATE')
            return scheduler_tick(c)
    c = connection
    expire(c)
    timestamp = iso(now())
    for r in c.execute("SELECT id,status,start_at,end_at FROM orders WHERE status IN ('SCHEDULED','LIVE')").fetchall():
        if parse(r['end_at']) <= now():
            transition(c, r['id'], 'COMPLETED', [r['status']])
            audit(c, 'SCHEDULER_COMPLETED', r['id'])
        elif parse(r['start_at']) <= now() and r['status'] == 'SCHEDULED':
            transition(c, r['id'], 'LIVE', ['SCHEDULED'])
            audit(c, 'SCHEDULER_LIVE', r['id'])
    c.execute('INSERT OR REPLACE INTO scheduler_state VALUES(1,?)', (timestamp,))
    c.execute("UPDATE payments SET status='EXPIRED' WHERE status='PENDING' AND order_id IN (SELECT id FROM orders WHERE status='EXPIRED')")
    return {'last_tick': timestamp}


@app.get('/api/v1/config')
def config():
    return public_config()


@app.get('/terms')
@app.get('/privacy')
@app.get('/status')
def legal_page():
    return FileResponse(ROOT / 'static' / 'index.html')


@app.get('/api/v1/screens/{screen_id}/quote')
def preview_quote(screen_id: str, start_at: str, end_at: str):
    start, end = parse(start_at), parse(end_at)
    validate_booking_schedule(start,end)
    with db() as c:
        screen = c.execute('SELECT * FROM screens WHERE id=? AND status="ACTIVE"', (screen_id,)).fetchone()
        if not screen:
            raise HTTPException(404, 'Layar tidak ditemukan')
        return {**quote(iso(start), iso(end), screen['monthly_price'], screen['tax_rate']),
                'available': not overlaps(c, screen_id, iso(start), iso(end))}


@app.post('/api/v1/admin/orders/{id}/confirm-payment')
async def confirm_payment(id: str, request: Request, background_tasks: BackgroundTasks):
    admin(request)
    body = await request.json()
    reference = str(body.get('reference', '')).strip()
    if len(reference) < 6 or len(reference) > 120:
        raise HTTPException(422, 'Referensi bank harus 6–120 karakter')
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        expire(c)
        o = get_order(c, id)
        if o['status'] != 'AWAITING_PAYMENT':
            raise HTTPException(409, 'Tagihan tidak aktif atau sudah kedaluwarsa')
        if body.get('amount') != o['total']:
            raise HTTPException(422, 'Nominal penerimaan harus sama dengan tagihan')
        if not booking_window_open(o) or overlaps(c, o['screen_id'], o['start_at'], o['end_at'], id):
            raise HTTPException(409, 'Jadwal sudah tidak tersedia')
        if c.execute('SELECT 1 FROM payment_confirmations WHERE reference=?', (reference,)).fetchone():
            raise HTTPException(409, 'Referensi bank sudah digunakan')
        c.execute('INSERT INTO payment_confirmations VALUES(?,?,?)', (id, reference, iso(now())))
        c.execute("UPDATE payments SET status='PAID' WHERE order_id=? AND status='PENDING'", (id,))
        transition(c, id, 'PAID', ['AWAITING_PAYMENT'])
        c.execute('UPDATE orders SET paid_at=? WHERE id=?', (iso(now()), id))
        transition(c, id, 'SCHEDULED', ['PAID'])
        audit(c, 'BANK_PAYMENT_CONFIRMED', id, reference)
        scheduler_tick(c)
        status=get_order(c,id)['status']
        enqueue_order_email(c,get_order(c,id),'PAYMENT_CONFIRMED',event_key='paid:'+id,timestamp=now())
        background_tasks.add_task(process_outbox,DB,clock=now)
    return {'status': status}


@app.get('/api/v1/admin/schedule')
def schedule(request: Request, date: str = ''):
    admin(request)
    try:
        day = datetime.fromisoformat(date).replace(tzinfo=TZ, hour=0, minute=0, second=0, microsecond=0) if date else now().astimezone(TZ).replace(hour=0, minute=0, second=0, microsecond=0)
    except ValueError:
        raise HTTPException(422, 'Tanggal tidak valid')
    start, end = iso(day.astimezone(timezone.utc)), iso((day + timedelta(days=7)).astimezone(timezone.utc))
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        scheduler_tick(c)
        bookings = [row(r) for r in c.execute("SELECT id,order_no,company,screen_id,start_at,end_at,status,content_title FROM orders WHERE start_at<? AND end_at>? AND status IN ('AWAITING_PAYMENT','SCHEDULED','LIVE','COMPLETED') ORDER BY start_at", (end, start))]
        devices = []
        for screen in c.execute('SELECT * FROM screens'):
            heartbeat = c.execute('SELECT * FROM heartbeats WHERE screen_id=?', (screen['id'],)).fetchone()
            devices.append({**screen_info(screen), 'last_seen': heartbeat['reported_at'] if heartbeat else None,
                            'online': bool(heartbeat and (now() - parse(heartbeat['reported_at'])).total_seconds() < 60)})
        return {'start': start, 'end': end, 'orders': bookings, 'screens': devices,
                'blackouts': [row(r) for r in c.execute('SELECT * FROM blackouts WHERE start_at<? AND end_at>?', (end, start))],
                'scheduler': row(c.execute('SELECT * FROM scheduler_state WHERE id=1').fetchone())}


@app.post('/api/v1/admin/blackouts')
async def add_blackout(request: Request):
    admin(request)
    b = await request.json()
    start, end = iso(parse(b.get('start_at', ''))), iso(parse(b.get('end_at', '')))
    if parse(end) <= parse(start) or not str(b.get('reason', '')).strip():
        raise HTTPException(422, 'Rentang waktu dan alasan wajib diisi')
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        if not c.execute('SELECT 1 FROM screens WHERE id=?', (b.get('screen_id'),)).fetchone():
            raise HTTPException(404, 'Layar tidak ditemukan')
        if overlaps(c, b['screen_id'], start, end):
            raise HTTPException(409, 'Blackout bertabrakan dengan jadwal yang sudah dipesan')
        id = uid()
        c.execute('INSERT INTO blackouts VALUES(?,?,?,?,?)', (id, b['screen_id'], start, end, str(b['reason'])[:500]))
        audit(c, 'BLACKOUT_CREATED', id, b['reason'])
        return {'id': id}


@app.delete('/api/v1/admin/blackouts/{id}')
def remove_blackout(id: str, request: Request):
    admin(request)
    with db() as c:
        if not c.execute('SELECT 1 FROM blackouts WHERE id=?', (id,)).fetchone():
            raise HTTPException(404, 'Blackout tidak ditemukan')
        c.execute('DELETE FROM blackouts WHERE id=?', (id,))
        audit(c, 'BLACKOUT_REMOVED', id)
    return {'ok': True}


@app.get('/api/v1/orders/{id}/creative')
def creative_preview(id: str, request: Request):
    with db() as c:
        o = get_order(c, id)
        owner(request, o)
        if not o['content_file']:
            raise HTTPException(404, 'Tidak ada file')
        return FileResponse(UPLOAD / o['content_file'], media_type=o['content_mime'])


@app.post('/api/v1/admin/devices')
async def enroll_device(request: Request):
    admin(request)
    body = await request.json()
    name = str(body.get('name', '')).strip()
    if not name or len(name) > 120:
        raise HTTPException(422, 'Nama perangkat wajib diisi (maksimal 120 karakter)')
    token = secrets.token_urlsafe(40)
    digest = hmac.new(SECRET.encode(), token.encode(), hashlib.sha256).hexdigest()
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        if not c.execute('SELECT 1 FROM screens WHERE id=?', (body.get('screen_id'),)).fetchone():
            raise HTTPException(404, 'Layar tidak ditemukan')
        id = uid()
        c.execute('INSERT INTO devices VALUES(?,?,?,?,?,NULL)', (id, body['screen_id'], name, digest, iso(now())))
        audit(c, 'DEVICE_ENROLLED', id, name)
    return {'id': id, 'token': token, 'screen_id': body['screen_id'], 'name': name}


@app.get('/api/v1/admin/devices')
def list_devices(request: Request):
    admin(request)
    with db() as c:
        return [row(r) for r in c.execute('SELECT id,screen_id,name,created_at,revoked_at FROM devices ORDER BY created_at DESC')]


@app.delete('/api/v1/admin/devices/{id}')
def revoke_device(id: str, request: Request):
    admin(request)
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        if not c.execute('SELECT 1 FROM devices WHERE id=?', (id,)).fetchone():
            raise HTTPException(404, 'Perangkat tidak ditemukan')
        c.execute('UPDATE devices SET revoked_at=? WHERE id=?', (iso(now()), id))
        audit(c, 'DEVICE_REVOKED', id)
    return {'ok': True}


@app.get('/api/v1/order-status')
def readonly_order_status(request:Request):
    access=request.headers.get('x-order-status','')
    try:
        data=status_serializer.loads(access,max_age=7*86400)
        id=data['order']
    except (BadSignature,KeyError,TypeError):
        raise HTTPException(401,'Tautan status tidak valid atau telah berakhir. Buka tautan dari email terbaru.')
    with db() as c:
        order=get_order(c,id)
        screen=c.execute('SELECT name FROM screens WHERE id=?',(order['screen_id'],)).fetchone()
        notes=c.execute("SELECT detail FROM audit WHERE entity=? AND action='ADMIN_MODERATION_REJECT' ORDER BY created_at DESC LIMIT 1",(id,)).fetchone()
        result={key:order[key] for key in ('order_no','status','content_title','start_at','end_at')}
        result['screen']=screen['name']
        result['review_note']=notes['detail'] if notes and order['status']=='CONTENT_REJECTED' else ''
        result['history']=[row(r) for r in c.execute('SELECT to_status,created_at FROM history WHERE order_id=? ORDER BY id',(id,))]
    return JSONResponse(result,headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'})
