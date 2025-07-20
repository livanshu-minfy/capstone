# Deploy-Tool: End-to-End CLI Deployment Automation
## Overview
Deploy-Tool is a feature-rich command-line tool that automates the entire deployment process of various web applications. my tool fills the gap between development and operations by offering a uniform, single deployment process for various frameworks and environments.
## Some of the key featues that i have implemented
- **Auto-Detection Framework**: Automatically detects React, React + Vite, Angular, and Next.js applications
- **Multi-Environment Support**: Deploy development, staging, and production environments
- **Intelligent Deployment Strategy**: Various deployment strategies based on application type
- **Infrastructure Provisioning**: Automated creation and management of AWS resources
- **Rollback Functionality**: Full infrastructure cleanup and rollback features
## Supported Frameworks
| Framework | Deployment Method | Target Infrastructure |
|-----------|-------------------|----------------------|
| React | Static site build | Amazon S3 |
| React + Vite | Static site build | Amazon S3 |
| Angular | Static site build | Amazon S3 |
| Next.js | Docker containerization | Amazon EC2
## Prerequisites
- Node.js (version 14 or higher)
- Python 3.8+
- AWS CLI installed on your system with valid credentials
- SSH key pair for EC2 login in deploy-tool folder. in my case "livanshu-kp.pem".
## Installation
### From Source
git clone https://github.com/livanshu-minfy/capstone

cd deploy-tool

pip install -r requirements.txt

## Commands Reference
### Launch Project
deploy-tool init github-repository-url
Copies the given GitHub repository, checks the codebase to identify the framework, and then returns the auto selected framework in cli

### Deploy Application
deploy-tool deploy environment
Carries out deployment procedure according to the auto selected framework and selected environment.

-- dev, staging or prod
**Example:**
deploy-tool deploy staging

### Start Monitoring
deploy-tool monitor init
Installs Prometheus and Grafana monitoring stack on the EC2 instance with Docker containers. Returns public URLs of monitoring dashboards.
WIP - work in progress.
**my learning:** Static sites hosted on S3 (React, Angular, React + Vite) don'thave metrics endpoints and can't be monitored using traditional application monitoring.
### Rollback Deployment
deploy-tool rollback
Shuts down all AWS resources established during the deployment process, such as EC2 instances, S3 buckets, and security groups.
## Deployment Architecture
### Static Site Deployment (React, Angular, React + Vite)
1. **Build Process**: Framework-specific build commands used to build application
2. **Asset Upload**: Built assets uploaded to S3 bucket specific to environment
3. **Public Access**: S3 bucket set up for static website hosting
4. **URL Generation**: Public URL returned upon deployment success
### Next.js Application Deployment
1. **Dockerfile Generation**: Automatic Dockerfile creation if not present
2. **EC2 Provisioning**: EC2 instance launched with appropriate security groups
3. **Docker Setup**: Docker engine installed and configured on EC2 instance
4. **Application Deployment**: Container deployed via SSH and SCP using Python subprocess
5. **Container Build**: Application containerized using generated Dockerfile
6. **Service Exposure**: Public-facing URL provided for application access


### Framework Detection Logic
The tool autonomously identifies frameworks based on:
- **React**: Existence of `package.json` with React packages, no Vite config
- **React + Vite**: Existence of `vite.config.js` or `vite.config.ts` with React
- **Angular**: Existence of `angular.json` config file
- **Next.js**: Existence of `next.config.js` or Next.js packages
## AWS Resources Created
### For Static Sites (S3 Deployment)
- S3 bucket with static website hosting
- Bucket policy for public read access
### For Applications of Next.js (EC2 Deployment)
- EC2 instance (configurable instance type)
- Security group with HTTP and SSH access
- SSH key pair
### For Infrastructure Monitoring
- Prometheus and Grafana EC2 instance

### Future enhancements that can be added
- A more safer and optimised code approach from security perspective.
- Containerization and Orchestration support using docker and Kubernetes.
- serverless deployment using aws lambda.

### CLI screenshots of the whole deployment process
## react + vite app example
<img width="1079" height="199" alt="image" src="https://github.com/user-attachments/assets/efde3fc4-ead8-46cd-ae7b-137aa5d4e739" />
<img width="1197" height="237" alt="image" src="https://github.com/user-attachments/assets/a5380ce7-abbc-43e0-b0bb-f4308e4cb3fa" />
<img width="1343" height="278" alt="image" src="https://github.com/user-attachments/assets/e1d7af05-e9f9-4ba7-ad0e-b4fff7d13985" />
<img width="1906" height="1019" alt="image" src="https://github.com/user-attachments/assets/05b5e2cf-e16e-4682-bc08-65590694c150" />
<img width="881" height="133" alt="image" src="https://github.com/user-attachments/assets/4a7e6778-3950-4b2d-afa7-a923e64840b5" />

NOTE FOR THE READER - 

since i was alloted to work in ap-south-1, so i have used that as default region.

I have also made a readme.md file in examples folder which contains the demo repos that i have used for testing my deploy-tool
