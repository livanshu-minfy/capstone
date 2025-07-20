import boto3
REGION = "ap-south-1"
# monitor_config.py
import os

KEY_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'livanshu-kp.pem'))

MONITOR_INSTANCE_NAME = "monitoring-ec2"
PROMETHEUS_PORT = 9090
GRAFANA_PORT = 3000

def get_monitor_instance_ip():
    ec2 = boto3.resource('ec2', region_name=REGION)
    instances = ec2.instances.filter(
        Filters=[
            {'Name': 'tag:Name', 'Values': [MONITOR_INSTANCE_NAME]},
            {'Name': 'instance-state-name', 'Values': ['running']}
        ]
    )
    for instance in instances:
        return instance.public_ip_address
    return None
