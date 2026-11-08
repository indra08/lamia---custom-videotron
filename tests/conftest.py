"""Keep imports and API tests isolated from operator data."""
import os
from tempfile import TemporaryDirectory

_test_storage = TemporaryDirectory(prefix='vistara-tests-')
os.environ['DB_PATH'] = os.path.join(_test_storage.name, 'initial.db')

import pytest
import app as application
import services
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(application, 'DB', tmp_path / 'test.db')
    monkeypatch.setattr(application, 'UPLOAD', tmp_path / 'uploads')
    application.UPLOAD.mkdir()
    monkeypatch.setenv('ENABLE_DEMO_OTP', 'true')
    monkeypatch.setenv('ENABLE_DEMO_PAYMENTS', 'true')
    monkeypatch.setenv('APP_ENV', 'development')
    monkeypatch.setenv('SMTP_FROM', 'noreply@example.test')
    # Isolate delivery during API tests; never send email to fixture addresses.
    monkeypatch.setattr(application, 'deliver_otp', lambda channel, destination, code: {'message':'Isolated test delivery', 'demo_code':code})
    monkeypatch.setattr(services, 'send_email', lambda message: None)
    application.init()
    with TestClient(application.app) as client:
        yield client
