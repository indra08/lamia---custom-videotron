"""Configurable contact delivery and public operator settings."""
import os
import smtplib
import ssl
from email_templates import verification_email

import httpx

TERMS_VERSION = '2026-11-08'


def enabled(name):
    return os.getenv('APP_ENV', 'development') != 'production' and os.getenv(name, '').lower() == 'true'


def booking_policy():
    development = os.getenv('APP_ENV', 'development').strip().lower() == 'development'
    return {
        'immediate_start': development,
        'minimum_lead_minutes': 0 if development else 1440,
        'minimum_duration_minutes': 24 if development else 1440,
        'start_grace_seconds': 300 if development else 0,
    }


def public_config():
    return {
        'terms_version': TERMS_VERSION,
        'booking_policy': booking_policy(),
        'operator': (os.getenv('OPERATOR_NAME') or 'LAMIA'),
        'support_email': os.getenv('SUPPORT_EMAIL', ''),
        'legal_configured': bool(os.getenv('OPERATOR_NAME') and os.getenv('SUPPORT_EMAIL')),
        'demo_otp': enabled('ENABLE_DEMO_OTP'),
        'email_delivery': 'smtp',
        'demo_payments': enabled('ENABLE_DEMO_PAYMENTS'),
        'bank': {
            'name': os.getenv('BANK_NAME', ''),
            'account': os.getenv('BANK_ACCOUNT', ''),
            'holder': os.getenv('BANK_HOLDER', ''),
        },
    }


def deliver_otp(channel, destination, code):
    if channel == 'PHONE' and enabled('ENABLE_DEMO_OTP'):
        return {'message': 'Kode pengujian lokal; tidak dikirim ke kontak.', 'demo_code': code}
    if channel == 'EMAIL':
        mail = verification_email(os.environ['SMTP_FROM'], destination, code, support=os.getenv('SUPPORT_EMAIL',''))
        send_email(mail)
    else:
        url = os.environ['PHONE_OTP_WEBHOOK_URL']
        if not url.startswith('https://'):
            raise ValueError('Phone delivery requires HTTPS')
        response = httpx.post(url, json={'to': destination, 'code': code, 'expires_in': 300},
                              headers={'Authorization': 'Bearer ' + os.environ['PHONE_OTP_WEBHOOK_TOKEN']}, timeout=15)
        response.raise_for_status()
    return {'message': 'Kode verifikasi telah dikirim. Berlaku selama 5 menit.'}


def send_email(message):
    """Send through the configured SMTP server; callers handle persistence/retry."""
    host = os.environ['SMTP_HOST']
    encryption = os.getenv('SMTP_ENCRYPTION', '').strip().lower()
    if not encryption:
        encryption = 'ssl' if os.getenv('SMTP_SECURE', '').strip().lower() == 'true' else 'starttls'
    if encryption not in ('ssl', 'tls', 'starttls'):
        raise ValueError('SMTP_ENCRYPTION must be ssl, tls, or starttls')
    implicit_tls = encryption == 'ssl'
    port = int(os.getenv('SMTP_PORT') or ('465' if implicit_tls else '587'))
    context = ssl.create_default_context()
    transport = smtplib.SMTP_SSL if implicit_tls else smtplib.SMTP
    options = {'timeout': 15}
    if implicit_tls:
        options['context'] = context
    with transport(host, port, **options) as smtp:
        if not implicit_tls:
            smtp.starttls(context=context)
        if os.getenv('SMTP_USERNAME'):
            smtp.login(os.environ['SMTP_USERNAME'], os.environ['SMTP_PASSWORD'])
        smtp.send_message(message)
