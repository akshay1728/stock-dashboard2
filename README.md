# Pro Market Intelligence Dashboard (Nifty 500)

A professional-grade multi-page Streamlit dashboard for analyzing the Indian stock market using the Nifty 500 universe.

## 🚀 Key Features

### 1. 📊 Market Breadth (Home)
- **Segmented Breadth**: Monitor Nifty 500, Midcap 150, and Smallcap 250 independently.
- **DMA Breadth**: Tracks percentage of stocks above 20, 50, and 200-day Daily Moving Averages (DMA/SMA).
- **Historical Trends**: Interactive line charts for breadth trend analysis.
- **Volatility Monitor**: Integrated India VIX tracking with historical volatility regimes.

### 2. 📉 Market Exhaustion
- **Distribution Tracker**: Identifies "Distribution Days" to spot institutional selling.
- **Divergence Scoring**: Detects price-breadth divergences indicating trend fatigue.

### 3. 🌟 Leadership Change
- **Sector Momentum Shifts**: Ranks sectors by participation and detects "Emerging Leaders" or "Weakening" sectors.
- **Participation Map**: Scatters sectors by their breadth relative to momentum ranks.

### 4. 💰 Smart Money Flow
- **Accumulation/Distribution**: Classifies stocks based on delivery volume expansion and SMA relative action.
- **Heatmaps**: Visualizes institutional money flow across sectors.

### 5. 🔄 Sector Rotation (RRG)
- **Relative Rotation Graph**: Visualize sector rotation with professional Plotly RRG charts (Leading, Weakening, Lagging, Improving).
- **Interactive Filtering**: Select specific sectors or view the top 8 momentum leaders by default.
- **Weekly RS Tail**: High-readability 8-period weekly tails with directional arrows.
- **RS Confirmation**: Tracks sector strength vs the Nifty 500 benchmark (^CRSLDX).

### 6. 📈 RS Leaders & Watchlist
- **Relative Strength Leaders**: Top 50 Nifty 500 stocks outperforming the benchmark.
- **EOD Watchlist**: Curated candidates with high RS, volume spikes, and confirmed uptrends.

### 7. 🎯 Options Intelligence (Live)
- **Real-time Flow**: Ingests minute-by-minute option chain data via Stocko API.
- **Gamma Squeeze Detector**: Monitors extreme hedging pressure in the Nifty 50 option chain.
- **Institutional Alerts**: Detects sudden OI spikes, volume anomalies, and block trades.
- **Strategy Builder**: Interactive payoff visualizer for multi-leg option strategies (Live & Historical).

---

## 🛠 Setup & Installation

1. **Install Dependencies**:
   ```bash
   pip install yfinance pandas streamlit plotly requests beautifulsoup4 pyoauthbridge pyotp
   ```

2. **Configuration**:
   Create a `.env` file with your Stocko API credentials:
   ```env
   STOCKO_API_KEY=your_api_key
   STOCKO_API_SECRET=your_api_secret
   STOCKO_CLIENT_CODE=your_client_code
   STOCKO_PASSWORD=your_password
   STOCKO_TOTP_SECRET=your_totp_secret_optional
   ```

3. **Initialize & Update Data**:
   ```bash
   python data_manager.py
   ```

4. **Start Live Data Collection**:
   Run the background collector to ingest live market and option chain data:
   ```bash
   python collector_service.py
   ```

5. **Run the Dashboard**:
   ```bash
   streamlit run app.py
   ```

---

## 🚀 Desktop Quick Launch (One-Click)

For a professional "one-click" experience, use the included launcher scripts:

### **Windows**
1. Right-click `run_dashboard.bat`.
2. Select **Send to > Desktop (create shortcut)**.
3. Now you can launch and update the app directly from your desktop.

### **macOS / Linux**
1. Open terminal in the project folder.
2. Run `chmod +x run_dashboard.sh`.
3. Double-click `run_dashboard.sh` to start.

## ⚙️ Optimization & Architecture
- **Data Layer**: Powered by `yfinance` with batched downloads (100 symbols/batch).
- **Storage Layer**: SQLite database (`breadth_data.db`) for historical performance tracking.
- **Processing Layer**: Daily pipeline handles SMA, RSI, RS, and momentum calculations.
- **UI Layer**: Streamlit multi-page app with high-performance caching.

## 📅 Automatic Updates
To run the data pipeline automatically every trading day:
```bash
0 18 * * 1-5 /usr/bin/python3 /path/to/data_manager.py >> /path/to/cron.log 2>&1
```
