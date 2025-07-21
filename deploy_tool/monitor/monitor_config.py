# monitor_config.py
import os
import json
import boto3

REGION = "ap-south-1"
KEY_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'livanshu-kp.pem'))

MONITOR_INSTANCE_NAME = "monitoring-ec2"
PROMETHEUS_PORT = 9090
GRAFANA_PORT = 3000

CONFIG_PATH = os.path.expanduser("~/.deploy_tool/monitor_instance.json")
BUCKET_JSON_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'bucket.json'))

def get_monitor_instance_config():
    """
    Load monitor metadata saved during `monitor init`
    """
    if not os.path.exists(CONFIG_PATH):
        raise FileNotFoundError(f"No monitoring instance config found at {CONFIG_PATH}")
    
    with open(CONFIG_PATH, "r") as f:
        return json.load(f)

def get_monitor_instance_ip():
    """
    Legacy fallback to retrieve public IP via EC2 tags (not preferred anymore)
    """
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

def get_s3_dashboard_url():
    """
    Reads the bucket.json to construct the public S3 website URL for dashboard access.
    """
    try:
        with open(BUCKET_JSON_PATH, 'r') as f:
            data = json.load(f)
            bucket = data['bucket']
            region = data.get('region', REGION)
            return f"http://{bucket}.s3-website.{region}.amazonaws.com"
    except Exception as e:
        print(f"⚠️ Error reading bucket.json: {e}")
        return None
