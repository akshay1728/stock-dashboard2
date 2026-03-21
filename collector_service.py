import time
import logging
import signal
from config import Config
from stocko_auth import StockoAuth
from stocko_data import StockoData
from database import Database

logging.basicConfig(
    level=getattr(logging, Config.LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("CollectorService")

class CollectorService:
    def __init__(self):
        self.auth = StockoAuth()
        self.db = Database()
        self.running = True
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)

    def stop(self, signum=None, frame=None):
        logger.info("Stopping Collector Service...")
        self.running = False

    def run(self):
        logger.info("Starting Live Market Data Collector...")
        # Background service should NOT pop up a browser
        if not self.auth.login(allow_browser=False):
            logger.error("Failed to authenticate with Stocko API. Background collector requires a valid cached token. Please log in via the Dashboard first.")
            # We continue the loop and retry login occasionally, in case the user logs in via UI later
            data_fetcher = None
        else:
            data_fetcher = StockoData(self.auth)

        while self.running:
            try:
                # Retry login if client is not initialized or token expired
                if not data_fetcher:
                    logger.debug("Collector: Client not ready, attempting silent login...")
                    if self.auth.login(allow_browser=False):
                        logger.info("Collector: Client re-authorized successfully.")
                        data_fetcher = StockoData(self.auth)
                    else:
                        logger.warning("Collector: Silent auth failed. Waiting for user login via dashboard...")
                        time.sleep(60)
                        continue

                loop_start = time.time()
                logger.info(f"Collector: Cycle started for {Config.SYMBOL}...")

                # Index Data
                index_data = data_fetcher.fetch_index_data(Config.SYMBOL)
                if index_data and not Config.DRY_RUN:
                    self.db.save_index_data(index_data)
                    logger.debug(f"Collector: Index price saved ({index_data['last_price']})")
                else:
                    logger.warning("Collector: Failed to fetch index price.")

                # Option Chain
                spot_price = index_data['last_price'] if index_data else None
                chain_data = data_fetcher.fetch_option_chain(Config.SYMBOL, limit=150, spot_price=spot_price)
                if chain_data and not Config.DRY_RUN:
                    self.db.save_option_chain(chain_data)
                    logger.info(f"Collector: Successfully archived {len(chain_data)} option records.")
                else:
                    logger.warning("Collector: Option chain fetch returned no results.")

                fetch_duration = time.time() - loop_start
                sleep_time = max(0, Config.FETCH_INTERVAL - fetch_duration)
                for _ in range(int(sleep_time)):
                    if not self.running: break
                    time.sleep(1)
            except Exception as e:
                logger.error(f"Error in collection loop: {e}")
                time.sleep(10)

if __name__ == "__main__":
    service = CollectorService()
    service.run()
