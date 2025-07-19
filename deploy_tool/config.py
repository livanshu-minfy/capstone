import os
import json
from pathlib import Path

CONFIG_PATH = Path.home() / ".deploy_tool_config.json"

def save_config(config):
    with open(CONFIG_PATH, 'w') as f:
        json.dump(config, f)

def load_config():
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH) as f:
            return json.load(f)
    return None


# Extra state file for bucket metadata
CONFIG_FILE = Path("bucket.json")

def load_bucket_config():
    if not CONFIG_FILE.exists():
        return None
    with open(CONFIG_FILE, 'r') as f:
        return json.load(f)
