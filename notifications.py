"""Durable transactional-email outbox. No SMTP calls run inside booking transactions."""
import json
import logging
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import make_msgid, parseaddr

import services
from email_templates import transaction_email, review_email

MAX_ATTEMPTS = 5


def init_outbox(connection):
    connection.executescript('''
    CREATE TABLE IF NOT EXISTS email_outbox(
        id TEXT PRIMARY KEY, event_key TEXT UNIQUE NOT NULL, order_id TEXT NOT NULL,
        kind TEXT NOT NULL, payload TEXT NOT NULL, message_id TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'PENDING', attempts INTEGER NOT NULL DEFAULT 0,
        next_attempt_at REAL NOT NULL, claimed_until REAL, claim_token TEXT,
        last_error TEXT, created_at TEXT NOT NULL, sent_at TEXT
    );
    CREATE INDEX IF NOT EXISTS email_outbox_delivery ON email_outbox(status,next_attempt_at);
    ''')


def enqueue_order_email(connection, order, kind, *, event_key, timestamp, simulated=False, status_url='', review_reason=''):
    existing = connection.execute('SELECT id FROM email_outbox WHERE event_key=?', (event_key,)).fetchone()
    if existing:
        return existing['id']
    config = services.public_config()
    screen = dict(connection.execute('SELECT * FROM screens WHERE id=?', (order['screen_id'],)).fetchone())
    confirmation = connection.execute('SELECT * FROM payment_confirmations WHERE order_id=?', (order['id'],)).fetchone()
    # Never copy authentication/session material or NPWP hashes into notification payloads.
    snapshot = {key: value for key, value in order.items() if key != 'npwp_hash'}
    payload = {'order': snapshot, 'screen': screen,
               'lines': [dict(row) for row in connection.execute('SELECT date,hours,amount FROM price_lines WHERE order_id=? ORDER BY date', (order['id'],))],
               'confirmation': dict(confirmation) if confirmation else None,
               'simulated': simulated, 'bank': config['bank'],
               'issuer': {'name': config['operator'], 'email': config['support_email'], 'address': os.getenv('OPERATOR_ADDRESS','')},
               'base_url': os.getenv('PUBLIC_BASE_URL','').strip(),'status_url':status_url,'review_reason':review_reason}
    # Screen QR tokens are not needed in email either.
    payload['screen'].pop('token', None)
    identifier = str(uuid.uuid4())
    address = parseaddr(os.getenv('SMTP_FROM',''))[1]
    domain = address.rsplit('@',1)[-1] if '@' in address else 'lamia.local'
    connection.execute('''INSERT INTO email_outbox
        (id,event_key,order_id,kind,payload,message_id,next_attempt_at,created_at)
        VALUES(?,?,?,?,?,?,?,?)''',
        (identifier, event_key, order['id'], kind, json.dumps(payload), make_msgid(domain=domain), timestamp.timestamp(), timestamp.isoformat()))
    return identifier


@contextmanager
def _connect(database):
    connection = sqlite3.connect(database, timeout=10, isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        if connection.in_transaction:
            connection.commit()
    except BaseException:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()


def _finish(database, item, status, timestamp, error=None):
    with _connect(database) as connection:
        connection.execute('BEGIN IMMEDIATE')
        next_attempt = timestamp.timestamp() + min(60 * 2 ** (item['attempts'] - 1), 900)
        cursor = connection.execute('''UPDATE email_outbox SET status=?,last_error=?,
            sent_at=?,next_attempt_at=?,claimed_until=NULL,claim_token=NULL
            WHERE id=? AND claim_token=?''',
            (status, error, timestamp.isoformat() if status == 'SENT' else None, next_attempt, item['id'], item['claim_token']))
        if cursor.rowcount:
            action = 'EMAIL_' + ('RETRY' if status == 'PENDING' else status)
            connection.execute('INSERT INTO audit(id,action,entity,detail,created_at) VALUES(?,?,?,?,?)',
                               (str(uuid.uuid4()), action, item['order_id'], item['kind'] + (': '+error if error else ''), timestamp.isoformat()))


def process_outbox(database, *, clock=None, limit=1):
    clock = clock or (lambda: datetime.now(timezone.utc))
    processed = 0
    for _ in range(limit):
        timestamp = clock()
        with _connect(database) as connection:
            connection.execute('BEGIN IMMEDIATE')
            connection.execute("UPDATE email_outbox SET status='FAILED',last_error='DeliveryLeaseExpired',claimed_until=NULL,claim_token=NULL WHERE status='SENDING' AND attempts>=? AND claimed_until<=?", (MAX_ATTEMPTS,timestamp.timestamp()))
            item = connection.execute('''SELECT * FROM email_outbox WHERE attempts<? AND
                ((status='PENDING' AND next_attempt_at<=?) OR (status='SENDING' AND claimed_until<=?))
                ORDER BY created_at,id LIMIT 1''', (MAX_ATTEMPTS, timestamp.timestamp(), timestamp.timestamp())).fetchone()
            if not item:
                return processed
            item = dict(item)
            item['attempts'] += 1
            item['claim_token'] = str(uuid.uuid4())
            connection.execute("UPDATE email_outbox SET status='SENDING',attempts=?,claim_token=?,claimed_until=? WHERE id=?",
                               (item['attempts'], item['claim_token'], timestamp.timestamp()+120, item['id']))
        # The transaction and its lock have ended before constructing or sending email.
        try:
            payload = json.loads(item['payload'])
            if item['kind'] == 'BILL_CREATED':
                with _connect(database) as connection:
                    order = connection.execute('SELECT status,hold_expires FROM orders WHERE id=?', (item['order_id'],)).fetchone()
                if not order or order['status'] != 'AWAITING_PAYMENT' or datetime.fromisoformat(order['hold_expires']) <= clock():
                    _finish(database, item, 'CANCELLED', clock())
                    processed += 1
                    continue
            if item['kind'].startswith('MATERIAL_'):
                with _connect(database) as connection:
                    current=connection.execute('SELECT status,content_version FROM orders WHERE id=?',(item['order_id'],)).fetchone()
                if not current or current['content_version']!=payload['order']['content_version'] or (item['kind']=='MATERIAL_PENDING' and current['status']!='NEEDS_REVIEW'):
                    _finish(database,item,'CANCELLED',clock())
                    processed+=1
                    continue
            receipt = None
            if item['kind'] == 'PAYMENT_CONFIRMED':
                from invoices import render_invoice
                receipt = render_invoice(payload['order'], payload['screen'], payload['lines'],
                                         confirmation=payload['confirmation'], simulated=payload['simulated'], issuer=payload['issuer'])
            if item['kind'].startswith('MATERIAL_'):
                mail=review_email(os.environ['SMTP_FROM'],payload,item['kind'],message_id=item['message_id'])
            else:
                mail=transaction_email(os.environ['SMTP_FROM'],payload,item['kind'],invoice_pdf=receipt,message_id=item['message_id'])
            services.send_email(mail)
        except Exception as error:
            # Keep credentials/provider responses out of logs and API responses.
            error_name = type(error).__name__
            _finish(database, item, 'FAILED' if item['attempts'] >= MAX_ATTEMPTS else 'PENDING', clock(), error_name)
            logging.warning('Email notification %s could not be delivered (%s)', item['id'], error_name)
        else:
            _finish(database, item, 'SENT', clock())
        processed += 1
    return processed
