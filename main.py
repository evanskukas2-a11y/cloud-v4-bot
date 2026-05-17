from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
import uvicorn
import websocket
import json
import threading
import os
from collections import Counter, deque
import time
import random

app = FastAPI()

# =========================================
# GLOBAL STATE
# =========================================

status = "CONNECTING..."
bot_running = False

confidence = 0
signal = "WAITING..."

last_digit = "-"
tick_price = "-"

market_condition = "NORMAL"

wins = 0
losses = 0

win_rate = 0

cooldown = 0

active_trade = "NONE"

last_result = "-"

# =========================================
# STORAGE
# =========================================

digits_history = deque(maxlen=100)

trade_history = deque(maxlen=10)

# =========================================
# DERIV CONFIG
# =========================================

TOKEN = os.getenv("DERIV_TOKEN")

APP_ID = "1089"

SYMBOL = "R_50"

# =========================================
# UPDATE WIN RATE
# =========================================

def update_win_rate():

    global win_rate

    total = wins + losses

    if total > 0:

        win_rate = round((wins / total) * 100, 2)

# =========================================
# SIMULATED TRADE ENGINE
# =========================================

def simulate_trade(signal_name):

    global wins
    global losses
    global active_trade
    global last_result

    active_trade = signal_name

    time.sleep(2)

    # =====================================
    # SIMULATED OUTCOME
    # =====================================

    result = random.choices(
        ["WIN", "LOSS"],
        weights=[68, 32]
    )[0]

    if result == "WIN":

        wins += 1

    else:

        losses += 1

    update_win_rate()

    last_result = result

    trade_history.appendleft(
        f"{signal_name} → {result}"
    )

    active_trade = "NONE"

# =========================================
# MARKET ENGINE
# =========================================

def deriv_engine():

    global status
    global confidence
    global signal
    global last_digit
    global tick_price
    global market_condition
    global cooldown

    try:

        ws = websocket.create_connection(
            f"wss://ws.derivws.com/websockets/v3?app_id={APP_ID}"
        )

        # AUTHORIZE
        ws.send(json.dumps({
            "authorize": TOKEN
        }))

        auth_response = json.loads(ws.recv())

        if "error" in auth_response:

            status = "AUTH FAILED"

            return

        status = "CONNECTED TO DERIV"

        # SUBSCRIBE TICKS
        ws.send(json.dumps({
            "ticks": SYMBOL,
            "subscribe": 1
        }))

        while True:

            data = json.loads(ws.recv())

            if "tick" in data:

                price = data["tick"]["quote"]

                tick_price = str(price)

                # =================================
                # LAST DIGIT
                # =================================

                digit = int(str(price)[-1])

                last_digit = digit

                digits_history.append(digit)

                if len(digits_history) < 30:
                    continue

                # =================================
                # DIGIT ANALYSIS
                # =================================

                counter = Counter(digits_history)

                most_common_digit = counter.most_common(1)[0][0]

                frequency = counter.most_common(1)[0][1]

                ratio = frequency / len(digits_history)

                # =================================
                # VOLATILITY FILTER
                # =================================

                recent_digits = list(digits_history)[-5:]

                repeated_count = recent_digits.count(
                    recent_digits[-1]
                )

                if repeated_count >= 4:

                    market_condition = "VOLATILE"

                    signal = "BLOCKED"

                    confidence = 10

                    continue

                else:

                    market_condition = "NORMAL"

                # =================================
                # COOLDOWN
                # =================================

                if cooldown > 0:

                    cooldown -= 1

                    signal = "COOLDOWN"

                    confidence = 15

                    continue

                # =================================
                # DIFFER ENGINE
                # =================================

                if digit != most_common_digit:

                    confidence = min(
                        int(ratio * 100),
                        95
                    )

                    if confidence >= 55:

                        signal = f"DIFFER {most_common_digit}"

                        # =========================
                        # SIMULATED EXECUTION
                        # =========================

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

                else:

                    signal = "WAITING..."

                    confidence = 20

                # =================================
                # SAFETY COOLDOWN
                # =================================

                if confidence < 40:

                    cooldown = 3

                time.sleep(0.2)

    except Exception as e:

        status = f"ERROR: {e}"

# =========================================
# START ENGINE THREAD
# =========================================

threading.Thread(
    target=deriv_engine,
    daemon=True
).start()

# =========================================
# START BOT
# =========================================

@app.get("/start")
def start_bot():

    global bot_running

    bot_running = True

    return RedirectResponse(
        url="/",
        status_code=303
    )

# =========================================
# STOP BOT
# =========================================

@app.get("/stop")
def stop_bot():

    global bot_running

    bot_running = False

    return RedirectResponse(
        url="/",
        status_code=303
    )

# =========================================
# DASHBOARD
# =========================================

@app.get("/", response_class=HTMLResponse)
def dashboard():

    history_html = ""

    for item in trade_history:

        history_html += f"<p>{item}</p>"

    return f"""
    <html>

    <head>

        <title>DIGIT DIFFER ENGINE V3</title>

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

        <h1>DIGIT DIFFER ENGINE V3</h1>

        <h2>
        THE VENTURED KINGS LTD — EVANS MUKUKA
        </h2>

        <div class="card">

            <h3>Status</h3>

            <p>{status}</p>

            <p>
            Bot Running: {bot_running}
            </p>

        </div>

        <div class="card">

            <h3>Market</h3>

            <p>Tick: {tick_price}</p>

            <p>Last Digit: {last_digit}</p>

            <p>Condition: {market_condition}</p>

        </div>

        <div class="card">

            <h3>Signal Engine</h3>

            <p>{signal}</p>

            <p>
            Confidence: {confidence}%
            </p>

        </div>

        <div class="card">

            <h3>Simulation</h3>

            <p>Active Trade: {active_trade}</p>

            <p>Last Result: {last_result}</p>

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

# =========================================
# RUN SERVER
# =========================================

if __name__ == "__main__":

    port = int(os.environ.get("PORT", 8000))

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port
    )
