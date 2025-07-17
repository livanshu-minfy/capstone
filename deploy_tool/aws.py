import boto3
import json
import uuid
import os
from botocore.exceptions import ClientError

REGION = "ap-south-1"

def generate_unique_bucket_name(prefix="static-site"):
    suffix = str(uuid.uuid4())[:8]
    return f"{prefix}-{suffix}"

def create_public_s3_bucket(prefix):
    s3 = boto3.client('s3', region_name=REGION)
    bucket_name = generate_unique_bucket_name(prefix)

    try:
        # 1. Create bucket
        s3.create_bucket(
            Bucket=bucket_name,
            CreateBucketConfiguration={'LocationConstraint': REGION}
        )
        print(f"✅ Bucket '{bucket_name}' created in '{REGION}'")

        

        # 2. Attach bucket policy to allow public read access
        policy = {
            "Version": "2012-10-17",
            "Statement": [{
                "Sid": "PublicReadGetObject",
                "Effect": "Allow",
                "Principal": "*",
                "Action": ["s3:GetObject"],
                "Resource": f"arn:aws:s3:::{bucket_name}/*"
            }]
        }

        # 3. Disable all public access blocks
        s3.put_public_access_block(
            Bucket=bucket_name,
            PublicAccessBlockConfiguration={
                'BlockPublicAcls': False,
                'IgnorePublicAcls': False,
                'BlockPublicPolicy': False,
                'RestrictPublicBuckets': False
            }
        )

        s3.put_bucket_policy(
            Bucket=bucket_name,
            Policy=json.dumps(policy)
        )

        s3.put_bucket_website(
            Bucket = bucket_name,
            WebsiteConfiguration={
                'IndexDocument': {'Suffix': 'index.html'},
                'ErrorDocument': {'Key': 'index.html'}  # Good for SPA routing
            }
        )

        print("🌍 Public read access granted.")
        return bucket_name

    except ClientError as e:
        print(f"❌ AWS Error: {e}")
        return None

def delete_s3_bucket(bucket_name):
    s3 = boto3.resource("s3", region_name="ap-south-1")

    bucket = s3.Bucket(bucket_name)

    # Delete all objects (mandatory before deleting bucket)
    for obj in bucket.objects.all():
        obj.delete()

    # Delete bucket itself
    bucket.delete()
    print(f"✅ Deleted bucket: {bucket_name}")


def upload_to_s3(build_dir, bucket_name):
    s3 = boto3.client('s3')
    for root, dirs, files in os.walk(build_dir):
        for file in files:
            local_path = os.path.join(root, file)
            relative_path = os.path.relpath(local_path, build_dir)
            s3.upload_file(local_path, bucket_name, relative_path)

def enable_static_website(bucket_name):
    s3 = boto3.client('s3')
    s3.put_bucket_website(
        Bucket=bucket_name,
        WebsiteConfiguration={
            'IndexDocument': {'Suffix': 'index.html'},
            'ErrorDocument': {'Key': 'index.html'}
        }
    )
def get_website_url(bucket, region):
    return f"http://{bucket}.s3-website.{region}.amazonaws.com"