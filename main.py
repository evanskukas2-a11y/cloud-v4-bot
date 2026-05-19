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

# =====================================================
# GLOBALS
# =====================================================

status = "CONNECTING..."
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

starting_balance = 0
balance = 0
profit = 0.0

base_stake = 1.00
current_stake = 1.00

take_profit_total = 50.00
stop_loss_total = 20.00

loss_streak = 0
max_loss_streak = 5

total_staked = 0.0
total_payout = 0.0

TOKEN = os.getenv("DERIV_TOKEN")
APP_ID = "1089"

SYMBOL = "R_10"

TRADE_COOLDOWN = 10
PREDICTIONS = 10

last_trade_time = 0
confidence_threshold = 65


# =====================================================
# HELPERS
# =====================================================

def update_win_rate():
    global win_rate

    total = wins + losses

    if total > 0:
        win_rate = round((wins / total) * 100, 2)


def status_message(msg):
    global status
    status = msg


def check_limits():
    global bot_running

    if profit >= take_profit_total:
        bot_running = False
        status_message("TARGET HIT +$" + str(round(profit, 2)))

    if profit <= -stop_loss_total:
        bot_running = False
        status_message("STOP LOSS HIT $" + str(round(profit, 2)))

    if loss_streak >= max_loss_streak:
        bot_running = False
        status_message("MAX STREAK " + str(loss_streak) + " PAUSED")


# =====================================================
# RESET
# =====================================================

@app.get("/reset")
def reset_session():
    global wins
    global losses
    global win_rate
    global profit
    global loss_streak
    global current_stake
    global bot_running
    global active_trade
    global total_staked
    global total_payout

    wins = 0
    losses = 0
    win_rate = 0

    profit = 0.0

    loss_streak = 0

    current_stake = base_stake

    bot_running = False

    active_trade = "NONE"

    total_staked = 0.0
    total_payout = 0.0

    trade_history.clear()

    status_message("SESSION RESET")

    return RedirectResponse(url="/", status_code=303)


# =====================================================
# PREDICTION ENGINE
# =====================================================

def predict_digits(recent_digits, n=10):

    if len(recent_digits) < 20:
        return []

    window = recent_digits[-50:] if len(recent_digits) >= 50 else recent_digits

    counts = Counter(window)

    freq_top = [d for d, _ in counts.most_common(10)]

    last10 = recent_digits[-10:]

    gap_digits = [d for d in range(10) if d not in last10]

    current = recent_digits[-1]

    next_digits = []

    for i in range(len(recent_digits) - 1):

        if recent_digits[i] == current:
            next_digits.append(recent_digits[i + 1])

    pattern_top = []

    if next_digits:
        pattern_counts = Counter(next_digits)
        pattern_top = [d for d, _ in pattern_counts.most_common(10)]

    last5 = recent_digits[-5:]

    streak_digit = None

    if len(set(last5)) == 1:
        streak_digit = last5[0]

    scores = {d: 0 for d in range(10)}

    for i, d in enumerate(freq_top[:10]):
        scores[d] += (10 - i)

    for d in gap_digits[:10]:
        scores[d] += 2

    for i, d in enumerate(pattern_top[:10]):
        scores[d] += (10 - i)

    if streak_digit is not None:
        scores[streak_digit] -= 5

    ranked = sorted(scores.items(), key=lambda x: x[1], reverse=True)

    return [d for d, s in ranked[:n]]


def get_confidence(recent_digits, digits):

    if not digits or len(recent_digits) < 20:
        return 0

    window = recent_digits[-30:]

    total = len(window)

    hits = sum(window.count(d) for d in digits)

    base_conf = (hits / total) * 100

    if len(digits) >= 3:
        base_conf = min(base_conf * 1.15, 95)

    return round(base_conf, 1)


# =====================================================
# TRADING ENGINE
# =====================================================

def place_digitmatch_trades(digits):

    global wins
    global losses
    global active_trade
    global balance
    global profit
    global loss_streak
    global total_staked
    global total_payout

    active_trade = "MATCH " + str(digits)

    try:

        ws = websocket.create_connection(
            "wss://ws.derivws.com/websockets/v3?app_id=" + APP_ID
        )

        ws.send(json.dumps({
            "authorize": TOKEN
        }))

        auth = json.loads(ws.recv())

        if "error" in auth:

            status_message(
                "AUTH FAILED: " + auth["error"]["message"]
            )

            active_trade = "NONE"

            ws.close()

            return

        stake = current_stake

        contracts = {}

        for digit in digits:

            ws.send(json.dumps({
                "buy": 1,
                "price": stake,
                "parameters": {
                    "amount": stake,
                    "basis": "stake",
                    "contract_type": "DIGITMATCH",
                    "currency": "USD",
                    "duration": 5,
                    "duration_unit": "t",
                    "symbol": SYMBOL,
                    "barrier": str(digit)
                }
            }))

            buy_resp = json.loads(ws.recv())

            if "error" in buy_resp:

                status_message(
                    "ERROR digit "
                    + str(digit)
                    + ": "
                    + buy_resp["error"]["message"]
                )

                continue

            contract_id = buy_resp["buy"]["contract_id"]

            contracts[digit] = contract_id

            total_staked += stake

            status_message(
                "PLACED MATCH "
                + str(digit)
                + " | ID: "
                + str(contract_id)
            )

            time.sleep(0.3)

        if not contracts:

            active_trade = "NONE"

            ws.close()

            return

        results = {}

        lock = threading.Lock()

        def wait_for_result(digit, cid):

            try:

                ws2 = websocket.create_connection(
                    "wss://ws.derivws.com/websockets/v3?app_id=" + APP_ID
                )