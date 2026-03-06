import logging
import pandas as pd
from config import Config

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
            search_res = self.client.search_scrip({'key': symbol})
            if search_res.get("error", {}).get("code") != 0:
                logger.error(f"Error searching for {symbol}: {search_res}")
                return None

            index_token = None
            for item in search_res.get("result", []):
                if item.get("symbol") == symbol and item.get("exchange") == "NSE":
                    index_token = item.get("token")
                    break

            if not index_token:
                logger.error(f"Could not find index token for {symbol}")
                return None

            price_res = self.client.fetch_scrip_price({'exchange': 'NSE', 'instrument_token': index_token})
            result = price_res.get("result", {})
            return {
                "symbol": symbol,
                "timestamp": pd.Timestamp.now(),
                "open": result.get("open"),
                "high": result.get("high"),
                "low": result.get("low"),
                "close": result.get("close"),
                "last_price": result.get("ltp") or result.get("last_traded_price")
            }
        except Exception as e:
            logger.error(f"Error fetching index data: {e}")
            return None

    def fetch_option_chain(self, symbol="NIFTY", limit=600):
        try:
            if not self.client:
                logger.error("Stocko Fetch: Client not initialized. Cannot fetch option chain.")
                return []

            # Search for the underlying index or instruments
            search_res = self.client.search_scrip({'key': symbol})
            if search_res.get("error", {}).get("code") != 0:
                logger.error(f"Stocko Fetch: Search failed. Error: {search_res.get('error')}")
                return []

            all_results = search_res.get("result", [])

            # Refine filtering:
            # 1. Must be NFO (Derivatives)
            # 2. Must start with the symbol (e.g. NIFTY...) to avoid FINNIFTY or BANKNIFTY
            # 3. Must have CE or PE suffix
            options = [item for item in all_results
                      if item.get("exchange") == "NFO" and
                      item.get("trading_symbol", "").startswith(symbol) and
                      any(suffix in item.get("trading_symbol", "") for suffix in ["CE", "PE"])]

            if not options:
                logger.warning(f"No options found for {symbol}")
                return []

            spot_data = self.fetch_index_data(symbol)
            spot_price = spot_data['last_price'] if spot_data else None

            if not spot_price:
                logger.error("Could not get spot price to filter option chain.")
                return []

            # Multi-threaded fetching of detailed scrip info to speed up chain collection
            from concurrent.futures import ThreadPoolExecutor

            def get_scrip_info(opt):
                try:
                    res_info = self.client.fetch_scripinfo({'exchange': 'NFO', 'instrument_token': opt.get("token")})
                    res = res_info.get("result", {})
                    if not res: return None

                    return {
                        "timestamp": pd.Timestamp.now(),
                        "symbol": symbol,
                        "expiry_date": res.get("expiry_string") or res.get("expiry"),
                        "strike": float(res.get("strike", 0)),
                        "option_type": res.get("option_type"),
                        "ltp": float(res.get("ltp") or res.get("last_traded_price") or 0),
                        "bid": float(res.get("best_bid_price") or res.get("bidPrice") or 0),
                        "ask": float(res.get("best_ask_price") or res.get("askPrice") or 0),
                        "volume": int(res.get("trade_volume") or res.get("volume") or 0),
                        "open_interest": int(res.get("open_interest") or res.get("currentOpenInterest") or 0),
                        "oi_change": int(res.get("change_in_oi") or 0),
                        "implied_volatility": float(res.get("implied_volatility") or 0),
                        "underlying_price": float(spot_price)
                    }
                except:
                    return None

            with ThreadPoolExecutor(max_workers=10) as executor:
                results = list(executor.map(get_scrip_info, options[:limit]))

            chain_data = [r for r in results if r is not None]
            logger.info(f"Fetched {len(chain_data)} option records from Stocko API.")
            return chain_data

        except Exception as e:
            logger.error(f"Error fetching option chain: {e}")
            return []
