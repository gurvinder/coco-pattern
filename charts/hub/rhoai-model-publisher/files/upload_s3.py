"""Publish one encrypted release; verify the object bytes before activation."""
import hashlib
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlparse

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.config import Config
from botocore.exceptions import ClientError


def digest(stream):
    value = hashlib.sha256()
    while chunk := stream.read(8 * 1024 * 1024):
        value.update(chunk)
    return value.hexdigest()


def publish(path, uri, endpoint):
    parsed = urlparse(uri)
    assert parsed.scheme == "s3" and parsed.netloc
    key = parsed.path.lstrip("/")
    assert key.endswith("/qwen.tar") and len(key.split("/")) >= 3
    assert not parsed.query and not parsed.fragment and ".." not in key.split("/")
    assert endpoint.startswith("https://")
    client = boto3.client(
        "s3", endpoint_url=endpoint,
        verify=os.environ.get("AWS_CA_BUNDLE") or True,
        config=Config(s3={"addressing_style": "path"},
                      retries={"mode": "standard", "max_attempts": 3}),
    )
    with path.open("rb") as source:
        expected = digest(source)
    exists = False
    try:
        existing = client.head_object(Bucket=parsed.netloc, Key=key)
    except ClientError as error:
        if error.response["Error"]["Code"] not in ("404", "NoSuchKey", "NotFound"):
            raise
    else:
        # Retries may verify an already published byte-identical archive.
        assert existing.get("Metadata", {}).get("sha256") == expected, \
            "Release path already exists with different bytes; choose a new release ID"
        exists = True
    if not exists:
        print("S3_UPLOAD_STARTED", flush=True)
        client.upload_file(
            str(path), parsed.netloc, key,
            ExtraArgs={"Metadata": {"sha256": expected}, "ContentType": "application/x-tar"},
            Config=TransferConfig(multipart_threshold=64 * 1024 * 1024,
                                  multipart_chunksize=64 * 1024 * 1024,
                                  max_concurrency=2),
        )
    head = client.head_object(Bucket=parsed.netloc, Key=key)
    assert head["ContentLength"] == path.stat().st_size
    assert head["Metadata"]["sha256"] == expected
    print("S3_READBACK_STARTED", flush=True)
    body = client.get_object(Bucket=parsed.netloc, Key=key)["Body"]
    try:
        assert digest(body) == expected, "Published ciphertext checksum mismatch"
    finally:
        body.close()
    print("S3_PUBLICATION_VERIFIED " + json.dumps(
        {"uri": uri, "sha256": expected, "bytes": head["ContentLength"], "verified": True}
    ))


if __name__ == "__main__":
    publish(Path(sys.argv[1]), os.environ["MODEL_URI"], os.environ["AWS_ENDPOINT_URL"])
