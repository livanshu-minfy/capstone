import boto3
import json
import uuid
import os
import time
import socket
import subprocess
import shlex
from botocore.exceptions import ClientError
from .config import load_bucket_config, CONFIG_FILE

REGION = "ap-south-1"
KEY_PATH = "./livanshu-kp.pem"
os.chmod(KEY_PATH, 0o400)
REMOTE_USER = "ec2-user"

def generate_unique_bucket_name(prefix="static-site"):
    suffix = str(uuid.uuid4())[:8]
    return f"{prefix}-{suffix}"

def create_public_s3_bucket(prefix, region= "ap-south-1"):
    s3 = boto3.client('s3', region_name=REGION)
    bucket_name = generate_unique_bucket_name(prefix)

    try:
        s3.create_bucket(
            Bucket=bucket_name,
            CreateBucketConfiguration={'LocationConstraint': REGION}
        )
        print(f"✅ Bucket '{bucket_name}' created in '{REGION}'")

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

        s3.put_public_access_block(
            Bucket=bucket_name,
            PublicAccessBlockConfiguration={
                'BlockPublicAcls': False,
                'IgnorePublicAcls': False,
                'BlockPublicPolicy': False,
                'RestrictPublicBuckets': False
            }
        )

        s3.put_bucket_policy(Bucket=bucket_name, Policy=json.dumps(policy))

        s3.put_bucket_website(
            Bucket=bucket_name,
            WebsiteConfiguration={
                'IndexDocument': {'Suffix': 'index.html'},
                'ErrorDocument': {'Key': 'index.html'}
            }
        )
        print("🌍 Public read access granted.")
        return bucket_name

    except ClientError as e:
        print(f"❌ AWS Error: {e}")
        return None

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

def provision_ec2_with_docker(environment):
    ec2 = boto3.resource('ec2', region_name=REGION)

    sg = ec2.create_security_group(
        GroupName=f"{environment}-sg",
        Description='Allow HTTP and SSH'
    )

    sg.authorize_ingress(IpPermissions=[
        {
            'IpProtocol': 'tcp',
            'FromPort': 22,
            'ToPort': 22,
            'IpRanges': [{'CidrIp': '0.0.0.0/0'}],
        },
        {
            'IpProtocol': 'tcp',
            'FromPort': 80,
            'ToPort': 80,
            'IpRanges': [{'CidrIp': '0.0.0.0/0'}],
        }
    ])

    user_data =  """#!/bin/bash
exec > /var/log/user-data.log 2>&1

# Update system and install required packages
yum update -y
yum install -y unzip docker

# Start Docker and enable it on boot
systemctl start docker
systemctl enable docker

# Add ec2-user to docker group
usermod -aG docker ec2-user

# Wait for Docker daemon to fully initialize
sleep 15

# Force a Docker command to ensure it's responding
docker info || (echo "Docker failed to start" && exit 1)

echo "✅ Docker is ready"
"""

    instance = ec2.create_instances(
        ImageId='ami-0b09627181c8d5778',
        InstanceType='t2.micro',
        MinCount=1,
        MaxCount=1,
        KeyName='livanshu-kp',
        SecurityGroupIds=[sg.id],
        UserData=user_data
    )[0]

    print("🚀 Waiting for EC2 instance to initialize...")
    instance.wait_until_running()
    instance.reload()

    with open("ec2_instance_id.txt", "w") as f:
        f.write(instance.id)

    with open("security_group_id.txt", "w") as f:
        f.write(sg.id)

    print(f"✅ Instance ready: {instance.public_ip_address}")
    return instance.public_ip_address

def wait_for_ssh(ip, port=22, timeout=300):
    """Waits until SSH port is available on the given IP."""
    print("⏳ Waiting for SSH to become available...")
    start_time = time.time()
    while True:
        try:
            with socket.create_connection((ip, port), timeout=5):
                print("✅ SSH is ready!")
                return
        except (socket.timeout, ConnectionRefusedError, OSError):
            if time.time() - start_time > timeout:
                raise TimeoutError("❌ Timed out waiting for SSH.")
            print("🔄 Still waiting for SSH...")
            time.sleep(5)

def wait_for_docker(ip, timeout=120):
    """Waits until Docker is ready inside EC2 instance."""
    print("⏳ Waiting for Docker to be ready...")
    for _ in range(timeout // 5):
        result = subprocess.run(
            [
                "ssh",
                "-i", KEY_PATH,
                "-o", "StrictHostKeyChecking=no",
                "-o", "UserKnownHostsFile=/dev/null",
                f"{REMOTE_USER}@{ip}",
                "docker --version"
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        if "Docker version" in result.stdout:
            print(f"✅ Docker is ready: {result.stdout.strip()}")
            return
        time.sleep(5)
    raise Exception("❌ Docker did not become ready in time.")


def upload_file(ip, local_path, remote_path="app.zip"):
    """Uploads file to EC2 using SCP."""
    print(f"📦 Uploading {local_path} to EC2...")
    result = subprocess.run(
        [
            "scp",
            "-i", KEY_PATH,
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            local_path,
            f"{REMOTE_USER}@{ip}:{remote_path}"
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True
    )
    if result.returncode != 0:
        print(result.stderr)
        raise RuntimeError("❌ Failed to upload file.")
    else:
        print("✅ File uploaded.")


def run_ssh_command(ip, command):
    """Runs a single SSH command via subprocess without host key prompts."""
    ssh_command = [
        "ssh",
        "-i", KEY_PATH,
        "-o", "StrictHostKeyChecking=no",
        "-o", "UserKnownHostsFile=/dev/null",
        f"{REMOTE_USER}@{ip}",
        command
    ]

    print(f"💻 Running: {command}")
    process = subprocess.Popen(
        ssh_command,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        encoding='utf-8',
        errors='replace'
    )

    for line in process.stdout:
        print(line, end="")

    process.wait()
    if process.returncode != 0:
        raise RuntimeError(f"❌ Command failed: {command}")



def run_commands(ip, commands):
    for cmd in commands:
        run_ssh_command(ip, cmd)

def upload_and_run_on_ec2(public_ip, zip_path, framework=None):
    print(f"🚀 Starting deployment to EC2 {public_ip}...")

    wait_for_ssh(public_ip)
    wait_for_docker(public_ip)
    upload_file(public_ip, zip_path)

    commands = [
        "sudo systemctl start docker",
        "while ! sudo docker info > /dev/null 2>&1; do echo '⏳ Waiting for Docker daemon to start...'; sleep 2; done",
        "sudo unzip -o app.zip -d app",
        "cd app && sudo docker build -t myapp .",
        "sudo docker run -d -p 80:3000 myapp"
    ]
    run_commands(public_ip, commands)

    print(f"✅ Deployment complete! App should be live at: http://{public_ip}")


def delete_s3_bucket(bucket_name):
    s3 = boto3.resource("s3", region_name=REGION)
    bucket = s3.Bucket(bucket_name)
    for obj in bucket.objects.all():
        obj.delete()
    bucket.delete()
    print(f"✅ Deleted bucket: {bucket_name}")

def rollback_all_resources():
    ec2 = boto3.resource("ec2", region_name=REGION)

    if os.path.exists("ec2_instance_id.txt"):
        with open("ec2_instance_id.txt") as f:
            instance_id = f.read().strip()
        instance = ec2.Instance(instance_id)
        print(f"🛑 Terminating EC2: {instance_id}")
        instance.terminate()
        instance.wait_until_terminated()
        os.remove("ec2_instance_id.txt")
        print("✅ EC2 terminated.")

    if os.path.exists("security_group_id.txt"):
        with open("security_group_id.txt") as f:
            sg_id = f.read().strip()
        sg = ec2.SecurityGroup(sg_id)
        print(f"🔐 Deleting security group: {sg_id}")
        sg.delete()
        os.remove("security_group_id.txt")
        print("✅ Security group deleted.")

    state = load_bucket_config()
    if state:
        delete_s3_bucket(state["bucket"])
        print(f"🪣 Deleted S3 bucket: {state['bucket']}")
        CONFIG_FILE.unlink(missing_ok=True)
    else:
        print("⚠️ No S3 bucket found to delete.")