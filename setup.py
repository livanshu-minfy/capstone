from setuptools import setup, find_packages

setup(
    name='deploy-tool',
    version='0.1',
    packages=find_packages(),
    install_requires=[
        'boto3',
        'click',
        'paramiko',
        'scp'
    ],
    entry_points={
        'console_scripts': [
            'deploy-tool=deploy_tool.cli:cli',
        ],
    },
)
