import webbrowser
import os
import json

CONFIG_PATH = os.path.expanduser("~/.deploy_tool/monitoring_config.json")

def show_monitoring_dashboard():
    if not os.path.exists(CONFIG_PATH):
        print("❌ Monitoring not initialized. Run: deploy-tool monitor init")
        return

    with open(CONFIG_PATH, 'r') as f:
        config = json.load(f)

    s3_exists = config.get("s3_monitoring", False)
    ec2_ip = config.get("ec2_monitor_ip")

    if s3_exists and ec2_ip:
        choice = input("Which dashboard do you want to view?\n1. S3 Monitoring\n2. EC2 App Monitoring\nChoose (1 or 2): ")
        if choice == "1":
            open_grafana_dashboard(ec2_ip, panel="s3")
        elif choice == "2":
            open_grafana_dashboard(ec2_ip, panel="ec2")
        else:
            print("Invalid choice.")
    elif s3_exists:
        open_grafana_dashboard(ec2_ip, panel="s3")
    elif ec2_ip:
        open_grafana_dashboard(ec2_ip, panel="ec2")
    else:
        print(" No monitoring targets found.")

def open_grafana_dashboard(ip, panel):
    # Customize based on how you set up your Grafana dashboards
    print(f"🌐 Opening Grafana for {panel.upper()} Monitoring at http://{ip}:3000")
    webbrowser.open(f"http://{ip}:3000")
