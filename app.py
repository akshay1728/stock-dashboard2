import streamlit as st

# Global Styles - MUST BE FIRST
st.set_page_config(page_title="Market Intelligence Pro", layout="wide", page_icon="🚀")

import logging

# Unified logging configuration for the entire application
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("dashboard.log")
    ]
)
logger = logging.getLogger("DashboardUI")

import sqlite3
import requests
import json
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta
import subprocess
import os
import sys
import time
from streamlit_autorefresh import st_autorefresh
from options_manager import OptionsManager
from options_strategy import OptionsStrategy
from simulator_manager import SimulatorManager
from stocko_auth import StockoAuth
from config import Config

DB_NAME = 'breadth_data.db'

@st.dialog("Stocko API Login")
def login_dialog():
    st.write("### 🤖 Automated Authentication")
    st.write("The dashboard will now use the credentials provided in the settings to log in automatically.")
    st.info("Ensure Client Code, Password, and TOTP Secret are correctly configured.")

    if st.button("🚀 Start Automated Login"):
        auth = StockoAuth()
        with st.spinner("Authenticating with Stocko API..."):
            st.session_state.authenticated = False
            success = auth.login()
            if success:
                st.success("Authenticated successfully!")
                st.session_state.authenticated = True
                st.cache_data.clear()
                time.sleep(1)
                st.rerun()
            else:
                st.error("Authentication failed. Please verify your credentials and TOTP Secret in the settings.")

# Initialize Authentication State
if 'authenticated' not in st.session_state:
    # Check if token already exists
    if os.path.exists("stocko_token.json"):
        # We can try to validate it or just assume authenticated for UI
        # For robustness, we check it
        auth = StockoAuth()
        if auth._load_cached_token():
            st.session_state.authenticated = True
        else:
            st.session_state.authenticated = False
    else:
        st.session_state.authenticated = False

# Global CSS
st.markdown("""
<style>
    .metric-card {
        background: #f8f9fa;
        padding: 20px;
        border-radius: 12px;
        border: 1px solid #dee2e6;
        text-align: center;
        transition: all 0.3s ease;
        height: 100%;
        box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    .metric-card:hover {
        transform: translateY(-5px);
        background: #ffffff;
        border-color: #adb5bd;
        box-shadow: 0 4px 8px rgba(0,0,0,0.1);
    }
    .metric-label {
        color: #6c757d;
        margin: 0;
        font-size: 0.75rem;
        text-transform: uppercase;
        letter-spacing: 1.2px;
        font-weight: 600;
    }
    .metric-value {
        margin: 8px 0 0 0;
        font-size: 1.5rem;
        font-weight: 700;
        color: #212529;
    }
    .status-badge {
        display: inline-block;
        padding: 2px 8px;
        border-radius: 4px;
        font-size: 0.7rem;
        font-weight: bold;
        text-transform: uppercase;
    }
    /* Option Chain Table Styles */
    .opt-table {
        width: 100%;
        border-collapse: collapse;
        font-size: 0.85rem;
    }
    .opt-table th {
        background: #e9ecef;
        padding: 8px;
        border: 1px solid #dee2e6;
        text-align: center;
    }
    .opt-table td {
        padding: 4px 8px;
        border: 1px solid #dee2e6;
        text-align: center;
    }
    .strike-cell {
        background: #f1f3f5;
        font-weight: bold;
        color: #495057;
    }
    .ce-cell { background: rgba(46, 184, 46, 0.05); }
    .pe-cell { background: rgba(255, 75, 75, 0.05); }
</style>
""", unsafe_allow_html=True)

def stunning_tile(label, value, color="#212529"):
    st.markdown(f"""
    <div class="metric-card" style="border-top: 4px solid {color};">
        <p class="metric-label">{label}</p>
        <p class="metric-value" style="color: {color};">{value}</p>
    </div>
    """, unsafe_allow_html=True)

def init_saved_strategies_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    # Migration: Check if id column exists
    c.execute("PRAGMA table_info(saved_strategies)")
    cols = [row[1] for row in c.fetchall()]
    if cols and 'id' not in cols:
        c.execute("DROP TABLE saved_strategies")

    c.execute('''CREATE TABLE IF NOT EXISTS saved_strategies
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, timestamp DATETIME, legs_json TEXT)''')
    conn.commit()
    conn.close()

@st.dialog("Save Strategy")
def save_strategy_dialog():
    st.write("Save your current multi-leg strategy to your portfolio.")
    name = st.text_input("Strategy Name", value=f"Strategy {datetime.now().strftime('%d %b %H:%M')}")
    if st.button("Confirm Save"):
        import json
        legs_json = json.dumps(st.session_state.strategy_legs)
        conn = sqlite3.connect(DB_NAME)
        conn.execute("INSERT INTO saved_strategies (name, timestamp, legs_json) VALUES (?, ?, ?)",
                     (name, datetime.now().strftime('%Y-%m-%d %H:%M:%S'), legs_json))
        conn.commit()
        conn.close()
        st.success(f"Strategy '{name}' saved to portfolio!")
        time.sleep(1)
        st.rerun()

# Initialize session state for settings
if 'settings' not in st.session_state:
    st.session_state.settings = {
        'lot_sizes': {'NIFTY': 50, 'BANKNIFTY': 15, 'FINNIFTY': 40, 'MIDCPNIFTY': 75},
        'risk_free_rate': 0.07,
        'default_iv': 0.15
    }

# Simulator State Initialization
if 'sim_state' not in st.session_state:
    st.session_state.sim_state = {
        'is_playing': False,
        'current_idx': 0,
        'speed': 1,
        'data': pd.DataFrame(),
        'trade_log': [],
        'realized_pnl': 0.0,
        'equity_curve': [],
        'expiry_date': (datetime.now() + timedelta(days=7)).replace(hour=15, minute=30)
    }

if 'strategy_legs' not in st.session_state:
    st.session_state.strategy_legs = []

def apply_perf_shades(val):
    try:
        val = float(val)
        if val > 7: return 'background-color: #004d00; color: white'
        if val > 4: return 'background-color: #006400; color: white'
        if val > 2: return 'background-color: #228b22; color: white'
        if val > 0: return 'background-color: #90ee90; color: black'
        if val < -7: return 'background-color: #8b0000; color: white'
        if val < -4: return 'background-color: #b22222; color: white'
        if val < -2: return 'background-color: #ff4500; color: white'
        if val < 0: return 'background-color: #ffcccb; color: black'
    except: pass
    return ''

def apply_score_shades(val):
    try:
        val = float(val)
        if val >= 85: return 'background-color: #004d00; color: white'
        if val >= 75: return 'background-color: #006400; color: white'
        if val >= 65: return 'background-color: #228b22; color: white'
        if val >= 50: return 'background-color: #90ee90; color: black'
        if val < 20: return 'background-color: #8b0000; color: white'
        if val < 40: return 'background-color: #ffcccb; color: black'
    except: pass
    return ''

def apply_rank_shades(val):
    try:
        val = float(val)
        if val <= 50: return 'background-color: #004d00; color: white'
        if val <= 100: return 'background-color: #006400; color: white'
        if val <= 250: return 'background-color: #228b22; color: white'
        if val <= 500: return 'background-color: #90ee90; color: black'
    except: pass
    return ''

def apply_action_colors(val):
    if val == 'Accumulation': return 'background-color: #006400; color: white'
    if val == 'Distribution': return 'background-color: #8b0000; color: white'
    return 'background-color: #e9ecef; color: black'

SECTORS = {
    "^NSEI": "Nifty 50 (Benchmark)", "^NSEBANK": "Nifty Bank", "^CNXIT": "Nifty IT",
    "^CNXAUTO": "Nifty Auto", "^CNXPHARMA": "Nifty Pharma", "^CNXFMCG": "Nifty FMCG",
    "^CNXMETAL": "Nifty Metal", "^CNXREALTY": "Nifty Realty", "^CNXENERGY": "Nifty Energy",
    "^CNXMEDIA": "Nifty Media", "^CNXINFRA": "Nifty Infra", "^CNXPSE": "Nifty PSE",
    "^CNXPSUBANK": "Nifty PSU Bank", "^CNXFIN": "Nifty Fin Service"
}

@st.cache_data(ttl=3600)
def load_breadth_dma(segment="Nifty 500"):
    if not os.path.exists(DB_NAME): return pd.DataFrame()
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT * FROM breadth_counts WHERE segment = ? ORDER BY date ASC", conn, params=(segment,))
    conn.close()
    if not df.empty: df['date'] = pd.to_datetime(df['date'])
    return df

@st.cache_data(ttl=3600)
def load_exhaustion(segment="Nifty 500"):
    if not os.path.exists(DB_NAME): return pd.DataFrame()
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT * FROM market_exhaustion WHERE segment = ? ORDER BY date ASC", conn, params=(segment,))
    conn.close()
    if not df.empty: df['date'] = pd.to_datetime(df['date'])
    return df

@st.cache_data(ttl=3600)
def load_rrg():
    if not os.path.exists(DB_NAME): return pd.DataFrame()
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT * FROM rrg_data ORDER BY date ASC", conn)
    conn.close()
    if not df.empty: df['date'] = pd.to_datetime(df['date'])
    return df

@st.cache_data(ttl=3600)
def load_risk():
    if not os.path.exists(DB_NAME): return pd.DataFrame()
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT * FROM risk_metrics ORDER BY date ASC", conn)
    conn.close()
    if not df.empty: df['date'] = pd.to_datetime(df['date'])
    return df

@st.cache_data(ttl=3600)
def load_stock_metrics():
    if not os.path.exists(DB_NAME): return pd.DataFrame()
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT * FROM stock_metrics ORDER BY rs_rank ASC", conn)
    conn.close()
    return df

@st.cache_data(ttl=3600)
def load_stealth_accumulation():
    if not os.path.exists(DB_NAME): return pd.DataFrame()
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT * FROM stealth_accumulation ORDER BY score DESC", conn)
    conn.close()
    if not df.empty and 'date' in df.columns: df['date'] = pd.to_datetime(df['date'])
    return df

@st.cache_data(ttl=3600)
def load_breakout_ready():
    if not os.path.exists(DB_NAME): return pd.DataFrame()
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT * FROM breakout_ready ORDER BY probability_score DESC, score DESC", conn)
    conn.close()
    if not df.empty and 'date' in df.columns: df['date'] = pd.to_datetime(df['date'])
    return df

@st.cache_data(ttl=3600)
def load_sector_performance():
    if not os.path.exists(DB_NAME): return pd.DataFrame()
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT * FROM sector_performance ORDER BY momentum_score DESC", conn)
    conn.close()
    if not df.empty and 'date' in df.columns: df['date'] = pd.to_datetime(df['date'])
    return df

@st.cache_data(ttl=30)
def load_options_snapshots():
    if not os.path.exists(DB_NAME): return pd.DataFrame()
    conn = sqlite3.connect(DB_NAME)

    # Priority 1: Intelligence Snapshots (Processed by OptionsManager)
    df = pd.read_sql_query("SELECT * FROM option_snapshots WHERE timestamp = (SELECT MAX(timestamp) FROM option_snapshots)", conn)

    # Priority 2: Raw Collector Snapshots (Background Service)
    if df.empty or len(df) < 10:
        raw_df = pd.read_sql_query("SELECT * FROM option_chain_snapshots WHERE timestamp = (SELECT MAX(timestamp) FROM option_chain_snapshots)", conn)
        if not raw_df.empty:
            # Normalize column names to match the UI expectation (option_snapshots format)
            df = raw_df.rename(columns={
                'option_type': 'type',
                'expiry_date': 'expiry',
                'open_interest': 'oi',
                'implied_volatility': 'iv',
                'underlying_price': 'spot'
            })

    conn.close()
    return df

@st.cache_data(ttl=30)
def load_options_alerts():
    if not os.path.exists(DB_NAME): return pd.DataFrame()
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT * FROM option_alerts ORDER BY timestamp DESC LIMIT 100", conn)
    conn.close()
    return df

@st.cache_data(ttl=10)
def get_live_market_data():
    """Fetches live Nifty 50 and India VIX data."""
    results = {
        "nifty": {"last": None, "chg": None},
        "vix": {"last": None, "chg": None}
    }

    # Method 0: Stocko Ingested Data (Highest Priority if recent)
    try:
        if os.path.exists(DB_NAME):
            conn = sqlite3.connect(DB_NAME)
            # Check for recent data in index_prices (within last 5 minutes)
            five_min_ago = (datetime.now() - timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S')
            df = pd.read_sql_query("SELECT * FROM index_prices WHERE timestamp > ? ORDER BY timestamp DESC LIMIT 1", conn, params=(five_min_ago,))
            if not df.empty:
                latest = df.iloc[0]
                results["nifty"] = {"last": latest['last_price'], "chg": 0.0} # We don't store chg currently
                # For chg, we'd need previous day's close
                conn.close()
                return results
            conn.close()
    except: pass

    # Method 1: NSE API
    url = "https://www.nseindia.com/api/allIndices"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.nseindia.com/market-data/live-equity-market"
    }
    try:
        session = requests.Session()
        session.get("https://www.nseindia.com", headers=headers, timeout=5)
        response = session.get(url, headers=headers, timeout=5)
        if response.status_code == 200:
            data = response.json()
            for index in data.get("data", []):
                idx_name = index.get("index")
                if idx_name == "NIFTY 50":
                    val = str(index.get("last")).replace(',', '')
                    chg = str(index.get("percentChange")).replace(',', '')
                    results["nifty"] = {"last": float(val), "chg": float(chg)}
                elif idx_name == "INDIA VIX":
                    val = str(index.get("last")).replace(',', '')
                    chg = str(index.get("percentChange")).replace(',', '')
                    results["vix"] = {"last": float(val), "chg": float(chg)}

            if results["nifty"]["last"] is not None and results["vix"]["last"] is not None:
                return results
    except:
        pass

    # Method 2: yfinance Fallback
    try:
        if results["nifty"]["last"] is None:
            n_tick = yf.Ticker("^NSEI").fast_info
            last = n_tick['last_price']
            prev = n_tick['regular_market_previous_close']
            results["nifty"] = {"last": float(last), "chg": ((last/prev)-1)*100}

        if results["vix"]["last"] is None:
            v_tick = yf.Ticker("^INDIAVIX").fast_info
            last = v_tick['last_price']
            prev = v_tick['regular_market_previous_close']
            results["vix"] = {"last": float(last), "chg": ((last/prev)-1)*100}
    except:
        pass

    return results

def save_strategy(name, legs):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    legs_json = json.dumps(legs)
    c.execute("INSERT INTO saved_strategies (name, legs_json, timestamp) VALUES (?, ?, ?)",
              (name, legs_json, datetime.now().strftime('%Y-%m-%d %H:%M:%S')))
    conn.commit()
    conn.close()

def load_saved_strategies():
    init_saved_strategies_db()
    conn = sqlite3.connect(DB_NAME)
    try:
        df = pd.read_sql_query("SELECT * FROM saved_strategies", conn)
        conn.close()
        return {row['name']: json.loads(row['legs_json']) for _, row in df.iterrows()}
    except Exception as e:
        print(f"Error loading strategies: {e}")
        conn.close()
        return {}

def delete_strategy(name):
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute("DELETE FROM saved_strategies WHERE name = ?", (name,))
    conn.commit()
    conn.close()

@st.cache_data(ttl=30)
def load_options_regime():
    if not os.path.exists(DB_NAME): return pd.DataFrame()
    conn = sqlite3.connect(DB_NAME)
    df = pd.read_sql_query("SELECT * FROM market_regime ORDER BY timestamp DESC LIMIT 1", conn)
    conn.close()
    return df

def render_unified_strategy_builder(mode='live', sim_data=None):
    """
    Unified component for Strategy Builder and Strategy Simulator.
    mode: 'live' or 'sim'
    sim_data: Dictionary containing 'spot', 'time', 'dte', 'sim_manager'
    """
    # Contextual parameters
    if mode == 'live':
        spot_price, _ = get_live_market_data()['nifty'].values()
        if not spot_price: spot_price = 22000.0
        curr_time = datetime.now()
        sim_manager = SimulatorManager()
    else:
        spot_price = sim_data['spot']
        curr_time = sim_data['time']
        sim_manager = sim_data['sim_manager']

    # --- Option Chain with Buy/Sell Buttons ---
    snaps = load_options_snapshots()
    with st.expander("📊 Interactive Option Chain", expanded=False):
        if not snaps.empty:
            # Show last refreshed date/time
            last_ts = snaps['timestamp'].iloc[0]
            st.caption(f"🕒 Option Chain Last Refreshed: {last_ts}")

            available_expiries = sorted([e for e in snaps['expiry'].unique().tolist() if e])
            # Show next 4 expiries as requested
            available_expiries = available_expiries[:4]
            sel_expiry = st.selectbox("Select Expiry", available_expiries, key=f"chain_exp_{mode}")

            # Filter chain for selected expiry
            chain = snaps[snaps['expiry'] == sel_expiry].copy()

            # Center strikes around spot
            center_strike = round(spot_price/50)*50
            # Sort unique strikes to find the requested 30 Call + 30 Put strikes range
            # Note: OptionsManager.filter_strikes already handles the EOD/Snapshot limit,
            # but we'll ensure the UI focus matches.
            sorted_strikes = sorted(chain['strike'].unique())
            try:
                atm_idx = np.argmin([abs(s - spot_price) for s in sorted_strikes])
                start_s = sorted_strikes[max(0, atm_idx - 30)]
                end_s = sorted_strikes[min(len(sorted_strikes)-1, atm_idx + 30)]
                display_chain = chain[(chain['strike'] >= start_s) & (chain['strike'] <= end_s)].sort_values('strike')
            except:
                display_chain = chain.sort_values('strike')

            # We need a custom display because standard dataframe doesn't support streamlit buttons inside cells easily.
            # We'll use columns for the headers and then rows.
            head_cols = st.columns([1, 1, 1, 1, 1, 1, 1])
            head_cols[0].write("**CE Buy**")
            head_cols[1].write("**CE Price**")
            head_cols[2].write("**CE Sell**")
            head_cols[3].write("**Strike**")
            head_cols[4].write("**PE Buy**")
            head_cols[5].write("**PE Price**")
            head_cols[6].write("**PE Sell**")

            for strike in display_chain['strike'].unique():
                cols = st.columns([1, 1, 1, 1, 1, 1, 1])
                ce = display_chain[(display_chain['strike'] == strike) & (display_chain['type'] == 'CE')]
                pe = display_chain[(display_chain['strike'] == strike) & (display_chain['type'] == 'PE')]

                # CE Side
                if not ce.empty:
                    cp = ce.iloc[0]['ltp']
                    if cols[0].button("B", key=f"cb_{strike}_{mode}"):
                        st.session_state.strategy_legs.append({'type': 'Call', 'position': 'Buy', 'strike': strike, 'premium': cp, 'qty': 1, 'lot_size': 50, 'status': 'Open', 'exit_price': 0.0, 'expiry': sel_expiry})
                        if mode == 'sim': st.session_state.sim_state['trade_log'].append(f"[{curr_time.strftime('%H:%M')}] Buy Call {sel_expiry} @ {strike} for {cp}")
                        st.rerun()
                    cols[1].write(f"{cp}")
                    if cols[2].button("S", key=f"cs_{strike}_{mode}"):
                        st.session_state.strategy_legs.append({'type': 'Call', 'position': 'Sell', 'strike': strike, 'premium': cp, 'qty': 1, 'lot_size': 50, 'status': 'Open', 'exit_price': 0.0, 'expiry': sel_expiry})
                        if mode == 'sim': st.session_state.sim_state['trade_log'].append(f"[{curr_time.strftime('%H:%M')}] Sell Call {sel_expiry} @ {strike} for {cp}")
                        st.rerun()

                # Strike
                cols[3].markdown(f"**{strike}**")

                # PE Side
                if not pe.empty:
                    pp = pe.iloc[0]['ltp']
                    if cols[4].button("B", key=f"pb_{strike}_{mode}"):
                        st.session_state.strategy_legs.append({'type': 'Put', 'position': 'Buy', 'strike': strike, 'premium': pp, 'qty': 1, 'lot_size': 50, 'status': 'Open', 'exit_price': 0.0, 'expiry': sel_expiry})
                        if mode == 'sim': st.session_state.sim_state['trade_log'].append(f"[{curr_time.strftime('%H:%M')}] Buy Put {sel_expiry} @ {strike} for {pp}")
                        st.rerun()
                    cols[5].write(f"{pp}")
                    if cols[6].button("S", key=f"ps_{strike}_{mode}"):
                        st.session_state.strategy_legs.append({'type': 'Put', 'position': 'Sell', 'strike': strike, 'premium': pp, 'qty': 1, 'lot_size': 50, 'status': 'Open', 'exit_price': 0.0, 'expiry': sel_expiry})
                        if mode == 'sim': st.session_state.sim_state['trade_log'].append(f"[{curr_time.strftime('%H:%M')}] Sell Put {sel_expiry} @ {strike} for {pp}")
                        st.rerun()
        else:
            st.info("Option chain data not available. Direct adding from chain disabled.")

    st.divider()
    c1, c2 = st.columns([1, 2])

    with c1:
        st.subheader("Strategy Config")
        # Quick Templates
        template_name = st.selectbox("Quick Templates", ["Custom"] + list(OptionsStrategy.get_templates().keys()), key=f"tmpl_{mode}")
        if template_name != "Custom":
            if st.button("Apply Template", key=f"btn_tmpl_{mode}"):
                st.session_state.strategy_legs = []
                tmpl_legs = OptionsStrategy.get_templates()[template_name]
                latest_exp = sorted(snaps['expiry'].unique().tolist())[0] if not snaps.empty else None
                for tl in tmpl_legs:
                    l_strike = round((spot_price + tl['strike_offset'])/50)*50
                    if mode == 'sim':
                        p = sim_manager.get_option_price(spot_price, l_strike, sim_data['dte'], tl['type'], st.session_state.settings['default_iv'], st.session_state.settings['risk_free_rate'])
                    else:
                        # Try to get live premium
                        p = 100.0
                        if not snaps.empty:
                            m = snaps[(snaps['strike'] == l_strike) & (snaps['type'] == ('CE' if tl['type'] == 'Call' else 'PE')) & (snaps['expiry'] == latest_exp)]
                            if not m.empty: p = m.iloc[0]['ltp']

                    st.session_state.strategy_legs.append({
                        'type': tl['type'], 'position': tl['position'],
                        'strike': l_strike,
                        'premium': round(p, 2), 'qty': tl['qty'],
                        'lot_size': st.session_state.settings['lot_sizes'].get('NIFTY', 50),
                        'status': 'Open', 'exit_price': 0.0, 'expiry': latest_exp
                    })

        # Manual Add
        with st.expander("➕ Manual Entry", expanded=False):
            available_expiries = sorted(snaps['expiry'].unique().tolist()) if not snaps.empty else []
            l_expiry = st.selectbox("Expiry Date", available_expiries, key=f"new_l_exp_{mode}")
            l_type = st.selectbox("Type", ["Call", "Put", "Futures"], key=f"new_l_type_{mode}")
            l_pos = st.selectbox("Position", ["Buy", "Sell"], key=f"new_l_pos_{mode}")
            l_strike = st.number_input("Strike / Entry", value=round(spot_price/50)*50, step=50, key=f"new_l_strike_{mode}")

            # Auto-fetch premium logic
            default_prem = 100.0
            if l_type != "Futures":
                if mode == 'live':
                    match = snaps[(snaps['strike'] == l_strike) & (snaps['type'] == ('CE' if l_type == 'Call' else 'PE')) & (snaps['expiry'] == l_expiry)]
                    if not match.empty: default_prem = match.iloc[0]['ltp']
                else:
                    exp_dt = datetime.strptime(l_expiry, "%Y-%m-%d") if isinstance(l_expiry, str) else l_expiry
                    if hasattr(curr_time, 'tzinfo') and curr_time.tzinfo is not None: curr_time_naive = curr_time.replace(tzinfo=None)
                    else: curr_time_naive = curr_time
                    leg_dte = (exp_dt - curr_time_naive).total_seconds() / (24*3600)
                    default_prem = sim_manager.get_option_price(spot_price, l_strike, leg_dte, l_type, st.session_state.settings['default_iv'], st.session_state.settings['risk_free_rate'])

            l_prem = st.number_input("Premium", value=float(default_prem), step=0.1, key=f"new_l_prem_{mode}")
            l_qty = st.number_input("Lots", value=1, step=1, key=f"new_l_lots_{mode}")

            if st.button("Add Leg Manually", key=f"btn_add_{mode}"):
                st.session_state.strategy_legs.append({'type': l_type, 'position': l_pos, 'strike': l_strike, 'premium': l_prem, 'qty': l_qty, 'lot_size': 50, 'status': 'Open', 'exit_price': 0.0, 'expiry': l_expiry})
                if mode == 'sim': st.session_state.sim_state['trade_log'].append(f"[{curr_time.strftime('%H:%M')}] {l_pos} {l_type} {l_expiry} @ {l_strike} for {l_prem:.2f}")
                st.rerun()

    with c2:
        if st.session_state.strategy_legs:
            st.subheader("Current Legs")
            legs_to_del = []
            for i, leg in enumerate(st.session_state.strategy_legs):
                cols = st.columns([0.2, 1.3, 1, 1, 1, 0.5])
                status_icon = "🟢" if leg.get('status', 'Open') == 'Open' else "🔴"
                cols[0].write(status_icon)
                # Dynamic Coloring for Leg Label
                # Call = Green, Put = Red
                # Buy = Green, Sell = Red
                pos_color = "#2eb82e" if leg['position'] == "Buy" else "#ff4b4b"
                type_color = "#2eb82e" if leg['type'] == "Call" else "#ff4b4b" if leg['type'] == "Put" else "#212529"

                label_html = f"<span style='color:{pos_color}; font-weight:bold;'>{leg['position']}</span> "
                label_html += f"<span style='color:{type_color}; font-weight:bold;'>{leg['type']}</span> "
                if leg.get('expiry'):
                    label_html += f"<span style='color:#6c757d;'>{leg['expiry']}</span>"

                cols[1].markdown(label_html, unsafe_allow_html=True)
                cols[2].write(f"K: {leg['strike']}")
                cols[3].write(f"P: {leg['premium']}")
                cols[4].write(f"Q: {leg['qty']} (x{leg['lot_size']})")

                with cols[5]:
                    pop = st.popover("⚙️")
                    if leg.get('status', 'Open') == 'Open':
                        pop.markdown("**Edit Leg Details**")
                        e_strike = pop.number_input("Strike", value=float(leg['strike']), step=50.0, key=f"e_strike_{mode}_{i}")
                        e_prem = pop.number_input("Entry Premium", value=float(leg['premium']), step=0.1, key=f"e_prem_{mode}_{i}")
                        e_qty = pop.number_input("Lots", value=int(leg['qty']), step=1, key=f"e_qty_{mode}_{i}")

                        if pop.button("Update Leg", key=f"upd_{mode}_{i}"):
                            leg['strike'] = e_strike; leg['premium'] = e_prem; leg['qty'] = e_qty; st.rerun()

                        pop.divider()
                        pop.markdown("**Exit Position**")
                        exit_p = pop.number_input("Exit Price", value=float(leg['premium']), key=f"exit_p_{mode}_{i}")
                        if pop.button("Close Position", key=f"close_{mode}_{i}"):
                            leg['status'] = 'Closed'; leg['exit_price'] = exit_p
                            if mode == 'sim':
                                mult = 1 if leg['position'] == 'Buy' else -1
                                pnl = (exit_p - leg['premium']) * mult * leg['qty'] * leg['lot_size']
                                st.session_state.sim_state['realized_pnl'] += pnl
                                st.session_state.sim_state['trade_log'].append(f"[{curr_time.strftime('%H:%M')}] Closed {leg['type']} {leg['strike']} @ {exit_p:.2f} (P&L: ₹{pnl:,.0f})")
                            st.rerun()
                    else:
                        if pop.button("Re-open", key=f"reopen_{mode}_{i}"): leg['status'] = 'Open'; st.rerun()
                    if pop.button("🗑️ Delete Leg", key=f"del_{mode}_{i}"): legs_to_del.append(i)

            if legs_to_del:
                for idx in sorted(legs_to_del, reverse=True): st.session_state.strategy_legs.pop(idx)
                st.rerun()
            c_save, c_clear = st.columns(2)
            if c_save.button("💾 Save Strategy", key=f"save_{mode}"):
                save_strategy_dialog()
            if c_clear.button("Clear All", key=f"clear_{mode}"):
                st.session_state.strategy_legs = []; st.session_state.sim_state['realized_pnl'] = 0.0; st.rerun()
        else:
            st.info("No legs added yet. Use the option chain or templates above.")

    # Payoff Analysis & Greeks
    if st.session_state.strategy_legs:
        st.divider()
        r_min, r_max = spot_price * 0.85, spot_price * 1.15
        price_range = np.linspace(r_min, r_max, 500)
        total_payoff = np.zeros_like(price_range)
        t0_payoff = np.zeros_like(price_range)
        total_premium = 0; total_delta = 0; total_theta = 0; total_vega = 0; realized_pnl = 0

        for leg in st.session_state.strategy_legs:
            total_payoff += OptionsStrategy.calculate_payoff(price_range, leg)
            mult = int(leg['qty']) * int(leg['lot_size'])
            net_p = float(leg['premium']) * mult
            if leg['position'] == 'Buy': total_premium -= net_p
            else: total_premium += net_p

            if leg.get('status', 'Open') == 'Closed':
                p = (float(leg['exit_price']) - float(leg['premium'])) * mult * (1 if leg['position'] == 'Buy' else -1)
                realized_pnl += p; t0_payoff += p; continue

            # Scenario - use nearest expiry DTE for Greeks/T+0 focus
            T_adj = 7/365.0 # Default
            if mode == 'sim': T_adj = sim_data['dte']/365.0

            prices_t0 = np.array([OptionsStrategy.black_scholes(p, float(leg['strike']), T_adj, 0.07, 0.15, leg['type'].lower()) for p in price_range])
            if leg['position'] == 'Buy': t0_p = (prices_t0 - float(leg['premium'])) * mult
            else: t0_p = (float(leg['premium']) - prices_t0) * mult
            t0_payoff += t0_p

            greeks = OptionsStrategy.calculate_greeks(spot_price, float(leg['strike']), T_adj, 0.07, 0.15, leg['type'].lower())
            g_mult = mult * (1 if leg['position'] == 'Buy' else -1)
            total_delta += greeks['delta'] * g_mult; total_theta += greeks['theta'] * g_mult; total_vega += greeks['vega'] * g_mult

        max_p, min_p, unl_p, unl_l = OptionsStrategy.analyze_risk_reward(st.session_state.strategy_legs)
        m_cols = st.columns(4)
        with m_cols[0]: stunning_tile("Net Premium", f"₹{total_premium:,.0f}", "#00d4ff")
        with m_cols[1]: stunning_tile("Max Profit", "Unlimited" if unl_p else f"₹{max_p:,.0f}", "#2eb82e")
        with m_cols[2]: stunning_tile("Max Loss", "Unlimited" if unl_l else f"₹{min_p:,.0f}", "#ff4b4b")
        with m_cols[3]:
            # Realized P&L display
            stunning_tile("Realized P&L", f"₹{realized_pnl:,.0f}", "#7c4dff" if realized_pnl >= 0 else "#ff5252")

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=price_range, y=np.where(total_payoff >= 0, total_payoff, 0), fill='tozeroy', fillcolor='rgba(46,184,46,0.2)', line=dict(color='#2eb82e', width=2), name="Expiry Profit"))
        fig.add_trace(go.Scatter(x=price_range, y=np.where(total_payoff < 0, total_payoff, 0), fill='tozeroy', fillcolor='rgba(255,75,75,0.2)', line=dict(color='#ff4b4b', width=2), name="Expiry Loss"))
        fig.add_trace(go.Scatter(x=price_range, y=t0_payoff, name="T+0 days", line=dict(color='magenta', width=2, dash='dot')))
        fig.add_vline(x=spot_price, line_dash="dash", line_color="black")
        fig.add_hline(y=0, line_color="black", line_width=1)
        fig.update_layout(template="plotly_white", height=400)
        st.plotly_chart(fig, use_container_width=True)

        st.markdown("### Strategy Greeks")
        g1, g2, g3 = st.columns(3)
        with g1: stunning_tile("Delta", f"{total_delta:.2f}", "#212529")
        with g2: stunning_tile("Theta", f"₹{total_theta:,.0f}/day", "#212529")
        with g3: stunning_tile("Vega", f"₹{total_vega:,.0f}/1% IV", "#212529")

# Auto-refresh every 60 seconds
st_autorefresh(interval=60000, key="datarefresh")

st.sidebar.title("🚀 Navigation")

# Live Market Status in Sidebar
st.sidebar.subheader("📡 Live Market Status")
market_data = get_live_market_data()
live_spot = market_data['nifty']['last']
live_chg = market_data['nifty']['chg']
live_vix = market_data['vix']['last']
live_vix_chg = market_data['vix']['chg']

if live_spot:
    spot_color = "green" if live_chg >= 0 else "red"
    st.sidebar.markdown(f"### NIFTY 50: <span style='color:{spot_color}'>{live_spot:,.2f}</span> ({live_chg:+.2f}%)", unsafe_allow_html=True)
if live_vix:
    vix_color = "green" if live_vix_chg >= 0 else "red"
    st.sidebar.markdown(f"### INDIA VIX: <span style='color:{vix_color}'>{live_vix:.2f}</span> ({live_vix_chg:+.2f}%)", unsafe_allow_html=True)

if not live_spot and not live_vix:
    st.sidebar.info("Market Closed / Fetching live data...")

# DB Update Status
if os.path.exists(DB_NAME):
    mtime = os.path.getmtime(DB_NAME)
    last_update = datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M")
    st.sidebar.caption(f"📅 Last Data Update: {last_update}")

# Function to change page
def nav_to(page_name):
    st.session_state.current_page = page_name
    st.rerun()

def ensure_options_data_is_fresh(live_spot=None):
    """Ensures that option chain data is updated if stale. Handles failure gracefully."""
    regime_df = load_options_regime()
    should_update = False
    if regime_df.empty:
        should_update = True
    else:
        last_ts = pd.to_datetime(regime_df.iloc[0]['timestamp'])
        # Only try updating if it's more than 65s old
        if (datetime.now() - last_ts).total_seconds() > 65:
            # We use session state to avoid retry loops if update fails
            if 'last_update_attempt' not in st.session_state or \
               (datetime.now() - st.session_state.last_update_attempt).total_seconds() > 30:
                should_update = True

    if should_update:
        st.session_state.last_update_attempt = datetime.now()
        with st.spinner("Updating real-time option chain..."):
            auth = StockoAuth()
            # If not authenticated, om.update will fallback to scraper
            om = OptionsManager(stocko_auth=auth if st.session_state.get('authenticated') else None)
            om.update(spot_price_hint=live_spot)
            st.cache_data.clear()
            # We don't rerun here to allow the app to proceed with whatever is in DB
            # if the update failed or succeeded.

def render_portfolio():
    st.header("💼 Strategy Portfolio")
    st.write("Track and manage your saved multi-leg strategies.")

    init_saved_strategies_db()
    conn = sqlite3.connect(DB_NAME)
    df_saved = pd.read_sql_query("SELECT * FROM saved_strategies ORDER BY timestamp DESC", conn)
    conn.close()

    if df_saved.empty:
        st.info("Your portfolio is empty. Create a strategy in the Strategy Builder and save it.")
    else:
        # Calculate Total Portfolio P&L (Unrealized)
        total_pnl = 0.0
        snaps = load_options_snapshots()

        for _, row in df_saved.iterrows():
            import json
            legs = json.loads(row['legs_json'])
            strat_pnl = 0.0
            for leg in legs:
                mult = int(leg['qty']) * int(leg['lot_size'])
                if leg.get('status') == 'Closed':
                    p = (float(leg['exit_price']) - float(leg['premium'])) * mult * (1 if leg['position'] == 'Buy' else -1)
                    strat_pnl += p
                else:
                    # Look up current market price
                    if not snaps.empty:
                        match = snaps[(snaps['strike'] == leg['strike']) &
                                      (snaps['type'] == ('CE' if leg['type'] == 'Call' else 'PE')) &
                                      (snaps['expiry'] == leg['expiry'])]
                        if not match.empty:
                            curr_price = match.iloc[0]['ltp']
                            p = (curr_price - float(leg['premium'])) * mult * (1 if leg['position'] == 'Buy' else -1)
                            strat_pnl += p

            total_pnl += strat_pnl

            # Display Card
            with st.container(border=True):
                c1, c2, c3 = st.columns([2, 1, 1])
                c1.markdown(f"### {row['name']}")
                c1.caption(f"Saved: {row['timestamp']}")

                color = "green" if strat_pnl >= 0 else "red"
                c2.markdown(f"**Strategy P&L**")
                c2.markdown(f"<h3 style='color:{color}; margin-top:0;'>₹{strat_pnl:,.0f}</h3>", unsafe_allow_html=True)

                with c3:
                    if st.button("👁️ View/Edit", key=f"view_{row['id']}"):
                        import json
                        st.session_state.strategy_legs = json.loads(row['legs_json'])
                        nav_to("🛠️ Strategy Builder")
                    if st.button("🗑️ Delete", key=f"del_strat_{row['id']}"):
                        conn = sqlite3.connect(DB_NAME)
                        conn.execute("DELETE FROM saved_strategies WHERE id=?", (row['id'],))
                        conn.commit(); conn.close()
                        st.rerun()

        st.divider()
        p_color = "green" if total_pnl >= 0 else "red"
        stunning_tile("Total Portfolio P&L (Live)", f"₹{total_pnl:,.0f}", p_color)

# Sidebar Navigation
nav_options = ["💼 Portfolio", "🏠 Market Breadth", "🎯 Options Intelligence", "🛠️ Strategy Builder", "📈 Strategy Simulator", "🔄 Sector Rotation", "📉 Market Exhaustion", "💰 Smart Money Flow", "🕵️ Stealth Accumulation", "🚀 Breakout Ready", "📈 RS Leaders", "🔥 EOD Watchlist", "⚙️ Settings", "💾 Data Management"]

# Initialize current_page
if 'current_page' not in st.session_state:
    st.session_state.current_page = nav_options[0]

# Ensure current_page is valid
if st.session_state.current_page not in nav_options:
    st.session_state.current_page = nav_options[0]

def on_nav_change():
    st.session_state.current_page = st.session_state.nav_radio_sidebar

page = st.sidebar.radio("Go to",
    nav_options,
    index=nav_options.index(st.session_state.current_page),
    key="nav_radio_sidebar",
    on_change=on_nav_change
)

st.sidebar.divider()
if st.sidebar.button("🔄 Refresh All Data"):
    with st.spinner("Updating Market Data..."):
        subprocess.run([sys.executable, "data_manager.py"])
        st.cache_data.clear()
        st.rerun()

# --- PORTFOLIO ---
if page == "💼 Portfolio":
    render_portfolio()

# --- SETTINGS ---
elif page == "⚙️ Settings":
    st.title("⚙️ Global Settings")
    st.write("Configure API credentials and dashboard parameters.")

    tab1, tab2, tab3 = st.tabs(["🔑 Stocko API Configuration", "💹 Trading Parameters", "⚙️ Model Parameters"])

    with tab1:
        st.subheader("Stocko API Credentials")
        col1, col2 = st.columns(2)
        with col1:
            api_key = st.text_input("API Key (App ID)", value=Config.API_KEY or "")
            api_secret = st.text_input("API Secret", value=Config.API_SECRET or "", type="password")
            client_code = st.text_input("Client Code", value=Config.CLIENT_CODE or "")
        with col2:
            totp_secret = st.text_input("TOTP Secret (2FA Key)", value=Config.TOTP_SECRET or "", type="password")
            base_url = st.text_input("Base URL", value=Config.BASE_URL or "https://api.stocko.in")
            password = st.text_input("Stocko Password", value=Config.PASSWORD or "", type="password")
            redirect_url = st.text_input("Redirect URL", value=Config.REDIRECT_URL or "http://127.0.0.1:65015/")

        if st.button("Save API Configuration"):
            # Sanitize inputs before saving
            Config.save_to_db({
                "API_KEY": api_key.strip(),
                "API_SECRET": api_secret.strip(),
                "REDIRECT_URL": redirect_url.strip(),
                "BASE_URL": base_url.strip().rstrip('/'),
                "CLIENT_CODE": client_code.strip(),
                "PASSWORD": password, # Don't strip password as spaces might be intended
                "TOTP_SECRET": totp_secret.strip()
            })
            st.success("API configuration saved to database!")
            st.rerun()

        st.divider()
        st.subheader("Authentication Status")
        if st.session_state.authenticated:
            st.success("🟢 Authenticated: Connected to Stocko API")
            if st.button("Logout / Re-authenticate"):
                st.session_state.authenticated = False
                if os.path.exists("stocko_token.json"): os.remove("stocko_token.json")
                st.rerun()
        else:
            st.warning("🔴 Not Authenticated")
            if st.button("Initiate Login"):
                login_dialog()

    with tab2:
        st.subheader("Index Lot Sizes")
        if 'settings' not in st.session_state:
            st.session_state.settings = {'lot_sizes': {'NIFTY': 50, 'BANKNIFTY': 15, 'FINNIFTY': 40, 'MIDCPNIFTY': 75}, 'risk_free_rate': 0.07, 'default_iv': 0.15}

        for idx, lot in st.session_state.settings['lot_sizes'].items():
            new_lot = st.number_input(f"{idx} Lot Size", value=lot, step=1, key=f"lot_{idx}")
            st.session_state.settings['lot_sizes'][idx] = new_lot

    with tab3:
        st.subheader("Black-Scholes Parameters")
        st.session_state.settings['risk_free_rate'] = st.number_input("Risk-Free Rate (e.g. 0.07 for 7%)", value=st.session_state.settings['risk_free_rate'], step=0.005, format="%.3f")
        st.session_state.settings['default_iv'] = st.number_input("Base Implied Volatility (0.15 = 15%)", value=st.session_state.settings['default_iv'], step=0.01, format="%.2f")

    if st.button("Save Local Parameters"):
        st.success("Trading and Model settings updated for this session!")

# --- HOME ---
elif page == "🏠 Market Breadth":
    st.title("🚀 Market Intelligence Dashboard")
    segment = st.selectbox("Market Segment", ["Nifty 500", "Midcap 150", "Smallcap 250"], key="seg_home")

    df = load_breadth_dma(segment)
    risk_df = load_risk()

    if not df.empty:
        latest = df.iloc[-1]
        prev = df.iloc[-2] if len(df) > 1 else latest

        # Summary Insight Box
        b20 = (latest['above_sma20'] / latest['total_stocks']) * 100
        b50 = (latest['above_sma50'] / latest['total_stocks']) * 100
        b200 = (latest['above_sma200'] / latest['total_stocks']) * 100

        avg_breadth = (b20 + b50 + b200) / 3
        if avg_breadth > 70: health, h_color = "Extremely Bullish", "green"
        elif avg_breadth > 55: health, h_color = "Bullish", "#90ee90"
        elif avg_breadth > 45: health, h_color = "Neutral / Mixed", "orange"
        elif avg_breadth > 30: health, h_color = "Bearish", "#ffcccb"
        else: health, h_color = "Extremely Bearish", "red"

        st.markdown(f"""
        <div style="padding: 20px; border-radius: 10px; background-color: #f8f9fa; border-left: 10px solid {h_color};">
            <h2 style="margin:0;">Market Health: <span style="color:{h_color}">{health}</span></h2>
            <p style="margin:5px 0 0 0;">Average Breadth (20/50/200 DMA): <strong>{avg_breadth:.1f}%</strong></p>
        </div>
        """, unsafe_allow_html=True)

        st.write("")
        st.header(f":blue[{segment}] Internal Strength")

        c1, c2, c3, c4 = st.columns(4)
        def metric_ui(label, curr, total, p_val, seg):
            total = total if total > 0 else 1
            pct = (curr / total) * 100
            p_pct = (p_val / total) * 100
            st.metric(f"{seg} > {label}", f"{pct:.1f}%", f"{pct - p_pct:.1f}%")
            st.caption(f"**{curr} / {total}** stocks")

        with c1: metric_ui("20 DMA", latest['above_sma20'], latest['total_stocks'], prev['above_sma20'], segment)
        with c2: metric_ui("50 DMA", latest['above_sma50'], latest['total_stocks'], prev['above_sma50'], segment)
        with c3: metric_ui("200 DMA", latest['above_sma200'], latest['total_stocks'], prev['above_sma200'], segment)
        with c4:
            if live_vix:
                st.metric("India VIX", f"{live_vix:.2f}", f"{live_vix_chg:+.2f}%")
            elif not risk_df.empty:
                v = risk_df.iloc[-1]
                v_prev = risk_df.iloc[-2]['vix_close'] if len(risk_df) > 1 else v['vix_close']
                st.metric("India VIX", f"{v['vix_close']:.2f}", f"{v['vix_close'] - v_prev:+.2f}")

        st.subheader(f"Historical Breadth Trend: {segment}")
        selected_smas = st.multiselect("Select DMA Periods", [20, 50, 200], default=[20, 50, 200])

        fig = go.Figure()
        colors = {20: "blue", 50: "orange", 200: "green"}
        for sma in selected_smas:
            fig.add_trace(go.Scatter(x=df['date'], y=(df[f'above_sma{sma}']/df['total_stocks'])*100, name=f"{segment} > {sma} DMA", line=dict(color=colors[sma])))

        fig.update_layout(template="plotly_white", height=450, yaxis_title="Percentage Above DMA (%)", hovermode="x unified")
        st.plotly_chart(fig, use_container_width=True)

# --- OPTIONS ---
elif page == "🎯 Options Intelligence":
    st.title("🎯 Nifty 50 Options Intelligence")
    ensure_options_data_is_fresh(live_spot=live_spot)
    regime_df = load_options_regime()
    snapshots = load_options_snapshots()
    alerts_df = load_options_alerts()

    if not regime_df.empty:
        intelligence_regime = regime_df.iloc[0]
        last_refreshed = intelligence_regime['timestamp']
        st.caption(f"🕒 Intelligence & Chain Last Refreshed: {last_refreshed}")

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Market Classification", intelligence_regime['classification'])
        c2.metric("Nifty Spot", f"{intelligence_regime['spot']:.2f}")
        c3.metric("ATM IV", f"{intelligence_regime['iv_atm']:.2f}%")

        gamma_score = intelligence_regime['gamma_score']
        g_color = "red" if gamma_score > 70 else "orange" if gamma_score > 50 else "green"
        c4.markdown(f"### Gamma Squeeze: <span style='color:{g_color}'>{gamma_score}/100</span>", unsafe_allow_html=True)

        st.info(f"💡 **Positioning Bias:** {intelligence_regime['bias']} | **Volatility Regime:** {intelligence_regime['iv_regime']} | **Institutional Confidence:** {intelligence_regime['confidence_score']}%")
        if gamma_score > 60:
            st.error(f"⚠️ **URGENT: Gamma Squeeze Risk ({gamma_score}/100)** - Extreme hedging pressure detected.")
        elif gamma_score > 40:
            st.warning(f"⚠️ **Caution: Elevating Gamma Risk ({gamma_score}/100)**")

    tab1, tab2, tab3, tab4 = st.tabs(["🚀 Pro Strategy & Alerts", "⚡ OI Spike Detector", "📊 Volume Spike Detector", "📈 Gamma & S/R Monitor"])

    with tab1:
        col1, col2 = st.columns([1, 1])
        with col1:
            st.subheader("💡 Institutional Strategy")
            strategy_alerts = alerts_df[alerts_df['type'] == "Strategy"]
            if not strategy_alerts.empty:
                latest_strat = strategy_alerts.iloc[0]
                conf = latest_strat['confidence']
                st.info(f"### {latest_strat['message']}")

                c_score_col1, c_score_col2 = st.columns([1, 2])
                c_score_col1.metric("Confidence Score", f"{conf}%")
                c_score_col2.progress(conf / 100)

                st.caption("Strategy is dynamically mapped to IV regime, PCR bias, and institutional build-up.")
            else:
                st.write("Analyzing market internals for optimal strategy...")

        with col2:
            st.subheader("🚩 Institutional Flow Alerts")
            if not alerts_df.empty:
                display_alerts = alerts_df[alerts_df['type'].isin(["OI Spike", "Volume Spike", "Block Trade"])].head(6)
                for _, alert in display_alerts.iterrows():
                    color = "red" if "Short" in alert['message'] or "Bearish" in alert['message'] else "green" if "Long" in alert['message'] or "Bullish" in alert['message'] else "blue"
                    icon = "⚡" if alert['type'] == "OI Spike" else "📊" if alert['type'] == "Volume Spike" else "🐳"
                    try: ts_display = pd.to_datetime(alert['timestamp']).strftime("%Y-%m-%d %H:%M:%S")
                    except: ts_display = alert['timestamp']

                    st.markdown(f"""
                    <div style="padding: 10px; border-radius: 5px; border-left: 5px solid {color}; background-color: #f8f9fa; margin-bottom: 5px;">
                        <span style="font-size: 0.8em; color: gray;">{ts_display}</span><br>
                        <strong>{icon} {alert['type']}</strong>: {alert['message']}
                    </div>
                    """, unsafe_allow_html=True)
            else:
                st.success("No critical institutional alerts detected in the last hour.")

    with tab2:
        st.subheader("🚀 Sudden Open Interest Spikes")
        if not alerts_df.empty:
            oi_spikes = alerts_df[alerts_df['type'] == "OI Spike"].copy()
            if not oi_spikes.empty: st.dataframe(oi_spikes[['timestamp', 'strike', 'opt_type', 'message', 'confidence']].style.map(apply_score_shades, subset=['confidence']), use_container_width=True)
            else: st.info("No major OI spikes detected in recent snapshots.")

    with tab3:
        st.subheader("📊 Unusual Volume Activity")
        if not alerts_df.empty:
            vol_spikes = alerts_df[alerts_df['type'] == "Volume Spike"].copy()
            if not vol_spikes.empty: st.dataframe(vol_spikes[['timestamp', 'strike', 'opt_type', 'message', 'confidence']].style.map(apply_score_shades, subset=['confidence']), use_container_width=True)
            else: st.info("No unusual volume activity detected.")

    with tab4:
        if not snapshots.empty:
            st.subheader("🏰 Shifting Support & Resistance zones")
            chain = snapshots.copy()
            res = chain[chain['type'] == 'CE'].sort_values('oi', ascending=False).head(5)
            sup = chain[chain['type'] == 'PE'].sort_values('oi', ascending=False).head(5)
            sc1, sc2 = st.columns(2)
            sc1.markdown("#### 🔴 Resistance Walls (Call Writing)")
            st.dataframe(res[['strike', 'oi', 'oi_change', 'iv']].style.map(apply_perf_shades, subset=['oi_change']), use_container_width=True)
            sc2.markdown("#### 🟢 Support Bases (Put Writing)")
            st.dataframe(sup[['strike', 'oi', 'oi_change', 'iv']].style.map(apply_perf_shades, subset=['oi_change']), use_container_width=True)

            st.subheader("🌊 Gamma Pressure Zones")
            spot_val = intelligence_regime['spot'] if not regime_df.empty else chain['strike'].median()
            near_chain = chain[(chain['strike'] >= spot_val - 400) & (chain['strike'] <= spot_val + 400)]
            fig = go.Figure()
            fig.add_trace(go.Bar(x=near_chain[near_chain['type']=='CE']['strike'], y=near_chain[near_chain['type']=='CE']['oi'], name='Call OI (Resistance)', marker_color='#ff4b4b'))
            fig.add_trace(go.Bar(x=near_chain[near_chain['type']=='PE']['strike'], y=near_chain[near_chain['type']=='PE']['oi'], name='Put OI (Support)', marker_color='#2eb82e'))
            fig.update_layout(title=f"OI Concentration Near Spot ({spot_val:.0f})", barmode='group', template="plotly_white", height=400)
            st.plotly_chart(fig, use_container_width=True)
            st.subheader("🔍 Detailed Option Chain")
            st.dataframe(chain.sort_values('strike'), use_container_width=True)
        else:
            st.warning("No option chain snapshots available.")

# --- Builder / Simulator Pages ---
elif page == "🛠️ Strategy Builder":
    st.title("🛠️ Options Strategy Builder")
    ensure_options_data_is_fresh(live_spot=live_spot)

    st.write("Build multi-leg option strategies, visualize payoffs, and analyze risk.")
    render_unified_strategy_builder(mode='live')

elif page == "📈 Strategy Simulator":
    st.title("📈 Options Strategy Simulator")
    st.markdown("Replay historical market movement and test your strategy adjustments in real-time.")
    sim_manager = SimulatorManager()

    with st.sidebar:
        st.header("🎮 Simulator Controls")

        mode = st.radio("Data Source", ["Local History (1.5Y)", "Live yfinance Fetch"])

        if mode == "Live yfinance Fetch":
            sim_days = st.slider("Historical Days to Fetch", 1, 30, 5)
            if st.button("Load Live Data"):
                with st.spinner("Fetching historical intraday data..."):
                    if sim_manager.fetch_historical_intraday(days=sim_days, use_local=False):
                        st.session_state.sim_state['data'] = sim_manager.data
                        st.session_state.sim_state['current_idx'] = 0; st.success("Data Loaded!")
        else:
            if st.button("Load Local 1.5Y History"):
                with st.spinner("Loading local historical database..."):
                    if sim_manager.fetch_historical_intraday(use_local=True):
                        st.session_state.sim_state['data'] = sim_manager.data
                        st.session_state.sim_state['current_idx'] = 0; st.success(f"Loaded {len(sim_manager.data)} records!")

        if not st.session_state.sim_state['data'].empty:
            st.divider()
            col1, col2 = st.columns(2)
            if col1.button("▶ Play" if not st.session_state.sim_state['is_playing'] else "⏸ Pause"):
                st.session_state.sim_state['is_playing'] = not st.session_state.sim_state['is_playing']
            if col2.button("↺ Reset"):
                st.session_state.sim_state['current_idx'] = 0; st.session_state.strategy_legs = []; st.session_state.sim_state['realized_pnl'] = 0.0; st.session_state.sim_state['trade_log'] = []
            st.session_state.sim_state['speed'] = st.selectbox("Replay Speed", [1, 2, 5, 10, 50], index=0)
            st.divider(); st.subheader("Time Navigation")
            tn1, tn2, tn3 = st.columns(3)
            if tn1.button("⏪ -1H"): st.session_state.sim_state['current_idx'] = max(0, st.session_state.sim_state['current_idx'] - 12)
            if tn2.button("Step"): st.session_state.sim_state['current_idx'] = min(len(st.session_state.sim_state['data'])-1, st.session_state.sim_state['current_idx'] + 1)
            if tn3.button("+1H ⏩"): st.session_state.sim_state['current_idx'] = min(len(st.session_state.sim_state['data'])-1, st.session_state.sim_state['current_idx'] + 12)

    if st.session_state.sim_state['data'].empty: st.info("👈 Please load historical data from the sidebar.")
    else:
        df = st.session_state.sim_state['data']
        if st.session_state.sim_state['is_playing']:
            st.session_state.sim_state['current_idx'] = min(len(df)-1, st.session_state.sim_state['current_idx'] + st.session_state.sim_state['speed'])
            if st.session_state.sim_state['current_idx'] >= len(df)-1: st.session_state.sim_state['is_playing'] = False
            time.sleep(0.1); st.rerun()
        curr_idx = st.session_state.sim_state['current_idx']
        curr_row = df.iloc[curr_idx]; curr_time = df.index[curr_idx]; curr_spot = curr_row['Close']
        expiry = st.session_state.sim_state['expiry_date']
        if hasattr(curr_time, 'tzinfo') and curr_time.tzinfo is not None: curr_time_naive = curr_time.replace(tzinfo=None)
        else: curr_time_naive = curr_time
        expiry_dt = datetime.combine(expiry, datetime.min.time())
        dte = (expiry_dt - curr_time_naive).total_seconds() / (24*3600)

        m1, m2, m3 = st.columns(3)
        with m1: stunning_tile("Spot Price", f"₹{curr_spot:,.2f}", "#212529")
        with m2: stunning_tile("Time", curr_time.strftime("%d %b, %H:%M"), "#2979ff")
        with m3: stunning_tile("DTE", f"{dte:.2f} Days", "#ffea00")

        st.subheader("📊 Intraday Index Chart")
        visible_df = df.iloc[max(0, curr_idx-100):curr_idx+1]
        fig = go.Figure(); fig.add_trace(go.Scatter(x=visible_df.index, y=visible_df['Close'], mode='lines+markers', name="Nifty 50"))
        fig.update_layout(template="plotly_white", height=300, margin=dict(l=0,r=0,t=0,b=0)); st.plotly_chart(fig, use_container_width=True)

        st.divider()
        render_unified_strategy_builder(mode='sim', sim_data={'spot': curr_spot, 'time': curr_time, 'dte': dte, 'sim_manager': sim_manager})
        with st.expander("📝 Simulator Trade Log"):
            for entry in reversed(st.session_state.sim_state['trade_log']): st.caption(entry)

# --- RRG ---
elif page == "🔄 Sector Rotation":
    st.title("🔄 Sector Relative Rotation")
    rrg_df = load_rrg()
    if not rrg_df.empty:
        all_syms = [s for s in rrg_df['symbol'].unique() if s != "^NSEI"]
        selected = st.multiselect("Select Sectors to Visualize", all_syms, default=all_syms[:8], format_func=lambda x: SECTORS.get(x, x))
        fig = go.Figure()
        fig.add_shape(type="rect", x0=100, y0=100, x1=120, y1=120, fillcolor="rgba(0,255,0,0.15)", line_width=0, layer="below")
        fig.add_shape(type="rect", x0=100, y0=80, x1=120, y1=100, fillcolor="rgba(255,255,0,0.15)", line_width=0, layer="below")
        fig.add_shape(type="rect", x0=80, y0=80, x1=100, y1=100, fillcolor="rgba(255,0,0,0.1)", line_width=0, layer="below")
        fig.add_shape(type="rect", x0=80, y0=100, x1=100, y1=120, fillcolor="rgba(0,0,255,0.1)", line_width=0, layer="below")
        for s in selected:
            data = rrg_df[rrg_df['symbol'] == s].tail(10)
            fig.add_trace(go.Scatter(x=data['rs_ratio'], y=data['rs_momentum'], mode='lines+markers', name=SECTORS.get(s, s).replace("Nifty ", "")))
        fig.update_layout(template="plotly_white", height=700, xaxis=dict(range=[85, 115]), yaxis=dict(range=[85, 115])); st.plotly_chart(fig, use_container_width=True)

    st.divider()
    st.subheader("📊 Sector Performance Matrix")
    perf_df = load_sector_performance()
    if not perf_df.empty:
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("#### 🏆 Top Performing Sectors")
            st.dataframe(perf_df.sort_values('perf_1w', ascending=False).head(10)[['name', 'perf_1w', 'rs_vs_nifty', 'momentum_score']].style.map(apply_perf_shades, subset=['perf_1w']), use_container_width=True)
        with c2:
            st.markdown("#### 🚀 Improving Momentum")
            st.dataframe(perf_df.sort_values('momentum_score', ascending=False).head(10)[['name', 'perf_1m', 'momentum_score', 'accumulation_ratio']].style.map(apply_score_shades, subset=['momentum_score']), use_container_width=True)

        st.subheader("🔍 All Sector Metrics")
        st.dataframe(perf_df.style.map(apply_perf_shades, subset=['perf_1w', 'perf_1m', 'perf_3m', 'rs_vs_nifty']), use_container_width=True)
    else:
        st.info("No sector performance metrics available.")

# --- EXHAUSTION ---
elif page == "📉 Market Exhaustion":
    st.title("📉 Market Exhaustion Module")
    segment = st.selectbox("Benchmark Segment", ["Nifty 500", "Midcap 150", "Smallcap 250"], key="seg_ex")
    df = load_exhaustion(segment)
    if not df.empty:
        latest = df.iloc[-1]
        c1, c2 = st.columns(2)
        c1.metric("Risk Score", f"{latest['exhaustion_score']}/100"); c2.metric("Dist Days", int(latest['dist_days']))
        fig = go.Figure(); fig.add_trace(go.Scatter(x=df['date'], y=df['exhaustion_score'], name="Exhaustion Score")); fig.update_layout(template="plotly_white", height=400); st.plotly_chart(fig, use_container_width=True)

# --- SMART MONEY ---
elif page == "💰 Smart Money Flow":
    st.title("💰 Smart Money Flow")
    sm_df = load_stock_metrics()
    if not sm_df.empty:
        acc_count = len(sm_df[sm_df['classification'] == "Accumulation"])
        dist_count = len(sm_df[sm_df['classification'] == "Distribution"])
        c1, c2 = st.columns(2)
        with c1: stunning_tile("Accumulating", f"{acc_count}", "#00e676")
        with c2: stunning_tile("Distributing", f"{dist_count}", "#ff5252")

        tab1, tab2 = st.tabs(["🚀 Institutional Accumulation", "📉 Institutional Distribution"])
        with tab1:
            acc_df = sm_df[sm_df['classification'] == "Accumulation"].sort_values('rs_rank', ascending=True)
            st.dataframe(acc_df[['symbol', 'rs_rank', 'delivery_pct', 'vol_expansion', 'delivery_slope']].style.map(apply_perf_shades, subset=['delivery_pct']), use_container_width=True)
        with tab2:
            dist_df = sm_df[sm_df['classification'] == "Distribution"].sort_values('rs_rank', ascending=False)
            st.dataframe(dist_df[['symbol', 'rs_rank', 'delivery_pct', 'vol_expansion', 'delivery_slope']].style.map(apply_perf_shades, subset=['delivery_pct']), use_container_width=True)

# --- BREAKOUT READY ---
elif page == "🚀 Breakout Ready":
    st.title("🚀 Breakout Ready Stocks")
    df = load_breakout_ready()
    if not df.empty:
        c1, c2 = st.columns([1, 3])
        with c1:
            segment = st.selectbox("Filter Segment", ["All", "Nifty 500", "Midcap 150", "Smallcap 250"], key="br_seg")
            min_score = st.slider("Min Probability Score", 0, 100, 50, key="br_score")

        display_df = df.copy()
        if segment != "All": display_df = display_df[display_df['segment'] == segment]
        display_df = display_df[display_df['probability_score'] >= min_score]

        st.subheader(f"🎯 High Probability Breakouts ({len(display_df)})")
        st.dataframe(display_df.sort_values('probability_score', ascending=False).style.map(apply_score_shades, subset=['probability_score']), use_container_width=True)

# --- STEALTH ACCUMULATION ---
elif page == "🕵️ Stealth Accumulation":
    st.title("🕵️ Stealth Accumulation")
    df = load_stealth_accumulation()
    if not df.empty:
        st.markdown("> *Identifying institutional support before price breakouts.*")
        min_sa_score = st.slider("Min Stealth Score", 0, 100, 60, key="sa_score")
        sa_df = df[df['score'] >= min_sa_score].sort_values('score', ascending=False)
        st.dataframe(sa_df.style.map(apply_score_shades, subset=['score']).map(apply_perf_shades, subset=['delivery_pct']), use_container_width=True)

# --- RS LEADERS ---
elif page == "📈 RS Leaders":
    st.title("📈 Relative Strength Leaders")
    df = load_stock_metrics()
    if not df.empty:
        top_rs = df[df['rs_rank'] <= 20].sort_values('rs_rank')
        st.dataframe(top_rs[['symbol', 'rs_rank', 'rs_score', 'classification', 'segment']].style.map(apply_score_shades, subset=['rs_rank']), use_container_width=True)

# --- EOD WATCHLIST ---
elif page == "🔥 EOD Watchlist":
    st.title("🔥 EOD Action Watchlist")
    df = load_stock_metrics()
    if not df.empty:
        wl = df[df['is_watchlist'] == 1]
        if not wl.empty:
            st.dataframe(wl[['symbol', 'setup_tags', 'rs_rank', 'delivery_pct', 'classification']].style.map(apply_perf_shades, subset=['delivery_pct']), use_container_width=True)
        else:
            st.info("No stocks in today's ACTION watchlist yet.")

# --- DATA MANAGEMENT ---
elif page == "💾 Data Management":
    st.title("💾 Historical Data Management")
    st.write("Manage real 1-minute historical data for Nifty 50 and Options.")

    from database import Database
    db = Database()

    # Stats
    stats = db.get_history_stats()
    c1, c2 = st.columns(2)
    with c1:
        s = stats.get('index_1m_history', {})
        st.markdown(f"""
        <div style="background: #e3f2fd; padding: 15px; border-radius: 10px; border-left: 5px solid #2196f3;">
            <h4>📈 Index 1m History</h4>
            <p>Total Records: <strong>{s.get('count', 0):,}</strong></p>
            <p>Start: {s.get('start', 'N/A')}</p>
            <p>End: {s.get('end', 'N/A')}</p>
        </div>
        """, unsafe_allow_html=True)

    with c2:
        s = stats.get('option_1m_history', {})
        st.markdown(f"""
        <div style="background: #f1f8e9; padding: 15px; border-radius: 10px; border-left: 5px solid #4caf50;">
            <h4>🎯 Option 1m History</h4>
            <p>Total Records: <strong>{s.get('count', 0):,}</strong></p>
            <p>Start: {s.get('start', 'N/A')}</p>
            <p>End: {s.get('end', 'N/A')}</p>
        </div>
        """, unsafe_allow_html=True)

    st.divider()
    st.subheader("📤 Bulk CSV Import")
    st.info("Import real historical data from CSV. Expected columns: `timestamp`, `symbol`, `open`, `high`, `low`, `close`, `volume` (Index) or `timestamp`, `symbol`, `expiry_date`, `strike`, `option_type`, `ltp`, `open_interest`, `implied_volatility` (Options).")

    target_table = st.selectbox("Select Target Table", ["index_1m_history", "option_1m_history"])
    uploaded_file = st.file_uploader("Choose a CSV file", type="csv")

    if uploaded_file is not None:
        if st.button("Start Import"):
            # Save temporary file
            with open("temp_import.csv", "wb") as f:
                f.write(uploaded_file.getbuffer())

            with st.spinner("Importing data..."):
                success, msg = db.import_csv("temp_import.csv", target_table)
                if success:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(f"Import failed: {msg}")

# --- OTHERS ---
else:
    st.title(f"🚀 {page}")
    df = load_stock_metrics()
    if not df.empty: st.dataframe(df.head(50), use_container_width=True)
