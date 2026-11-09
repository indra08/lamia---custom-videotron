-- Independent Cloudflare D1 schema. Never applied to the VPS database.

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
        

        CREATE TABLE IF NOT EXISTS consents(order_id TEXT PRIMARY KEY REFERENCES orders(id),version TEXT NOT NULL,accepted_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS payment_confirmations(order_id TEXT PRIMARY KEY REFERENCES orders(id),reference TEXT UNIQUE NOT NULL,confirmed_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS devices(id TEXT PRIMARY KEY,screen_id TEXT NOT NULL REFERENCES screens(id),name TEXT NOT NULL,token_digest TEXT UNIQUE NOT NULL,created_at TEXT NOT NULL,revoked_at TEXT);
        CREATE TABLE IF NOT EXISTS scheduler_state(id INTEGER PRIMARY KEY CHECK(id=1),last_tick TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS orders_screen_schedule ON orders(screen_id,start_at,end_at,status);
        

    CREATE TABLE IF NOT EXISTS admin_sessions(
        digest TEXT PRIMARY KEY,username TEXT NOT NULL,version TEXT NOT NULL,
        created_at REAL NOT NULL,last_seen REAL NOT NULL,expires_at REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS admin_login_attempts(
        bucket TEXT PRIMARY KEY,attempts INTEGER NOT NULL,started_at REAL NOT NULL,blocked_until REAL
    );
    

    CREATE TABLE IF NOT EXISTS email_outbox(
        id TEXT PRIMARY KEY, event_key TEXT UNIQUE NOT NULL, order_id TEXT NOT NULL,
        kind TEXT NOT NULL, payload TEXT NOT NULL, message_id TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'PENDING', attempts INTEGER NOT NULL DEFAULT 0,
        next_attempt_at REAL NOT NULL, claimed_until REAL, claim_token TEXT,
        last_error TEXT, created_at TEXT NOT NULL, sent_at TEXT
    );
    CREATE INDEX IF NOT EXISTS email_outbox_delivery ON email_outbox(status,next_attempt_at);
    
CREATE TABLE IF NOT EXISTS tx_guards(id INTEGER CONSTRAINT lamia_guard CHECK(id=1));
CREATE UNIQUE INDEX IF NOT EXISTS one_pending_payment ON payments(order_id) WHERE status='PENDING';
CREATE INDEX IF NOT EXISTS cf_orders_status ON orders(status,start_at,end_at);
CREATE INDEX IF NOT EXISTS cf_otp_order ON otp(order_id,verified);
CREATE TRIGGER IF NOT EXISTS cf_reservation_guard BEFORE UPDATE OF status,start_at,end_at ON orders
WHEN NEW.status IN ('AWAITING_PAYMENT','PAID','SCHEDULED','LIVE')
BEGIN
  SELECT CASE WHEN EXISTS(SELECT 1 FROM orders o WHERE o.id!=NEW.id AND o.screen_id=NEW.screen_id
    AND o.start_at<NEW.end_at AND o.end_at>NEW.start_at
    AND (o.status IN ('PAID','SCHEDULED','LIVE') OR (o.status='AWAITING_PAYMENT' AND o.hold_expires>strftime('%Y-%m-%dT%H:%M:%fZ','now'))))
    OR EXISTS(SELECT 1 FROM blackouts b WHERE b.screen_id=NEW.screen_id AND b.start_at<NEW.end_at AND b.end_at>NEW.start_at)
    THEN RAISE(ABORT,'SLOT_CONFLICT') END;
END;
CREATE TRIGGER IF NOT EXISTS cf_blackout_guard BEFORE INSERT ON blackouts
BEGIN
  SELECT CASE WHEN EXISTS(SELECT 1 FROM orders o WHERE o.screen_id=NEW.screen_id AND o.start_at<NEW.end_at AND o.end_at>NEW.start_at
    AND (o.status IN ('PAID','SCHEDULED','LIVE') OR (o.status='AWAITING_PAYMENT' AND o.hold_expires>strftime('%Y-%m-%dT%H:%M:%fZ','now'))))
    OR EXISTS(SELECT 1 FROM blackouts b WHERE b.screen_id=NEW.screen_id AND b.start_at<NEW.end_at AND b.end_at>NEW.start_at)
    THEN RAISE(ABORT,'SLOT_CONFLICT') END;
END;
INSERT OR IGNORE INTO screens VALUES('cf-vtr-001','VTR-001','Videotron Tengah Kota','Semarang, Jawa Tengah',1920,1080,100000000,'0.11',lower(hex(randomblob(16))),'ACTIVE');
INSERT OR IGNORE INTO screens VALUES('cf-vtr-002','VTR-002','Videotron Kota Lama','Semarang, Jawa Tengah',1920,1080,75000000,'0.11',lower(hex(randomblob(16))),'ACTIVE');
INSERT OR IGNORE INTO screens VALUES('cf-vtr-003','VTR-003','Videotron Alun-Alun','Ungaran, Jawa Tengah',1920,1080,45000000,'0.11',lower(hex(randomblob(16))),'ACTIVE');
