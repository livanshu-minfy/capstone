import boto3
import time
REGION = "ap-south-1"
from deploy_tool.monitor.monitor_config import MONITOR_INSTANCE_NAME, PROMETHEUS_PORT, GRAFANA_PORT

def monitor_init():
    ec2 = boto3.resource('ec2', region_name=REGION)

    print("🚀 Launching EC2 instance for monitoring...")

    user_data_script = f"""#!/bin/bash
exec > /var/log/user-data.log 2>&1

yum update -y
amazon-linux-extras install docker -y
service docker start
usermod -a -G docker ec2-user

docker run -d --name prometheus -p {PROMETHEUS_PORT}:9090 prom/prometheus
docker run -d --name grafana -p {GRAFANA_PORT}:3000 grafana/grafana
"""

    instance = ec2.create_instances(
        ImageId="ami-0c02fb55956c7d316",
        MinCount=1,
        MaxCount=1,
        InstanceType="t3.micro",
        KeyName="livanshu-kp",
        TagSpecifications=[{
            'ResourceType': 'instance',
            'Tags': [{'Key': 'Name', 'Value': MONITOR_INSTANCE_NAME}]
        }],
        SecurityGroups=["default"],
        UserData=user_data_script  # ✅ Must be set here
    )[0]

    instance.wait_until_running()
    instance.reload()

    public_ip = instance.public_ip_address
    print(f"🟢 Instance ready at: {public_ip}")
    print("⏳ Waiting for Prometheus and Grafana to start...")
    time.sleep(60)

    print(f"✅ Monitoring setup complete.")
    print(f"🔗 Prometheus: http://{public_ip}:{PROMETHEUS_PORT}")
    print(f"🔗 Grafana: http://{public_ip}:{GRAFANA_PORT}")
