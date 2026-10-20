"""Test the real S3 endpoint from the trusted publisher, without changing releases."""
import base64
import configparser
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
from urllib.parse import urlparse

import boto3
from botocore.exceptions import ClientError
from jwcrypto import jwe
from kserve_storage import Storage
from kserve_storage.confidential import JWEDecryptor


uri = urlparse(os.environ["MODEL_URI"])
bucket, key = uri.netloc, uri.path.lstrip("/")
client = boto3.client("s3", **Storage._get_s3_client_kwargs())
client.head_bucket(Bucket=bucket)
listed = client.list_objects_v2(Bucket=bucket, Prefix=key)
assert any(o["Key"] == key for o in listed["Contents"])
head = client.head_object(Bucket=bucket, Key=key)
assert head["Metadata"]["sha256"] == os.environ["EXPECTED_SHA256"]
print("S3_READER_PROBE_LIST_HEAD_PASS", flush=True)

for operation in ("put_object", "delete_object"):
    args = {"Bucket": bucket, "Key": key.rsplit("/", 1)[0]+"/reader-denied-probe"}
    if operation == "put_object":
        args["Body"] = b"must be denied"
    try:
        getattr(client, operation)(**args)
    except ClientError as error:
        assert error.response["ResponseMetadata"]["HTTPStatusCode"] == 403
    else:
        raise AssertionError("Reader incorrectly allowed "+operation)
print("S3_READER_WRITE_DELETE_DENIED", flush=True)
publisher_config = configparser.ConfigParser(interpolation=None)
publisher_config.read("/publisher-credentials/credentials")
publisher = boto3.client("s3", **Storage._get_s3_client_kwargs(),
                        **dict(publisher_config["default"]))
try:
    publisher.delete_object(Bucket=bucket, Key=key.rsplit("/", 1)[0]+"/writer-denied-probe")
except ClientError as error:
    assert error.response["ResponseMetadata"]["HTTPStatusCode"] == 403
else:
    raise AssertionError("Publisher incorrectly allowed object deletion")
print("S3_PUBLISHER_DELETE_DENIED", flush=True)

for name, overrides, expected in [
    ("INVALID_CREDENTIALS", {"AWS_ACCESS_KEY_ID": "invalid-test-access-key",
                            "AWS_SECRET_ACCESS_KEY": "invalid-test-secret"}, ("403", "AccessDenied", "InvalidAccessKeyId", "SignatureDoesNotMatch")),
    ("UNTRUSTED_CA", {"AWS_CA_BUNDLE": "/scripts/wrong-ca.crt"}, ("CERTIFICATE_VERIFY_FAILED", "certificate verify failed")),
]:
    result = subprocess.run(
        [sys.executable, "-c", "from kserve_storage import Storage; import os; Storage._download_s3(os.environ['MODEL_URI'], '/tmp/rejected-download')"],
        env={**os.environ, **overrides}, text=True, capture_output=True)
    assert result.returncode != 0 and any(x in result.stdout+result.stderr for x in expected), name+" did not fail for the expected reason"
    print("S3_PRODUCT_"+name+"_REJECTED", flush=True)

# Read one small JWE file from the published tar, not a synthetic substitute.
body = client.get_object(Bucket=bucket, Key=key)["Body"]
try:
    with tarfile.open(fileobj=body, mode="r|") as archive:
        member = next(m for m in archive if m.isfile() and m.size < 1024*1024 and m.name.endswith(".jwe"))
        assert Path(member.name).name == member.name
        encrypted = Path("/tmp")/member.name
        ciphertext = archive.extractfile(member).read()
        encrypted.write_bytes(ciphertext)
finally:
    body.close()
jwk = json.loads(Path("/keys/model-key.json").read_text())
model_key = base64.urlsafe_b64decode(jwk["k"]+"="*((-len(jwk["k"])) % 4))

class Resolver:
    def resolve_key(self, resource_id):
        assert resource_id == "publisher-verification-only"
        return model_key

decryptor = JWEDecryptor(Resolver(), "publisher-verification-only")
plain = decryptor.decrypt_file(encrypted)
inventory = {name: digest for digest, name in
             (line.split() for line in Path("/scripts/model.sha256").read_text().splitlines())}
assert hashlib.sha256(plain.read_bytes()).hexdigest() == inventory[plain.name]
original = plain.read_bytes()
parts = ciphertext.split(b".")
tag = bytearray(parts[-1])
tag[0] = ord("A") if tag[0] != ord("A") else ord("B")
parts[-1] = bytes(tag)
encrypted.write_bytes(b".".join(parts))
try:
    decryptor.decrypt_file(encrypted)
except jwe.InvalidJWEData:
    pass
else:
    raise AssertionError("Modified published JWE was accepted")
assert plain.read_bytes() == original
print("S3_PUBLISHED_JWE_TAMPER_REJECTED", flush=True)
