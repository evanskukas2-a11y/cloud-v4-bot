from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
import uvicorn
import websocket
import json
import threading
import os
import random
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

starting_balance = 100

balance = 100

base_stake = 0.35

current_stake = 0.35

martingale_multiplier = 2.2

take_profit = 10

stop_loss = 10

profit = 0

loss_streak = 0

# ======================================
# CONFIG
# ======================================

TOKEN = os.getenv("DERIV_TOKEN")

APP_ID = "1089"

SYMBOL = "R_50"

# ======================================
# UPDATE WIN RATE
# ======================================

def update_win_rate():

    global win_rate

    total = wins + losses

    if total > 0:

        win_rate = round(
            (wins / total) * 100,
            2
        )

# ======================================
# CHECK TP / SL
# ======================================

def check_limits():

    global bot_running

    if profit >= take_profit:

        bot_running = False

    if profit <= -stop_loss:

        bot_running = False

# ======================================
# SIMULATED TRADE
# ======================================

def simulate_trade(signal_name):

    global wins
    global losses
    global active_trade
    global last_result

    global balance
    global current_stake
    global profit
    global loss_streak

    active_trade = signal_name

    time.sleep(2)

    # ==================================
    # SIMULATION OUTCOME
    # ==================================

    result = random.choices(
        ["WIN", "LOSS"],
        weights=[58, 42]
    )[0]

    # ==================================
    # WIN
    # ==================================

    if result == "WIN":

        wins += 1

        trade_profit = round(
            current_stake * 0.9,
            2
        )

        balance += trade_profit

        profit += trade_profit

        current_stake = base_stake

        loss_streak = 0

    # ==================================
    # LOSS
    # ==================================

    else:

        losses += 1

        balance -= current_stake

        profit -= current_stake

        loss_streak += 1

        current_stake = round(
            current_stake * martingale_multiplier,
            2
        )

    update_win_rate()

    check_limits()

    last_result = result

    trade_history.appendleft(
        f"{signal_name} | {result} | Stake: ${current_stake}"
    )

    active_trade = "NONE"

# ======================================
# DERIV ENGINE
# ======================================

def deriv_engine():

    global status
    global confidence
    global signal
    global last_digit
    global tick_price

    try:

        ws = websocket.create_connection(
            f"wss://ws.derivws.com/websockets/v3?app_id={APP_ID}"
        )

        ws.send(json.dumps({
            "authorize": TOKEN
        }))

        auth = json.loads(ws.recv())

        if "error" in auth:

            status = "AUTH FAILED"

            return

        status = "CONNECTED TO DERIV"

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

                confidence = random.randint(25, 90)

                if confidence >= 60:

                    signal = f"DIFFER {random.randint(0,9)}"

                    if (
                        bot_running
                        and active_trade == "NONE"
                    ):

                        threading.Thread(
                            target=simulate_trade,
                            args=(signal,),
                            daemon=True
                        ).start()

                else:

                    signal = "WAITING..."

                time.sleep(0.2)

    except Exception as e:

        status = f"ERROR: {e}"

# ======================================
# START ENGINE
# ======================================

threading.Thread(
    target=deriv_engine,
    daemon=True
).start()

# ======================================
# START BOT
# ======================================

@app.get("/start")
def start_bot():

    global bot_running

    bot_running = True

    return RedirectResponse(
        url="/",
        status_code=303
    )

# ======================================
# STOP BOT
# ======================================

@app.get("/stop")
def stop_bot():

    global bot_running

    bot_running = False

    return RedirectResponse(
        url="/",
        status_code=303
    )

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

        <title>DIGIT DIFFER ENGINE V5</title>

        <meta http-equiv="refresh" content="2">

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

            button {{

                padding:12px 25px;
                border:none;
                border-radius:10px;
                color:white;
                font-size:16px;
                margin:10px;
                cursor:pointer;

            }}

        </style>

    </head>

    <body>

        <h1>DIGIT DIFFER ENGINE V5</h1>

        <h2>
        THE VENTURED KINGS LTD — EVANS MUKUKA
        </h2>

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

            <p>Balance: ${round(balance,2)}</p>

            <p>Profit/Loss: ${round(profit,2)}</p>

            <p>Current Stake: ${current_stake}</p>

            <p>Loss Streak: {loss_streak}</p>

        </div>

        <div class="card">

            <h3>Settings</h3>

            <p>Base Stake: ${base_stake}</p>

            <p>Martingale: x{martingale_multiplier}</p>

            <p>Take Profit: ${take_profit}</p>

            <p>Stop Loss: ${stop_loss}</p>

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

                <button
                    type="submit"
                    style="background:green;">

                    START BOT

                </button>

            </form>

            <form action="/stop" method="get">

                <button
                    type="submit"
                    style="background:red;">

                    STOP BOT

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

    port = int(
        os.environ.get("PORT", 8000)
    )

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port
)
