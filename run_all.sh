#!/bin/bash
# Kill existing processes
kill $(lsof -t -i :8501) 2>/dev/null || true
pkill -f collector_service.py 2>/dev/null || true

# Fix dependencies
echo "Fixing library dependencies..."
python fix_library.py

# Start the background collector
echo "Starting Stocko Live Data Collector..."
python collector_service.py > collector.log 2>&1 &

# Start the Streamlit Dashboard
echo "Starting Market Intelligence Dashboard..."
streamlit run app.py
