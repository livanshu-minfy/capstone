import tempfile
import click
import json
import os
import shutil
import subprocess
import platform
import stat
from pathlib import Path

from .aws import (
    create_public_s3_bucket,
    delete_s3_bucket,
    upload_to_s3,
    enable_static_website,
    get_website_url,
)

CONFIG_FILE = Path("bucket.json")

@click.group()
def cli():
    """🛠️ CLI for deploying static sites to AWS S3"""
    pass

# ----------------------
# 🔧 Config Management
# ----------------------

def save_bucket_config(bucket_name, region="ap-south-1"):
    with open(CONFIG_FILE, "w") as f:
        json.dump({"bucket": bucket_name, "region": region}, f)

def load_bucket_config():
    if CONFIG_FILE.exists():
        with open(CONFIG_FILE) as f:
            return json.load(f)
    return None

# ----------------------
# 📦 Init Command
# ----------------------

@cli.command()
@click.option('--prefix', default='static-site', help='Prefix for unique bucket name')
def init(prefix):
    """📦 Initializes a public S3 bucket with a unique name"""
    bucket_name = create_public_s3_bucket(prefix)
    if bucket_name:
        save_bucket_config(bucket_name)
        click.echo(f"🪣 Bucket ready: {bucket_name}")
    else:
        click.echo("❌ Failed to create bucket.")

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


# ----------------------
# 🚀 Deploy Command
# ----------------------

@cli.command()
@click.argument('repo_url')
def deploy(repo_url):
    """🚀 Deploy a React project from a GitHub repo to the S3 bucket."""
    state = load_bucket_config()
    if not state:
        click.echo("❌ No bucket found. Run 'deploy-tool init' first.")
        return

    bucket = state['bucket']
    region = state['region']

    # 1. Clone the repo
    tmp_dir = tempfile.mkdtemp()
    click.echo("📥 Cloning repo...")
    if not clone_repository(repo_url, tmp_dir):
        click.echo("❌ Failed to clone repository.")
        return

    # 2. Find React project
    react_path = find_react_project_path(tmp_dir)
    if not react_path:
        click.echo("❌ No React project found in the repo.")
        return

    # 3. Build the project
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

    # 4. Upload to S3
    click.echo("📤 Uploading via AWS CLI using s3 sync...")
    try:
        subprocess.run(
            [
                "aws", "s3", "sync", build_dir, f"s3://{bucket}"
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

    # Cleanup
    try:
        shutil.rmtree(tmp_dir)
    except PermissionError:
        click.echo("⚠️ Warning: Could not clean up temp files. You can manually delete:")
        click.echo(f"   {tmp_dir}")


# ----------------------
# 🧹 Rollback Command
# ----------------------

@cli.command()
def rollback():
    """🧹 Rollback by deleting the created S3 bucket"""
    state = load_bucket_config()
    if not state:
        click.echo("⚠️ No saved bucket found. Run `init` first.")
        return
    delete_s3_bucket(state['bucket'])
    click.echo(f"✅ Rolled back. Deleted bucket: {state['bucket']}")
    CONFIG_FILE.unlink(missing_ok=True)

# ----------------------
# 🔥 Entrypoint
# ----------------------

if __name__ == '__main__':
    cli()
