"""Private, version-aware S3 object storage with mandatory SSE-KMS and checksums."""

from __future__ import annotations

import asyncio
import base64
import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, cast
from urllib.parse import urlencode

import boto3
from botocore.config import Config


class ObjectStoreError(RuntimeError):
    """An object operation failed without exposing provider details."""


class ObjectStoreConfigurationError(ObjectStoreError):
    """The configured bucket does not meet the security contract."""


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    version_id: str
    content_sha256: str
    content_length: int


class SecureObjectStore(Protocol):
    async def is_ready(self) -> bool: ...

    async def put_quarantined(
        self,
        *,
        key: str,
        content: bytes,
        content_type: str,
        content_sha256: str,
    ) -> StoredObject: ...

    async def read_verified(
        self,
        *,
        key: str,
        version_id: str,
        expected_sha256: str,
        maximum_bytes: int,
    ) -> bytes: ...

    async def promote_clean(
        self,
        *,
        source_key: str,
        source_version_id: str,
        destination_key: str,
        content_type: str,
        content_sha256: str,
    ) -> StoredObject: ...

    async def delete_all_versions(self, *, key: str) -> int: ...


class _ResponseBody(Protocol):
    def read(self, amount: int | None = None) -> bytes: ...


class _S3Client(Protocol):
    def get_bucket_versioning(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def get_public_access_block(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def get_bucket_encryption(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def put_object(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def get_object(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def copy_object(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def list_object_versions(self, **kwargs: Any) -> Mapping[str, Any]: ...

    def delete_objects(self, **kwargs: Any) -> Mapping[str, Any]: ...


class S3EncryptedObjectStore:
    """Small-object adapter enforcing private versioned SSE-KMS storage."""

    def __init__(
        self,
        *,
        bucket: str,
        region: str,
        kms_key_id: str,
        endpoint_url: str | None = None,
        connect_timeout_seconds: float = 3.0,
        read_timeout_seconds: float = 10.0,
        client: _S3Client | None = None,
    ) -> None:
        self.bucket = bucket
        self.region = region
        self.kms_key_id = kms_key_id
        self._client = client or cast(
            _S3Client,
            boto3.client(
                "s3",
                region_name=region,
                endpoint_url=endpoint_url,
                config=Config(
                    connect_timeout=connect_timeout_seconds,
                    read_timeout=read_timeout_seconds,
                    retries={"max_attempts": 3, "mode": "standard"},
                    signature_version="s3v4",
                ),
            ),
        )

    async def is_ready(self) -> bool:
        try:
            return await asyncio.to_thread(self._verify_bucket_controls)
        except Exception:
            return False

    def _verify_bucket_controls(self) -> bool:
        versioning = self._client.get_bucket_versioning(Bucket=self.bucket)
        if versioning.get("Status") != "Enabled":
            raise ObjectStoreConfigurationError("object storage versioning must be enabled")

        public_access = self._client.get_public_access_block(Bucket=self.bucket)
        block = public_access.get("PublicAccessBlockConfiguration")
        required = (
            "BlockPublicAcls",
            "IgnorePublicAcls",
            "BlockPublicPolicy",
            "RestrictPublicBuckets",
        )
        if not isinstance(block, Mapping) or not all(block.get(name) is True for name in required):
            raise ObjectStoreConfigurationError(
                "all object storage public-access blocks are required"
            )

        encryption = self._client.get_bucket_encryption(Bucket=self.bucket)
        configuration = encryption.get("ServerSideEncryptionConfiguration")
        rules = configuration.get("Rules") if isinstance(configuration, Mapping) else None
        if not isinstance(rules, list) or not any(self._is_kms_rule(rule) for rule in rules):
            raise ObjectStoreConfigurationError("object storage default SSE-KMS is required")
        return True

    def _is_kms_rule(self, rule: object) -> bool:
        if not isinstance(rule, Mapping):
            return False
        default = rule.get("ApplyServerSideEncryptionByDefault")
        return isinstance(default, Mapping) and default.get("SSEAlgorithm") == "aws:kms"

    async def put_quarantined(
        self,
        *,
        key: str,
        content: bytes,
        content_type: str,
        content_sha256: str,
    ) -> StoredObject:
        self._validate_digest(content, content_sha256)
        try:
            response = await asyncio.to_thread(
                self._client.put_object,
                Bucket=self.bucket,
                Key=key,
                Body=content,
                ContentLength=len(content),
                ContentType=content_type,
                ChecksumSHA256=base64.b64encode(bytes.fromhex(content_sha256)).decode("ascii"),
                ServerSideEncryption="aws:kms",
                SSEKMSKeyId=self.kms_key_id,
                BucketKeyEnabled=True,
                Metadata={"content-sha256": content_sha256, "stage": "quarantine"},
                Tagging=urlencode({"stage": "quarantine"}),
            )
            version_id = response.get("VersionId")
            if not isinstance(version_id, str) or not version_id:
                raise ObjectStoreConfigurationError("versioned object response is required")
            return StoredObject(
                key=key,
                version_id=version_id,
                content_sha256=content_sha256,
                content_length=len(content),
            )
        except ObjectStoreError:
            raise
        except Exception as exc:
            raise ObjectStoreError("quarantine object upload failed") from exc

    async def read_verified(
        self,
        *,
        key: str,
        version_id: str,
        expected_sha256: str,
        maximum_bytes: int,
    ) -> bytes:
        try:
            response = await asyncio.to_thread(
                self._client.get_object,
                Bucket=self.bucket,
                Key=key,
                VersionId=version_id,
                ChecksumMode="ENABLED",
            )
            length = response.get("ContentLength")
            if not isinstance(length, int) or length < 0 or length > maximum_bytes:
                raise ObjectStoreError("stored object length is outside the approved limit")
            if response.get("ServerSideEncryption") != "aws:kms":
                raise ObjectStoreError("stored object is not protected by SSE-KMS")
            body = cast(_ResponseBody, response.get("Body"))
            content = await asyncio.to_thread(body.read, maximum_bytes + 1)
            if len(content) != length or len(content) > maximum_bytes:
                raise ObjectStoreError("stored object length verification failed")
            self._validate_digest(content, expected_sha256)
            return content
        except ObjectStoreError:
            raise
        except Exception as exc:
            raise ObjectStoreError("verified object download failed") from exc

    async def promote_clean(
        self,
        *,
        source_key: str,
        source_version_id: str,
        destination_key: str,
        content_type: str,
        content_sha256: str,
    ) -> StoredObject:
        try:
            response = await asyncio.to_thread(
                self._client.copy_object,
                Bucket=self.bucket,
                Key=destination_key,
                CopySource={
                    "Bucket": self.bucket,
                    "Key": source_key,
                    "VersionId": source_version_id,
                },
                ContentType=content_type,
                MetadataDirective="REPLACE",
                Metadata={"content-sha256": content_sha256, "stage": "released"},
                TaggingDirective="REPLACE",
                Tagging=urlencode({"stage": "released"}),
                ChecksumAlgorithm="SHA256",
                ServerSideEncryption="aws:kms",
                SSEKMSKeyId=self.kms_key_id,
                BucketKeyEnabled=True,
            )
            version_id = response.get("VersionId")
            if not isinstance(version_id, str) or not version_id:
                raise ObjectStoreConfigurationError("versioned object response is required")
            return StoredObject(
                key=destination_key,
                version_id=version_id,
                content_sha256=content_sha256,
                content_length=0,
            )
        except ObjectStoreError:
            raise
        except Exception as exc:
            raise ObjectStoreError("clean object promotion failed") from exc

    async def delete_all_versions(self, *, key: str) -> int:
        try:
            return await asyncio.to_thread(self._delete_all_versions_sync, key)
        except ObjectStoreError:
            raise
        except Exception as exc:
            raise ObjectStoreError("versioned object deletion failed") from exc

    def _delete_all_versions_sync(self, key: str) -> int:
        key_marker: str | None = None
        version_marker: str | None = None
        deleted = 0
        while True:
            parameters: dict[str, object] = {"Bucket": self.bucket, "Prefix": key}
            if key_marker is not None:
                parameters["KeyMarker"] = key_marker
            if version_marker is not None:
                parameters["VersionIdMarker"] = version_marker
            page = self._client.list_object_versions(**parameters)
            candidates: list[dict[str, str]] = []
            for group in ("Versions", "DeleteMarkers"):
                entries = page.get(group, [])
                if not isinstance(entries, list):
                    raise ObjectStoreError("object version listing is malformed")
                for entry in entries:
                    if not isinstance(entry, Mapping) or entry.get("Key") != key:
                        continue
                    version_id = entry.get("VersionId")
                    if isinstance(version_id, str) and version_id:
                        candidates.append({"Key": key, "VersionId": version_id})
            if candidates:
                response = self._client.delete_objects(
                    Bucket=self.bucket,
                    Delete={"Objects": candidates, "Quiet": False},
                )
                errors = response.get("Errors")
                if isinstance(errors, list) and errors:
                    raise ObjectStoreError("one or more object versions could not be deleted")
                deleted += len(candidates)
            if page.get("IsTruncated") is not True:
                break
            next_key = page.get("NextKeyMarker")
            next_version = page.get("NextVersionIdMarker")
            if not isinstance(next_key, str) or not isinstance(next_version, str):
                raise ObjectStoreError("object version pagination markers are missing")
            key_marker = next_key
            version_marker = next_version
        return deleted

    @staticmethod
    def _validate_digest(content: bytes, expected_sha256: str) -> None:
        if len(expected_sha256) != 64 or hashlib.sha256(content).hexdigest() != expected_sha256:
            raise ObjectStoreError("object SHA-256 verification failed")
