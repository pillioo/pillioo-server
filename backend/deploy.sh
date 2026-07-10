#!/bin/bash

# Exit immediately if a command exits with a non-zero status
set -e

echo "[Pillioo] Starting the deployment script..."

# 1. Navigate to the backend directory (Automatically resolves based on script location)
cd "$(dirname "$0")"

# 2. Automatically fetch the latest code from Git
echo "Fetching the latest code for the current branch from Git..."
# Automatically identifies the currently checked-out branch and pulls updates.
CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
git pull origin "$CURRENT_BRANCH"

# 3. Clean up and stop existing containers and volumes
echo "Removing existing containers and data volumes..."
docker compose --profile rag down -v

# 4. Build and run containers in the background
echo "Building and running new containers..."
docker compose --profile rag up -d --build

# 5. Wait for Database (PostgreSQL) stabilization
echo "Waiting 5 seconds for the database to be ready..."
sleep 5

# 6. Execute Alembic migrations (Upgrade to the latest head)
echo "Running Alembic database migrations..."
docker compose exec fastapi alembic upgrade head

echo "✨ [Pillioo] All containers have been successfully deployed and initialized!"
echo "📊 Current container status:"
docker compose ps

# Fetch current instance's public IP and display Swagger UI URL
echo "--------------------------------------------------"
echo "🌍 Fetching current Public IP..."
CURRENT_IP=$(curl -s https://api.ipify.org)

echo "📌 Swagger UI is available at:"
echo "👉 http://${CURRENT_IP}:8000/docs"
echo "--------------------------------------------------"