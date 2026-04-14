#!/bin/bash

# Путь к проекту (измените если нужно)
PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "Starting backend..."

cd "$PROJECT_DIR/backend"

# активация venv
source venv/Scripts/activate

# запуск backend в фоне
python -m server &
BACKEND_PID=$!

echo "Backend started (PID=$BACKEND_PID)"

echo "Starting web server..."

cd "$PROJECT_DIR/webapp"

# запуск http.server
python -m http.server 5501 &
WEB_PID=$!

echo "Web server started (PID=$WEB_PID)"

# ожидание завершения
wait