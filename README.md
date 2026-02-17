# Crypto Trading Bot v2

Automated cryptocurrency trading bot using Coinbase Advanced Trade API with technical analysis signals (RSI, MACD, volume, support/resistance).

## Features

- **Multi-pair trading**: BTC, ETH, SOL, AVAX, LINK, DOGE, ADA, DOT, XRP, AAVE
- **Technical indicators**: RSI, MACD, EMA, volume analysis, support bounce detection
- **Risk management**: Configurable stop-loss and take-profit levels
- **Limit orders**: Better execution prices with maker fees
- **Portfolio tracking**: JSON-based trade history and P&L tracking
- **Telegram notifications**: Real-time alerts for trades and positions (optional)

## Prerequisites

- Python 3.8 or higher
- Coinbase Advanced Trade account with API credentials
- (Optional) Telegram bot for notifications

## Installation

1. **Clone or download this repository**

2. **Create virtual environment** (recommended):
   ```bash
   python3 -m venv trading-env
   source trading-env/bin/activate  # On Windows: trading-env\Scripts\activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

4. **Configure Coinbase API credentials**:
   - Create `~/.secrets/coinbase.json` with your API credentials:
     ```json
     {
       "api_key": "your_coinbase_api_key",
       "api_secret": "your_coinbase_api_secret"
     }
     ```
   - Or set custom path via `COINBASE_SECRETS_PATH` environment variable

5. **Configure environment variables**:
   ```bash
   cp .env.example .env
   # Edit .env with your actual values
   ```

## Configuration

### Required Configuration

- **Coinbase API credentials**: Must be set via `coinbase.json` file or `COINBASE_SECRETS_PATH` env var

### Optional Configuration (via .env)

- `TG_BOT_TOKEN`: Telegram bot token (get from @BotFather)
- `TG_CHAT_ID`: Your Telegram chat ID (get from @userinfobot)
- `MAX_POSITION_USD`: Maximum USD per position (default: 50.0)
- `MAX_OPEN_POSITIONS`: Max concurrent positions (default: 5)
- `STOP_LOSS_PCT`: Stop loss percentage (default: 0.05 = 5%)
- `TAKE_PROFIT_PCT`: Take profit percentage (default: 0.08 = 8%)
- `MIN_USD_BALANCE`: Minimum USD reserve (default: 10.0)
- `INITIAL_CAPITAL`: Starting capital for tracking (default: 100.0)

See `.env.example` for full configuration options.

## Usage

### Start the bot:
```bash
python trade_executor.py
```

### Run in background:
```bash
nohup python trade_executor.py > bot.log 2>&1 &
```

### Stop the bot:
```bash
# Find process ID
ps aux | grep trade_executor

# Kill process
kill <PID>
```

## Trading Strategy

The bot uses a multi-signal scoring system (0-100) to identify buy opportunities:

1. **RSI Analysis**: Identifies oversold conditions
   - Deeply oversold (RSI < 25): +35 points
   - Oversold (RSI < 30): +25 points
   - Approaching oversold (RSI < 35): +15 points

2. **MACD Crossover**: Bullish momentum near support (+15 points)

3. **Volume Spike**: High volume on green candles (+20 points)

4. **Support Bounce**: Price bouncing off support with wick rejection (+20 points)

5. **Below EMA**: Buying dips below 20-period EMA (+10 points)

**Buy Signal Threshold**: Score >= 50/100

**Exit Strategy**:
- **Stop Loss**: Triggered at -5% from entry (configurable)
- **Take Profit**: Triggered at +8% from entry (configurable)

## File Structure

```
.
├── trade_executor.py          # Main trading bot script
├── .env.example               # Example environment configuration
├── .gitignore                 # Git ignore rules
├── requirements.txt           # Python dependencies
├── portfolio.json.example     # Example portfolio structure
├── README.md                  # This file
├── portfolio.json             # Auto-generated trade history (not tracked)
├── trade_log.txt              # Auto-generated execution log (not tracked)
└── monitor_state.json         # Auto-generated state file (not tracked)
```

## Security Notes

- **Never commit `.env` file** to version control
- **Never commit `coinbase.json`** or any credential files
- **Keep API keys secure** with appropriate permissions
- Consider using **paper trading** mode first for testing
- Review the `.gitignore` file to ensure sensitive files are excluded

## Monitoring

### Log Files
- `trade_log.txt`: Last 50 log entries (auto-rotated)
- Check logs for trade execution and system status

### Telegram Notifications
Configure Telegram bot to receive:
- Trade entry/exit notifications
- Stop loss and take profit alerts
- Bot startup/shutdown notifications

### Portfolio Tracking
- `portfolio.json`: Complete trade history and P&L
- Track initial capital, open positions, and closed trades

## Risk Warning

**CRYPTOCURRENCY TRADING INVOLVES SUBSTANTIAL RISK OF LOSS.**

- This bot is provided for educational purposes
- Past performance does not guarantee future results
- Only trade with capital you can afford to lose
- Test thoroughly with small amounts before scaling
- Monitor the bot regularly and set appropriate limits
- Consider market conditions and volatility

## Troubleshooting

### "ERROR: Missing dependencies"
```bash
pip install -r requirements.txt
```

### "ERROR: Coinbase credentials not found"
- Ensure `~/.secrets/coinbase.json` exists with valid credentials
- Or set `COINBASE_SECRETS_PATH` environment variable

### Bot not taking trades
- Check log file for signal analysis details
- Verify sufficient USD/USDC balance
- Check if maximum open positions limit is reached
- Ensure trading pairs have sufficient liquidity

### Telegram notifications not working
- Verify `TG_BOT_TOKEN` and `TG_CHAT_ID` in `.env`
- Test bot token with @BotFather
- Check network connectivity

## License

This project is provided as-is for educational purposes. Use at your own risk.

## Support

For issues, questions, or contributions, please refer to the project documentation or contact the maintainer.
