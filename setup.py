from setuptools import setup, find_packages

setup(
    name='deploy-tool',
    version='0.1',
    packages=find_packages(where='.'),
    install_requires=[
        'click',
        'boto3'
    ],
    entry_points={
        'console_scripts': [
            'deploy-tool=deploy_tool.cli:cli'
        ],
    },
)
