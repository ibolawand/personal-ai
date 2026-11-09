"""The Gmail app password, from the system keyring entry MyNotion saved (service "MyNotion Mail", account = the
address; see MyNotion/note/src/mail/account.ts). Never stored anywhere else."""
try:
    import secretstorage
except ImportError:                     # pragma: no cover
    secretstorage = None

KEYRING_SERVICE = "MyNotion Mail"


def mail_password(address: str) -> str | None:
    if not address or secretstorage is None:
        return None
    try:
        conn = secretstorage.dbus_init()
        col = secretstorage.get_default_collection(conn)
        if col.is_locked():
            col.unlock()
        for item in col.search_items({"service": KEYRING_SERVICE, "username": address}):
            secret = item.get_secret()
            return secret.decode() if isinstance(secret, bytes) else secret
    except Exception as e:
        print(f"[Mail] keyring not available: {e}")
    return None
