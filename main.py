from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
import uvicorn
import websocket
import json
import threading
import os
import random
import time

from collections import deque, Counter

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

wins = 0

losses = 0

win_rate = 0

active_trade = "NONE"

last_result = "-"

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

        win_rate = round(
            (wins / total) * 100,
            2
        )

# =========================================
# SIMULATED TRADE
# =========================================

def simulate_trade(signal_name):

    global wins
    global losses
    global active_trade
    global last_result

    active_trade = signal_name

    time.sleep(2)

    # =====================================
    # SMARTER OUTCOME SIMULATION
    # =====================================

    result = random.choices(
        ["WIN", "LOSS"],
        weights=[62, 38]
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
# V4 REAL FILTER ENGINE
# =========================================

def deriv_engine():

    global status
    global confidence
    global signal
    global last_digit
    global tick_price
    global active_trade

    digits_buffer = deque(maxlen=25)

    cooldown = 0

    try:

        ws = websocket.create_connection(
            f"wss://ws.derivws.com/websockets/v3?app_id={APP_ID}"
        )

        # AUTHORIZE
        ws.send(json.dumps({
            "authorize": TOKEN
        }))

        auth = json.loads(ws.recv())

        if "error" in auth:

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

                price_str = f"{price:.2f}"

digit = int(price_str[-1])

                last_digit = digit

                digits_buffer.append(digit)

                # =================================
                # WAIT FOR DATA
                # =================================

                if len(digits_buffer) < 15:

                    signal = "COLLECTING DATA..."

                    continue

                # =================================
                # COOLDOWN
                # =================================

                if cooldown > 0:

                    cooldown -= 1

                    signal = "COOLDOWN"

                    confidence = 0

                    continue

                recent = list(digits_buffer)[-6:]

                last = recent[-1]

                repeat_count = recent.count(last)

                # =================================
                # DIGIT ANALYSIS
                # =================================

                counter = Counter(recent)

                most_common = counter.most_common(1)[0][0]

                frequency = counter.most_common(1)[0][1]

                # =================================
                # EXHAUSTION LOGIC
                # =================================

                if frequency >= 4:

                    confidence = min(
                        55 + (frequency * 5),
                        90
                    )

                    signal = f"DIFFER {most_common}"

                    # =============================
                    # EXECUTION
                    # =============================

                    if (
                        bot_running
                        and active_trade == "NONE"
                    ):

                        threading.Thread(
                            target=simulate_trade,
                            args=(signal,),
                            daemon=True
                        ).start()

                        cooldown = 8

                else:

                    confidence = 15

                    signal = "WAITING..."

                # =================================
                # VOLATILITY BLOCK
                # =================================

                if repeat_count >= 5:

                    signal = "VOLATILE MARKET"

                    confidence = 5

                    cooldown = 12

                time.sleep(0.3)

    except Exception as e:

        status = f"ERROR: {e}"

# =========================================
# START ENGINE
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
        url="/
