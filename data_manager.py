import pandas as pd
import yfinance as yf
import sqlite3
import logging
from datetime import datetime, timedelta
import os
import numpy as np
import requests
import io
import time
from options_manager import OptionsManager

DB_NAME = 'breadth_data.db'
logger = logging.getLogger(__name__)

# Basic logging config if run directly
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
NIFTY_500_URL = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
MIDCAP_150_URL = "https://archives.nseindia.com/content/indices/ind_niftymidcap150list.csv"
SMALLCAP_250_URL = "https://archives.nseindia.com/content/indices/ind_niftysmallcap250list.csv"

SECTORS = {
    "^NSEI": "Nifty 50 (Benchmark)", "^NSEBANK": "Nifty Bank", "^CNXIT": "Nifty IT",
    "^CNXAUTO": "Nifty Auto", "^CNXPHARMA": "Nifty Pharma", "^CNXFMCG": "Nifty FMCG",
    "^CNXMETAL": "Nifty Metal", "^CNXREALTY": "Nifty Realty", "^CNXENERGY": "Nifty Energy",
    "^CNXMEDIA": "Nifty Media", "^CNXINFRA": "Nifty Infra", "^CNXPSE": "Nifty PSE",
    "^CNXPSUBANK": "Nifty PSU Bank", "^CNXFIN": "Nifty Fin Service"
}

def get_symbols(url):
    try:
        logger.info(f"Downloading symbols from {url}")
        r = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'})
        if r.status_code != 200:
            logger.error(f"Failed to download symbols. Status: {r.status_code}")
            return pd.DataFrame(columns=['Symbol'])

        df = pd.read_csv(io.StringIO(r.text))
        # NSE CSVs sometimes have different column names or casing
        df.columns = [c.strip() for c in df.columns]
        if 'Symbol' not in df.columns and 'SYMBOL' in df.columns:
            df.rename(columns={'SYMBOL': 'Symbol'}, inplace=True)
        logger.info(f"Successfully loaded {len(df)} symbols.")
        return df
    except Exception as e:
        logger.error(f"Error loading symbols: {str(e)}")
        return pd.DataFrame(columns=['Symbol'])

def get_delivery_data():
    """
    Downloads NSE full bhavcopy to get delivery data.
    Tries recent dates starting from today.
    """
    logger.info("Fetching delivery data from NSE archives...")
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    for i in range(5):
        date = (datetime.now() - timedelta(days=i)).strftime('%d%m%Y')
        url = f"https://archives.nseindia.com/products/content/sec_bhavdata_full_{date}.csv"
        try:
            logger.debug(f"Trying delivery data for {date}: {url}")
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                df = pd.read_csv(io.StringIO(r.text))
                df.columns = [c.strip() for c in df.columns]
                logger.info(f"Successfully retrieved delivery data for {date}. Rows: {len(df)}")
                return df
        except Exception as e:
            logger.warning(f"Attempt for {date} failed: {str(e)}")
            continue
    logger.error("Could not retrieve delivery data for any of the last 5 days.")
    return pd.DataFrame()

def init_db():
    logger.info(f"Initializing database at {DB_NAME}...")
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()

    # Breadth Counts Migration
    c.execute("PRAGMA table_info(breadth_counts)")
    cols = [row[1] for row in c.fetchall()]
    if cols and ('segment' not in cols or 'above_sma20' not in cols):
        c.execute("DROP TABLE breadth_counts")

    c.execute('CREATE TABLE IF NOT EXISTS breadth_counts (date DATE, segment TEXT, above_sma20 INTEGER, above_sma50 INTEGER, above_sma200 INTEGER, total_stocks INTEGER, advances INTEGER, declines INTEGER, new_highs INTEGER, new_lows INTEGER, PRIMARY KEY (date, segment))')
    c.execute('CREATE TABLE IF NOT EXISTS market_exhaustion (date DATE, segment TEXT, dist_days INTEGER, exhaustion_score INTEGER, signals TEXT, PRIMARY KEY (date, segment))')
    c.execute('CREATE TABLE IF NOT EXISTS rrg_data (date DATE, symbol TEXT, rs_ratio REAL, rs_momentum REAL, PRIMARY KEY (date, symbol))')
    c.execute('CREATE TABLE IF NOT EXISTS sector_performance (date DATE, symbol TEXT, name TEXT, perf_1w REAL, perf_1m REAL, perf_3m REAL, rs_vs_nifty REAL, momentum_score REAL, accumulation_ratio REAL, PRIMARY KEY (date, symbol))')

    # Stock Metrics Migration for Segment
    c.execute("PRAGMA table_info(stock_metrics)")
    cols = [row[1] for row in c.fetchall()]
    if cols and 'segment' not in cols:
        c.execute("DROP TABLE stock_metrics")
    c.execute('CREATE TABLE IF NOT EXISTS stock_metrics (date DATE, symbol TEXT, rs_score REAL, rs_rank INTEGER, adl REAL, obv REAL, delivery_pct REAL, delivery_slope REAL, vol_expansion REAL, classification TEXT, is_watchlist INTEGER, setup_tags TEXT, segment TEXT, PRIMARY KEY (date, symbol))')

    c.execute('CREATE TABLE IF NOT EXISTS risk_metrics (date DATE PRIMARY KEY, vix_close REAL, vix_change REAL, volatility_regime TEXT)')
    c.execute('CREATE TABLE IF NOT EXISTS daily_delivery (date DATE, symbol TEXT, delivery_pct REAL, PRIMARY KEY (date, symbol))')

    # Stealth Accumulation Migration
    c.execute("PRAGMA table_info(stealth_accumulation)")
    cols = [row[1] for row in c.fetchall()]
    if cols and 'segment' not in cols:
        c.execute("DROP TABLE stealth_accumulation")
    c.execute('CREATE TABLE IF NOT EXISTS stealth_accumulation (date DATE, symbol TEXT, score INTEGER, delivery_pct REAL, delivery_trend TEXT, vol_contraction REAL, higher_low TEXT, ad_trend TEXT, rs_trend TEXT, sector TEXT, segment TEXT, PRIMARY KEY (date, symbol))')

    c.execute('CREATE TABLE IF NOT EXISTS breakout_ready (date DATE, symbol TEXT, score INTEGER, base_type TEXT, delivery_status TEXT, rs_status TEXT, resistance REAL, segment TEXT, probability_score INTEGER, PRIMARY KEY (date, symbol))')

    # Unified Saved Strategies table with ID
    c.execute("PRAGMA table_info(saved_strategies)")
    cols = [row[1] for row in c.fetchall()]
    if cols and 'id' not in cols:
        logger.warning("Migration: Dropping old saved_strategies table for ID column update.")
        c.execute("DROP TABLE saved_strategies")
    c.execute('CREATE TABLE IF NOT EXISTS saved_strategies (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, timestamp DATETIME, legs_json TEXT)')

    conn.commit(); conn.close()
    logger.info("Database initialization complete.")

def calculate_sma(df, period):
    """Calculates Simple Moving Average (SMA/DMA)."""
    return df.rolling(window=period).mean()

def get_fo_symbols():
    # Attempt to get FNO list from NSE API
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': 'https://www.nseindia.com/'
    }
    common_fo = ["RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "ICICIBANK.NS", "INFY.NS", "IDEA.NS", "SBIN.NS", "BHARTIARTL.NS"]

    try:
        session = requests.Session()
        session.get("https://www.nseindia.com", headers=headers, timeout=5)
        url = "https://www.nseindia.com/api/equity-stockIndices?index=SECURITIES%20IN%20F%26O"
        r = session.get(url, headers=headers, timeout=10)
        if r.status_code == 200:
            data = r.json()
            syms = [item['symbol'] + ".NS" for item in data.get('data', []) if 'symbol' in item]
            if len(syms) > 100: # Sanity check
                return list(set(syms))
    except Exception as e:
        print(f"Error fetching F&O list from API: {e}")

    return common_fo

def update_data():
    start_time_total = time.time()
    logger.info("Starting Data Pipeline Update...")
    init_db()
    n500 = get_symbols(NIFTY_500_URL); m150 = get_symbols(MIDCAP_150_URL); s250 = get_symbols(SMALLCAP_250_URL)
    fo_list = get_fo_symbols()
    syms = {
        "Nifty 500": [s+".NS" for s in n500['Symbol'].tolist()],
        "Midcap 150": [s+".NS" for s in m150['Symbol'].tolist()],
        "Smallcap 250": [s+".NS" for s in s250['Symbol'].tolist()]
    }
    all_syms = list(set(syms["Nifty 500"] + syms["Midcap 150"] + syms["Smallcap 250"]))

    conn = sqlite3.connect(DB_NAME); cursor = conn.cursor()

    # Determine the last update date
    cursor.execute("SELECT MAX(date) FROM breadth_counts")
    last_date_str = cursor.fetchone()[0]
    if last_date_str:
        last_date = datetime.strptime(last_date_str, '%Y-%m-%d')
        start_date = last_date - timedelta(days=300) # Increased to ensure enough data for 200 DEMA
    else:
        last_date = None
        start_date = datetime.now() - timedelta(days=730)

    end = datetime.now()
    logger.info(f"Downloading benchmark data from {start_date.strftime('%Y-%m-%d')} to {end.strftime('%Y-%m-%d')}...")

    # Try to get live Nifty spot (Method 1)
    live_nifty = None
    try:
        om_temp = OptionsManager()
        live_nifty = om_temp.get_realtime_spot()
    except: pass

    bench = yf.download(["^NSEI", "^CRSLDX", "^INDIAVIX"], start=start_date, end=end, progress=False)
    if bench.empty:
        logger.error("No benchmark data returned from yfinance.")
        return

    n50 = bench['Close']['^NSEI'].ffill().bfill()
    if live_nifty and not n50.empty:
        # If live nifty is available and newer than yfinance, we can use it as the latest point
        # But for consistency in daily charts, we usually stick to EOD or latest 15-min.
        # For the Options Intelligence hint, it's already used.
        pass
    n500idx = bench['Close']['^CRSLDX'].ffill().bfill()
    n50vol = bench['Volume']['^NSEI'].ffill().fillna(0)
    vix = bench['Close']['^INDIAVIX'].ffill().bfill()

    logger.info(f"Downloading data for {len(all_syms)} stocks...")
    stocks = yf.download(all_syms, start=start_date, end=end, group_by='ticker', progress=False)
    logger.info("Downloading sector data...")
    sectors = yf.download(list(SECTORS.keys()), start=start_date, end=end, group_by='ticker', progress=False)

    valid_syms = [s for s in all_syms if s in stocks and not stocks[s].empty]
    logger.info(f"Successfully retrieved data for {len(valid_syms)} / {len(all_syms)} stocks.")
    closes = pd.DataFrame({s: stocks[s]['Close'] for s in valid_syms}).ffill().bfill()
    highs = pd.DataFrame({s: stocks[s]['High'] for s in valid_syms}).ffill().bfill()
    lows = pd.DataFrame({s: stocks[s]['Low'] for s in valid_syms}).ffill().bfill()
    volumes = pd.DataFrame({s: stocks[s]['Volume'] for s in valid_syms}).ffill().fillna(0)

    new_dates = closes.index
    if last_date:
        new_dates = new_dates[new_dates > last_date]

    if not new_dates.empty:
        for seg, s_list in syms.items():
            logger.info(f"Processing {seg} Breadth for {len(new_dates)} new days...")
            s_closes = closes[closes.columns.intersection(s_list)]
            if s_closes.empty: continue

            # Use SMA (Simple Moving Average / DMA)
            s20 = calculate_sma(s_closes, 20)
            s50 = calculate_sma(s_closes, 50)
            s200 = calculate_sma(s_closes, 200)

            a20, a50, a200 = (s_closes > s20).sum(axis=1).fillna(0), (s_closes > s50).sum(axis=1).fillna(0), (s_closes > s200).sum(axis=1).fillna(0)
            tot = s_closes.notna().sum(axis=1).replace(0, 1).fillna(1)

            for date in new_dates:
                dstr = date.strftime('%Y-%m-%d')
                cursor.execute('INSERT OR REPLACE INTO breadth_counts VALUES (?,?,?,?,?,?,?,?,?,?)', (dstr, seg, int(a20[date]), int(a50[date]), int(a200[date]), int(tot[date]), 0, 0, 0, 0))

            # Exhaustion
            n_ret = n50.pct_change()
            dd = ((n_ret < -0.002) & (n50vol > n50vol.shift(1))).rolling(25).sum()
            br = a50 / tot
            # Prepare exhaustion components
            dd_indexed = dd.reindex(s_closes.index).ffill().fillna(0)
            n50_indexed = n50.reindex(s_closes.index).ffill()
            n50_rolling_max = n50_indexed.rolling(20).max()

            for date in new_dates:
                dstr = date.strftime('%Y-%m-%d')
                score = int(dd_indexed[date]) * 10
                idx_near_high = (n50_indexed[date] > n50_rolling_max[date]*0.98)
                breadth_weakening = (br[date] < br.rolling(20).mean().fillna(0)[date])
                div = 1 if (idx_near_high and breadth_weakening) else 0
                if div: score += 25
                cursor.execute('INSERT OR REPLACE INTO market_exhaustion VALUES (?,?,?,?,?)', (dstr, seg, int(dd_indexed[date]), min(score, 100), "Divergence" if div else ""))
    else:
        logger.info("Breadth data already up to date.")

    # RRG
    logger.info("Processing RRG (Relative Rotation Graph) logic...")
    s_c = pd.DataFrame({s: sectors[s]['Close'] for s in SECTORS if s in sectors and not sectors[s].empty}).ffill().bfill()
    s_w = s_c.resample('W').last(); n_w = n500idx.resample('W').last()
    rs = s_w.div(n_w, axis=0)
    rs_r = (rs / rs.rolling(10).mean().replace(0, np.nan)) * 100
    rs_m = (rs_r / rs_r.rolling(4).mean().replace(0, np.nan)) * 100
    for date in rs_r.index[-52:]:
        for s in SECTORS:
            if s in rs_r.columns and not np.isnan(rs_r.loc[date, s]) and not np.isnan(rs_m.loc[date, s]):
                cursor.execute('INSERT OR REPLACE INTO rrg_data VALUES (?,?,?,?)', (date.strftime('%Y-%m-%d'), s, float(rs_r.loc[date, s]), float(rs_m.loc[date, s])))

    # Sector Performance
    logger.info("Processing Sector Performance metrics...")
    latest_date_sec = s_c.index[-1]
    n50_c = n50.reindex(s_c.index).ffill()

    for s in SECTORS:
        if s not in s_c.columns: continue
        try:
            p_1w = (s_c[s].iloc[-1] / s_c[s].iloc[-6] - 1) * 100 if len(s_c) > 6 else 0
            p_1m = (s_c[s].iloc[-1] / s_c[s].iloc[-22] - 1) * 100 if len(s_c) > 22 else 0
            p_3m = (s_c[s].iloc[-1] / s_c[s].iloc[-64] - 1) * 100 if len(s_c) > 64 else 0

            n_3m = (n50_c.iloc[-1] / n50_c.iloc[-64] - 1) * 100 if len(n50_c) > 64 else 0
            rs_val = p_3m - n_3m
            mom_score = (p_1w * 0.4 + p_1m * 0.3 + p_3m * 0.3)

            cursor.execute('INSERT OR REPLACE INTO sector_performance VALUES (?,?,?,?,?,?,?,?,?)',
                           (latest_date_sec.strftime('%Y-%m-%d'), s, SECTORS[s], float(p_1w), float(p_1m), float(p_3m), float(rs_val), float(mom_score), 0.0))
        except Exception as e:
            logger.error(f"Error calculating performance for {s}: {str(e)}")

    # Stock Metrics & Stealth Accumulation
    logger.info("Processing Stock Metrics, Stealth Accumulation & Breakout models...")
    latest_date = closes.index[-1]
    latest_date_str = latest_date.strftime('%Y-%m-%d')

    # 1. Delivery Data
    del_df = get_delivery_data()
    delivery_map = {}
    if not del_df.empty:
        del_df['SYMBOL'] = del_df['SYMBOL'] + ".NS"
        for _, row in del_df.iterrows():
            try:
                d_pct = float(row['DELIV_PER'])
                delivery_map[row['SYMBOL']] = d_pct
                cursor.execute('INSERT OR REPLACE INTO daily_delivery VALUES (?,?,?)', (latest_date_str, row['SYMBOL'], d_pct))
            except: continue
    else:
        logger.warning("Could not fetch real delivery data; technical proxy will be used for current day.")

    # 2. Load historical delivery for trends
    hist_del = pd.read_sql_query("SELECT * FROM daily_delivery WHERE date > ?", conn, params=((latest_date - timedelta(days=30)).strftime('%Y-%m-%d'),))
    hist_del_pivot = hist_del.pivot(index='date', columns='symbol', values='delivery_pct').ffill() if not hist_del.empty else pd.DataFrame()

    # 3. Technical Indicators for Stealth, RS Rank & Breakout Ready
    # RS Score: 6-month (126 day) relative performance
    n50_ret = n50 / n50.shift(126).replace(0, np.nan)
    stock_ret = closes / closes.shift(126).replace(0, np.nan)
    rs_score_df = (stock_ret.div(n50_ret, axis=0) - 1) * 100
    rs_ranks = rs_score_df.loc[latest_date].rank(ascending=False, method='min').fillna(0)

    rs_df = closes.div(n50, axis=0)
    rs_trend = (rs_df.rolling(5).mean() > rs_df.rolling(20).mean())
    atr = (highs - lows).rolling(20).mean()
    vol_cont = atr / atr.rolling(60).mean().replace(0, np.nan)
    h_lows = lows.rolling(5).min() > lows.shift(5).rolling(5).min()
    mfv = ((closes - lows) - (highs - closes)) / (highs - lows).replace(0, 1) * volumes
    adl = mfv.cumsum()
    ad_trend = adl.rolling(5).mean() > adl.rolling(20).mean()
    vol_avg = volumes.rolling(20).mean()
    vol_exp = (volumes / vol_avg.replace(0, 1))

    # Breakout specific indicators
    df_range = highs - lows
    range_trend = df_range.rolling(20).mean().diff()
    resistance_30 = highs.rolling(30).max()

    # RS near new high
    rs_high_30 = rs_df.rolling(30).max()
    rs_near_high = (rs_df >= rs_high_30 * 0.98)

    # Bollinger Band Squeeze
    ma20 = closes.rolling(20).mean()
    std20 = closes.rolling(20).std()
    upper_bb = ma20 + (std20 * 2)
    lower_bb = ma20 - (std20 * 2)
    bb_width = (upper_bb - lower_bb) / ma20
    bb_squeeze = bb_width < bb_width.rolling(100).min() * 1.1

    # Volume Dry-up then Expansion
    vol_dryup = volumes < volumes.rolling(20).mean() * 0.7
    vol_expansion = volumes > volumes.rolling(20).mean() * 1.5

    # Sector RS for probability model
    sector_closes = pd.DataFrame({s: sectors[s]['Close'] for s in SECTORS if s in sectors}).ffill().bfill()
    sector_rs = sector_closes.div(n50, axis=0)
    sector_rs_trend = (sector_closes.rolling(5).mean() > sector_closes.rolling(20).mean())

    # Use SMA 50 for classification
    sma50 = calculate_sma(closes, 50)

    # 4. Sector Map from Nifty 500
    sector_map = n500.set_index('Symbol')['Industry'].to_dict() if 'Industry' in n500.columns else {}

    cursor.execute("DELETE FROM stock_metrics")
    cursor.execute("DELETE FROM stealth_accumulation WHERE date = ?", (latest_date_str,))
    cursor.execute("DELETE FROM breakout_ready WHERE date = ?", (latest_date_str,))

    for sym in valid_syms:
        # Standard Metrics
        v_exp = float(vol_exp.loc[latest_date, sym])
        d_pct = delivery_map.get(sym, 0.0)
        if d_pct == 0.0: # Fallback to proxy
            range_width = (highs[sym] - lows[sym]).replace(0, 1)
            d_pct = float(((closes[sym] - lows[sym]) / range_width).rolling(5).mean().iloc[-1] * 100)

        c_sma50 = sma50.loc[latest_date, sym]; curr_close = closes.loc[latest_date, sym]
        cls = "Accumulation" if (curr_close > c_sma50 and v_exp > 1.2) else "Distribution" if (curr_close < c_sma50 and v_exp > 1.2) else "Neutral"

        r_score = float(rs_score_df.loc[latest_date, sym]) if not np.isnan(rs_score_df.loc[latest_date, sym]) else 0.0
        r_rank = int(rs_ranks[sym])

        # Consistent Segment Tagging
        seg_tag = "F&O" if sym in fo_list else "Cash"
        # Additional deep check for high RS candidates if they might have options
        if seg_tag == "Cash" and r_rank <= 100:
            try:
                # Optimized check: avoid full download
                if len(yf.Ticker(sym).options) > 0:
                    seg_tag = "F&O"
                    fo_list.append(sym)
            except: pass

        cursor.execute('INSERT INTO stock_metrics VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)', (latest_date_str, sym, r_score, r_rank, float(adl.loc[latest_date, sym]), 0, d_pct, 0, v_exp, cls, 0, "", seg_tag))

        # Stealth Detection
        score = 0
        d_trend_val = "Stable"
        if d_pct > 50: score += 20

        if not hist_del_pivot.empty and sym in hist_del_pivot.columns:
            s_del = hist_del_pivot[sym].dropna()
            if len(s_del) > 5 and s_del.iloc[-1] > s_del.rolling(15).mean().iloc[-1]:
                score += 20; d_trend_val = "Rising"

        if sym in vol_cont.columns and vol_cont[sym].iloc[-1] < 0.95: score += 20
        if sym in h_lows.columns and h_lows[sym].iloc[-1]: score += 20
        if sym in ad_trend.columns and ad_trend[sym].iloc[-1]: score += 10
        if sym in rs_trend.columns and rs_trend[sym].iloc[-1]: score += 10

        sect = sector_map.get(sym.replace(".NS", ""), "Others")
        if score >= 50:
            # Handle possible NaNs in indicators
            v_cont_val = 0.0
            if sym in vol_cont.columns:
                v_cont_val = float(vol_cont[sym].fillna(0).iloc[-1])

            h_low_val = "No"
            if sym in h_lows.columns and h_lows[sym].fillna(False).iloc[-1]:
                h_low_val = "Yes"

            ad_trend_val = "Flat"
            if sym in ad_trend.columns and ad_trend[sym].fillna(False).iloc[-1]:
                ad_trend_val = "Rising"

            rs_trend_val = "Lagging"
            if sym in rs_trend.columns and rs_trend[sym].fillna(False).iloc[-1]:
                rs_trend_val = "Improving"

            cursor.execute('INSERT INTO stealth_accumulation VALUES (?,?,?,?,?,?,?,?,?,?,?)',
                           (latest_date_str, sym, score, d_pct, d_trend_val,
                            v_cont_val, h_low_val, ad_trend_val, rs_trend_val, sect, seg_tag))

        # Breakout Ready Detection
        bo_score = 0
        if score >= 50: bo_score += 20 # Accumulation detected

        v_contracting = False
        if sym in range_trend.columns and range_trend[sym].iloc[-1] < 0:
            bo_score += 20; v_contracting = True

        tight_range = False
        if sym in df_range.columns:
            # Range narrowing if current range is less than 80% of 20-day avg range
            if df_range[sym].iloc[-1] < (df_range[sym].rolling(20).mean().iloc[-1] * 0.8):
                bo_score += 15; tight_range = True

        res_val = float(resistance_30.loc[latest_date, sym])
        res_tests = 0
        if sym in highs.columns:
            res_tests = int((highs[sym] >= res_val * 0.98).rolling(30).sum().iloc[-1])
            if res_tests >= 2: bo_score += 15

        rs_strong = False
        if sym in rs_near_high.columns and rs_near_high[sym].iloc[-1]:
            bo_score += 15; rs_strong = True

        del_rising = False
        if not hist_del_pivot.empty and sym in hist_del_pivot.columns:
            s_del = hist_del_pivot[sym].dropna()
            if len(s_del) > 5 and s_del.rolling(15).mean().diff().iloc[-1] > 0:
                bo_score += 15; del_rising = True

        # Breakout Probability Model (0-100)
        prob_score = 0

        # 1. Accumulation Strength (20)
        if score >= 50: prob_score += 10 # Stealth acc
        if sym in ad_trend.columns and ad_trend[sym].iloc[-1]: prob_score += 10 # ADL rising

        # 2. Volatility Compression (15)
        if v_contracting: prob_score += 7.5
        if sym in bb_squeeze.columns and bb_squeeze[sym].iloc[-1]: prob_score += 7.5

        # 3. Resistance Pressure (15)
        if res_tests >= 2: prob_score += 10
        if sym in h_lows.columns and h_lows[sym].iloc[-1]: prob_score += 5

        # 4. RS Leadership (15)
        if sym in rs_trend.columns and rs_trend[sym].iloc[-1]: prob_score += 7.5
        if rs_strong: prob_score += 7.5

        # 5. Volume & Delivery Expansion (15)
        # Check for volume dry-up in the last 3 days
        if sym in vol_dryup.columns and vol_dryup[sym].iloc[-3:-1].any(): prob_score += 7.5
        if sym in vol_expansion.columns and vol_expansion[sym].iloc[-1]: prob_score += 7.5

        # 6. Sector Strength (10)
        sect_sym = None
        for k, v in SECTORS.items():
            if v.replace("Nifty ", "") == sect: sect_sym = k; break
        if sect_sym and sect_sym in sector_rs_trend.columns and sector_rs_trend[sect_sym].iloc[-1]:
            prob_score += 10

        # 7. Market Environment (10)
        # We'll use a simplified check: if Nifty 50 is above its 20 SMA
        if n50.iloc[-1] > calculate_sma(n50, 20).iloc[-1]:
            prob_score += 10

        if bo_score >= 60 or prob_score >= 55:
            segment = seg_tag

            base_type = "Volatility Squeeze" if v_contracting else "Tight Base" if tight_range else "Consolidation"
            del_status = "Rising" if del_rising else "Stable"
            rs_status = "Near High" if rs_strong else "Improving"
            cursor.execute('INSERT OR REPLACE INTO breakout_ready VALUES (?,?,?,?,?,?,?,?,?)',
                           (latest_date_str, sym, bo_score, base_type, del_status, rs_status, res_val, segment, int(prob_score)))

    # Risk
    vix_new = vix[vix.index > (last_date if last_date else start_date)]
    for date, val in vix_new.items():
        cursor.execute('INSERT OR REPLACE INTO risk_metrics VALUES (?,?,?,?)', (date.strftime('%Y-%m-%d'), float(val), 0.0, "Normal"))

    conn.commit(); conn.close()

    logger.info("Updating Options Intelligence module...")
    try:
        latest_n50 = float(n50.iloc[-1]) if not n50.empty else None
        # Prioritize live spot if available
        if live_nifty:
            hint = live_nifty
        else:
            hint = latest_n50

        om = OptionsManager()
        om.update(spot_price_hint=hint)
    except Exception as e:
        logger.error(f"Options Intelligence update failed: {str(e)}")

    duration = time.time() - start_time_total
    logger.info(f"Data Pipeline Update complete in {duration:.2f} seconds.")

if __name__ == "__main__":
    update_data()
