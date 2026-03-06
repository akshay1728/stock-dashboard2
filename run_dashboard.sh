#!/bin/bash
echo "=========================================="
echo "  Nifty Market Intelligence Dashboard"
echo "=========================================="
echo

# --- Conda Detection & Activation ---
if [ -z "$CONDA_SH" ]; then
    CONDA_SH_PATHS=(
        "$HOME/anaconda3/etc/profile.d/conda.sh"
        "$HOME/miniconda3/etc/profile.d/conda.sh"
        "/opt/anaconda3/etc/profile.d/conda.sh"
        "/opt/miniconda3/etc/profile.d/conda.sh"
        "/usr/local/anaconda3/etc/profile.d/conda.sh"
    )
    for p in "${CONDA_SH_PATHS[@]}"; do
        if [ -f "$p" ]; then
            source "$p"
            echo "[0/2] Activated Conda environment."
            break
        fi
    done
fi

echo "[1/2] Updating Market Data..."
python3 data_manager.py
if [ $? -ne 0 ]; then
    echo
    echo "ERROR: Data update failed."
    exit 1
fi
echo
echo "[2/2] Launching Stocko Live Data Collector (background)..."
python3 collector_service.py > collector.log 2>&1 &

echo "[3/2] Launching Streamlit Dashboard..."
streamlit run app.py
