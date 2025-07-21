import tempfile
import click
import json
import os
import shutil
import subprocess
import platform
import time
import stat
from pathlib import Path
import boto3
import requests
from botocore.exceptions import ClientError
from .config import load_config, save_config
from .aws import rollback_all_resources


from .aws import (
    create_public_s3_bucket,
    delete_s3_bucket,
    enable_static_website,
    get_website_url,
    provision_ec2_with_docker,
    upload_and_run_on_ec2,
)

CONFIG_FILE = Path("bucket.json")

@click.group()
def cli():
    """🛠️ CLI for deploying static sites to AWS S3"""
    pass

# ----------------------
# 🔧 Config Management
# ----------------------

def save_bucket_config(bucket_name, region="ap-south-1", environment=None):  # <--
    """Persist the *last deployed* bucket (per env if provided)."""  # <--
    data = {"bucket": bucket_name, "region": region}
    if environment:  
        data["env"] = environment  
    with open(CONFIG_FILE, "w") as f:
        json.dump(data, f)

def load_bucket_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return None

# ----------------------
# 📦 Init Command
# ----------------------

@cli.command()
@click.argument('repo_url')
def init(repo_url):
    """🔍 Initializes project by detecting framework and saving metadata."""
    tmp_dir = tempfile.mkdtemp()
    click.echo(" Cloning repo...")
    if not clone_repository(repo_url, tmp_dir):
        click.echo("Failed to clone repository.")
        return

    framework = detect_framework(tmp_dir)
    if not framework:
        click.echo("Framework not supported.")
        return

    save_config({
        "repo_url": repo_url,
        "framework": framework
    })
    click.echo(f"Detected framework: {framework}")


    shutil.rmtree(tmp_dir, ignore_errors=True)

# ----------------------
# 🔍 Path Detector
# ----------------------

def find_react_project_path(root):
    """Recursively search for the first folder containing a package.json with react."""
    for dirpath, _, filenames in os.walk(root):
        if 'package.json' in filenames:
            try:
                with open(os.path.join(dirpath, 'package.json')) as f:
                    package_data = json.load(f)
                    deps = package_data.get("dependencies", {})
                    dev_deps = package_data.get("devDependencies", {})
                    if "react" in deps or "react" in dev_deps:
                        return dirpath
            except Exception:
                continue
    return None

def find_angular_project_path(root):

    for dirpath, _, filenames in os.walk(root):
        if 'angular.json' in filenames:
            return dirpath
            
        if 'package.json' in filenames:
            try:
                with open(os.path.join(dirpath, 'package.json')) as f:
                    package_data = json.load(f)
                    deps = package_data.get("dependencies", {})
                    dev_deps = package_data.get("devDependencies", {})

                    angular_deps = ["@angular/core", "@angular/cli", "@angular/common", "angular"]
                    
                    for dep in angular_deps:
                        if dep in deps or dep in dev_deps:
                            return dirpath
                            
            except Exception:
                continue
    return None


def find_react_vite_project_path(root):
    """Recursively search for the first folder containing a React + Vite project."""
    for dirpath, _, filenames in os.walk(root):
        vite_config_files = ['vite.config.js', 'vite.config.ts', 'vite.config.mjs', 'vite.config.cjs']
        has_vite_config = any(config in filenames for config in vite_config_files)
        
        if has_vite_config and 'package.json' in filenames:
            try:
                with open(os.path.join(dirpath, 'package.json')) as f:
                    package_data = json.load(f)
                    deps = package_data.get("dependencies", {})
                    dev_deps = package_data.get("devDependencies", {})
                    
                    has_react = "react" in deps or "react" in dev_deps
                    has_vite = "vite" in dev_deps or "@vitejs/plugin-react" in dev_deps
                    
                    if has_react and has_vite:
                        return dirpath
                        
            except Exception:
                continue
    return None



# ----------------------
# 📥 Git Cloner
# ----------------------

def handle_remove_readonly(func, path, exc_info):
    """
    Clear readonly flag and retry the removal. Needed for Windows.
    """
    os.chmod(path, stat.S_IWRITE)
    func(path)

def clone_repository(repo_url, tmp_dir):
    """Clones a Git repo to a temporary directory and removes .git folder."""
    try:
        subprocess.run(['git', 'clone', '--depth', '1', repo_url, tmp_dir], check=True)
        
        # Force remove .git even if files are readonly (Windows)
        git_dir = os.path.join(tmp_dir, '.git')
        if os.path.exists(git_dir):
            shutil.rmtree(git_dir, onerror=handle_remove_readonly)
        
        return True
    except subprocess.CalledProcessError:
        return False

def detect_framework(project_path):
    for dirpath, _, filenames in os.walk(project_path):
        if 'package.json' in filenames:
            try:
                with open(os.path.join(dirpath, 'package.json')) as f:
                    pkg = json.load(f)
                deps = pkg.get("dependencies", {})
                dev_deps = pkg.get("devDependencies", {})
                all_deps = {**deps, **dev_deps}

                if "next" in all_deps:
                    return "nextjs"
                if "@angular/core" in all_deps:
                    return "angular"

                if ("react" in all_deps and 
                    ("vite" in all_deps or "@vitejs/plugin-react" in all_deps)):
                    return "react-vite"

                if "react" in all_deps:
                    return "react"
            except Exception:
                continue
    return None


# ----------------------
# 🚀 Deploy Command
# ----------------------

@cli.command()
@click.argument('environment')
def deploy(environment):
    config = load_config()
    if not config:
        click.echo("Run 'deploy-tool init <repo_url>' first.")
        return

    repo_url = config["repo_url"]
    framework = config["framework"]
    tmp_dir = tempfile.mkdtemp()

    click.echo(f"Cloning repo: {repo_url}")
    if not clone_repository(repo_url, tmp_dir):
        click.echo("Failed to clone repo.")
        return

    if framework == "react":
        deploy_react(tmp_dir, environment)
    elif framework == "react-vite":
        deploy_react_vite(tmp_dir, environment)
    elif framework == "angular":
        deploy_angular(tmp_dir, environment)
    elif framework == "nextjs":
        deploy_dockerized(tmp_dir, framework, environment)
    else:
        click.echo(" Unsupported framework.")

    shutil.rmtree(tmp_dir, ignore_errors=True)



def deploy_dockerized(tmp_dir, framework, environment):
    write_dockerfile(framework, tmp_dir)

    click.echo(" Launching EC2...")
    instance_ip = provision_ec2_with_docker(environment)
    if not instance_ip:
        click.echo("❌EC2 setup failed.")
        return

    click.echo(" Packaging app...")
    archive_path = shutil.make_archive('app', 'zip', tmp_dir)

    click.echo(" Uploading and running app on EC2...")
    upload_and_run_on_ec2(instance_ip, archive_path, framework)

    click.echo(f" Deployed at: http://{instance_ip}")

def write_dockerfile(framework, path):
    dockerfile_path = os.path.join(path, 'Dockerfile')
    if framework == 'nextjs':
        content = """\
FROM node:18-alpine
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build
EXPOSE 3000
CMD ["npm", "run", "start"]
"""
    
    with open(dockerfile_path, 'w') as f:
        f.write(content)

def bucket_exists(bucket_name):
    s3 = boto3.client("s3")
    try:
        s3.head_bucket(Bucket=bucket_name)
        return True
    except ClientError:
        return False

def get_bucket_region(bucket_name):
    s3 = boto3.client("s3")
    try:
        response = s3.get_bucket_location(Bucket=bucket_name)
        loc = response.get("LocationConstraint")
        return "us-east-1" if loc is None else loc
    except ClientError:
        return None

def deploy_react(project_root, environment):

    react_path = find_react_project_path(project_root)
    if not react_path:
        click.echo("No React project found in the repo.")
        return

    click.echo(f"Building React app at: {react_path}")
    is_windows = platform.system() == "Windows"
    shell_flag = True if is_windows else False
    try:
        subprocess.run(['npm', 'install'], cwd=react_path, check=True, shell=shell_flag)
        subprocess.run(['npm', 'run', 'build'], cwd=react_path, check=True, shell=shell_flag)
    except subprocess.CalledProcessError:
        click.echo("Build failed. Ensure it's a valid React project.")
        return

    build_dir = os.path.join(react_path, 'build')
    if not os.path.exists(build_dir):
        click.echo("Build folder not found.")
        return

    state = load_bucket_config()
    bucket = None
    region = "ap-south-1"

    if state and state.get("env") == environment:
        candidate = state.get("bucket")
        if bucket_exists(candidate):
            bucket = candidate
            region = get_bucket_region(candidate) or region
            click.echo(f"Reusing bucket: {bucket} (env={environment})")
        else:
            click.echo(f"Config refers to a deleted/missing bucket: {candidate}. Recreating...")
    
    if not bucket:
        click.echo(f"Creating new bucket for env: {environment}")
        bucket = create_public_s3_bucket(prefix=f"{environment}-site", region=region)
        if not bucket:
            click.echo(" Failed to create bucket.")
            return
        save_bucket_config(bucket, region=region, environment=environment)

    click.echo("Uploading via AWS CLI using s3 sync...")
    try:
        subprocess.run(
            [
                "aws", "s3", "sync", build_dir, f"s3://{bucket}", "--delete"
            ],
            check=True
        )
    except subprocess.CalledProcessError:
        click.echo("AWS CLI sync failed. Ensure AWS CLI is installed and configured.")
        return

    enable_static_website(bucket)

    public_url = get_website_url(bucket, region)
    click.echo(f" Site deployed: {public_url}")

def deploy_angular(project_root, environment):

    angular_path = find_angular_project_path(project_root)
    if not angular_path:
        click.echo("No Angular project found in the repo.")
        return

    click.echo(f"Building Angular app at: {angular_path}")
    is_windows = platform.system() == "Windows"
    shell_flag = True if is_windows else False

    build_env = os.environ.copy()
    build_env["NODE_OPTIONS"] = "--openssl-legacy-provider"

    try:
        subprocess.run(['npm', 'install'], cwd=angular_path, check=True, shell=shell_flag, env=build_env)
        subprocess.run(
            ['ng', 'build', '--configuration=production'],
            cwd=angular_path, check=True, shell=shell_flag, env=build_env
        )
    except subprocess.CalledProcessError:
        click.echo(" Build failed. Ensure it's a valid Angular project and Node options are supported.")
        return

    base_build_dir = os.path.join(angular_path, 'dist')
    if not os.path.exists(base_build_dir):
        click.echo("Build folder not found.")
        return

    def find_index_html_directory(base_path):
        """Recursively find the directory containing index.html."""
        for root, dirs, files in os.walk(base_path):
            if 'index.html' in files:
                return root
        return None

    build_dir = find_index_html_directory(base_build_dir)
    if not build_dir:
        click.echo("Could not find index.html in build output.")
        return

    state = load_bucket_config()
    bucket = None
    region = "ap-south-1"

    if state and state.get("env") == environment:
        candidate = state.get("bucket")
        if bucket_exists(candidate):
            bucket = candidate
            region = get_bucket_region(candidate) or region
            click.echo(f"Reusing bucket: {bucket} (env={environment})")
        else:
            click.echo(f"Config refers to a deleted/missing bucket: {candidate}. Recreating...")

    if not bucket:
        click.echo(f"Creating new bucket for env: {environment}")
        bucket = create_public_s3_bucket(prefix=f"{environment}-angular-site", region=region)
        if not bucket:
            click.echo("Failed to create bucket.")
            return
        save_bucket_config(bucket, region=region, environment=environment)

    click.echo("Uploading via AWS CLI using s3 sync...")
    try:
        subprocess.run(
            ["aws", "s3", "sync", build_dir, f"s3://{bucket}", "--delete"],
            check=True
        )
    except subprocess.CalledProcessError:
        click.echo("AWS CLI sync failed. Ensure AWS CLI is installed and configured.")
        return

    enable_static_website(bucket)

    public_url = get_website_url(bucket, region)
    click.echo(f" Site deployed: {public_url}")



def deploy_react_vite(project_root, environment):

    react_vite_path = find_react_vite_project_path(project_root)
    if not react_vite_path:
        click.echo("No React + Vite project found in the repo.")
        return

    click.echo(f" Building React + Vite app at: {react_vite_path}")
    is_windows = platform.system() == "Windows"
    shell_flag = True if is_windows else False
    try:
        subprocess.run(['npm', 'install'], cwd=react_vite_path, check=True, shell=shell_flag)
        subprocess.run(
            ['npm', 'run', 'build'],
            cwd=react_vite_path, check=True, shell=shell_flag
        )
    except subprocess.CalledProcessError:
        click.echo(" Build failed. Ensure it's a valid React + Vite project.")
        return

    build_dir = os.path.join(react_vite_path, 'dist')
    if not os.path.exists(build_dir):
        click.echo(" Build folder not found.")
        return

    if not os.path.exists(os.path.join(build_dir, 'index.html')):
        click.echo(" index.html not found in build output.")
        return

    state = load_bucket_config()
    bucket = None
    region = "ap-south-1"

    if state and state.get("env") == environment:
        candidate = state.get("bucket")
        if bucket_exists(candidate):
            bucket = candidate
            region = get_bucket_region(candidate) or region
            click.echo(f" Reusing bucket: {bucket} (env={environment})")
        else:
            click.echo(f"Config refers to a deleted/missing bucket: {candidate}. Recreating...")

    if not bucket:
        click.echo(f"Creating new bucket for env: {environment}")
        bucket = create_public_s3_bucket(prefix=f"{environment}-react-vite-site", region=region)
        if not bucket:
            click.echo("Failed to create bucket.")
            return
        save_bucket_config(bucket, region=region, environment=environment)

    click.echo(" Uploading via AWS CLI using s3 sync...")
    try:
        subprocess.run(
            ["aws", "s3", "sync", build_dir, f"s3://{bucket}", "--delete"],
            check=True
        )
    except subprocess.CalledProcessError:
        click.echo("AWS CLI sync failed. Ensure AWS CLI is installed and configured.")
        return

    enable_static_website(bucket)

    public_url = get_website_url(bucket, region)
    click.echo(f"Site deployed: {public_url}")


@cli.group()
def monitor():
    pass

@monitor.command()
def status():
    click.echo(f"have to implement this logic in future, sorry")


@monitor.command()
def init():

    default_instance_type = "t3.small"
    click.echo(f"Setting up monitoring stack on EC2 ({default_instance_type})...")
    from deploy_tool.monitor.ec2_monitor import provision_monitoring_instance
    provision_monitoring_instance(default_instance_type)

from deploy_tool.monitor.monitor_config import get_monitor_instance_config

@monitor.command("dashboard")
@click.pass_context
def create_dashboard(ctx):
    """Create and update Grafana dashboard with app link if S3 deployed."""
    import requests
    import json
    import os
    from pathlib import Path
    

    config = get_monitor_instance_config()
    ip = config["public_ip"]

    headers = {
        "Content-Type": "application/json"
    }

    auth = ('admin', 'admin')

    s3_app_url = None
    try:
        bucket_json_path = Path.home() / ".deploy-tool" / "bucket.json"
        if bucket_json_path.exists():
            with open(bucket_json_path) as f:
                bucket_config = json.load(f)
                bucket = bucket_config["bucket"]
                region = bucket_config["region"]
                s3_app_url = f"https://{bucket}.s3.{region}.amazonaws.com/index.html"
    except Exception as e:
        click.echo(f"⚠️ Warning: Could not read S3 link: {e}")

    
    uid = get_prometheus_uid()
    panels = []

# CPU Usage Panel
    panels.append({
        "type": "timeseries",
        "title": "CPU Usage (%)",
        "datasource": {
            "type": "prometheus",
            "uid": uid
        },
        "targets": [
            {
                "expr": "100 - (avg by(instance) (rate(node_cpu_seconds_total{mode=\"idle\"}[5m])) * 100)",
                "legendFormat": "{{instance}}",
                "refId": "A"
            }
        ],
        "gridPos": {"x": 0, "y": 0, "w": 24, "h": 8},
        "fieldConfig": {
            "defaults": {
                "unit": "percent",
                "thresholds": {
                    "mode": "absolute",
                    "steps": [
                        {"color": "green", "value": None},
                        {"color": "orange", "value": 70},
                        {"color": "red", "value": 90}
                    ]
                }
            },
            "overrides": []
        },
        "options": {
            "legend": {
                "displayMode": "table",
                "placement": "bottom"
            },
            "tooltip": {
                "mode": "single"
            }
        }
    })

    # Memory Usage Panel
    panels.append({
        "type": "timeseries",
        "title": "Memory Usage (%)",
        "datasource": {
            "type": "prometheus",
            "uid": uid
        },
        "targets": [
            {
                "expr": "(1 - (node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)) * 100",
                "legendFormat": "{{instance}}",
                "refId": "B"
            }
        ],
        "gridPos": {"x": 0, "y": 8, "w": 24, "h": 8},
        "fieldConfig": {
            "defaults": {
                "unit": "percent",
                "thresholds": {
                    "mode": "absolute",
                    "steps": [
                        {"color": "green", "value": None},
                        {"color": "orange", "value": 70},
                        {"color": "red", "value": 90}
                    ]
                }
            },
            "overrides": []
        },
        "options": {
            "legend": {
                "displayMode": "table",
                "placement": "bottom"
            },
            "tooltip": {
                "mode": "single"
            }
        }
    })

    # Disk Usage Panel
    panels.append({
        "type": "timeseries",
        "title": "Disk Usage (%)",
        "datasource": {
            "type": "prometheus",
            "uid": uid
        },
        "targets": [
            {
                "expr": "(node_filesystem_size_bytes{mountpoint!=\"/boot\",fstype!~\"tmpfs|overlay\"} - node_filesystem_free_bytes{mountpoint!=\"/boot\",fstype!~\"tmpfs|overlay\"}) / node_filesystem_size_bytes{mountpoint!=\"/boot\",fstype!~\"tmpfs|overlay\"} * 100",
                "legendFormat": "{{instance}} {{mountpoint}}",
                "refId": "C"
            }
        ],
        "gridPos": {"x": 0, "y": 16, "w": 24, "h": 8},
        "fieldConfig": {
            "defaults": {
                "unit": "percent",
                "thresholds": {
                    "mode": "absolute",
                    "steps": [
                        {"color": "green", "value": None},
                        {"color": "orange", "value": 70},
                        {"color": "red", "value": 90}
                    ]
                }
            },
            "overrides": []
        },
        "options": {
            "legend": {
                "displayMode": "table",
                "placement": "bottom"
            },
            "tooltip": {
                "mode": "single"
            }
        }
    })

    # Network Traffic Panel
    panels.append({
        "type": "timeseries",
        "title": "Network Traffic (Bytes/sec)",
        "datasource": {
            "type": "prometheus",
            "uid": uid
        },
        "targets": [
            {
                "expr": "rate(node_network_receive_bytes_total[5m])",
                "legendFormat": "{{instance}} RX",
                "refId": "D"
            },
            {
                "expr": "rate(node_network_transmit_bytes_total[5m])",
                "legendFormat": "{{instance}} TX",
                "refId": "E"
            }
        ],
        "gridPos": {"x": 0, "y": 24, "w": 24, "h": 8},
        "fieldConfig": {
            "defaults": {
                "unit": "Bps",
                "thresholds": {
                    "mode": "absolute",
                    "steps": [
                        {"color": "green", "value": None},
                        {"color": "orange", "value": 1000000},
                        {"color": "red", "value": 10000000}
                    ]
                }
            },
            "overrides": []
        },
        "options": {
            "legend": {
                "displayMode": "table",
                "placement": "bottom"
            },
            "tooltip": {
                "mode": "single"
            }
        }
    })

    dashboard_payload = {
        "dashboard": {
            "id": None,
            "uid": "auto-metrics",
            "title": "Auto Monitoring Dashboard",
            "tags": ["auto-generated"],
            "timezone": "browser",
            "panels": panels,
            "schemaVersion": 36,
            "version": 1
        },
        "overwrite": True
    }



    url = f"http://{ip}:3000/api/dashboards/db"
    response = requests.post(url, headers=headers, json=dashboard_payload, auth=auth)

    if response.status_code == 200:
        click.echo("Grafana dashboard created successfully!")
        click.echo(f"View it at: http://{ip}:3000/d/auto-metrics/auto-monitoring-dashboard")
    else:
        click.echo(f"❌ Failed to create dashboard: {response.status_code}")
        click.echo(response.text)


def get_stored_grafana_url():
    metadata_file = os.path.expanduser("~/.deploy_tool/monitor.json")
    if not os.path.exists(metadata_file):
        raise Exception("No monitoring metadata found. Did you run `deploy-tool monitor init`?")
    
    with open(metadata_file) as f:
        data = json.load(f)
        return data.get("grafana_url")

def get_prometheus_uid():
    config = get_monitor_instance_config()
    ip = config["public_ip"]
    
    headers = {"Content-Type": "application/json"}
    auth = ("admin", "admin")
    
    # Wait for Grafana to be ready
    max_retries = 5
    for attempt in range(max_retries):
        try:
            # First check if Prometheus datasource exists
            response = requests.get(
                f"http://{ip}:3000/api/datasources",
                headers=headers,
                auth=auth
            )
            response.raise_for_status()
            
            # Look for existing Prometheus datasource
            datasources = response.json()
            for ds in datasources:
                if ds["type"] == "prometheus":
                    click.echo("Found existing Prometheus datasource")
                    return ds["uid"]
            
            # If we get here, no Prometheus found - let's create it
            click.echo("Creating Prometheus datasource...")
            datasource_payload = {
                "name": "Prometheus",
                "type": "prometheus",
                "url": "http://prometheus:9090",
                "access": "proxy",
                "isDefault": True,
                "jsonData": {
                    "timeInterval": "15s"
                }
            }
            
            create_response = requests.post(
                f"http://{ip}:3000/api/datasources",
                headers=headers,
                auth=auth,
                json=datasource_payload
            )
            create_response.raise_for_status()
            
            new_datasource = create_response.json()
            click.echo("Prometheus datasource created successfully")
            return new_datasource["datasource"]["uid"]
            
        except Exception as e:
            if attempt == max_retries - 1:
                raise Exception("Failed to setup Prometheus datasource after multiple attempts") from e
            click.echo(f"Attempt {attempt + 1}: Waiting for Grafana API...")
            time.sleep(10)
            
    raise Exception("Could not setup Prometheus datasource")

@cli.command() 
def rollback():
    rollback_all_resources()
    click.echo("Full rollback complete.")


if __name__ == '__main__':
    cli()
