"""Unit tests for the lead email transport."""
from email.message import EmailMessage

from api import lead


class _FakeSMTP:
    instances = []

    def __init__(self, host, port, **kwargs):
        self.host = host
        self.port = port
        self.kwargs = kwargs
        self.calls = []
        self.message = None
        self.__class__.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def ehlo(self):
        self.calls.append("ehlo")

    def starttls(self, **_kwargs):
        self.calls.append("starttls")

    def login(self, username, password):
        self.calls.append(("login", username, password))

    def send_message(self, message: EmailMessage):
        self.calls.append("send_message")
        self.message = message


def _set_common_env(monkeypatch):
    monkeypatch.setenv("LEAD_SMTP_HOST", "smtp.example.test")
    monkeypatch.setenv("LEAD_SMTP_PORT", "587")
    monkeypatch.setenv("LEAD_SMTP_USER", "project-123")
    monkeypatch.setenv("LEAD_SMTP_PASSWORD", "secret")
    monkeypatch.setenv("LEAD_FROM_EMAIL", "info@aptekaa.ru")


def test_send_email_uses_starttls_for_unisender(monkeypatch):
    _FakeSMTP.instances.clear()
    _set_common_env(monkeypatch)
    monkeypatch.setenv("LEAD_SMTP_SECURITY", "starttls")
    monkeypatch.setattr(lead.smtplib, "SMTP", _FakeSMTP)

    lead._send_email("Новая заявка", "Текст заявки")

    smtp = _FakeSMTP.instances[-1]
    assert (smtp.host, smtp.port) == ("smtp.example.test", 587)
    assert smtp.calls == [
        "ehlo",
        "starttls",
        "ehlo",
        ("login", "project-123", "secret"),
        "send_message",
    ]
    assert smtp.message["From"] == "info@aptekaa.ru"
    assert smtp.message["To"] == "info@aptekaa.ru"


def test_send_email_keeps_legacy_ssl_mode(monkeypatch):
    _FakeSMTP.instances.clear()
    _set_common_env(monkeypatch)
    monkeypatch.setenv("LEAD_SMTP_SECURITY", "ssl")
    monkeypatch.setattr(lead.smtplib, "SMTP_SSL", _FakeSMTP)

    lead._send_email("Новая заявка", "Текст заявки")

    smtp = _FakeSMTP.instances[-1]
    assert smtp.calls == [
        ("login", "project-123", "secret"),
        "send_message",
    ]
