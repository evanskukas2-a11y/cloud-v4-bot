from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse
import uvicorn
import websocket
import json
import threading
import os
import time
from collections import deque

app = FastAPI()

# ======================================
# GLOBALS
# ======================================

status = "CONNECTING..."
bot_running = False
tick_price = "-"
last_digit = "-"
wins = 0
losses = 0
win_rate = 0
active_trade = "NONE"
trade_history = deque(maxlen=10)
current_profit = 0.0
contract_id_active = None
signal = "WAITING..."

# ======================================
# MONEY MANAGEMENT
# ======================================

starting_balance = 0
balance = 0
profit = 0.0
base_stake = 1.00
current_stake = 1.00
take_profit_per_trade = 2.00
stop_loss_per_trade = 1.00
take_profit_total = 20.00
stop_loss_total = 10.00
loss_streak = 0
max_loss_streak = 3

# ======================================
# ACCUMULATOR SETTINGS
# ======================================

# growth_rate options on Deriv:
# 0.01 = 1% per tick (safer, longer)
# 0.02 = 2% per tick (moderate)
# 0.03 = 3% per tick (faster, riskier)
# 0.04 = 4% per tick
# 0.05 = 5% per tick (fastest, most risk)
GROWTH_RATE     = 0.03
TARGET_TICKS    = 10    # Cash out after this many ticks
TRADE_COOLDOWN  = 15    # Seconds between trades
CONTRACT_TYPE   = "ACCU"  # ACCU = Accumulator

# ======================================
# CONFIG
# ======================================

TOKEN  = os.getenv("DERIV_TOKEN")
APP_ID = "1089"
SYMBOL = "R_50"

# ======================================
# SETTINGS
# ======================================

last_trade_time      = 0
confidence_threshold = 75

# ======================================
# HELPERS
# ======================================

def update_win_rate():
    global win_rate
    total = wins + losses
    if total > 0:
        win_rate = round(
            (wins / total) * 100, 2
        )

def status_message(msg):
    global status
    status = msg

# ======================================
# CHECK TOTAL LIMITS
# ======================================

def check_limits():
    global bot_running
    if profit >= take_profit_total:
        bot_running = False
        status_message(
            f"DAILY TARGET HIT +${profit:.2f}"
        )
    if profit <= -stop_loss_total:
        bot_running = False
        status_message(
            f"DAILY STOP LOSS HIT ${profit:.2f}"
        )
    if loss_streak >= max_loss_streak:
        bot_running = False
        status_message(
            f"MAX LOSS STREAK {loss_streak} — PAUSED"
        )

# ======================================
# RESET
# ======================================

@app.get("/reset")
def reset_session():
    global wins, losses, win_rate, profit
    global loss_streak, current_stake, bot_running
    global active_trade, contract_id_active
    global current_profit
    wins               = 0
    losses             = 0
    win_rate           = 0
    profit             = 0.0
    loss_streak        = 0
    current_stake      = base_stake
    bot_running        = False
    active_trade       = "NONE"
    contract_id_active = None
    current_profit     = 0.0
    trade_history.clear()
    status_message("SESSION RESET")
    return RedirectResponse(url="/", status_code=303)

# ======================================
# SIGNAL ENGINE
# ======================================

def analyse_digits(recent_digits):
    """
    For Accumulators we want LOW VOLATILITY —
    price staying in a narrow range = accumulator survives longer.
    Check if last digits are spread (volatile) or clustered (calm).
    Returns (should_trade, confidence, reason)
    """
    if len(recent_digits) < 15:
        return False, 0, "COLLECTING DATA..."

    window = recent_digits[-15:]

    # Check volatility — how much are digits jumping
    jumps = sum(
        abs(window[i] - window[i-1])
        for i in range(1, len(window))
    )
    avg_jump = jumps / (len(window) - 1)

    # Check if same digit repeating (too calm = suspicious)
    unique = len(set(window[-5:]))

    # Ideal = moderate movement, not wild swings
    if avg_jump > 5.0:
        return False, 20, "VOLATILE — SKIP"

    if unique == 1:
        return False, 20, "SUSPICIOUS PATTERN — SKIP"

    if avg_jump <= 2.5:
        conf = 90
        reason = f"CALM MARKET | Avg jump: {avg_jump:.1f}"
        return True, conf, reason

    if avg_jump <= 3.5:
        conf = 80
        reason = f"MODERATE MARKET | Avg jump: {avg_jump:.1f}"
        return True, conf, reason

    conf = 60
    reason = f"BORDERLINE | Avg jump: {avg_jump:.1f}"
    return False, conf, reason

# ======================================
# PLACE ACCUMULATOR TRADE
# ======================================

def place_accumulator_trade():
    global wins, losses, active_trade
    global balance, profit, loss_streak
    global contract_id_active, current_profit

    active_trade = "ACCUMULATOR"

    try:
        ws = websocket.create_connection(
            f"wss://ws.derivws.com/websockets/v3?app_id={APP_ID}"
        )

        # Authorize
        ws.send(json.dumps({"authorize": TOKEN}))
        auth = json.loads(ws.recv())

        if "error" in auth:
            status_message(
                f"AUTH FAILED: {auth['error']['message']}"
            )
            active_trade = "NONE"
            ws.close()
            return

        stake = current_stake

        # Place Accumulator contract
        ws.send(json.dumps({
            "buy": 1,
            "price": stake,
            "parameters": {
                "amount":        stake,
                "basis":         "stake",
                "contract_type": "ACCU",
                "currency":      "USD",
                "symbol":        SYMBOL,
                "growth_rate":   GROWTH_RATE,
                "limit_order": {
                    "take_profit": round(
                        stake * TARGET_TICKS
                        * GROWTH_RATE, 2
                    )
                }
            }
        }))

        buy_resp = json.loads(ws.recv())

        if "error" in buy_resp:
            status_message(
                f"TRADE ERROR: {buy_resp['error']['message']}"
            )
            active_trade = "NONE"
            ws.close()
            return

        contract_id = buy_resp["buy"]["contract_id"]
        contract_id_active = contract_id
        status_message(
            f"ACCUMULATOR RUNNING | ID: {contract_id} | "
            f"Growth: {int(GROWTH_RATE*100)}% per tick"
        )

        # Subscribe to contract updates
        ws.send(json.dumps({
            "proposal_open_contract": 1,
            "contract_id": contract_id,
            "subscribe": 1
        }))

        result       = None
        trade_profit = 0.0
        tick_count   = 0

        while True:
            resp = json.loads(ws.recv())
            poc  = resp.get(
                "proposal_open_contract", {}
            )

            contract_status = poc.get("status")
            current_profit  = round(
                float(poc.get("profit", 0)), 2
            )
            tick_count = poc.get(
                "tick_count", tick_count
            )

            status_message(
                f"ACCUMULATOR LIVE | "
                f"Ticks: {tick_count} | "
                f"Profit: ${current_profit}"
            )

            # Auto cash out at target ticks
            if (
                tick_count >= TARGET_TICKS
                and current_profit > 0
            ):
                # Sell contract
                ws.send(json.dumps({
                    "sell": contract_id,
                    "price": 0
                }))
                sell_resp = json.loads(ws.recv())
                trade_profit = round(
                    float(
                        sell_resp.get(
                            "sell", {}
                        ).get("sold_for", 0)
                    ) - stake, 2
                )
                result = "WIN"
                status_message(
                    f"CASHED OUT at tick {tick_count} | "
                    f"+${trade_profit}"
                )
                break

            if contract_status == "won":
                result = "WIN"
                trade_profit = round(
                    float(poc.get("profit", 0)), 2
                )
                break
            elif contract_status == "lost":
                result = "LOSS"
                trade_profit = round(
                    float(poc.get("profit", 0)), 2
                )
                break

        # Fetch real balance
        ws.send(json.dumps({"balance": 1}))
        bal_resp = json.loads(ws.recv())
        if "balance" in bal_resp:
            balance = round(
                float(
                    bal_resp["balance"]["balance"]
                ), 2
            )

        ws.close()

        # ========================
        # WIN
        # ========================
        if result == "WIN":
            wins          += 1
            profit        += trade_profit
            loss_streak    = 0
            status_message(
                f"WIN +${trade_profit} | "
                f"Total: ${profit:.2f} | "
                f"Balance: ${balance}"
            )

        # ========================
        # LOSS
        # ========================
        else:
            losses      += 1
            profit      += trade_profit
            loss_streak += 1
            status_message(
                f"LOSS ${trade_profit} | "
                f"Total: ${profit:.2f} | "
                f"Streak: {loss_streak}"
            )

        update_win_rate()
        check_limits()

        current_profit     = 0.0
        contract_id_active = None

        trade_history.appendleft(
            f"ACCU {int(GROWTH_RATE*100)}% | "
            f"{result} | Ticks:{tick_count} | "
            f"Stake ${stake} | P/L ${trade_profit}"
        )

    except Exception as e:
        status_message(f"TRADE EXCEPTION: {e}")

    finally:
        active_trade       = "NONE"
        contract_id_active = None
        current_profit     = 0.0

# ======================================
# MANUAL CASHOUT ENDPOINT
# ======================================

@app.get("/cashout")
def manual_cashout():
    """
    Manually cash out the active accumulator
    at any time from the dashboard.
    """
    global contract_id_active
    if contract_id_active is None:
        status_message("No active contract to cash out")
        return RedirectResponse(url="/", status_code=303)

    try:
        ws = websocket.create_connection(
            f"wss://ws.derivws.com/websockets/v3?app_id={APP_ID}"
        )
        ws.send(json.dumps({"authorize": TOKEN}))
        ws.recv()
        ws.send(json.dumps({
            "sell": contract_id_active,
            "price": 0
        }))
        sell_resp = json.loads(ws.recv())
        sold_for  = sell_resp.get(
            "sell", {}
        ).get("sold_for", 0)
        status_message(
            f"MANUAL CASHOUT | Sold for ${sold_for}"
        )
        ws.close()
    except Exception as e:
        status_message(f"CASHOUT ERROR: {e}")

    return RedirectResponse(url="/", status_code=303)

# ======================================
# DERIV ENGINE
# ======================================

def deriv_engine():
    global status, signal, last_digit
    global tick_price, last_trade_time
    global balance, starting_balance

    recent_digits = []

    while True:
        try:
            ws = websocket.create_connection(
                f"wss://ws.derivws.com/websockets/v3?app_id={APP_ID}"
            )

            ws.send(json.dumps({"authorize": TOKEN}))
            auth = json.loads(ws.recv())

            if "error" in auth:
                status = "AUTH FAILED"
                time.sleep(5)
                continue

            real_balance     = auth["authorize"]["balance"]
            balance          = round(float(real_balance), 2)
            starting_balance = balance

            status = f"CONNECTED | Balance: ${balance}"

            ws.send(json.dumps({
                "ticks": SYMBOL,
                "subscribe": 1
            }))

            while True:
                data = json.loads(ws.recv())

                if "tick" in data:
                    price      = data["tick"]["quote"]
                    tick_price = str(price)
                    price_str  = f"{price:.2f}"
                    digit      = int(price_str[-1])
                    last_digit = digit
                    recent_digits.append(digit)

                    if len(recent_digits) > 50:
                        recent_digits.pop(0)

                    should_trade, conf, reason = (
                        analyse_digits(recent_digits)
                    )

                    signal = reason

                    seconds_since_trade = (
                        time.time() - last_trade_time
                    )

                    if (
                        should_trade
                        and conf >= confidence_threshold
                        and bot_running
                        and active_trade == "NONE"
                        and seconds_since_trade
                        >= TRADE_COOLDOWN
                    ):
                        last_trade_time = time.time()
                        threading.Thread(
                            target=place_accumulator_trade,
                            daemon=True
                        ).start()

                    time.sleep(0.2)

        except Exception as e:
            status = f"RECONNECTING... {e}"
            time.sleep(5)

# ======================================
# START / STOP
# ======================================

@app.get("/start")
def start_bot():
    global bot_running
    bot_running = True
    status_message("BOT STARTED")
    return RedirectResponse(url="/", status_code=303)

@app.get("/stop")
def stop_bot():
    global bot_running
    bot_running = False
    status_message("BOT STOPPED")
    return RedirectResponse(url="/", status_code=303)

# ======================================
# SETTINGS
# ======================================

@app.post("/settings")
def update_settings(
    stake: float = Form(...),
    tp_trade: float = Form(...),
    sl_trade: float = Form(...),
    tp_total: float = Form(...),
    sl_total: float = Form(...),
    growth: float = Form(...),
    ticks: int = Form(...)
):
    global base_stake, current_stake
    global take_profit_per_trade, stop_loss_per_trade
    global take_profit_total, stop_loss_total
    global GROWTH_RATE, TARGET_TICKS

    base_stake             = stake
    current_stake          = stake
    take_profit_per_trade  = tp_trade
    stop_loss_per_trade    = sl_trade
    take_profit_total      = tp_total
    stop_loss_total        = sl_total
    GROWTH_RATE            = growth
    TARGET_TICKS           = ticks

    status_message("SETTINGS UPDATED")
    return RedirectResponse(url="/", status_code=303)

# ======================================
# DASHBOARD
# ======================================

@app.get("/", response_class=HTMLResponse)
def dashboard():
    history_html = ""
    for item in trade_history:
        color = "green" if "WIN" in item else "red"
        history_html += (
            f"<p style='color:{color}'>{item}</p>"
        )

    active_html = ""
    if active_trade != "NONE":
        active_html = f"""
        <div class="card" style="border:2px solid gold">
            <h3>LIVE CONTRACT</h3>
            <p>Type: {active_trade}</p>
            <p>Running Profit: ${current_profit}</p>
            <form action="/cashout" method="get">
                <button type="submit"
                    style="background:gold;color:black;font-weight:bold;">
                    CASH OUT NOW
                </button>
            </form>
        </div>
        """

    return f"""
<html>
<head>
    <title>ACCUMULATOR ENGINE V11</title>
    <meta http-equiv="refresh" content="5">
    <style>
        body {{
            background:#0f172a;
            color:white;
            font-family:Arial;
            text-align:center;
            padding:20px;
        }}
        .card {{
            background:#1e293b;
            padding:20px;
            margin:15px auto;
            border-radius:12px;
            max-width:500px;
        }}
        input {{
            padding:10px;
            width:200px;
            border:none;
            border-radius:8px;
            margin:5px;
            color:black;
        }}
        button {{
            padding:12px 25px;
            border:none;
            border-radius:10px;
            color:white;
            font-size:16px;
            margin:8px;
            cursor:pointer;
        }}
        h1 {{ color: gold; }}
    </style>
</head>
<body>
    <h1>ACCUMULATOR ENGINE V11</h1>
    <h3>THE VENTURED KINGS LTD — EVANS MUKUKA</h3>

    <div class="card">
        <h3>Status</h3>
        <p>{status}</p>
        <p>Bot: {"RUNNING" if bot_running else "STOPPED"}</p>
    </div>

    <div class="card">
        <h3>Market</h3>
        <p>Symbol: {SYMBOL}</p>
        <p>Tick: {tick_price}</p>
        <p>Last Digit: {last_digit}</p>
        <p>Signal: {signal}</p>
    </div>

    {active_html}

    <div class="card">
        <h3>Session Performance</h3>
        <p>Balance: ${round(balance, 2)}</p>
        <p>Session P/L: ${round(profit, 2)}</p>
        <p>Stake: ${current_stake}</p>
        <p>Wins: {wins} | Losses: {losses}</p>
        <p>Win Rate: {win_rate}%</p>
        <p>Loss Streak: {loss_streak}</p>
    </div>

    <div class="card">
        <h3>Accumulator Settings</h3>
        <form action="/settings" method="post">
            <p>Stake ($)</p>
            <input type="number" step="0.01"
                name="stake" value="{base_stake}">
            <p>Take Profit per Trade ($)</p>
            <input type="number" step="0.01"
                name="tp_trade"
                value="{take_profit_per_trade}">
            <p>Stop Loss per Trade ($)</p>
            <input type="number" step="0.01"
                name="sl_trade"
                value="{stop_loss_per_trade}">
            <p>Daily Take Profit ($)</p>
            <input type="number" step="0.1"
                name="tp_total"
                value="{take_profit_total}">
            <p>Daily Stop Loss ($)</p>
            <input type="number" step="0.1"
                name="sl_total"
                value="{stop_loss_total}">
            <p>Growth Rate (0.01 to 0.05)</p>
            <input type="number" step="0.01"
                name="growth" value="{GROWTH_RATE}">
            <p>Cash Out After N Ticks</p>
            <input type="number"
                name="ticks" value="{TARGET_TICKS}">
            <br><br>
            <button type="submit"
                style="background:blue;">
                SAVE SETTINGS
            </button>
        </form>
    </div>

    <div class="card">
        <h3>Trade History</h3>
        {history_html}
    </div>

    <div class="card">
        <h3>Controls</h3>
        <form action="/start" method="get">
            <button type="submit"
                style="background:green;">
                START BOT
            </button>
        </form>
        <form action="/stop" method="get">
            <button type="submit"
                style="background:red;">
                STOP BOT
            </button>
        </form>
        <form action="/reset" method="get">
            <button type="submit"
                style="background:orange;">
                RESET SESSION
            </button>
        </form>
    </div>

</body>
</html>
"""

# ======================================
# RUN
# ======================================

if __name__ == "__main__":
    threading.Thread(
        target=deriv_engine,
        daemon=True
    ).start()

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)