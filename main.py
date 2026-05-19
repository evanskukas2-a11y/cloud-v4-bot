from fastapi import FastAPI, Form
from fastapi.responses import HTMLResponse, RedirectResponse
import uvicorn
import websocket
import json
import threading
import os
import time
from collections import deque, Counter

app = FastAPI()

# =========================
# GLOBAL STATE
# =========================
status = "STARTING..."
bot_running = False
tick_price = "-"
last_digit = "-"
wins = 0
losses = 0
win_rate = 0
active_trade = "NONE"
trade_history = deque(maxlen=15)

signal = "WAITING..."
predicted_digits = []

balance = 0
profit = 0.0

base_stake = 1.0
current_stake = 1.0

take_profit_total = 50
stop_loss_total = 20

loss_streak = 0
max_loss_streak = 5

total_staked = 0.0
total_payout = 0.0

TOKEN = os.getenv("DERIV_TOKEN")
APP_ID = "1089"
SYMBOL = "R_10"

TRADE_COOLDOWN = 10
PREDICTIONS = 10
confidence_threshold = 65

last_trade_time = 0


# =========================
# SAFETY STATUS
# =========================
def status_message(msg):
    global status
    print(msg)
    status = msg


def check_limits():
    global bot_running

    if profit >= take_profit_total:
        bot_running = False
        status_message("TARGET HIT")

    if profit <= -stop_loss_total:
        bot_running = False
        status_message("STOP LOSS HIT")

    if loss_streak >= max_loss_streak:
        bot_running = False
        status_message("MAX LOSS STREAK HIT")


# =========================
# PREDICTION ENGINE
# =========================
def predict_digits(data, n=10):
    if len(data) < 20:
        return []

    window = data[-50:]
    counts = Counter(window)

    top = [d for d, _ in counts.most_common(10)]

    scores = {i: 0 for i in range(10)}

    for i, d in enumerate(top):
        scores[d] += (10 - i)

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    return [d for d, _ in ranked[:n]]


def confidence(data, preds):
    if len(data) < 20 or not preds:
        return 0

    window = data[-30:]
    hits = sum(window.count(d) for d in preds)

    return round((hits / len(window)) * 100, 1)


# =========================
# DERIV ENGINE (SAFE LOOP)
# =========================
def deriv_engine():
    global balance, tick_price, last_digit
    global predicted_digits, signal
    global last_trade_time

    if not TOKEN:
        status_message("ERROR: NO DERIV TOKEN")
        return

    recent = []

    while True:
        try:
            ws = websocket.create_connection(
                f"wss://ws.derivws.com/websockets/v3?app_id={APP_ID}"
            )

            ws.send(json.dumps({"authorize": TOKEN}))
            auth = json.loads(ws.recv())

            if "error" in auth:
                status_message("AUTH FAILED")
                time.sleep(5)
                continue

            ws.send(json.dumps({"ticks": SYMBOL, "subscribe": 1}))

            status_message("CONNECTED")

            while True:
                data = json.loads(ws.recv())

                if "tick" not in data:
                    continue

                price = float(data["tick"]["quote"])
                tick_price = price

                digit = int(str(price)[-1])
                last_digit = digit

                recent.append(digit)
                if len(recent) > 100:
                    recent.pop(0)

                if len(recent) < 20:
                    signal = "COLLECTING DATA..."
                    continue

                preds = predict_digits(recent, PREDICTIONS)
                conf = confidence(recent, preds)

                predicted_digits = preds
                signal = f"Pred: {preds} | {conf}%"

                if (
                    bot_running
                    and active_trade == "NONE"
                    and conf >= confidence_threshold
                    and time.time() - last_trade_time > TRADE_COOLDOWN
                ):
                    last_trade_time = time.time()
                    status_message("SIGNAL READY (SIMULATED TRADE)")

                time.sleep(0.1)

        except Exception as e:
            status_message(f"RECONNECTING: {e}")
            time.sleep(5)


# =========================
# STARTUP FIX (IMPORTANT)
# =========================
@app.on_event("startup")
def startup():
    print("APP STARTED")

    threading.Thread(target=deriv_engine, daemon=True).start()


# =========================
# ROUTES
# =========================
@app.get("/start")
def start():
    global bot_running
    bot_running = True
    status_message("BOT STARTED")
    return RedirectResponse("/", 303)


@app.get("/stop")
def stop():
    global bot_running
    bot_running = False
    status_message("BOT STOPPED")
    return RedirectResponse("/", 303)


# =========================
# DASHBOARD
# =========================
@app.get("/", response_class=HTMLResponse)
def home():

    return f"""
    <html>
    <head>
    <title>BOT</title>
    <style>
    body{{background:#0f172a;color:white;font-family:Arial;text-align:center}}
    .box{{background:#1e293b;padding:20px;margin:20px;border-radius:10px}}
    </style>
    </head>

    <body>

    <h1>DIGIT BOT</h1>

    <div class="box">
    <h3>Status</h3>
    <p>{status}</p>
    <p>Bot: {"RUNNING" if bot_running else "STOPPED"}</p>
    </div>

    <div class="box">
    <h3>Market</h3>
    <p>Tick: {tick_price}</p>
    <p>Last Digit: {last_digit}</p>
    <p>{signal}</p>
    </div>

    <div class="box">
    <h3>Predictions</h3>
    <p>{predicted_digits}</p>
    </div>

    <div class="box">
    <a href="/start"><button>START</button></a>
    <a href="/stop"><button>STOP</button></a>
    </div>

    </body>
    </html>
    """


# =========================
# RUN
# =========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)