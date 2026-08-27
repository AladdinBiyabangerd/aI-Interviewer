"""Versioned application keyring and authenticated field encryption."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import os
import re
from dataclasses import dataclass
from typing import Any, Literal, cast

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from pydantic import SecretStr

KeyPurpose = Literal["field_encryption", "manifest_hmac", "subject_hmac"]
_KEY_ID_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,63}$")
_SUPPORTED_PURPOSES: frozenset[str] = frozenset(
    {"field_encryption", "manifest_hmac", "subject_hmac"}
)


class KeyringError(ValueError):
    """Keyring material is malformed, incomplete, or cannot decrypt a value."""


@dataclass(frozen=True, slots=True)
class EncryptedValue:
    key_id: str
    nonce: bytes
    ciphertext: bytes


class ApplicationKeyring:
    """Immutable multi-purpose keyring supporting safe key rotation."""

    def __init__(
        self,
        *,
        active: dict[KeyPurpose, str],
        keys: dict[str, tuple[KeyPurpose, bytes]],
    ) -> None:
        for purpose in cast(tuple[KeyPurpose, ...], tuple(_SUPPORTED_PURPOSES)):
            key_id = active.get(purpose)
            if key_id is None or key_id not in keys or keys[key_id][0] != purpose:
                raise KeyringError(f"keyring requires an active {purpose} key")
        self._active = dict(active)
        self._keys = dict(keys)

    @classmethod
    def from_secret(cls, secret: SecretStr) -> ApplicationKeyring:
        try:
            raw_document = json.loads(secret.get_secret_value())
        except (json.JSONDecodeError, TypeError) as exc:
            raise KeyringError("privacy keyring must be a JSON object") from exc
        if not isinstance(raw_document, dict):
            raise KeyringError("privacy keyring must be a JSON object")
        document = cast(dict[str, Any], raw_document)
        if document.get("version") != 1:
            raise KeyringError("privacy keyring version must be 1")
        raw_active = document.get("active")
        raw_keys = document.get("keys")
        if not isinstance(raw_active, dict) or not isinstance(raw_keys, list):
            raise KeyringError("privacy keyring requires active and keys entries")

        active_values = cast(dict[str, object], raw_active)
        active: dict[KeyPurpose, str] = {}
        for purpose in _SUPPORTED_PURPOSES:
            value = active_values.get(purpose)
            if not isinstance(value, str) or not _KEY_ID_PATTERN.fullmatch(value):
                raise KeyringError(f"invalid active key id for {purpose}")
            active[cast(KeyPurpose, purpose)] = value

        keys: dict[str, tuple[KeyPurpose, bytes]] = {}
        for entry in cast(list[object], raw_keys):
            if not isinstance(entry, dict):
                raise KeyringError("privacy key entries must be objects")
            key_id = entry.get("id")
            entry_purpose = entry.get("purpose")
            encoded = entry.get("material")
            if (
                not isinstance(key_id, str)
                or not _KEY_ID_PATTERN.fullmatch(key_id)
                or entry_purpose not in _SUPPORTED_PURPOSES
                or not isinstance(encoded, str)
                or key_id in keys
            ):
                raise KeyringError("privacy key entry is invalid or duplicated")
            try:
                material = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise KeyringError("privacy key material must be canonical base64") from exc
            if base64.b64encode(material).decode("ascii") != encoded:
                raise KeyringError("privacy key material must be canonical base64")
            if len(material) != 32:
                raise KeyringError("privacy keys must contain exactly 32 decoded bytes")
            keys[key_id] = (cast(KeyPurpose, entry_purpose), material)
        if set(active.values()) - set(keys):
            raise KeyringError("an active privacy key is missing from keys")
        return cls(active=active, keys=keys)

    def active_key_id(self, purpose: KeyPurpose) -> str:
        return self._active[purpose]

    def encrypt_field(self, plaintext: str, *, aad: bytes) -> EncryptedValue:
        if not plaintext:
            raise ValueError("plaintext must not be empty")
        key_id = self._active["field_encryption"]
        nonce = os.urandom(12)
        ciphertext = AESGCM(self._keys[key_id][1]).encrypt(nonce, plaintext.encode(), aad)
        return EncryptedValue(key_id=key_id, nonce=nonce, ciphertext=ciphertext)

    def decrypt_field(self, value: EncryptedValue, *, aad: bytes) -> str:
        key = self._keys.get(value.key_id)
        if key is None or key[0] != "field_encryption":
            raise KeyringError("field encryption key is unavailable")
        try:
            plaintext = AESGCM(key[1]).decrypt(value.nonce, value.ciphertext, aad)
            return plaintext.decode("utf-8")
        except (InvalidTag, UnicodeDecodeError) as exc:
            raise KeyringError("encrypted field authentication failed") from exc

    def hmac_digest(self, purpose: Literal["manifest_hmac", "subject_hmac"], data: bytes) -> str:
        key_id = self._active[purpose]
        return hmac.new(self._keys[key_id][1], data, hashlib.sha256).hexdigest()

    def verify_hmac(
        self,
        purpose: Literal["manifest_hmac", "subject_hmac"],
        *,
        key_id: str,
        data: bytes,
        digest: str,
    ) -> bool:
        key = self._keys.get(key_id)
        if key is None or key[0] != purpose:
            return False
        expected = hmac.new(key[1], data, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, digest)
