import tempfile
import click
import json
import os
import shutil
import subprocess
import platform
import stat
from pathlib import Path
import boto3
from botocore.exceptions import ClientError
from .config import load_config, save_config
from .aws import rollback_all_resources

# NOTE: added create_public_s3_bucket import because deploy_react now creates env buckets.  # <--
from .aws import (
    create_public_s3_bucket,  # <--
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
    if environment:  # <--
        data["env"] = environment  # <--
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
    click.echo("📥 Cloning repo...")
    if not clone_repository(repo_url, tmp_dir):
        click.echo("❌ Failed to clone repository.")
        return

    framework = detect_framework(tmp_dir)
    if not framework:
        click.echo("❌ Framework not supported.")
        return

    save_config({
        "repo_url": repo_url,
        "framework": framework
    })
    click.echo(f"✅ Detected framework: {framework}")

    # cleanup temp clone  # <--
    shutil.rmtree(tmp_dir, ignore_errors=True)  # <--

# ----------------------
# 🔍 React Detector
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

# ----------------------
# 🔍 Angular Detector
# ----------------------

def find_angular_project_path(root):
    """Recursively search for the first folder containing a package.json with Angular dependencies or angular.json file."""
    for dirpath, _, filenames in os.walk(root):
        # First check for angular.json file (Angular CLI configuration)
        if 'angular.json' in filenames:
            return dirpath
            
        # Also check package.json for Angular dependencies
        if 'package.json' in filenames:
            try:
                with open(os.path.join(dirpath, 'package.json')) as f:
                    package_data = json.load(f)
                    deps = package_data.get("dependencies", {})
                    dev_deps = package_data.get("devDependencies", {})
                    
                    # Look for core Angular dependencies
                    angular_deps = ["@angular/core", "@angular/cli", "@angular/common", "angular"]
                    
                    for dep in angular_deps:
                        if dep in deps or dep in dev_deps:
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
    """Detects if the project is React, Angular, or Next.js."""
    for dirpath, _, filenames in os.walk(project_path):
        if 'package.json' in filenames:
            try:
                with open(os.path.join(dirpath, 'package.json')) as f:
                    package_data = json.load(f)
                    deps = package_data.get("dependencies", {})
                    dev_deps = package_data.get("devDependencies", {})
                    all_deps = {**deps, **dev_deps}

                    # ✅ Detect nextjs before react
                    if "next" in all_deps:
                        return "nextjs"
                    if "@angular/core" in all_deps:
                        return "angular"
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
    """🚀 Deploys app to specified environment (dev/staging/prod)."""
    config = load_config()
    if not config:
        click.echo("❌ Run 'deploy-tool init <repo_url>' first.")
        return

    repo_url = config["repo_url"]
    framework = config["framework"]
    tmp_dir = tempfile.mkdtemp()

    click.echo(f"📥 Cloning repo: {repo_url}")
    if not clone_repository(repo_url, tmp_dir):
        click.echo("❌ Failed to clone repo.")
        return

    if framework == "react":
        deploy_react(tmp_dir, environment)
    elif framework == "angular":
        deploy_angular(tmp_dir, environment)  # <-- Add this line
    elif framework == "nextjs":
        deploy_dockerized(tmp_dir, framework, environment)
    else:
        click.echo("❌ Unsupported framework.")

    shutil.rmtree(tmp_dir, ignore_errors=True)


def deploy_dockerized(tmp_dir, framework, environment):
    write_dockerfile(framework, tmp_dir)

    click.echo("🚀 Launching EC2...")
    instance_ip = provision_ec2_with_docker(environment)  # returns IP/DNS  # <--
    if not instance_ip:
        click.echo("❌ EC2 setup failed.")
        return

    click.echo("📦 Packaging app...")
    archive_path = shutil.make_archive('app', 'zip', tmp_dir)

    click.echo("📤 Uploading and running app on EC2...")
    upload_and_run_on_ec2(instance_ip, archive_path, framework)

    click.echo(f"🌍 Deployed at: http://{instance_ip}")

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
    elif framework == 'angular':
        content = """\
FROM node:20.19.0-slim AS builder
WORKDIR /app
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build -- --no-progress

FROM nginx:alpine
COPY --from=builder /app/dist/* /usr/share/nginx/html/
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
"""
    else:
        raise ValueError("Unsupported framework")

    with open(dockerfile_path, 'w') as f:
        f.write(content)

def bucket_exists(bucket_name):
    """Check if a bucket actually exists in S3."""
    s3 = boto3.client("s3")
    try:
        s3.head_bucket(Bucket=bucket_name)
        return True
    except ClientError:
        return False

def get_bucket_region(bucket_name):
    """Get the bucket's region or fallback."""
    s3 = boto3.client("s3")
    try:
        response = s3.get_bucket_location(Bucket=bucket_name)
        loc = response.get("LocationConstraint")
        return "us-east-1" if loc is None else loc
    except ClientError:
        return None

def deploy_react(project_root, environment):
    """🚀 Build & deploy a React project in the given environment."""

    # 1. Find React project root
    react_path = find_react_project_path(project_root)
    if not react_path:
        click.echo("❌ No React project found in the repo.")
        return

    # 2. Build
    click.echo(f"⚙️ Building React app at: {react_path}")
    is_windows = platform.system() == "Windows"
    shell_flag = True if is_windows else False
    try:
        subprocess.run(['npm', 'install'], cwd=react_path, check=True, shell=shell_flag)
        subprocess.run(['npm', 'run', 'build'], cwd=react_path, check=True, shell=shell_flag)
    except subprocess.CalledProcessError:
        click.echo("❌ Build failed. Ensure it's a valid React project.")
        return

    build_dir = os.path.join(react_path, 'build')
    if not os.path.exists(build_dir):
        click.echo("❌ Build folder not found.")
        return

    # 3. Create (or verify) env bucket
    state = load_bucket_config()
    bucket = None
    region = "ap-south-1"

    if state and state.get("env") == environment:
        candidate = state.get("bucket")
        if bucket_exists(candidate):
            bucket = candidate
            region = get_bucket_region(candidate) or region
            click.echo(f"🔁 Reusing bucket: {bucket} (env={environment})")
        else:
            click.echo(f"⚠️ Config refers to a deleted/missing bucket: {candidate}. Recreating...")
    
    if not bucket:
        click.echo(f"🪣 Creating new bucket for env: {environment}")
        bucket = create_public_s3_bucket(prefix=f"{environment}-site", region=region)
        if not bucket:
            click.echo("❌ Failed to create bucket.")
            return
        save_bucket_config(bucket, region=region, environment=environment)

    # 4. Upload to S3 using AWS CLI
    click.echo("📤 Uploading via AWS CLI using s3 sync...")
    try:
        subprocess.run(
            [
                "aws", "s3", "sync", build_dir, f"s3://{bucket}", "--delete"
            ],
            check=True
        )
    except subprocess.CalledProcessError:
        click.echo("❌ AWS CLI sync failed. Ensure AWS CLI is installed and configured.")
        return

    # 5. Enable website hosting
    enable_static_website(bucket)

    # 6. Output public URL
    public_url = get_website_url(bucket, region)
    click.echo(f"🌐 Site deployed: {public_url}")

def deploy_angular(project_root, environment):
    """🚀 Build & deploy an Angular project in the given environment."""

    # 1. Find Angular project root
    angular_path = find_angular_project_path(project_root)
    if not angular_path:
        click.echo("❌ No Angular project found in the repo.")
        return

    # 2. Build
    click.echo(f"⚙️ Building Angular app at: {angular_path}")
    is_windows = platform.system() == "Windows"
    shell_flag = True if is_windows else False
    try:
        subprocess.run(['npm', 'install'], cwd=angular_path, check=True, shell=shell_flag)
        subprocess.run(
            ['ng', 'build', '--configuration=production'],
            cwd=angular_path, check=True, shell=shell_flag
        )
    except subprocess.CalledProcessError:
        click.echo("❌ Build failed. Ensure it's a valid Angular project.")
        return

    # 3. Locate build output directory containing index.html
    base_build_dir = os.path.join(angular_path, 'dist')
    if not os.path.exists(base_build_dir):
        click.echo("❌ Build folder not found.")
        return

    def find_index_html_directory(base_path):
        """Recursively find the directory containing index.html."""
        for root, dirs, files in os.walk(base_path):
            if 'index.html' in files:
                return root
        return None

    build_dir = find_index_html_directory(base_build_dir)
    if not build_dir:
        click.echo("❌ Could not find index.html in build output.")
        return

    # 4. Create (or verify) env bucket
    state = load_bucket_config()
    bucket = None
    region = "ap-south-1"

    if state and state.get("env") == environment:
        candidate = state.get("bucket")
        if bucket_exists(candidate):
            bucket = candidate
            region = get_bucket_region(candidate) or region
            click.echo(f"🔁 Reusing bucket: {bucket} (env={environment})")
        else:
            click.echo(f"⚠️ Config refers to a deleted/missing bucket: {candidate}. Recreating...")

    if not bucket:
        click.echo(f"🪣 Creating new bucket for env: {environment}")
        bucket = create_public_s3_bucket(prefix=f"{environment}-angular-site", region=region)
        if not bucket:
            click.echo("❌ Failed to create bucket.")
            return
        save_bucket_config(bucket, region=region, environment=environment)

    # 5. Upload to S3 using AWS CLI
    click.echo("📤 Uploading via AWS CLI using s3 sync...")
    try:
        subprocess.run(
            ["aws", "s3", "sync", build_dir, f"s3://{bucket}", "--delete"],
            check=True
        )
    except subprocess.CalledProcessError:
        click.echo("❌ AWS CLI sync failed. Ensure AWS CLI is installed and configured.")
        return

    # 6. Enable website hosting
    enable_static_website(bucket)

    # 7. Output public URL
    public_url = get_website_url(bucket, region)
    click.echo(f"🌐 Site deployed: {public_url}")


# ----------------------
# 🧹 Rollback Command
# ----------------------

@cli.command()  # <--- THIS is why it now shows up in `deploy-tool --help`
def rollback():
    """🧹 Rollback everything: EC2, SG, S3, Metadata"""
    rollback_all_resources()
    click.echo("🔥 Full rollback complete.")

# ----------------------
# 🔥 Entrypoint
# ----------------------

if __name__ == '__main__':
    cli()
