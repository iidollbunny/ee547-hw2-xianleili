#!/bin/bash
# Basic smoke tests for the ArXiv server using a temporary container

set -euo pipefail

TEST_PORT=8081
CONTAINER_NAME="arxiv-server-test-$$"  # unique per test run

# Ensure any leftover test container is removed
docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true

# Start container in detached mode
docker run -d --rm \
  --name "$CONTAINER_NAME" \
  -p "$TEST_PORT:8080" \
  arxiv-server:latest >/dev/null

# Wait for server to be ready
echo "Waiting for server startup on :$TEST_PORT..."
for i in {1..20}; do
  if curl -s "http://localhost:$TEST_PORT/papers" >/dev/null; then
    break
  fi
  sleep 0.3
done

pp() { python -m json.tool >/dev/null 2>&1; }

echo "Testing /papers endpoint..."
curl -s "http://localhost:$TEST_PORT/papers" | pp && echo "✓ /papers OK" || echo "✗ /papers failed"

echo "Testing /stats endpoint..."
curl -s "http://localhost:$TEST_PORT/stats" | pp && echo "✓ /stats OK" || echo "✗ /stats failed"

echo "Testing /search endpoint..."
curl -s "http://localhost:$TEST_PORT/search?q=machine" | pp && echo "✓ /search OK" || echo "✗ /search failed"

echo "Testing 404 handling..."
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://localhost:$TEST_PORT/does_not_exist")
if [ "$HTTP_CODE" = "404" ]; then
  echo "✓ 404 handling OK"
else
  echo "✗ 404 handling failed (got $HTTP_CODE)"
fi

# Cleanup test container
docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
echo "Tests complete"
