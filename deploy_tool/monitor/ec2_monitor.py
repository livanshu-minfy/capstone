import boto3
import time
from deploy_tool.monitor.monitor_config import KEY_PATH


REGION = "ap-south-1"
AMI_ID = "ami-0b09627181c8d5778" 

def provision_monitoring_instance(instance_type):
    ec2 = boto3.resource("ec2", region_name=REGION)

    # Create security group
    sg = ec2.create_security_group(
        GroupName="monitoring-sg",
        Description="Allow Grafana and Prometheus ports"
    )

    sg.authorize_ingress(IpPermissions=[
        {
            'IpProtocol': 'tcp',
            'FromPort': 22,
            'ToPort': 22,
            'IpRanges': [{'CidrIp': '0.0.0.0/0'}]
        },
        {
            'IpProtocol': 'tcp',
            'FromPort': 3000,
            'ToPort': 3000,
            'IpRanges': [{'CidrIp': '0.0.0.0/0'}]  # Grafana
        },
        {
            'IpProtocol': 'tcp',
            'FromPort': 9090,
            'ToPort': 9090,
            'IpRanges': [{'CidrIp': '0.0.0.0/0'}]  # Prometheus
        }
    ])

    user_data_script = """#!/bin/bash
        exec > /var/log/user-data.log 2>&1

        # Update & install Docker
        yum update -y
        yum install -y docker git

        # Start Docker service
        systemctl start docker
        systemctl enable docker
        usermod -aG docker ec2-user

        # Wait for Docker to be ready
        sleep 10

        # Run Prometheus
        docker run -d --name prometheus -p 9090:9090 prom/prometheus

        # Run Grafana
        docker run -d --name grafana -p 3000:3000 grafana/grafana
        """

    instance = ec2.create_instances(
        ImageId=AMI_ID,
        InstanceType=instance_type,
        KeyName="livanshu-kp",  # 🔐 Update if keypair name changes
        MinCount=1,
        MaxCount=1,
        SecurityGroupIds=[sg.id],
        UserData=user_data_script
    )[0]

    print("⏳ Waiting for instance to run...")
    instance.wait_until_running()
    instance.reload()

    print(f"✅ Monitoring stack deployed at: http://{instance.public_ip_address}:3000 (Grafana)")
    print(f"📊 Prometheus endpoint: http://{instance.public_ip_address}:9090")
