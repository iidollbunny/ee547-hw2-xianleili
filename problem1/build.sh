#!/bin/bash
# Build docker image for the ArXiv server
set -e

docker build -t arxiv-server:latest .
echo "Image built: arxiv-server:latest"
