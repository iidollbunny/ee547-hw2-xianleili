#!/bin/bash
# Run the ArXiv API server container on the given host port

set -e

PORT=${1:-8080}

# Validate port is numeric and in range
if ! [[ "$PORT" =~ ^[0-9]+$ ]]; then
  echo "Error: Port must be numeric"
  exit 1
fi
if [ "$PORT" -lt 1024 ] || [ "$PORT" -gt 65535 ]; then
  echo "Error: Port must be between 1024 and 65535"
  exit 1
fi

# Use a unique container name per port to avoid name conflicts
CONTAINER_NAME="arxiv-server-${PORT}"

# If a container with this name exists, remove it
if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER_NAME"; then
  echo "Removing existing container: $CONTAINER_NAME"
  docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
fi

echo "Starting ArXiv API server on port $PORT"
echo "Access at: http://localhost:$PORT"
echo "Available endpoints:"
echo "  GET /papers"
echo "  GET /papers/{arxiv_id}"
echo "  GET /search?q={query}"
echo "  GET /stats"
echo ""

# Run the container in the foreground; stops when you Ctrl+C
docker run --rm \
  --name "$CONTAINER_NAME" \
  -p "$PORT:8080" \
  arxiv-server:latest
