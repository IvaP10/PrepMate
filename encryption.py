import base64
import logging
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from config import settings

logger = logging.getLogger("encryption")

_fernet_instance = None

def _get_fernet() -> Fernet:
    global _fernet_instance
    if _fernet_instance is not None:
        return _fernet_instance

    master_key = settings.ENCRYPTION_MASTER_KEY
    if not master_key:
        raise RuntimeError("ENCRYPTION_MASTER_KEY is not configured")

    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=settings.ENCRYPTION_SALT.encode("utf-8"),
        info=b"fernet-key-derivation",
    )
    derived = hkdf.derive(master_key.encode("utf-8"))
    fernet_key = base64.urlsafe_b64encode(derived)
    _fernet_instance = Fernet(fernet_key)
    return _fernet_instance

def encrypt_field(plaintext: str) -> str:
    if not plaintext:
        return ""
    f = _get_fernet()
    encrypted = f.encrypt(plaintext.encode("utf-8"))
    return base64.urlsafe_b64encode(encrypted).decode("ascii")

def decrypt_field(ciphertext: str) -> str:
    if not ciphertext:
        return ""
    f = _get_fernet()
    raw = base64.urlsafe_b64decode(ciphertext.encode("ascii"))
    return f.decrypt(raw).decode("utf-8")
