"""Verify SMTP transport selection without sending email."""
import ssl
from unittest.mock import MagicMock

import pytest
import services


@pytest.fixture
def smtp_config(monkeypatch):
    monkeypatch.setenv('ENABLE_DEMO_OTP', 'false')
    monkeypatch.setenv('SMTP_HOST', 'smtp.example.test')
    monkeypatch.setenv('SMTP_FROM', 'noreply@example.test')
    monkeypatch.setenv('SMTP_USERNAME', 'test-user')
    monkeypatch.setenv('SMTP_PASSWORD', 'test-password')
    for name in ('SMTP_PORT', 'SMTP_ENCRYPTION', 'SMTP_SECURE'):
        monkeypatch.delenv(name, raising=False)
    implicit = MagicMock()
    explicit = MagicMock()
    monkeypatch.setattr(services.smtplib, 'SMTP_SSL', implicit)
    monkeypatch.setattr(services.smtplib, 'SMTP', explicit)
    return implicit, explicit


def test_ssl_configuration(smtp_config, monkeypatch):
    implicit, explicit = smtp_config
    monkeypatch.setenv('SMTP_ENCRYPTION', 'ssl')
    monkeypatch.setenv('SMTP_SECURE', 'true')
    monkeypatch.setenv('SMTP_PORT', '465')
    result = services.deliver_otp('EMAIL', 'customer@example.test', '123456')
    explicit.assert_not_called()
    assert implicit.call_args.args == ('smtp.example.test', 465)
    context = implicit.call_args.kwargs['context']
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname is True
    smtp = implicit.return_value.__enter__.return_value
    smtp.starttls.assert_not_called()
    smtp.login.assert_called_once_with('test-user', 'test-password')
    message = smtp.send_message.call_args.args[0]
    assert message['From'].addresses[0].addr_spec == 'noreply@example.test'
    assert message['To'] == 'customer@example.test'
    assert '123456' in message.get_body(preferencelist=('plain',)).get_content()
    assert 'demo_code' not in result


@pytest.mark.parametrize('encryption', ['starttls', 'tls', ''])
def test_starttls_configuration(smtp_config, monkeypatch, encryption):
    implicit, explicit = smtp_config
    monkeypatch.setenv('SMTP_ENCRYPTION', encryption)
    services.deliver_otp('EMAIL', 'customer@example.test', '123456')
    implicit.assert_not_called()
    assert explicit.call_args.args == ('smtp.example.test', 587)
    smtp = explicit.return_value.__enter__.return_value
    context = smtp.starttls.call_args.kwargs['context']
    assert context.check_hostname is True
    smtp.send_message.assert_called_once()


def test_secure_flag_selects_ssl(smtp_config, monkeypatch):
    implicit, explicit = smtp_config
    monkeypatch.setenv('SMTP_SECURE', 'true')
    services.deliver_otp('EMAIL', 'customer@example.test', '123456')
    explicit.assert_not_called()
    assert implicit.call_args.args[1] == 465


def test_invalid_encryption_does_not_connect(smtp_config, monkeypatch):
    implicit, explicit = smtp_config
    monkeypatch.setenv('SMTP_ENCRYPTION', 'none')
    with pytest.raises(ValueError, match='SMTP_ENCRYPTION'):
        services.deliver_otp('EMAIL', 'customer@example.test', '123456')
    implicit.assert_not_called()
    explicit.assert_not_called()


def test_email_uses_smtp_even_with_phone_demo_enabled(smtp_config, monkeypatch):
    implicit, explicit = smtp_config
    monkeypatch.setenv('ENABLE_DEMO_OTP', 'true')
    monkeypatch.setenv('APP_ENV', 'development')
    monkeypatch.setenv('SMTP_ENCRYPTION', 'ssl')
    result = services.deliver_otp('EMAIL', 'customer@example.test', '654321')
    explicit.assert_not_called()
    smtp = implicit.return_value.__enter__.return_value
    smtp.send_message.assert_called_once()
    message = smtp.send_message.call_args.args[0]
    html = message.get_body(preferencelist=('html',)).get_content()
    assert '654321' in html and 'cid:lamia-logo' in html
    assert '5 menit' in html and 'LAMIA' in html
    assert 'demo_code' not in result
    assert any(part.get('Content-ID') == '<lamia-logo@example.test>' for part in message.walk())


def test_verification_mime_roundtrip_has_inline_logo_and_small_html():
    from email.parser import BytesParser
    from email.policy import default
    from email_templates import verification_email
    mail=verification_email('noreply@example.test','customer@example.test','123456')
    parsed=BytesParser(policy=default).parsebytes(mail.as_bytes())
    html=parsed.get_body(preferencelist=('html',)).get_content()
    assert parsed.get_content_type()=='multipart/alternative'
    assert parsed.get_body(preferencelist=('plain',)) is not None
    assert '123456' in html and 'width:100%;max-width:600px' in html
    assert '<!--[if mso]>' in html
    assert 'display:flex' not in html and 'display:grid' not in html
    assert len(html.encode())<100_000
    logo=next(part for part in parsed.walk() if part.get('Content-ID')=='<lamia-logo@example.test>')
    assert logo.get_content_disposition()=='inline'
    assert logo.get_content_type()=='image/png'
    assert len(logo.get_payload(decode=True))<50_000
    assert 'cid:lamia-logo@example.test' in html
    assert parsed['Date'] and parsed['Message-ID']
