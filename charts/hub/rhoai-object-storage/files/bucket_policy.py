"""Grant separate MCG publisher and reader accounts access to one model prefix."""
import json
import os

import boto3
from botocore.config import Config


def policy(bucket, prefix, publisher, reader):
    resource = "arn:aws:s3:::" + bucket
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "ProbeAndList",
                "Effect": "Allow",
                "Principal": {"AWS": [publisher, reader]},
                # The RHOAI initializer probes the bucket and lists the URI prefix.
                "Action": ["s3:ListBucket", "s3:GetBucketLocation"],
                "Resource": [resource],
            },
            {
                "Sid": "ReadCiphertext",
                "Effect": "Allow",
                "Principal": {"AWS": [publisher, reader]},
                "Action": ["s3:GetObject"],
                "Resource": [resource + "/" + prefix + "/*"],
            },
            {
                "Sid": "PublishCiphertext",
                "Effect": "Allow",
                "Principal": {"AWS": [publisher]},
                "Action": ["s3:PutObject", "s3:AbortMultipartUpload",
                           "s3:ListMultipartUploadParts"],
                "Resource": [resource + "/" + prefix + "/*"],
            },
        ],
    }


if __name__ == "__main__":
    client = boto3.client("s3", endpoint_url=os.environ["AWS_ENDPOINT_URL"],
                          verify=os.environ["AWS_CA_BUNDLE"],
                          config=Config(s3={"addressing_style": "path"}))
    expected = policy(os.environ["BUCKET_NAME"], os.environ["MODEL_PREFIX"],
                      os.environ["PUBLISHER_ACCOUNT"], os.environ["READER_ACCOUNT"])
    client.put_bucket_policy(Bucket=os.environ["BUCKET_NAME"],
                             Policy=json.dumps(expected))
    actual = json.loads(client.get_bucket_policy(Bucket=os.environ["BUCKET_NAME"])["Policy"])
    assert actual == expected, "Bucket policy readback differs"
    print("S3_BUCKET_POLICY_READY", flush=True)
