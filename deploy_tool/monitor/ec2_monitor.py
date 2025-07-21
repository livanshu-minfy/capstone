import boto3
import time
import json
import os
from pathlib import Path
from deploy_tool.monitor.monitor_config import KEY_PATH  # assuming KEY_PATH is used elsewhere or future

REGION = "ap-south-1"
AMI_ID = "ami-0b09627181c8d5778"
CONFIG_PATH = Path.home() / ".deploy_tool" / "monitor_instance.json"

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
        },
        {
            'IpProtocol': 'tcp',
            'FromPort': 9100,
            'ToPort': 9100,
            'IpRanges': [{'CidrIp': '0.0.0.0/0'}]  # Node Exporter
        }
    ])

    user_data_script = """#!/bin/bash
exec > /var/log/user-data.log 2>&1

# Update and install Docker, Git, Docker Compose
yum update -y
yum install -y docker git

# Install Docker Compose (v2)
DOCKER_COMPOSE_VERSION=2.20.2
curl -SL https://github.com/docker/compose/releases/download/v${DOCKER_COMPOSE_VERSION}/docker-compose-linux-x86_64 -o /usr/local/bin/docker-compose
chmod +x /usr/local/bin/docker-compose
ln -s /usr/local/bin/docker-compose /usr/bin/docker-compose

# Start Docker service
systemctl start docker
systemctl enable docker
usermod -aG docker ec2-user

# Prepare app directory
mkdir -p /opt/monitoring
cd /opt/monitoring

# Create docker-compose.yml
cat <<EOF > docker-compose.yml
version: '3.8'

services:
  prometheus:
    image: prom/prometheus
    container_name: prometheus
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml
    ports:
      - "9090:9090"
    restart: unless-stopped

  grafana:
    image: grafana/grafana
    container_name: grafana
    ports:
      - "3000:3000"
    restart: unless-stopped

  node-exporter:
    image: prom/node-exporter
    container_name: node_exporter
    ports:
      - "9100:9100"
    restart: unless-stopped

  blackbox:
    image: prom/blackbox-exporter
    container_name: blackbox
    volumes:
      - ./blackbox.yml:/etc/blackbox_exporter/config.yml
    ports:
      - "9115:9115"
    restart: unless-stopped
EOF

# Create prometheus.yml
cat <<EOF > prometheus.yml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'prometheus'
    static_configs:
      - targets: ['localhost:9090']

  - job_name: 'node-exporter'
    static_configs:
      - targets: ['node-exporter:9100']

  - job_name: 'blackbox'
    metrics_path: /probe
    params:
      module: [http_2xx]
    static_configs:
      - targets:
          - http://example.com
          - http://localhost:3000
    relabel_configs:
      - source_labels: [__address__]
        target_label: __param_target
      - source_labels: [__param_target]
        target_label: instance
      - target_label: __address__
        replacement: blackbox:9115
EOF

# Create blackbox.yml
cat <<EOF > blackbox.yml
modules:
  http_2xx:
    prober: http
    timeout: 5s
    http:
      method: GET
EOF

# Wait for Docker to be ready
sleep 10

# Run all services
docker-compose up -d
"""

    instance = ec2.create_instances(
        ImageId=AMI_ID,
        InstanceType=instance_type,
        KeyName="livanshu-kp",
        MinCount=1,
        MaxCount=1,
        SecurityGroupIds=[sg.id],
        UserData=user_data_script
    )[0]

    print(" Waiting for instance to run...")
    instance.wait_until_running()
    instance.reload()

    # Optional tag for easier lookup
    instance.create_tags(Tags=[{"Key": "Name", "Value": "monitoring-instance"}])

    public_ip = instance.public_ip_address

    print(f"✅ Monitoring stack deployed!")
    print(f"Grafana: http://{public_ip}:3000")
    print(f"Prometheus: http://{public_ip}:9090")


    # Save metadata to config
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, "w") as f:
        json.dump({
            "instance_id": instance.id,
            "public_ip": public_ip,
            "grafana_port": 3000,
            "prometheus_port": 9090
        }, f, indent=2)

    print(f"📦 Metadata saved to: {CONFIG_PATH}")

    metadata_file = os.path.expanduser("~/.deploy_tool/monitor.json")
    os.makedirs(os.path.dirname(metadata_file), exist_ok=True)

    with open(metadata_file, "w") as f:
        json.dump({
            "grafana_url": f"http://{public_ip}:3000",
            "prometheus_url": f"http://{public_ip}:9090"
        }, f)

    print(f"🔗 Grafana URL stored in {metadata_file}")
