import requests
import pandas as pd
import numpy as np
import sqlite3
import logging
from datetime import datetime, timedelta
import os
import time

DB_NAME = 'breadth_data.db'
logger = logging.getLogger(__name__)

class OptionsManager:
    def __init__(self, stocko_auth=None):
        self.stocko_auth = stocko_auth
        self.base_url = "https://www.nseindia.com"
        self.api_url = "https://www.nseindia.com/api/option-chain-indices?symbol=NIFTY"
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Referer": "https://www.nseindia.com/option-chain"
        }
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        self.is_simulated = False

    def init_db(self):
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        # Option Snapshots
        c.execute('''CREATE TABLE IF NOT EXISTS option_snapshots
                     (timestamp DATETIME, strike REAL, type TEXT, expiry DATE, oi INTEGER, oi_change INTEGER,
                      volume INTEGER, iv REAL, ltp REAL, bid_qty INTEGER, ask_qty INTEGER, PRIMARY KEY (timestamp, strike, type, expiry))''')

        # Handle option_alerts schema migration
        c.execute("PRAGMA table_info(option_alerts)")
        cols = [row[1] for row in c.fetchall()]
        if cols and 'strike' not in cols:
            c.execute("DROP TABLE option_alerts")

        # Intelligence Alerts
        c.execute('''CREATE TABLE IF NOT EXISTS option_alerts
                     (timestamp DATETIME, type TEXT, message TEXT, confidence INTEGER, strike REAL, opt_type TEXT)''')

        # Handle market_regime schema migration (Robust)
        c.execute("PRAGMA table_info(market_regime)")
        cols = [row[1] for row in c.fetchall()]
        expected_regime_cols = ['timestamp', 'classification', 'bias', 'iv_regime', 'spot', 'vix', 'iv_atm', 'gamma_score', 'confidence_score', 'is_simulated']
        if cols and not all(col in cols for col in expected_regime_cols):
            c.execute("DROP TABLE market_regime")

        # Market Regime & Classification
        c.execute('''CREATE TABLE IF NOT EXISTS market_regime
                     (timestamp DATETIME PRIMARY KEY, classification TEXT, bias TEXT, iv_regime TEXT,
                      spot REAL, vix REAL, iv_atm REAL, gamma_score INTEGER, confidence_score INTEGER, is_simulated INTEGER)''')

        # Support/Resistance History
        c.execute('''CREATE TABLE IF NOT EXISTS options_sr_levels
                     (timestamp DATETIME, level REAL, type TEXT, strength INTEGER, PRIMARY KEY (timestamp, level, type))''')
        conn.commit()
        conn.close()

    def get_realtime_spot(self):
        """Method 1: Fetch spot from NSE allIndices API"""
        try:
            self.session.get(self.base_url, timeout=5)
            url = "https://www.nseindia.com/api/allIndices"
            response = self.session.get(url, timeout=5)
            if response.status_code == 200:
                data = response.json()
                for index in data.get("data", []):
                    if index.get("index") == "NIFTY 50":
                        val = index.get("last")
                        if isinstance(val, str):
                            val = val.replace(',', '')
                        return float(val)
        except: pass
        return None

    def fetch_data(self):
        """Fetches live option chain data from NSE API. No synthetic data fallback."""
        try:
            # Enhanced session handling for NSE
            self.session.cookies.clear()
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
                "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
                "Accept-Encoding": "gzip, deflate, br",
                "Connection": "keep-alive",
                "DNT": "1",
                "Upgrade-Insecure-Requests": "1"
            }

            logger.info("NSE Scraper: Initializing session cookies...")
            res1 = self.session.get(self.base_url, headers=headers, timeout=10)
            if res1.status_code == 403:
                logger.error("NSE Scraper: 403 Forbidden at Base URL. IP might be blocked by NSE.")
                return None

            # Additional hop often required by NSE
            self.session.get(self.base_url + "/get-quotes/derivatives?symbol=NIFTY", headers=headers, timeout=10)

            # API call requires different Referer and AJAX headers
            api_headers = headers.copy()
            api_headers["Referer"] = "https://www.nseindia.com/option-chain"
            api_headers["X-Requested-With"] = "XMLHttpRequest"

            logger.info(f"NSE Scraper: Fetching from {self.api_url}...")
            response = self.session.get(self.api_url, headers=api_headers, timeout=10)

            if response.status_code == 200:
                if len(response.content) > 100:
                    self.is_simulated = False
                    return response.json()
                else:
                    logger.error("NSE Scraper: Received empty/malformed JSON response (Content length too small).")
                    return None
            else:
                logger.error(f"NSE Scraper: API call failed. Status: {response.status_code}. Text: {response.text[:200]}")
                return None
        except Exception as e:
            logger.error(f"NSE Scraper: Exception during fetch: {str(e)}")
            return None

    def get_historical_data(self, strike, opt_type, expiry):
        conn = sqlite3.connect(DB_NAME)
        # Get the second most recent snapshot (before the one being added)
        query = "SELECT ltp, oi, volume, iv FROM option_snapshots WHERE strike=? AND type=? AND expiry=? ORDER BY timestamp DESC LIMIT 1"
        res = pd.read_sql_query(query, conn, params=(strike, opt_type, expiry))
        conn.close()
        return res.iloc[0] if not res.empty else None

    def filter_strikes(self, df, spot, count=30):
        """Filters for exactly 'count' strikes above and 'count' strikes below the spot."""
        if df.empty: return df

        filtered_dfs = []
        # Filter per expiry to ensure each has proper coverage
        for expiry in df['expiry'].unique():
            edf = df[df['expiry'] == expiry]
            strikes = sorted(edf['strike'].unique())
            # Find ATM strike
            idx = np.argmin([abs(s - spot) for s in strikes])

            # Get slice: idx-count to idx+count
            start_idx = max(0, idx - count)
            end_idx = min(len(strikes), idx + count + 1)
            target_strikes = strikes[start_idx:end_idx]

            filtered_dfs.append(edf[edf['strike'].isin(target_strikes)])

        final_df = pd.concat(filtered_dfs) if filtered_dfs else pd.DataFrame()
        logger.info(f"Strike Filter: Processed {len(df['expiry'].unique())} expiries. Total rows: {len(final_df)}.")
        return final_df

    def process_chain(self, data, expiry_count=4):
        spot = data["records"]["underlyingValue"]
        # Fetch up to 4 expiries as requested
        all_expiries = data["records"]["expiryDates"]
        target_expiries = all_expiries[:expiry_count]

        rows = []
        for item in data["records"]["data"]:
            if item.get("expiryDate") not in target_expiries: continue
            strike = item["strikePrice"]
            for opt_type in ["CE", "PE"]:
                if opt_type in item:
                    d = item[opt_type]
                    rows.append({
                        "strike": strike, "type": opt_type, "expiry": item.get("expiryDate"),
                        "oi": d.get("openInterest", 0), "oi_change": d.get("changeinOpenInterest", 0),
                        "volume": d.get("totalTradedVolume", 0), "iv": d.get("impliedVolatility", 0),
                        "ltp": d.get("lastPrice", 0), "bid_qty": d.get("bidQty", 0), "ask_qty": d.get("askQty", 0)
                    })

        df = pd.DataFrame(rows)
        # Apply 30-strike filtering per expiry
        df = self.filter_strikes(df, spot, count=30)
        return df, spot, target_expiries

    def get_historical_atm_iv(self, spot):
        conn = sqlite3.connect(DB_NAME)
        # Get average ATM IV from last 10 snapshots
        query = "SELECT iv_atm FROM market_regime ORDER BY timestamp DESC LIMIT 10"
        res = pd.read_sql_query(query, conn)
        conn.close()
        return res['iv_atm'].mean() if not res.empty else None

    def run_intelligence(self, df, spot, expiry):
        ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        alerts = []

        # 1. Sudden OI Spike Detection (Institutional Build-up)
        avg_oi_chg = df["oi_change"].abs().mean()
        for _, row in df.iterrows():
            hist = self.get_historical_data(row['strike'], row['type'], row['expiry'])
            prev_ltp = hist['ltp'] if hist is not None else row['ltp'] * 0.99
            price_change = row['ltp'] - prev_ltp

            is_spike = False
            if abs(row['oi_change']) > max(avg_oi_chg * 2, 10000): is_spike = True
            elif row['oi'] > 0 and (abs(row['oi_change']) / (row['oi'] - row['oi_change'] + 1)) > 0.25: is_spike = True

            if is_spike:
                # Positioning classification
                if price_change > 0 and row['oi_change'] > 0: buildup = "Long Build-up"
                elif price_change < 0 and row['oi_change'] > 0: buildup = "Short Build-up"
                elif price_change > 0 and row['oi_change'] < 0: buildup = "Short Covering"
                elif price_change < 0 and row['oi_change'] < 0: buildup = "Long Unwinding"
                else: buildup = "Neutral"

                alerts.append({
                    "timestamp": ts, "type": "OI Spike", "strike": row['strike'], "opt_type": row['type'],
                    "message": f"Massive {row['type']} activity at {row['strike']}: {buildup} detected.",
                    "confidence": 85 if abs(row['oi_change']) > avg_oi_chg * 3 else 70
                })

        # 2. Unusual Volume Spike Detection
        avg_vol = df["volume"].mean()
        for _, row in df.iterrows():
            if row['volume'] > avg_vol * 3:
                hist = self.get_historical_data(row['strike'], row['type'], row['expiry'])
                iv_change = (row['iv'] - hist['iv']) if hist is not None else 0
                price_change = (row['ltp'] - hist['ltp']) if hist is not None else 0

                interpretation = "Directional interest"
                if price_change > 0: interpretation = "Bullish momentum" if row['type'] == 'CE' else "Bearish pressure"
                elif price_change < 0: interpretation = "Bearish pressure" if row['type'] == 'CE' else "Bullish momentum"

                if iv_change < -1: interpretation += " (Writing activity)"

                alerts.append({
                    "timestamp": ts, "type": "Volume Spike", "strike": row['strike'], "opt_type": row['type'],
                    "message": f"Unusual volume at {row['strike']} {row['type']} ({row['volume']/avg_vol:.1f}x). {interpretation}.",
                    "confidence": 75
                })

        # 3. Large Block Trades Proxy
        blocks = df[(df["volume"] > avg_vol * 5) & (df["oi_change"].abs() > avg_oi_chg * 3)]
        for _, row in blocks.iterrows():
            intent = "Institutional Positioning"
            if row['type'] == 'CE' and row['oi_change'] > 0: intent = "Bullish Bet / Resistance Formation"
            elif row['type'] == 'PE' and row['oi_change'] > 0: intent = "Downside Hedge / Support Formation"

            alerts.append({
                "timestamp": ts, "type": "Block Trade", "strike": row['strike'], "opt_type": row['type'],
                "message": f"Large Call/Put block detected at {row['strike']}. Inferred intent: {intent}.",
                "confidence": 90
            })

        # 4. Writer Positioning & S/R
        resistance = df[df['type'] == 'CE'].sort_values('oi', ascending=False).head(3)
        support = df[df['type'] == 'PE'].sort_values('oi', ascending=False).head(3)
        sr_levels = []
        for _, r in resistance.iterrows(): sr_levels.append({"level": r['strike'], "type": "Resistance", "strength": int(r['oi']/1000)})
        for _, s in support.iterrows(): sr_levels.append({"level": s['strike'], "type": "Support", "strength": int(s['oi']/1000)})

        # 5 & 6. Volatility Regime & Market Classification (Bull/Bear/Breakout/Event)
        atm_strike = df.loc[(df["strike"] - spot).abs().idxmin()]["strike"]
        iv_atm = df[df["strike"] == atm_strike]["iv"].mean()
        iv_regime = "High" if iv_atm > 17 else "Moderate" if iv_atm > 13 else "Low"

        ce_oi_total = df[df['type'] == 'CE']['oi'].sum()
        pe_oi_total = df[df['type'] == 'PE']['oi'].sum()
        pcr = pe_oi_total / ce_oi_total if ce_oi_total > 0 else 1

        # Bias detection
        bias = "Neutral"
        if pcr > 1.15: bias = "Bullish"
        elif pcr < 0.85: bias = "Bearish"

        # Classification Module
        near_spot = df[abs(df['strike'] - spot) <= 100]
        unwinding_near = near_spot[near_spot['oi_change'] < 0]
        hist_iv = self.get_historical_atm_iv(spot)

        if iv_atm > 22 or (hist_iv and iv_atm > hist_iv * 1.3):
            classification = "Event"
        elif not unwinding_near.empty and iv_regime == "Low":
            classification = "Breakout"
        elif bias == "Bullish":
            classification = "Bull"
        elif bias == "Bearish":
            classification = "Bear"
        else:
            classification = "Range Bound"

        # 9. Gamma Squeeze Warning Module (Specific Weighted Logic)
        gamma_score = 0
        days_to_expiry = (pd.to_datetime(expiry) - datetime.now()).days + 1

        # Factor 1: OI cluster near spot (25 pts)
        near_oi_max = near_spot['oi'].max()
        if near_oi_max > df['oi'].median() * 3: gamma_score += 25

        # Factor 2: Rapid OI unwinding (20 pts)
        unwind_pct = abs(unwinding_near['oi_change'].sum()) / (near_spot['oi'].sum() + 1)
        if unwind_pct > 0.05: gamma_score += 20

        # Factor 3: ATM volume surge (20 pts) - 3x Avg threshold
        if near_spot['volume'].max() > avg_vol * 3: gamma_score += 20

        # Factor 4: Expiry proximity (15 pts)
        if days_to_expiry <= 1: gamma_score += 15
        elif days_to_expiry <= 3: gamma_score += 10

        # Factor 5: IV expansion (10 pts)
        if hist_iv and iv_atm > hist_iv * 1.05: gamma_score += 10
        elif iv_atm > 18: gamma_score += 5

        # Factor 6: Price near Resistance/Support (10 pts)
        dist_to_sr = min([abs(spot - l['level']) for l in sr_levels]) if sr_levels else 100
        if dist_to_sr <= 25: gamma_score += 10

        # 7. Strategy Suggestion Engine (Mapped to Regime & Volatility)
        mapping = {
            ("Bull", "Low"): "Bull Call Spread",
            ("Bull", "High"): "Bull Put Spread (Credit)",
            ("Bear", "Low"): "Bear Put Spread",
            ("Bear", "High"): "Bear Call Spread (Credit)",
            ("Range Bound", "Low"): "Iron Condor / Short Strangle",
            ("Range Bound", "High"): "Wide Iron Condor / Strangle",
            ("Breakout", "Low"): "Long Straddle / Strangle",
            ("Breakout", "High"): "Ratio Spreads",
            ("Event", "Any"): "Calendar Spreads / Long Volatility"
        }

        key_regime = classification
        if key_regime == "Event":
            strat = mapping[("Event", "Any")]
        else:
            vol_key = "High" if iv_regime != "Low" else "Low"
            strat = mapping.get((key_regime, vol_key), "Iron Condor")

        # 8. Strategy Confidence Score
        conf_score = int((abs(pcr - 1) * 50) + (gamma_score * 0.4) + (20 if iv_regime != "Moderate" else 10))
        conf_score = min(95, max(40, conf_score))

        # Save to Database
        conn = sqlite3.connect(DB_NAME)
        # Snapshot
        df_save = df.copy(); df_save['timestamp'] = ts
        df_save[['timestamp', 'strike', 'type', 'expiry', 'oi', 'oi_change', 'volume', 'iv', 'ltp', 'bid_qty', 'ask_qty']].to_sql('option_snapshots', conn, if_exists='append', index=False)
        # Regime
        conn.execute("INSERT OR REPLACE INTO market_regime VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                     (ts, classification, bias, iv_regime, spot, 0.0, iv_atm, gamma_score, conf_score, 1 if self.is_simulated else 0))
        # Alerts
        for a in alerts:
            conn.execute("INSERT INTO option_alerts VALUES (?, ?, ?, ?, ?, ?)",
                         (ts, a['type'], a['message'], a['confidence'], a['strike'], a['opt_type']))
        # Strategy as Alert
        conn.execute("INSERT INTO option_alerts VALUES (?, ?, ?, ?, ?, ?)", (ts, "Strategy", f"Recommended: {strat}", conf_score, 0, "ANY"))
        # S/R Levels
        for sr in sr_levels:
            conn.execute("INSERT OR REPLACE INTO options_sr_levels VALUES (?, ?, ?, ?)", (ts, sr['level'], sr['type'], sr['strength']))

        conn.commit(); conn.close()
        return strat, conf_score

    def fetch_from_stocko(self, symbol="NIFTY", expiry_count=4):
        """Fetches option chain data from Stocko API for multiple expiries."""
        if not self.stocko_auth:
            logger.debug("Stocko Fetch: No auth instance provided.")
            return None

        # Live validation check
        if not self.stocko_auth.client or not self.stocko_auth._validate_token():
            logger.info("Stocko Fetch: Re-authenticating...")
            if not self.stocko_auth.login():
                logger.error("Stocko Fetch: Authentication failed.")
                return None

        try:
            from stocko_data import StockoData
            sd = StockoData(self.stocko_auth)
            # Fetch a large chain to cover multiple expiries. 30 limit for multiple expiries is too small.
            # Using 60 (30 above, 30 below) for Nifty 50
            logger.info(f"Stocko Fetch: Retrieving chain for {symbol}...")
            chain = sd.fetch_option_chain(symbol, limit=60)
            if not chain:
                logger.warning("Stocko Fetch: API returned empty option chain.")
                return None

            # Identify first 4 expiries
            all_expiries = sorted(list(set([d.get('expiry_date') for d in chain if d.get('expiry_date')])))
            target_expiries = all_expiries[:expiry_count]

            rows = []
            spot = chain[0].get('underlying_price')

            for d in chain:
                if d.get('expiry_date') not in target_expiries: continue
                rows.append({
                    "strike": d.get('strike'), "type": d.get('option_type'), "expiry": d.get('expiry_date'),
                    "oi": d.get("open_interest", 0), "oi_change": d.get("oi_change", 0),
                    "volume": d.get("volume", 0), "iv": d.get("implied_volatility", 0),
                    "ltp": d.get("ltp", 0), "bid_qty": 0, "ask_qty": 0
                })

            df = pd.DataFrame(rows)
            # Filter for requested 30 strikes around spot per expiry
            df = self.filter_strikes(df, spot, count=30)

            logger.info(f"Stocko Fetch: Successfully processed {len(df)} records across {len(target_expiries)} expiries. Spot: {spot}")
            return df, spot, target_expiries
        except Exception as e:
            logger.error(f"Stocko Fetch: Exception occurred: {str(e)}")
            return None

    def fetch_from_db(self):
        """Fetches the latest option chain from the option_chain_snapshots table (from background collector)."""
        try:
            conn = sqlite3.connect(DB_NAME)
            latest_ts = conn.execute("SELECT MAX(timestamp) FROM option_chain_snapshots").fetchone()[0]
            if not latest_ts:
                logger.debug("DB Fetch: No snapshots found in option_chain_snapshots table.")
                conn.close()
                return None

            df = pd.read_sql_query("SELECT * FROM option_chain_snapshots WHERE timestamp = ?", conn, params=(latest_ts,))
            conn.close()

            if df.empty:
                logger.warning(f"DB Fetch: Table returned no records for timestamp {latest_ts}.")
                return None

            # Rename columns to match OptionsManager expected internal format
            df = df.rename(columns={
                'option_type': 'type',
                'expiry_date': 'expiry',
                'open_interest': 'oi',
                'implied_volatility': 'iv',
                'underlying_price': 'spot'
            })

            # Ensure numeric columns are correct
            for col in ['strike', 'ltp', 'oi', 'oi_change', 'volume', 'iv', 'spot']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce').fillna(0)

            spot = float(df['spot'].iloc[0])
            expiries = sorted([e for e in df['expiry'].unique().tolist() if e])
            expiry = expiries[0] if expiries else None

            # Add missing columns expected by run_intelligence
            if 'bid_qty' not in df.columns: df['bid_qty'] = 0
            if 'ask_qty' not in df.columns: df['ask_qty'] = 0

            return df, spot, expiry
        except Exception as e:
            logger.error(f"DB Fetch: Exception occurred: {str(e)}")
            return None

    def update(self, symbol="NIFTY", spot_price_hint=None):
        """Updates the database with live option chain data. Prioritizes Stocko if available."""
        logger.info(f"Options Update: Initiating update cycle for {symbol}...")
        self.init_db()

        df, spot, expiry = None, None, None

        # Priority 1: Direct Stocko API call (if auth provided)
        if self.stocko_auth:
            logger.info(f"Options Update: Attempting direct Stocko API fetch for {symbol}...")
            res = self.fetch_from_stocko(symbol=symbol)
            if res:
                df, spot, expiry = res
                logger.info("Options Update: Success via Stocko API.")

        # Priority 2: Latest data from DB (collected by background service)
        if df is None:
            logger.info("Options Update: Attempting DB snapshot retrieval...")
            res = self.fetch_from_db()
            if res:
                db_df, db_spot, db_expiries = res
                # Check if it's reasonably fresh (e.g., within 5 minutes)
                last_ts = pd.to_datetime(db_df['timestamp'].iloc[0])
                freshness = (datetime.now() - last_ts).total_seconds()
                if freshness < 300:
                    df, spot, expiries = db_df, db_spot, db_expiries
                    logger.info(f"Options Update: Success via DB snapshot (Age: {freshness:.0f}s).")
                else:
                    logger.warning(f"Options Update: DB snapshot too stale (Age: {freshness:.0f}s, Max: 300s).")

        # Priority 3: NSE Scraper (Fallback)
        if df is None:
            logger.info("Options Update: Attempting NSE Scraper fallback...")
            data = self.fetch_data()
            if data:
                try:
                    # process_chain now returns list of expiries
                    df, spot, expiries = self.process_chain(data, expiry_count=4)
                    logger.info("Options Update: Success via NSE Scraper.")
                except Exception as pe:
                    logger.error(f"Options Update: NSE processing failed: {str(pe)}")

        if df is None:
            logger.error("CRITICAL: Options Update failed to fetch live data from all sources (Stocko, DB, NSE).")
            return

        try:
            # Run intelligence on the nearest expiry only for regime/confidence
            nearest_expiry = expiries[0] if isinstance(expiries, list) else expiries
            nearest_df = df[df['expiry'] == nearest_expiry]
            self.run_intelligence(df, spot, nearest_expiry) # Passing full DF to run_intelligence but with nearest_expiry hint
            logger.info(f"Options Update: Cycle complete. Intelligence processed for spot {spot} (Nearest Expiry: {nearest_expiry}).")
        except Exception as e:
            logger.error(f"Options Update: Intelligence processing failed: {str(e)}")

if __name__ == "__main__":
    om = OptionsManager()
    om.update(spot_price_hint=25424)
