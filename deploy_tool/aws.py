import boto3
import json
import uuid
import os
import paramiko
import time
import socket
from botocore.exceptions import ClientError
from scp import SCPClient
from .config import load_bucket_config, CONFIG_FILE

REGION = "ap-south-1"
KEY_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "livanshu-kp.pem"))

def generate_unique_bucket_name(prefix="static-site"):
    suffix = str(uuid.uuid4())[:8]
    return f"{prefix}-{suffix}"

def create_public_s3_bucket(prefix):
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
                break
        except (socket.timeout, ConnectionRefusedError, OSError):
            if time.time() - start_time > timeout:
                raise TimeoutError("❌ Timed out waiting for SSH.")
            print("🔄 Still waiting...")
            time.sleep(5)

def wait_for_docker(ssh, timeout=120):

    print("⏳ Waiting for Docker to be ready...")
    for i in range(timeout // 5):
        stdin, stdout, stderr = ssh.exec_command("sudo docker --version")
        out = stdout.read().decode()
        err = stderr.read().decode()
        if "Docker version" in out:
            print(f"✅ Docker is ready: {out.strip()}")
            return True
        time.sleep(5)
    raise Exception("❌ Docker did not become ready within timeout.")


def upload_and_run_on_ec2(public_ip, zip_path, framework):
    wait_for_ssh(public_ip)
    print("🔐 Connecting to EC2...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        private_key = paramiko.RSAKey.from_private_key_file(KEY_PATH)

        ssh.connect(
            hostname=public_ip,
            username='ec2-user',
            pkey=private_key
        )

        wait_for_docker(ssh)
        ssh.close()

        print("🔁 Reconnecting to EC2 for proper Docker permissions...")
        time.sleep(5)

        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        private_key = paramiko.RSAKey.from_private_key_file(KEY_PATH)
        ssh.connect(hostname=public_ip, username='ec2-user', pkey=private_key)

        print("📦 Uploading app.zip...")
        with SCPClient(ssh.get_transport()) as scp:
            scp.put(zip_path, "app.zip")

        print("⚙️ Running deployment commands...")

        # === 1. UNZIP ===
        print("💻 Running: unzip app.zip")
        stdin, stdout, stderr = ssh.exec_command("sudo unzip -o app.zip -d app", get_pty=True)
        exit_status = stdout.channel.recv_exit_status()
        print(stdout.read().decode())
        print(stderr.read().decode())
        if exit_status != 0:
            print("❌ Failed: unzip")
            return

        # === 2. DOCKER BUILD ===
        print("💻 Running: docker build")
        stdin, stdout, stderr = ssh.exec_command("sudo docker build -t myapp ./app", get_pty=True)
        exit_status = stdout.channel.recv_exit_status()
        print(stdout.read().decode())
        print(stderr.read().decode())
        if exit_status != 0:
            print("❌ Failed: docker build")
            return

        # === 3. DOCKER RUN ===
        print("💻 Running: docker run")
        stdin, stdout, stderr = ssh.exec_command("sudo docker run -d -p 80:3000 myapp", get_pty=True)
        exit_status = stdout.channel.recv_exit_status()
        print(stdout.read().decode())
        print(stderr.read().decode())
        if exit_status != 0:
            print("❌ Failed: docker run")
            return

        print(f"✅ Deployment complete! App should be live at: http://{public_ip}")

    finally:
        ssh.close()



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