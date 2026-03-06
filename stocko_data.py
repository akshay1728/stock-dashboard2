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
        try:
            if not self.client:
                logger.error("Stocko Fetch: Client not initialized. Cannot fetch option chain.")
                return []

            search_symbol = symbol
            if symbol == "NIFTY": search_symbol = "Nifty 50"
            elif symbol == "BANKNIFTY": search_symbol = "Nifty Bank"

            token_instrument = self.client.get_instrument_by_symbol("NSE", search_symbol)
            if not token_instrument:
                logger.error(f"Could not find index instrument for {search_symbol}")
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

            # Fetch detailed info for near-the-money strikes (e.g., within 500 points)
            near_strikes = [d for d in chain_data if abs(d['strike'] - spot_price) < 500]

            def update_with_detailed_info(opt_record):
                try:
                    from stocko.stockoapi import Instrument
                    instr = Instrument(
                        exchange='NFO',
                        token=int(opt_record['token']),
                        symbol=opt_record['trading_symbol'],
                        name='',
                        expiry=expiry_date,
                        lot_size=0
                    )
                    res = self.client.get_scrip_info(instr)
                    if res.get("status") == "success":
                        detail = res.get("result", {})
                        opt_record.update({
                            "ltp": float(detail.get("ltp") or detail.get("last_traded_price") or opt_record['ltp']),
                            "open_interest": int(detail.get("open_interest") or 0),
                            "oi_change": int(detail.get("change_in_oi") or 0),
                            "implied_volatility": float(detail.get("implied_volatility") or 0),
                            "volume": int(detail.get("trade_volume") or 0)
                        })
                except Exception as e:
                    logger.debug(f"Error fetching detailed info for {opt_record.get('trading_symbol')}: {e}")

            if near_strikes:
                with ThreadPoolExecutor(max_workers=10) as executor:
                    executor.map(update_with_detailed_info, near_strikes)

            logger.info(f"Fetched {len(chain_data)} option records from Stocko API (Detailed info for {len(near_strikes)}).")
            return chain_data

        except Exception as e:
            logger.error(f"Error fetching option chain: {e}")
            return []
