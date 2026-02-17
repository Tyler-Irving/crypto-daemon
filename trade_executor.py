#!/usr/bin/env python3
"""Trade executor v2 — Limit orders, more pairs, tighter signals."""
import json, time, sys, os, subprocess, uuid
from pathlib import Path

# Load environment variables from .env file
def _load_env():
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())

_load_env()

# Import coinbase SDK (install via requirements.txt)
try:
    import requests as _requests
    from coinbase.rest import RESTClient
except ImportError:
    print("ERROR: Missing dependencies. Install with: pip install -r requirements.txt")
    sys.exit(1)

# Configuration - loaded from environment variables
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")

# Path configuration - uses relative paths or environment variables
BASE_DIR = Path(__file__).parent
CREDS_PATH = os.environ.get("COINBASE_SECRETS_PATH", str(Path.home() / ".secrets/coinbase.json"))
STATE_PATH = os.environ.get("STATE_PATH", str(BASE_DIR / "monitor_state.json"))
PORTFOLIO_PATH = os.environ.get("PORTFOLIO_PATH", str(BASE_DIR / "portfolio.json"))
LOG_PATH = os.environ.get("LOG_PATH", str(BASE_DIR / "trade_log.txt"))

# Validate required paths exist
def validate_paths():
    if not Path(CREDS_PATH).exists():
        print(f"ERROR: Coinbase credentials not found at {CREDS_PATH}")
        print("Set COINBASE_SECRETS_PATH environment variable or create ~/.secrets/coinbase.json")
        sys.exit(1)

# Telegram notification helper
def tg_notify(msg):
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        return  # Silent fail if Telegram not configured
    try:
        _requests.post(f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
            json={"chat_id": TG_CHAT_ID, "text": msg, "parse_mode": "HTML"}, timeout=10)
    except:
        pass

# Expanded pairs — high volume USD pairs
PAIRS = [
    "BTC-USDC", "ETH-USDC", "SOL-USDC",
    "BTC-USD", "ETH-USD", "SOL-USD", "AVAX-USD", "LINK-USD",
    "DOGE-USD", "ADA-USD", "DOT-USD", "XRP-USD", "AAVE-USD"
]

# Trading parameters (configurable via environment variables)
MAX_POSITION_USD = float(os.environ.get("MAX_POSITION_USD", "50.0"))   # max per trade
MAX_OPEN_POSITIONS = int(os.environ.get("MAX_OPEN_POSITIONS", "5"))    # max concurrent positions
STOP_LOSS_PCT = float(os.environ.get("STOP_LOSS_PCT", "0.05"))         # 5%
TAKE_PROFIT_PCT = float(os.environ.get("TAKE_PROFIT_PCT", "0.08"))     # 8% — wider to overcome fees
MIN_USD_BALANCE = float(os.environ.get("MIN_USD_BALANCE", "10.0"))     # keep reserve

def log(msg):
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    with open(LOG_PATH, 'a') as f:
        f.write(line + "\n")
    try:
        with open(LOG_PATH, 'r') as f:
            lines = f.readlines()
        if len(lines) > 50:
            with open(LOG_PATH, 'w') as f:
                f.writelines(lines[-50:])
    except:
        pass

def notify(msg):
    tg_notify(msg)

def get_client():
    with open(CREDS_PATH) as f:
        creds = json.load(f)
    return RESTClient(api_key=creds["api_key"], api_secret=creds["api_secret"])

def get_balance(client):
    """Get total available balance (USD + USDC)"""
    accounts = client.get_accounts(limit=50)
    balances = {}
    for acct in accounts["accounts"]:
        cur = acct["available_balance"]["currency"]
        val = float(acct["available_balance"]["value"])
        if cur in ["USD", "USDC"] and val > 0.01:
            balances[cur] = val
    # Return highest balance and its currency
    if not balances:
        return 0.0, "USD"
    best = max(balances, key=balances.get)
    return balances[best], best

def get_candles(client, pair, granularity="ONE_HOUR", count=20):
    end = int(time.time())
    start = end - count * 3600
    try:
        candles = client.get_candles(pair, start=str(start), end=str(end), granularity=granularity)
        return candles["candles"]
    except:
        return []

def calc_rsi(closes, periods=14):
    if len(closes) < periods + 1:
        return 50
    gains, losses = [], []
    for i in range(1, len(closes)):
        diff = closes[i] - closes[i-1]
        gains.append(max(0, diff))
        losses.append(max(0, -diff))
    avg_gain = sum(gains[-periods:]) / periods
    avg_loss = sum(losses[-periods:]) / periods
    if avg_loss == 0:
        return 100
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def calc_ema(data, period):
    if len(data) < period:
        return data[-1] if data else 0
    multiplier = 2 / (period + 1)
    ema = sum(data[:period]) / period
    for val in data[period:]:
        ema = (val - ema) * multiplier + ema
    return ema

def calc_macd(closes):
    """MACD = EMA12 - EMA26, Signal = EMA9 of MACD"""
    if len(closes) < 26:
        return 0, 0, 0
    ema12 = calc_ema(closes, 12)
    ema26 = calc_ema(closes, 26)
    macd = ema12 - ema26
    # Simplified signal — just use current MACD vs 0
    return macd, 0, macd

def check_volume_spike(candles):
    """Check if recent volume is above average"""
    if len(candles) < 10:
        return False
    volumes = [float(c["volume"]) for c in reversed(candles[:10])]
    avg_vol = sum(volumes[:-1]) / max(len(volumes) - 1, 1)
    recent_vol = volumes[-1]
    return recent_vol > avg_vol * 1.5

def check_support_bounce(candles):
    """Check for price bouncing off support with wick rejection"""
    if len(candles) < 5:
        return False
    for c in candles[:3]:
        o, h, l, cl = float(c["open"]), float(c["high"]), float(c["low"]), float(c["close"])
        candle_range = h - l
        if candle_range == 0:
            continue
        lower_wick = min(o, cl) - l
        # Strong bounce: lower wick > 50% of range, green candle
        if lower_wick / candle_range > 0.5 and cl > o:
            return True
    return False

def analyze_pair(client, pair):
    """Full technical analysis. Returns (should_buy, score, details)"""
    candles = get_candles(client, pair, "ONE_HOUR", 30)
    if len(candles) < 20:
        return False, 0, "insufficient data"
    
    closes = [float(c["close"]) for c in reversed(candles)]
    
    rsi = calc_rsi(closes)
    macd, signal, histogram = calc_macd(closes)
    vol_spike = check_volume_spike(candles)
    bounce = check_support_bounce(candles)
    
    # Current price vs 20-period EMA (trend)
    ema20 = calc_ema(closes, min(20, len(closes)))
    price = closes[-1]
    below_ema = price < ema20
    
    # Scoring system (0-100)
    score = 0
    reasons = []
    
    # RSI signals
    if rsi < 25:
        score += 35
        reasons.append(f"RSI deeply oversold ({rsi:.0f})")
    elif rsi < 30:
        score += 25
        reasons.append(f"RSI oversold ({rsi:.0f})")
    elif rsi < 35:
        score += 15
        reasons.append(f"RSI approaching oversold ({rsi:.0f})")
    
    # MACD turning bullish
    if macd > 0 and below_ema:
        score += 15
        reasons.append("MACD bullish crossover near support")
    
    # Volume spike on green candle
    if vol_spike and float(candles[0]["close"]) > float(candles[0]["open"]):
        score += 20
        reasons.append("Volume spike on green candle")
    
    # Support bounce
    if bounce:
        score += 20
        reasons.append("Support bounce detected")
    
    # Price below EMA (buying dip)
    if below_ema:
        score += 10
        reasons.append("Below EMA20 (dip)")
    
    should_buy = score >= 50  # Need at least 50/100 signal strength
    details = f"Score: {score}/100 | RSI: {rsi:.0f} | {', '.join(reasons) if reasons else 'No signals'}"
    
    return should_buy, score, details

def load_portfolio():
    try:
        with open(PORTFOLIO_PATH) as f:
            return json.load(f)
    except:
        # Initialize with default values if file doesn't exist
        default_portfolio = {
            "initial_capital": float(os.environ.get("INITIAL_CAPITAL", "100.0")),
            "start_date": time.strftime("%Y-%m-%d"),
            "trades": []
        }
        save_portfolio(default_portfolio)
        return default_portfolio

def save_portfolio(portfolio):
    with open(PORTFOLIO_PATH, 'w') as f:
        json.dump(portfolio, f, indent=2)

def get_open_positions(portfolio):
    open_pos = {}
    for t in portfolio["trades"]:
        if t["side"] == "buy" and not t.get("closed"):
            open_pos[t["pair"]] = t
    return open_pos

def place_limit_buy(client, pair, usd_amount, price):
    """Place a limit buy order slightly below current price"""
    # Set limit price 0.1% below current for better fill + maker fee
    limit_price = round(price * 0.999, 2)
    base_size = usd_amount / limit_price
    
    # Get product to determine precision
    try:
        product = client.get_product(pair)
        base_increment = float(product["base_increment"])
        quote_increment = float(product["quote_increment"])
        
        # Round to valid increments
        import math
        base_precision = max(0, -int(math.log10(base_increment)))
        quote_precision = max(0, -int(math.log10(quote_increment)))
        base_size = round(base_size, base_precision)
        limit_price_str = f"{round(limit_price, quote_precision)}"
        
        order = client.limit_order_gtc_buy(
            client_order_id=str(uuid.uuid4()),
            product_id=pair,
            base_size=str(base_size),
            limit_price=limit_price_str
        )
        return order, limit_price, base_size
    except Exception as e:
        log(f"LIMIT BUY FAILED {pair}: {e}")
        return None, 0, 0

def place_limit_sell(client, pair, base_amount, price):
    """Place a limit sell at target price"""
    try:
        product = client.get_product(pair)
        base_increment = float(product["base_increment"])
        quote_increment = float(product["quote_increment"])
        
        import math
        base_precision = max(0, -int(math.log10(base_increment)))
        quote_precision = max(0, -int(math.log10(quote_increment)))
        
        order = client.limit_order_gtc_sell(
            client_order_id=str(uuid.uuid4()),
            product_id=pair,
            base_size=str(round(base_amount, base_precision)),
            limit_price=str(round(price, quote_precision))
        )
        return order
    except Exception as e:
        log(f"LIMIT SELL FAILED {pair}: {e}")
        return None

def execute_market_sell(client, pair, base_amount):
    """Emergency market sell for stop losses"""
    try:
        product = client.get_product(pair)
        base_increment = float(product["base_increment"])
        import math
        base_precision = max(0, -int(math.log10(base_increment)))
        
        order = client.market_order_sell(
            client_order_id=str(uuid.uuid4()),
            product_id=pair,
            base_size=str(round(base_amount, base_precision))
        )
        return order
    except Exception as e:
        log(f"MARKET SELL FAILED {pair}: {e}")
        return None

def check_exits(client, portfolio):
    """Check open positions for stop-loss or take-profit"""
    open_pos = get_open_positions(portfolio)
    for pair, trade in open_pos.items():
        try:
            product = client.get_product(pair)
            price = float(product["price"])
            entry = trade["price"]
            pct_change = (price - entry) / entry

            if pct_change <= -STOP_LOSS_PCT:
                # STOP LOSS — market sell immediately
                asset = pair.split("-")[0]
                accounts = client.get_accounts(limit=50)
                bal = 0
                for acct in accounts["accounts"]:
                    if acct["available_balance"]["currency"] == asset:
                        bal = float(acct["available_balance"]["value"])
                if bal > 0:
                    result = execute_market_sell(client, pair, bal)
                    if result:
                        trade["closed"] = True
                        trade["close_price"] = price
                        trade["close_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
                        trade["close_reason"] = "stop_loss"
                        pnl = (price - entry) * trade["qty"]
                        log(f"🔴 STOP LOSS {pair} @ ${price:.4f} | PnL: ${pnl:.2f}")
                        notify(f"🔴 STOP LOSS {pair}\nEntry: ${entry:.4f}\nExit: ${price:.4f}\nPnL: ${pnl:.2f}")

            elif pct_change >= TAKE_PROFIT_PCT:
                # TAKE PROFIT — market sell to guarantee fill
                asset = pair.split("-")[0]
                accounts = client.get_accounts(limit=50)
                bal = 0
                for acct in accounts["accounts"]:
                    if acct["available_balance"]["currency"] == asset:
                        bal = float(acct["available_balance"]["value"])
                if bal > 0:
                    result = execute_market_sell(client, pair, bal)
                    if result:
                        trade["closed"] = True
                        trade["close_price"] = price
                        trade["close_time"] = time.strftime("%Y-%m-%d %H:%M:%S")
                        trade["close_reason"] = "take_profit"
                        pnl = (price - entry) * trade["qty"]
                        log(f"🟢 TAKE PROFIT {pair} @ ${price:.4f} | PnL: ${pnl:.2f}")
                        notify(f"🟢 TAKE PROFIT {pair}\nEntry: ${entry:.4f}\nExit: ${price:.4f}\nPnL: ${pnl:.2f}")
        except Exception as e:
            log(f"Exit check error {pair}: {e}")

    save_portfolio(portfolio)

def main_loop():
    log("=== Trade executor v2 started ===")
    log(f"Pairs: {len(PAIRS)} | Targets: +{TAKE_PROFIT_PCT*100:.0f}%/-{STOP_LOSS_PCT*100:.0f}% | Max positions: {MAX_OPEN_POSITIONS}")
    notify(f"⚡ Trading bot v2 online\n{len(PAIRS)} pairs | Limit orders | +{TAKE_PROFIT_PCT*100:.0f}%/-{STOP_LOSS_PCT*100:.0f}% targets")
    
    client = get_client()
    last_signal_time = {}
    cycle = 0
    
    while True:
        try:
            cycle += 1
            portfolio = load_portfolio()
            open_pos = get_open_positions(portfolio)
            
            # Check exits first
            if open_pos:
                check_exits(client, portfolio)
                portfolio = load_portfolio()
                open_pos = get_open_positions(portfolio)
            
            balance, bal_currency = get_balance(client)
            
            # Scan for entries
            if len(open_pos) < MAX_OPEN_POSITIONS and balance > MIN_USD_BALANCE:
                best_signal = None
                best_score = 0
                
                for pair in PAIRS:
                    if pair in open_pos:
                        continue
                    # Only trade pairs matching our balance currency
                    quote = pair.split("-")[1]
                    if quote != bal_currency:
                        continue
                    # Cooldown: 30 min between signals on same pair
                    if pair in last_signal_time and time.time() - last_signal_time[pair] < 1800:
                        continue
                    
                    try:
                        should_buy, score, details = analyze_pair(client, pair)
                        if should_buy and score > best_score:
                            best_signal = (pair, score, details)
                            best_score = score
                    except Exception as e:
                        pass
                
                # Execute best signal only
                if best_signal:
                    pair, score, details = best_signal
                    product = client.get_product(pair)
                    price = float(product["price"])
                    buy_amount = min(MAX_POSITION_USD, (balance - MIN_USD_BALANCE) * 0.4)
                    
                    if buy_amount >= 5:
                        max_profit = buy_amount * TAKE_PROFIT_PCT
                        max_loss = buy_amount * STOP_LOSS_PCT
                        
                        log(f"ENTRY {pair} @ ${price:.4f} | {details} | ${buy_amount:.2f}")
                        
                        result, limit_price, base_size = place_limit_buy(client, pair, buy_amount, price)
                        if result:
                            trade = {
                                "pair": pair,
                                "side": "buy",
                                "price": limit_price,
                                "qty": base_size,
                                "usdc": buy_amount,
                                "score": score,
                                "time": time.strftime("%Y-%m-%d %H:%M:%S"),
                                "closed": False,
                                "stop_loss": round(limit_price * (1 - STOP_LOSS_PCT), 4),
                                "target": round(limit_price * (1 + TAKE_PROFIT_PCT), 4),
                                "max_profit": round(max_profit, 2),
                                "max_loss": round(max_loss, 2),
                                "order_type": "limit"
                            }
                            portfolio["trades"].append(trade)
                            save_portfolio(portfolio)
                            last_signal_time[pair] = time.time()
                            
                            notify(f"🟢 LIMIT BUY {pair}\nPrice: ${limit_price:.4f}\nAmount: ${buy_amount:.2f}\nSignal: {score}/100\nStop: ${trade['stop_loss']:.4f} | Target: ${trade['target']:.4f}\nMax Profit: +${max_profit:.2f} | Max Loss: -${max_loss:.2f}")
            
            # Log every cycle
            log(f"CHECK | ${balance:.2f} {bal_currency} | Positions: {len(open_pos)}/{MAX_OPEN_POSITIONS}")
            
        except Exception as e:
            log(f"Loop error: {e}")
        
        time.sleep(30)

if __name__ == "__main__":
    import signal, atexit
    
    # Validate configuration before starting
    validate_paths()
    
    def on_exit(*args):
        log("=== Trade executor v2 STOPPED ===")
        sys.exit(0)
    
    signal.signal(signal.SIGTERM, on_exit)
    signal.signal(signal.SIGINT, on_exit)
    atexit.register(lambda: log("=== Trade executor v2 STOPPED ==="))
    
    main_loop()
