import websocket
import json
import time
import os
from collections import deque

TOKEN = os.getenv("TOKEN")

SYMBOLS = [
    "R_10",
    "R_25",
    "R_50",
    "R_75",
    "R_100"
]

BASE_STAKE = 0.35

MARTINGALE = [0.35, 0.80, 1.90]

TAKE_PROFIT = 2
STOP_LOSS = -15

MIN_CONFIDENCE = 88
MIN_SAMPLES = 50
BASE_COOLDOWN = 10

ws = None

trade_active = False
buy_lock = False
cooldown = 0

wins = 0
losses = 0
profit = 0
trade_count = 0

martingale_step = 0

signal_buffer = deque(maxlen=4)

market_data = {
    symbol: deque(maxlen=80)
    for symbol in SYMBOLS
}

def send(data):

    global ws

    try:
        ws.send(json.dumps(data))

    except Exception as e:
        print("SEND ERROR:", e)

def authorize():

    send({
        "authorize": TOKEN
    })

def subscribe_all():

    for symbol in SYMBOLS:

        send({
            "ticks": symbol,
            "subscribe": 1
        })

        print(f"SUBSCRIBED -> {symbol}")

def calculate_confidence(symbol):

    digits = list(market_data[symbol])

    if len(digits) < MIN_SAMPLES:
        return None, 0

    even_count = sum(1 for d in digits if d % 2 == 0)
    odd_count = len(digits) - even_count

    recent = digits[-15:]

    recent_even = sum(1 for d in recent if d % 2 == 0)
    recent_odd = len(recent) - recent_even

    confidence = 0

    if even_count > odd_count:

        contract_type = "DIGITEVEN"

        confidence += recent_even * 6

    else:

        contract_type = "DIGITODD"

        confidence += recent_odd * 6

    alternation = 0

    for i in range(1, len(recent)):

        if (recent[i] % 2) != (recent[i - 1] % 2):
            alternation += 1

    if alternation >= 10:
        confidence -= 40

    elif alternation <= 4:
        confidence += 15

    confidence = max(0, min(confidence, 100))

    return contract_type, confidence

def get_best_signal():

    best_symbol = None
    best_contract = None
    best_confidence = 0

    for symbol in SYMBOLS:

        contract, confidence = calculate_confidence(symbol)

        if confidence > best_confidence:

            best_symbol = symbol
            best_contract = contract
            best_confidence = confidence

    return best_symbol, best_contract, best_confidence

def buy_contract(symbol, contract_type):

    global trade_active
    global buy_lock
    global martingale_step

    if trade_active or buy_lock:
        return

    stake = MARTINGALE[
        min(martingale_step, len(MARTINGALE)-1)
    ]

    print(f"\nENTRY -> {symbol} {contract_type} ${stake}")

    buy_lock = True
    trade_active = True

    send({
        "buy": 1,
        "price": stake,
        "parameters": {
            "amount": stake,
            "basis": "stake",
            "contract_type": contract_type,
            "currency": "USD",
            "duration": 1,
            "duration_unit": "t",
            "symbol": symbol
        }
    })

def process_contract(contract):

    global trade_active
    global buy_lock
    global wins
    global losses
    global profit
    global martingale_step

    pnl = float(contract["profit"])

    profit += pnl

    if pnl > 0:

        wins += 1
        martingale_step = 0

        print(f"WIN +${round(pnl,2)}")

    else:

        losses += 1
        martingale_step += 1

        print(f"LOSS ${round(pnl,2)}")

    print(f"TOTAL PROFIT: ${round(profit,2)}")

    trade_active = False
    buy_lock = False

    if profit >= TAKE_PROFIT:

        print("TAKE PROFIT REACHED")
        ws.close()

    if profit <= STOP_LOSS:

        print("STOP LOSS HIT")
        ws.close()

def on_message(wsapp, message):

    global cooldown
    global signal_buffer

    try:

        data = json.loads(message)

        if "authorize" in data:

            print("AUTHORIZED")
            subscribe_all()

        if "tick" in data:

            symbol = data["tick"]["symbol"]

            digit = int(str(data["tick"]["quote"])[-1])

            market_data[symbol].append(digit)

            if cooldown > 0:
                cooldown -= 1

            best_symbol, best_contract, best_confidence = get_best_signal()

            signal_buffer.append(best_confidence)

            print(
                f"{best_symbol} | {best_contract} | {best_confidence}",
                end="\r"
            )

            if (
                best_confidence >= MIN_CONFIDENCE
                and len(signal_buffer) == 4
                and min(signal_buffer) >= MIN_CONFIDENCE
                and not trade_active
                and cooldown == 0
            ):

                buy_contract(best_symbol, best_contract)

        if "buy" in data:

            contract_id = data["buy"]["contract_id"]

            send({
                "proposal_open_contract": 1,
                "contract_id": contract_id,
                "subscribe": 1
            })

        if "proposal_open_contract" in data:

            poc = data["proposal_open_contract"]

            if poc.get("is_sold"):
                process_contract(poc)

    except Exception as e:

        print("MESSAGE ERROR:", e)

def on_open(wsapp):

    print("CONNECTED")
    authorize()

def on_error(wsapp, error):

    print("ERROR:", error)

def on_close(wsapp, a, b):

    print("RECONNECTING...")

while True:

    try:

        ws = websocket.WebSocketApp(
            "wss://ws.binaryws.com/websockets/v3?app_id=1089",
            on_open=on_open,
            on_message=on_message,
            on_error=on_error,
            on_close=on_close
        )

        ws.run_forever(
            ping_interval=20,
            ping_timeout=10
        )

    except Exception as e:

        print("RECONNECT ERROR:", e)

    time.sleep(5)