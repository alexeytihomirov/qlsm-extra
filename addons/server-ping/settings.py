"""Settings of the server-ping addon: the UDP port and the shared DTLS certificate.

One key pair for every host (spec section 4): the browser checks the server's DTLS
fingerprint against a single value in the ql-tournament env, so every ql-ping-echo
presents the same certificate. ql-ping-echo never creates it; generate_cert_pem() does,
once, and the playbook writes it to each host.

PEM layout ql-ping-echo loads: an "EC PRIVATE KEY" block (P-256) and its "CERTIFICATE".
"""
import datetime
import json
from pathlib import Path

ADDON_DIR = Path(__file__).resolve().parent

DEFAULT_PORT = '28111'
PORT_MIN = 1024     # the service runs as an unprivileged user without capabilities
PORT_MAX = 65535
CERT_DAYS = 3650
CERT_NAME = 'ql-ping-echo'


def addon_version():
    manifest = json.loads((ADDON_DIR / 'qlsm-addon.json').read_text(encoding='utf-8'))
    return manifest['version']


def validate_port(raw):
    """The port as a string of digits, or ValueError."""
    message = f'port must be a whole number from {PORT_MIN} to {PORT_MAX}.'
    if isinstance(raw, bool) or not isinstance(raw, (int, str)):
        raise ValueError(message)
    text = str(raw).strip()
    if not (text.isascii() and text.isdigit()):
        raise ValueError(message)
    number = int(text)
    if not PORT_MIN <= number <= PORT_MAX:
        raise ValueError(message)
    return str(number)


def generate_cert_pem(now=None):
    """A new P-256 key and a self-signed certificate valid for CERT_DAYS, as one PEM text."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.x509.oid import NameOID

    now = now or datetime.datetime.now(datetime.timezone.utc)
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, CERT_NAME)])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=CERT_DAYS + 1))
        .sign(key, hashes.SHA256())
    )
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,  # "EC PRIVATE KEY", what ql-ping-echo reads
        serialization.NoEncryption(),
    ).decode('ascii')
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode('ascii')
    return key_pem + cert_pem


def fingerprint(pem):
    """SHA-256 of the certificate as upper-case hex bytes joined by colons (what the SDP
    carries and ql-ping-echo prints). ValueError when the PEM is not a matching P-256
    key + certificate pair."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    if not isinstance(pem, str) or not pem.strip():
        raise ValueError('No DTLS certificate yet.')
    data = pem.encode('ascii', 'replace')
    try:
        cert = x509.load_pem_x509_certificate(data)
        key = serialization.load_pem_private_key(data, password=None)
    except (ValueError, TypeError) as e:
        raise ValueError(f'The stored DTLS certificate is not usable: {e}') from None
    if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
        raise ValueError('The stored DTLS key is not a P-256 key.')
    if key.public_key().public_numbers() != cert.public_key().public_numbers():
        raise ValueError('The stored DTLS key does not match its certificate.')
    return ':'.join(f'{b:02X}' for b in cert.fingerprint(hashes.SHA256()))
