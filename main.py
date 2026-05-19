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
confidence = 0
signal = "WAITING..."
last_digit = "-"
tick_price = "-"
wins = 0
losses = 0
win_rate = 0
active_trade = "NONE"
last_result = "-"
trade_history = deque(maxlen=10)

# ======================================
# MONEY MANAGEMENT
# ======================================

starting_balance = 0
balance = 0
base_stake = 0.35
current_stake = 0.35
martingale_multiplier = 1.8
take_profit = 10
stop_loss = 10
profit = 0
loss_streak = 0

# ======================================
# SETTINGS
# ======================================

confidence_threshold = 80
max_loss_streak = 5
trade_cooldown = 10
last_trade_time = 0

# ======================================
# CONFIG
# ======================================

TOKEN = os.getenv("DERIV_TOKEN")
APP_ID = "1089"
SYMBOL = "R_50"

# ======================================
# HELPERS
# ======================================

def update_win_rate():
    global win_rate
    total = wins + losses
    if total > 0:
        win_rate = round(
            (wins / total) * 100,
            2
        )

def status_message(msg):
    global status
    status = msg

# ======================================
# CHECK LIMITS
# ======================================

def check_limits():
    global bot_running
    if profit >= take_profit:
        bot_running = False
        status_message("TAKE PROFIT HIT")
    if profit <= -stop_loss:
        bot_running = False
        status_message("STOP LOSS HIT")
    if loss_streak >= max_loss_streak:
        bot_running = False
        status_message("MAX LOSS STREAK HIT")

# ======================================
# RESET SESSION
# ======================================

@app.get("/reset")
def reset_session():
    global wins, losses, win_rate, balance
    global profit, loss_streak, current_stake, bot_running
    wins = 0
    losses = 0
    win_rate = 0
    profit = 0
    loss_streak = 0
    current_stake = base_stake
    bot_running = False
    trade_history.clear()
    status_message("SESSION RESET")
    return RedirectResponse(url="/", status_code=303)

# ======================================
# SIGNAL ENGINE — OVER/UNDER DETECTOR
# ======================================

def analyse_digits(recent_digits):
    """
    Analyses last N digits to detect HIGH (5-9) or LOW (0-4) bias.
    DIGITOVER 4 = wins if last digit is 5,6,7,8,9
    DIGITUNDER 5 = wins if last digit is 0,1,2,3,4
    Returns (contract_type, barrier, confidence_score)
    """
    if len(recent_digits) < 15:
        return None, None, 0

    # Use last 20 ticks for analysis
    window = recent_digits[-20:] if len(
        recent_digits
    ) >= 20 else recent_digits

    high_count = sum(1 for d in window if d >= 5)
    low_count  = sum(1 for d in window if d < 5)
    total      = len(window)

    high_ratio = high_count / total
    low_ratio  = low_count  / total

    # Momentum — last 5 ticks
    last5      = recent_digits[-5:]
    last5_high = sum(1 for d in last5 if d >= 5)
    last5_low  = 5 - last5_high

    # Streak guard — skip if last 4 all same side
    last4      = recent_digits[-4:]
    last4_high = sum(1 for d in last4 if d >= 5)
    if last4_high == 4 or last4_high == 0:
        return None, None, 0

    # Streak guard — skip if last digit same 3 times
    if len(set(recent_digits[-3:])) == 1:
        return None, None, 0

    # Strong HIGH bias — trade OVER 4
    if high_ratio >= 0.65 and last5_high >= 3:
        conf = min(60 + int(high_ratio * 40), 95)
        return "DIGITOVER", "4", conf

    # Strong LOW bias — trade UNDER 5
    if low_ratio >= 0.65 and last5_low >= 3:
        conf = min(60 + int(low_ratio * 40), 95)
        return "DIGITUNDER", "5", conf

    # Moderate HIGH bias
    if high_ratio >= 0.58 and last5_high >= 3:
        return "DIGITOVER", "4", 80

    # Moderate LOW bias
    if low_ratio >= 0.58 and last5_low >= 3:
        return "DIGITUNDER", "5", 80

    return None, None, 25

# ======================================
# REAL DERIV TRADE
# ======================================

def place_real_trade(signal_name, barrier):
    global wins, losses, active_trade, last_result
    global balance, current_stake, profit, loss_streak

    active_trade = signal_name

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

        contract_type = signal_name.strip()
        if contract_type not in (
            "DIGITOVER", "DIGITUNDER"
        ):
            contract_type = "DIGITOVER"
            barrier = "4"

        stake = current_stake

        # Place real contract
        ws.send(json.dumps({
            "buy": 1,
            "price": stake,
            "parameters": {
                "amount": stake,
                "basis": "stake",
                "contract_type": contract_type,
                "currency": "USD",
                "duration": 5,
                "duration_unit": "t",
                "symbol": SYMBOL,
                "barrier": barrier
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
        status_message(
            f"CONTRACT PLACED | {contract_type} {barrier} | ID: {contract_id}"
        )

        # Wait for result
        ws.send(json.dumps({
            "proposal_open_contract": 1,
            "contract_id": contract_id,
            "subscribe": 1
        }))

        result = None
        while True:
            resp = json.loads(ws.recv())
            poc  = resp.get(
                "proposal_open_contract", {}
            )
            contract_status = poc.get("status")

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

        # Fetch real updated balance from Deriv
        ws.send(json.dumps({"balance": 1}))
        bal_resp = json.loads(ws.recv())
        if "balance" in bal_resp:
            balance = round(
                float(bal_resp["balance"]["balance"]), 2
            )

        ws.close()

        # ========================
        # WIN
        # ========================
        if result == "WIN":
            wins          += 1
            profit        += trade_profit
            current_stake  = base_stake
            loss_streak    = 0
            status_message(
                f"WIN +${trade_profit} | "
                f"Balance: ${balance}"
            )

        # ========================
        # LOSS
        # ========================
        else:
            losses        += 1
            profit        += trade_profit
            loss_streak   += 1
            current_stake  = round(
                current_stake * martingale_multiplier,
                2
            )
            status_message(
                f"LOSS ${trade_profit} | "
                f"Next Stake: ${current_stake} | "
                f"Streak: {loss_streak}"
            )

        update_win_rate()
        check_limits()

        last_result = result
        trade_history.appendleft(
            f"{contract_type} {barrier} | {result} | "
            f"Stake ${stake} | P/L ${trade_profit}"
        )

    except Exception as e:
        status_message(f"TRADE EXCEPTION: {e}")

    finally:
        active_trade = "NONE"

# ======================================
# DERIV ENGINE
# ======================================

def deriv_engine():
    global status, confidence, signal
    global last_digit, tick_price
    global last_trade_time, balance, starting_balance

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

            # Pull real balance from Deriv on connect
            real_balance = auth["authorize"]["balance"]
            balance = round(float(real_balance), 2)
            starting_balance = balance

            status = (
                f"CONNECTED | Balance: ${balance}"
            )

            ws.send(json.dumps({
                "ticks": SYMBOL,
                "subscribe": 1
            }))

            while True:
                data = json.loads(ws.recv())

                if "tick" in data:
                    price = data["tick"]["quote"]
                    tick_price = str(price)
                    price_str = f"{price:.2f}"
                    digit = int(price_str[-1])
                    last_digit = digit
                    recent_digits.append(digit)

                    if len(recent_digits) > 50:
                        recent_digits.pop(0)

                    if len(recent_digits) < 15:
                        signal = "COLLECTING DATA..."
                        confidence = 0
                        continue

                    # ==========================
                    # OVER/UNDER SIGNAL
                    # ==========================

                    contract_type, barrier, conf = (
                        analyse_digits(recent_digits)
                    )

                    confidence = conf

                    if contract_type == "DIGITOVER":
                        signal = f"DIGITOVER {barrier}"
                    elif contract_type == "DIGITUNDER":
                        signal = f"DIGITUNDER {barrier}"
                    else:
                        signal = "WAITING FOR SIGNAL..."

                    # ==========================
                    # COOLDOWN CHECK
                    # ==========================

                    seconds_since_trade = (
                        time.time() - last_trade_time
                    )

                    if (
                        seconds_since_trade
                        < trade_cooldown
                    ):
                        signal = (
                            f"{signal} | COOLDOWN"
                        )

                    # ==========================
                    # EXECUTION
                    # ==========================

                    if (
                        confidence >= confidence_threshold
                        and bot_running
                        and active_trade == "NONE"
                        and seconds_since_trade
                        >= trade_cooldown
                        and contract_type is not None
                        and barrier is not None
                    ):
                        last_trade_time = time.time()
                        threading.Thread(
                            target=place_real_trade,
                            args=(contract_type, barrier),
                            daemon=True
                        ).start()

                    time.sleep(0.2)

        except Exception as e:
            status = f"RECONNECTING... {e}"
            time.sleep(5)

# ======================================
# START BOT
# ======================================

@app.get("/start")
def start_bot():
    global bot_running
    bot_running = True
    status_message("BOT STARTED")
    return RedirectResponse(url="/", status_code=303)

# ======================================
# STOP BOT
# ======================================

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
    martingale: float = Form(...),
    tp: float = Form(...),
    sl: float = Form(...),
    confidence_input: int = Form(...)
):
    global base_stake, current_stake
    global martingale_multiplier
    global take_profit, stop_loss
    global confidence_threshold

    base_stake = stake
    current_stake = stake
    martingale_multiplier = martingale
    take_profit = tp
    stop_loss = sl
    confidence_threshold = confidence_input

    status_message("SETTINGS UPDATED")
    return RedirectResponse(url="/", status_code=303)

# ======================================
# DASHBOARD
# ======================================

@app.get("/", response_class=HTMLResponse)
def dashboard():
    history_html = ""
    for item in trade_history:
        history_html += f"<p>{item}</p>"

    return f"""
<html>
<head>
    <title>DIGIT OVER/UNDER ENGINE V10</title>
    <meta http-equiv="refresh" content="15">
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
            margin:20px;
            border-radius:12px;
        }}
        input {{
            padding:10px;
            width:220px;
            border:none;
            border-radius:8px;
            margin:5px;
        }}
        button {{
            padding:12px 25px;
            border:none;
            border-radius:10px;
            color:white;
            font-size:16px;
            margin:10px;
            cursor:pointer;
        }}
        .win {{ color: #22c55e; }}
        .loss {{ color: #ef4444; }}
    </style>
</head>
<body>
    <h1>DIGIT OVER/UNDER ENGINE V10</h1>
    <h2>THE VENTURED KINGS LTD — EVANS MUKUKA</h2>

    <div class="card">
        <h3>Status</h3>
        <p>{status}</p>
        <p>Bot Running: {bot_running}</p>
    </div>

    <div class="card">
        <h3>Market</h3>
        <p>Tick: {tick_price}</p>
        <p>Last Digit: {last_digit}</p>
    </div>

    <div class="card">
        <h3>Signal Engine</h3>
        <p>{signal}</p>
        <p>Confidence: {confidence}%</p>
    </div>

    <div class="card">
        <h3>Money Management</h3>
        <p>Balance: ${round(balance, 2)}</p>
        <p>Profit/Loss: ${round(profit, 2)}</p>
        <p>Current Stake: ${current_stake}</p>
        <p>Loss Streak: {loss_streak}</p>
        <p>Win Rate: {win_rate}%</p>
    </div>

    <div class="card">
        <h3>Professional Controls</h3>
        <form action="/settings" method="post">
            <p>Stake</p>
            <input type="number" step="0.01"
                name="stake" value="{base_stake}">
            <p>Martingale</p>
            <input type="number" step="0.1"
                name="martingale"
                value="{martingale_multiplier}">
            <p>Take Profit</p>
            <input type="number" step="0.1"
                name="tp" value="{take_profit}">
            <p>Stop Loss</p>
            <input type="number" step="0.1"
                name="sl" value="{stop_loss}">
            <p>Confidence Threshold</p>
            <input type="number"
                name="confidence_input"
                value="{confidence_threshold}">
            <br><br>
            <button type="submit"
                style="background:blue;">
                SAVE SETTINGS
            </button>
        </form>
    </div>

    <div class="card">
        <h3>Performance</h3>
        <p>Wins: {wins}</p>
        <p>Losses: {losses}</p>
        <p>Win Rate: {win_rate}%</p>
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
# RUN SERVER
# ======================================

if __name__ == "__main__":
    threading.Thread(
        target=deriv_engine,
        daemon=True
    ).start()

    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
