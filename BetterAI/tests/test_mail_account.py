import types

import pytest

from Engines import MailAccount


class Item:
    def __init__(self, secret):
        self.secret = secret

    def get_secret(self):
        return self.secret


def fake_secretstorage(items, fail=False):
    def dbus_init():
        if fail:
            raise RuntimeError("no Secret Service")
        return object()

    col = types.SimpleNamespace(is_locked=lambda: False, unlock=lambda: None,
                                search_items=lambda attrs: [Item(s) for a, s in items if a == attrs])
    return types.SimpleNamespace(dbus_init=dbus_init, get_default_collection=lambda conn: col)


def test_reads_what_mynotion_stored(monkeypatch):
    monkeypatch.setattr(MailAccount, "secretstorage", fake_secretstorage(
        [({"service": "MyNotion Mail", "username": "a@gmail.com"}, b"abcdabcdabcdabcd")]))
    assert MailAccount.mail_password("a@gmail.com") == "abcdabcdabcdabcd"
    assert MailAccount.mail_password("b@gmail.com") is None


def test_no_keyring_is_not_an_error(monkeypatch):
    monkeypatch.setattr(MailAccount, "secretstorage", fake_secretstorage([], fail=True))
    assert MailAccount.mail_password("a@gmail.com") is None
