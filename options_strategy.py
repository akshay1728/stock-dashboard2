import numpy as np
import pandas as pd
from scipy.stats import norm
from datetime import datetime

class OptionsStrategy:
    def __init__(self):
        pass

    @staticmethod
    def black_scholes(S, K, T, r, sigma, option_type='call'):
        """
        S: Current stock price
        K: Strike price
        T: Time to expiration (in years)
        r: Risk-free interest rate (e.g., 0.07 for 7%)
        sigma: Implied volatility
        """
        if T <= 0:
            if option_type == 'call':
                return max(0, S - K)
            else:
                return max(0, K - S)

        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)

        if option_type == 'call':
            price = S * norm.cdf(d1) - K * np.exp(-r * T) * norm.cdf(d2)
        else:
            price = K * np.exp(-r * T) * norm.cdf(-d2) - S * norm.cdf(-d1)

        return price

    @staticmethod
    def calculate_payoff(spot_range, leg):
        """
        spot_range: array of underlying prices
        leg: dict with {type, position, strike, premium, qty, lot_size, status, exit_price}
        """
        strike = float(leg['strike'])
        premium = float(leg['premium'])
        qty = int(leg['qty'])
        lot_size = int(leg.get('lot_size', 1))
        total_qty = qty * lot_size
        status = leg.get('status', 'Open')
        exit_price = float(leg.get('exit_price', 0))

        if status == 'Closed':
            if leg['position'] == 'Buy':
                payoff_per_unit = (exit_price - premium)
            else:
                payoff_per_unit = (premium - exit_price)
            return np.full_like(spot_range, payoff_per_unit * total_qty)

        if leg['type'] == 'Call':
            if leg['position'] == 'Buy':
                payoff = np.maximum(0, spot_range - strike) - premium
            else:
                payoff = premium - np.maximum(0, spot_range - strike)
        elif leg['type'] == 'Put':
            if leg['position'] == 'Buy':
                payoff = np.maximum(0, strike - spot_range) - premium
            else:
                payoff = premium - np.maximum(0, strike - spot_range)
        else: # Futures
            if leg['position'] == 'Buy':
                payoff = spot_range - strike # strike here is entry price
            else:
                payoff = strike - spot_range

        return payoff * total_qty

    @staticmethod
    def analyze_risk_reward(legs):
        """
        Analytically determine max profit and max loss.
        """
        if not legs: return 0, 0, False, False

        # We test at extremes and at all strikes
        strikes = [float(l['strike']) for l in legs if l['type'] != 'Futures']
        if not strikes:
            # Only futures
            return -np.inf, np.inf, True, True

        test_prices = sorted(list(set(strikes)))
        # Add values far outside
        min_s = min(test_prices)
        max_s = max(test_prices)
        test_prices = [0, min_s * 0.5] + test_prices + [max_s * 1.5, max_s * 10]

        test_prices = np.array(test_prices)
        total_payoff = np.zeros_like(test_prices)

        for leg in legs:
            total_payoff += OptionsStrategy.calculate_payoff(test_prices, leg)

        max_p = np.max(total_payoff)
        min_p = np.min(total_payoff)

        # Check extremes for unlimited
        unlimited_profit = total_payoff[-1] > total_payoff[-2] or total_payoff[0] > total_payoff[1]
        unlimited_loss = total_payoff[-1] < total_payoff[-2] or total_payoff[0] < total_payoff[1]

        # If the slope is positive at the end, max_p is infinity
        if total_payoff[-1] > total_payoff[-2] + 0.01: max_p = np.inf
        if total_payoff[0] > total_payoff[1] + 0.01: max_p = np.inf

        if total_payoff[-1] < total_payoff[-2] - 0.01: min_p = -np.inf
        if total_payoff[0] < total_payoff[1] - 0.01: min_p = -np.inf

        return max_p, min_p, unlimited_profit, unlimited_loss

    @staticmethod
    def get_templates():
        return {
            "Long Call": [
                {"type": "Call", "position": "Buy", "strike_offset": 0, "qty": 1}
            ],
            "Long Put": [
                {"type": "Put", "position": "Buy", "strike_offset": 0, "qty": 1}
            ],
            "Covered Call": [
                {"type": "Futures", "position": "Buy", "strike_offset": 0, "qty": 1},
                {"type": "Call", "position": "Sell", "strike_offset": 100, "qty": 1}
            ],
            "Bull Call Spread": [
                {"type": "Call", "position": "Buy", "strike_offset": 0, "qty": 1},
                {"type": "Call", "position": "Sell", "strike_offset": 200, "qty": 1}
            ],
            "Bear Put Spread": [
                {"type": "Put", "position": "Buy", "strike_offset": 0, "qty": 1},
                {"type": "Put", "position": "Sell", "strike_offset": -200, "qty": 1}
            ],
            "Iron Condor": [
                {"type": "Put", "position": "Buy", "strike_offset": -400, "qty": 1},
                {"type": "Put", "position": "Sell", "strike_offset": -200, "qty": 1},
                {"type": "Call", "position": "Sell", "strike_offset": 200, "qty": 1},
                {"type": "Call", "position": "Buy", "strike_offset": 400, "qty": 1}
            ],
            "Short Strangle": [
                {"type": "Put", "position": "Sell", "strike_offset": -200, "qty": 1},
                {"type": "Call", "position": "Sell", "strike_offset": 200, "qty": 1}
            ],
            "Long Straddle": [
                {"type": "Put", "position": "Buy", "strike_offset": 0, "qty": 1},
                {"type": "Call", "position": "Buy", "strike_offset": 0, "qty": 1}
            ],
            "Short Straddle": [
                {"type": "Put", "position": "Sell", "strike_offset": 0, "qty": 1},
                {"type": "Call", "position": "Sell", "strike_offset": 0, "qty": 1}
            ],
            "Butterfly": [
                {"type": "Call", "position": "Buy", "strike_offset": -200, "qty": 1},
                {"type": "Call", "position": "Sell", "strike_offset": 0, "qty": 2},
                {"type": "Call", "position": "Buy", "strike_offset": 200, "qty": 1}
            ]
        }

    @staticmethod
    def calculate_greeks(S, K, T, r, sigma, option_type='call'):
        if T <= 0: return {"delta": 0, "gamma": 0, "theta": 0, "vega": 0}

        d1 = (np.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * np.sqrt(T))
        d2 = d1 - sigma * np.sqrt(T)

        pdf_d1 = norm.pdf(d1)

        if option_type == 'call':
            delta = norm.cdf(d1)
            theta = (-S * pdf_d1 * sigma / (2 * np.sqrt(T)) - r * K * np.exp(-r * T) * norm.cdf(d2)) / 365
        else:
            delta = -norm.cdf(-d1)
            theta = (-S * pdf_d1 * sigma / (2 * np.sqrt(T)) + r * K * np.exp(-r * T) * norm.cdf(-d2)) / 365

        gamma = pdf_d1 / (S * sigma * np.sqrt(T))
        vega = S * np.sqrt(T) * pdf_d1 / 100

        return {"delta": delta, "gamma": gamma, "theta": theta, "vega": vega}
