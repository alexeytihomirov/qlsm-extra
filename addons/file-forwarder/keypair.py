"""The install-wide SFTP key: one ed25519 pair per qlsm install.

Generated with `cryptography` (a declared qlsm dependency, requirements.txt)
the first time it is needed, stored in the addon's own settings
(`sftp_private_key` secret, `sftp_public_key` plain). Only the public half is
ever returned or logged. The private half is the source of truth: the public
one is re-derived from it whenever it is missing or does not match, and a key
that is already stored is never replaced, because the VPS trusts exactly that
key (replacing it is a deliberate rotation, done by clearing the setting).
"""
import logging

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

PRIVATE_KEY_SETTING = 'sftp_private_key'
PUBLIC_KEY_SETTING = 'sftp_public_key'
KEY_COMMENT = 'qlsm-file-forwarder'

log = logging.getLogger('qlsm.addon.file-forwarder')


def _public_line(private_key):
    blob = private_key.public_key().public_bytes(
        serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH,
    ).decode('ascii')
    return f'{blob} {KEY_COMMENT}'


def _generate():
    key = Ed25519PrivateKey.generate()
    private_text = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.OpenSSH,
        serialization.NoEncryption(),
    ).decode('ascii')
    return private_text, _public_line(key)


def _derive_public(private_text):
    try:
        key = serialization.load_ssh_private_key(private_text.encode('ascii'), password=None)
    except Exception:
        # Deliberately not chained or formatted with the original error: some
        # parser messages quote the input.
        raise ValueError('the stored SFTP private key cannot be read; clear it to '
                         'generate a new one (and replace the key line on the VPS)') from None
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError('the stored SFTP private key is not an ed25519 key')
    return _public_line(key)


def ensure_keypair(settings):
    """Return the install's public key, generating the pair on first use.

    `settings` is the addon's ctx.settings (get/set by scope).
    """
    values = settings.get('global', 0)
    private_text = (values.get(PRIVATE_KEY_SETTING) or '').strip()
    stored_public = (values.get(PUBLIC_KEY_SETTING) or '').strip()

    if not private_text:
        private_text, public = _generate()
        settings.set('global', 0, {PRIVATE_KEY_SETTING: private_text, PUBLIC_KEY_SETTING: public})
        log.info('file-forwarder: generated the install SFTP key, public half: %s', public)
        return public

    public = _derive_public(private_text)
    if stored_public.split()[:2] != public.split()[:2]:
        settings.set('global', 0, {PUBLIC_KEY_SETTING: public})
        log.info('file-forwarder: re-derived the public SFTP key from the stored private key')
        return public
    return stored_public
