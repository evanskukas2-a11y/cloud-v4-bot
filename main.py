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

# ======================================
# GLOBALS
# ======================================

status           = "CONNECTING..."
bot_running      = False
tick_price       = "-"
last_digit       = "-"
wins             = 0
losses           = 0
win_rate         = 0
active_trade     = "NONE"
trade_history    = deque(maxlen=15)
signal           = "WAITING..."
predicted_digits = []

# ======================================
# MONEY MANAGEMENT
# ======================================

starting_balance  = 0
balance           = 0
profit            = 0.0
base_stake        = 1.00
current_stake     = 1.00
take_profit_total = 50.00
stop_loss_total   = 20.00
loss_streak       = 0
max_loss_streak   = 5
total_staked      = 0.0
total_payout      = 0.0

# ======================================
# CONFIG
# ======================================

TOKEN                = os.getenv("DERIV_TOKEN")
APP_ID               = "1089"
SYMBOL               = "R_10"
TRADE_COOLDOWN       = 10
PREDICTIONS          = 4
last_trade_time      = 0
confidence_threshold = 65

# ======================================
# HELPERS
# ======================================

def update_win_rate():
    global win_rate
    total = wins + losses
    if total > 0:
        win_rate = round((wins / total) * 100, 2)

def status_message(msg):
    global status
    status = msg

# ======================================
# CHECK LIMITS
# ======================================

def check_limits():
    global bot_running
    if profit >= take_profit_total:
        bot_running = False
        status_message(f"TARGET HIT! +${profit:.2f}")
    if profit <= -stop_loss_total:
        bot_running = False
        status_message(f"STOP LOSS HIT ${profit:.2f}")
    if loss_streak >= max_loss_streak:
        bot_running = False
        status_message(
            f"MAX STREAK {loss_streak} — PAUSED"
        )

# ======================================
# RESET
# ======================================

@app.get("/reset")
def reset_session():
    global wins, losses, win_rate, profit
    global loss_streak, current_stake, bot_running
    global active_trade, total_staked, total_payout
    wins          = 0
    losses        = 0
    win_rate      = 0
    profit        = 0.0
    loss_streak   = 0
    current_stake = base_stake
    bot_running   = False
    active_trade  = "NONE"
    total_staked  = 0.0
    total_payout  = 0.0
    trade_history.clear()
    status_message("SESSION RESET")
    return RedirectResponse(url="/", status_code=303)

# ======================================
# DIGIT PREDICTION ENGINE
# ======================================

def predict_digits(recent_digits, n=4):
    """
    Predicts N most likely digits using:
    1. Frequency — most common digits
    2. Gap — digits not seen recently
    3. Pattern — what follows current digit
    4. Anti-streak — avoid digits on long streaks
    """
    if len(recent_digits) < 20:
        return []

    window = (
        recent_digits[-50:]
        if len(recent_digits) >= 50
        else recent_digits
    )

    # Signal 1 — Frequency
    counts   = Counter(window)
    freq_top = [d for d, _ in counts.most_common(6)]

    # Signal 2 — Gap (not seen in last 10)
    last10     = recent_digits[-10:]
    gap_digits = [
        d for d in range(10)
        if d not in last10
    ]

    # Signal 3 — Pattern (what follows current)
    current     = recent_digits[-1]
    next_digits = []
    for i in range(len(recent_digits) - 1):
        if recent_digits[i] == current:
            next_digits.append(recent_digits[i + 1])

    pattern_top = []
    if next_digits:
        pattern_counts = Counter(next_digits)
        pattern_top    = [
            d for d, _ in
            pattern_counts.most_common(4)
        ]

    # Signal 4 — Anti-streak
    last5       = recent_digits[-5:]
    streak_digit = None
    if len(set(last5)) == 1:
        streak_digit = last5[0]

    # Score each digit
    scores = {d: 0 for d in range(10)}

    for i, d in enumerate(freq_top[:4]):
        scores[d] += (4 - i)

    for d in gap_digits[:4]:
        scores[d] += 2

    for i, d in enumerate(pattern_top[:3]):
        scores[d] += (5 - i)

    # Penalize streak digit
    if streak_digit is not None:
        scores[streak_digit] -= 5

    # Return top N
    ranked = sorted(
        scores.items(),
        key=lambda x: x[1],
        reverse=True
    )
    return [d for d, s in ranked[:n]]

def get_confidence(recent_digits, digits):
    if not digits or len(recent_digits) < 20:
        return 0
    window    = recent_digits[-30:]
    total     = len(window)
    hits      = sum(window.count(d) for d in digits)
    base_conf = (hits / total) * 100
    if len(digits) >= 3:
        base_conf = min(base_conf * 1.15, 95)
    return round(base_conf, 1)

# ======================================
# PLACE 4 DIGITMATCH TRADES
# ======================================

def place_digitmatch_trades(digits):
    global wins, losses, active_trade
    global balance, profit, loss_streak
    global total_staked, total_payout

    active_trade = f"MATCH {digits}"

    try:
        ws = websocket.create_connection(
            f"wss://ws.derivws.com/websockets/v3?app_id={APP_ID}"
        )

        ws.send(json.dumps({"authorize": TOKEN}))
        auth = json.loads(ws.recv())

        if "error" in auth:
            status_message(
                f"AUTH FAILED: {auth['error']['message']}"
            )
            active_trade = "NONE"
            ws.close()
            return

        stake     = current_stake
        contracts = {}

        # Place one contract per predicted digit
        for digit in digits:
            ws.send(json.dumps({
                "buy": 1,
                "price": stake,
                "parameters": {
                    "amount":        stake,
                    "basis":         "stake",
                    "contract_type": "DIGITMATCH",
                    "currency":      "USD",
                    "duration":      5,
                    "duration_unit": "t",
                    "symbol":        SYMBOL,
                    "barrier":       str(digit)
                }
            }))

            buy_resp = json.loads(ws.recv())

            if "error" in buy_resp:
                status_message(
                    f"ERROR digit {digit}: "
                    f"{buy_resp['error']['message']}"
                )
                continue

            contract_id      = buy_resp["buy"]["contract_id"]
            contracts[digit] = contract_id
            total_staked    += stake
            status_message(
                f"PLACED MATCH {digit} | "
                f"ID: {contract_id}"
            )
            time.sleep(0.3)

        if not contracts:
            active_trade = "NONE"
            ws.close()
            return

        # Wait for all results in parallel
        results = {}
        lock    = threading.Lock()

        def wait_for_result(digit, cid):
            try:
                ws2 = websocket.create_connection(
                    f"wss://ws.derivws.com/websockets/v3?app_id={APP_ID}"
                )
                ws2.send(json.dumps({"authorize": TOKEN}))
                ws2.recv()
                ws2.send(json.dumps({
                    "proposal_open_contract": 1,
                    "contract_id": cid,
                    "subscribe": 1
                }))
                while True:
                    resp = json.loads(ws2.recv())
                    poc  = resp.get(
                        "proposal_open_contract", {}
                    )
                    s = poc.get("status")
                    if s in ("won", "lost"):
                        p = round(
                            float(poc.get("profit", 0)), 2
                        )
                        with lock:
                            results[digit] = (s, p)
                        ws2.close()
                        break
            except Exception as e:
                with lock:
                    results[digit] = ("error", 0)

        threads = []
        for digit, cid in contracts.items():
            t = threading.Thread(
                target=wait_for_result,
                args=(digit, cid),
                daemon=True
            )
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=60)

        # Process results
        round_won    = 0
        round_lost   = 0
        round_profit = 0.0
        won_digits   = []
        lost_digits  = []

        for digit, (result, p) in results.items():
            if result == "won":
                round_won    += 1
                round_profit += p
                total_payout += (stake + p)
                won_digits.append(digit)
            elif result == "lost":
                round_lost   += 1
                round_profit += p
                lost_digits.append(digit)

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

        profit += round(round_profit, 2)

        if round_won > 0:
            wins       += round_won
            loss_streak = 0
            status_message(
                f"WON {round_won}/{len(digits)} | "
                f"Digits: {won_digits} | "
                f"+${round_profit:.2f} | "
                f"Balance: ${balance}"
            )
        else:
            losses     += round_lost
            loss_streak += 1
            status_message(
                f"ALL MISSED | "
                f"${round_profit:.2f} | "
                f"Streak: {loss_streak}"
            )

        update_win_rate()
        check_limits()

        trade_history.appendleft(
            f"MATCH {digits} | "
            f"Won:{round_won}/{len(digits)} | "
            f"Hit:{won_digits} | "
            f"P/L ${round_profit:.2f}"
        )

    except Exception as e:
        status_message(f"EXCEPTION: {e}")

    finally:
        active_trade = "NONE"

# ======================================
# DERIV ENGINE
# ======================================

def deriv_engine():
    global status, signal, last_digit
    global tick_price, last_trade_time
    global balance, starting_balance
    global predicted_digits

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

                    if len(recent_digits) > 100:
                        recent_digits.pop(0)

                    if len(recent_digits) < 20:
                        signal = (
                            f"COLLECTING... "
                            f"{len(recent_digits)}/20"
                        )
                        predicted_digits = []
                        continue

                    preds = predict_digits(
                        recent_digits, PREDICTIONS
                    )
                    conf  = get_confidence(
                        recent_digits, preds
                    )
                    predicted_digits = preds

                    if preds:
                        signal = (
                            f"PREDICTING: {preds} | "
                            f"Conf: {conf}%"
                        )
                    else:
                        signal = "ANALYSING..."

                    seconds_since_trade = (
                        time.time() - last_trade_time
                    )

                    if (
                        preds
                        and conf >= confidence_threshold
                        and bot_running
                        and active_trade == "NONE"
                        and seconds_since_trade
                        >= TRADE_COOLDOWN
                    ):
                        last_trade_time = time.time()
                        threading.Thread(
                            target=place_digitmatch_trades,
                            args=(preds,),
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
    tp: float = Form(...),
    sl: float = Form(...),
    conf: int = Form(...),
    cooldown: int = Form(...)
):
    global base_stake, current_stake
    global take_profit_total, stop_loss_total
    global confidence_threshold, TRADE_COOLDOWN

    base_stake           = stake
    current_stake        = stake
    take_profit_total    = tp
    stop_loss_total      = sl
    confidence_threshold = conf
    TRADE_COOLDOWN       = cooldown

    status_message("SETTINGS UPDATED")
    return RedirectResponse(url="/", status_code=303)

# ======================================
# DASHBOARD
# ======================================

@app.get("/", response_class=HTMLResponse)
def dashboard():
    history_html = ""
    for item in trade_history:
        color = (
            "lightgreen"
            if "Won:0" not in item
            else "#ff6b6b"
        )
        history_html += (
            f"<p style='color:{color}'>{item}</p>"
        )

    preds_display = (
        str(predicted_digits)
        if predicted_digits
        else "Analysing..."
    )

    return f"""
<html>
<head>
    <title>DIGITMATCH 4X ENGINE V12</title>
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
        h1 {{ color:gold; }}
        .digit-box {{
            display:inline-block;
            background:#334155;
            border-radius:10px;
            padding:10px 18px;
            margin:5px;
            font-size:28px;
            font-weight:bold;
            color:gold;
            border:2px solid #475569;
        }}
    </style>

    <script>
        let refreshTimer;
        function startRefresh() {{
            refreshTimer = setTimeout(function() {{
                window.location.reload();
            }}, 15000);
        }}
        function stopRefresh() {{
            clearTimeout(refreshTimer);
        }}
        startRefresh();
        document.addEventListener(
            'focusin', function(e) {{
            if (e.target.tagName === 'INPUT')
                stopRefresh();
        }});
        document.addEventListener(
            'focusout', function(e) {{
            if (e.target.tagName === 'INPUT')
                startRefresh();
        }});
    </script>
</head>
<body>
    <h1>DIGITMATCH 4X ENGINE V12</h1>
    <h3>THE VENTURED KINGS LTD — EVANS MUKUKA</h3>

    <div class="card">
        <h3>Status</h3>
        <p>{status}</p>
        <p>Bot: {"🟢 RUNNING" if bot_running else "🔴 STOPPED"}</p>
        <p>Active: {active_trade}</p>
    </div>

    <div class="card">
        <h3>Market — {SYMBOL}</h3>
        <p>Tick: {tick_price}</p>
        <p>Last Digit:
            <b style="font-size:28px;color:gold">
                {last_digit}
            </b>
        </p>
    </div>

    <div class="card">
        <h3>4 Digit Predictions</h3>
        <p>{signal}</p>
        {"".join(
            f'<div class="digit-box">{d}</div>'
            for d in predicted_digits
        )}
        <p style="font-size:12px;color:#94a3b8;margin-top:10px">
            Stake: ${base_stake} x 4 = ${base_stake*4:.2f} per round
            | Win one = +${base_stake*8:.2f}
        </p>
    </div>

    <div class="card">
        <h3>Session Performance</h3>
        <p>Balance:
            <b>${round(balance, 2)}</b>
        </p>
        <p>Session P/L:
            <b style="color:{'lightgreen' if profit >= 0 else '#ff6b6b'}">
                ${round(profit, 2)}
            </b>
        </p>
        <p>Total Staked: ${round(total_staked, 2)}</p>
        <p>Total Payout: ${round(total_payout, 2)}</p>
        <p>Wins: {wins} | Losses: {losses}</p>
        <p>Win Rate: {win_rate}%</p>
        <p>Loss Streak: {loss_streak}</p>
    </div>

    <div class="card">
        <h3>Settings</h3>
        <form action="/settings" method="post">
            <p>Stake per digit ($)</p>
            <input type="number" step="0.01"
                name="stake" value="{base_stake}">
            <p>Take Profit ($)</p>
            <input type="number" step="1"
                name="tp" value="{take_profit_total}">
            <p>Stop Loss ($)</p>
            <input type="number" step="1"
                name="sl" value="{stop_loss_total}">
            <p>Confidence Threshold (%)</p>
            <input type="number"
                name="conf"
                value="{confidence_threshold}">
            <p>Cooldown (seconds)</p>
            <input type="number"
                name="cooldown"
                value="{TRADE_COOLDOWN}">
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
 