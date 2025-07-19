import tempfile
import click
import json
import os
import shutil
import subprocess
import platform
import stat
from pathlib import Path

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
        deploy_react(tmp_dir, environment)  # <--
    elif framework in ("angular", "nextjs"):
        deploy_dockerized(tmp_dir, framework, environment)
    else:
        click.echo("❌ Unsupported framework.")

    shutil.rmtree(tmp_dir, ignore_errors=True)  # <--

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
FROM node:18-alpine AS builder
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build --prod

FROM nginx:alpine
COPY --from=builder /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
"""
    else:
        raise ValueError("Unsupported framework")

    with open(dockerfile_path, 'w') as f:
        f.write(content)

def deploy_react(project_root, environment):  # <--
    """🚀 Build & deploy a React project in the given environment."""
    # NOTE: We *no longer* rely on init-created bucket. We create per-env buckets.  # <--

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

    # 3. Create (or reuse) env bucket
    state = load_bucket_config()
    if state and state.get("env") == environment:
        bucket = state['bucket']
        region = state['region']
        click.echo(f"🔁 Reusing bucket: {bucket} (env={environment})")
    else:
        click.echo(f"🪣 Creating new bucket for env: {environment}")
        bucket = create_public_s3_bucket(prefix=f"{environment}-site")
        if not bucket:
            click.echo("❌ Failed to create bucket.")
            return
        region = "ap-south-1"  # TODO: make dynamic  # <--
        save_bucket_config(bucket, region=region, environment=environment)  # <--

    # 4. Upload to S3 (AWS CLI handles MIME)
    click.echo("📤 Uploading via AWS CLI using s3 sync...")
    try:
        subprocess.run(
            [
                "aws", "s3", "sync", build_dir, f"s3://{bucket}", "--delete"
            ],
            check=True
        )
    except subprocess.CalledProcessError:
        click.echo("❌ AWS CLI sync failed. Make sure AWS CLI is installed and configured.")
        return

    # 5. Enable website hosting
    enable_static_website(bucket)

    # 6. Output public URL
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
