import logging
import pandas as pd
from config import Config
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

class StockoData:
    def __init__(self, auth_client):
        self.auth = auth_client

    @property
    def client(self):
        return self.auth.client

    def fetch_index_data(self, symbol="NIFTY"):
        try:
            if not self.client:
                logger.error("Stocko client not initialized.")
                return None

            search_symbol = symbol
            if symbol == "NIFTY": search_symbol = "Nifty 50"
            elif symbol == "BANKNIFTY": search_symbol = "Nifty Bank"

            instrument = self.client.get_instrument_by_symbol('NSE', search_symbol)
            if not instrument:
                logger.error(f"Could not find index instrument for {search_symbol}")
                return None

            price_res = self.client.get_scrip_info(instrument)
            if price_res.get("status") != "success":
                logger.error(f"Error fetching scrip info for {search_symbol}: {price_res}")
                return None

            result = price_res.get("result", {})
            return {
                "symbol": symbol,
                "timestamp": pd.Timestamp.now(),
                "open": float(result.get("open") or 0),
                "high": float(result.get("high") or 0),
                "low": float(result.get("low") or 0),
                "close": float(result.get("close") or 0),
                "last_price": float(result.get("ltp") or result.get("last_traded_price") or 0)
            }
        except Exception as e:
            logger.error(f"Error fetching index data: {e}")
            return None

    def fetch_option_chain(self, symbol="NIFTY", limit=600):
        """Fetches the live option chain and populates detailed info for ATM strikes."""
        try:
            if not self.client:
                logger.error("Stocko Data: Client not initialized.")
                return []

            # Resolve index instrument
            search_symbol = symbol
            if symbol == "NIFTY": search_symbol = "Nifty 50"
            elif symbol == "BANKNIFTY": search_symbol = "Nifty Bank"

            token_instrument = self.client.get_instrument_by_symbol("NSE", search_symbol)
            if not token_instrument:
                # Try search if direct get fails
                logger.warning(f"Stocko Data: Direct instrument lookup failed for {search_symbol}, searching...")
                matches = self.client.search_instruments("NSE", search_symbol)
                if matches:
                    token_instrument = matches[0]
                else:
                    logger.error(f"Stocko Data: Could not find instrument for {search_symbol}")
                    return []

            spot_data = self.fetch_index_data(symbol)
            spot_price = spot_data['last_price'] if spot_data else None

            if not spot_price:
                logger.error("Could not get spot price to center option chain.")
                return []

            strikes_count = int(limit / 10)
            oc_res = self.client.get_optionchain(token_instrument, strikes_count, int(spot_price))

            if oc_res.get("status") != "success" or not oc_res.get("result"):
                logger.error(f"Option chain fetch failed: {oc_res}")
                return []

            data = oc_res['result'][0]
            expiry_date = data['expiry_date']

            chain_data = []
            for strike in data['strikes']:
                strike_price = float(strike['strike_price'])
                for opt_type in ['call_option', 'put_option']:
                    opt = strike[opt_type]
                    chain_data.append({
                        "timestamp": pd.Timestamp.now(),
                        "symbol": symbol,
                        "expiry_date": expiry_date,
                        "strike": strike_price,
                        "option_type": "CE" if opt_type == 'call_option' else "PE",
                        "ltp": float(opt.get("ltp") or opt.get("close_price") or 0),
                        "token": opt.get("token"),
                        "trading_symbol": opt.get("trading_symbol"),
                        "bid": 0.0,
                        "ask": 0.0,
                        "volume": 0,
                        "open_interest": 0,
                        "oi_change": 0,
                        "implied_volatility": 0.0,
                        "underlying_price": float(spot_price)
                    })

            # Fetch detailed info for near-the-money strikes (e.g., within 1000 points for better coverage)
            # Use a broader range to ensure we have enough data for Greeks/Intelligence
            near_strikes = [d for d in chain_data if abs(d['strike'] - spot_price) < 1000]

            def update_with_detailed_info(opt_record):
                try:
                    from stocko.stockoapi import Instrument
                    instr = Instrument(
                        exchange='NFO',
                        token=int(opt_record.get('token')),
                        symbol=opt_record.get('trading_symbol'),
                        name='',
                        expiry=expiry_date,
                        lot_size=0
                    )
                    res = self.client.get_scrip_info(instr)
                    if isinstance(res, dict) and res.get("status") == "success":
                        detail = res.get("result", {})

                        ltp = float(detail.get("ltp") or detail.get("last_traded_price") or opt_record['ltp'])
                        oi = int(detail.get("current_oi") or detail.get("open_interest") or 0)
                        prev_oi = int(detail.get("initial_oi") or 0)
                        # Estimate oi_change if not explicitly provided
                        oi_change = detail.get("oi_change") or detail.get("change_in_oi")
                        if oi_change is None and prev_oi > 0:
                            oi_change = oi - prev_oi

                        opt_record.update({
                            "ltp": ltp,
                            "open_interest": oi,
                            "oi_change": int(oi_change or 0),
                            "implied_volatility": float(detail.get("implied_volatility") or detail.get("iv") or 0),
                            "volume": int(detail.get("volume") or detail.get("trade_volume") or 0)
                        })
                except Exception as e:
                    logger.debug(f"Error fetching detailed info for {opt_record.get('trading_symbol')}: {e}")

            if near_strikes:
                logger.info(f"Stocko Data: Fetching detailed info for {len(near_strikes)} strikes near spot...")
                with ThreadPoolExecutor(max_workers=15) as executor:
                    list(executor.map(update_with_detailed_info, near_strikes))

            logger.info(f"Fetched {len(chain_data)} option records from Stocko API (Detailed info for {len(near_strikes)}).")

            # Ensure we have at least some data. If all LTPs are 0, something is wrong.
            valid_ltps = [d['ltp'] for d in chain_data if d['ltp'] > 0]
            if not valid_ltps:
                logger.warning("Stocko Data: All fetched LTPs are 0. API might be returning empty prices.")

            return chain_data

        except Exception as e:
            logger.error(f"Error fetching option chain: {e}")
            return []
