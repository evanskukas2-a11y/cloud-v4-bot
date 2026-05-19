import websocket
import json
import time
from collections import Counter, deque

=========================================

CONFIG

=========================================

TOKEN = "DERIV_TOKEN"

SYMBOLS = [
"R_10",
"R_25",
"R_50",
"R_75",
"R_100"
]

BASE_STAKE = 0.35
TAKE_PROFIT = 2
STOP_LOSS = -15

MARTINGALE = [0.35, 1.0, 2.2]

MIN_CONFIDENCE = 85
MIN_SAMPLES = 40
BASE_COOLDOWN = 8

=========================================

STATE

=========================================

ws = None
trade_active = False
buy_lock = False
cooldown = 0
step = 0

wins = 0
losses = 0
profit = 0
trade_count = 0

loss_streak = 0
pause_until = 0

stability buffer

signal_buffer = deque(maxlen=3)

market_data = {
symbol: deque(maxlen=60)
for symbol in SYMBOLS
}

=========================================

SEND

=========================================

def send(data):

global ws  

try:  
    ws.send(json.dumps(data))  
except Exception as e:  
    print("Send Error:", e)

=========================================

AUTHORIZE

=========================================

def authorize():
send({"authorize": TOKEN})

=========================================

SUBSCRIBE

=========================================

def subscribe_all():

for symbol in SYMBOLS:  

    send({  
        "ticks": symbol,  
        "subscribe": 1  
    })  

    print(f"Subscribed -> {symbol}")

=========================================

CONFIDENCE ENGINE

=========================================

def calculate_confidence(symbol):

digits = list(market_data[symbol])  

if len(digits) < MIN_SAMPLES:  
    return None, 0  

even_count = 0  
odd_count = 0  

# full sample pressure  
for d in digits:  

    if d % 2 == 0:  
        even_count += 1  
    else:  
        odd_count += 1  

# recent momentum  
recent = digits[-12:]  

recent_even = 0  
recent_odd = 0  

for d in recent:  

    if d % 2 == 0:  
        recent_even += 1  
    else:  
        recent_odd += 1  

confidence = 0  
contract_type = None  

# =====================================  
# EVEN PRESSURE  
# =====================================  
if even_count > odd_count:  

    contract_type = "DIGITEVEN"  

    diff = even_count - odd_count  

    if diff >= 6:  
        confidence += 30  

    if diff >= 10:  
        confidence += 20  

    if recent_even >= 8:  
        confidence += 30  

    if recent_even >= 10:  
        confidence += 15  

# =====================================  
# ODD PRESSURE  
# =====================================  
else:  

    contract_type = "DIGITODD"  

    diff = odd_count - even_count  

    if diff >= 6:  
        confidence += 30  

    if diff >= 10:  
        confidence += 20  

    if recent_odd >= 8:  
        confidence += 30  

    if recent_odd >= 10:  
        confidence += 15  

# =====================================  
# CHAOS FILTER  
# =====================================  
alternation = 0  

for i in range(1, len(recent)):  

    prev_even = recent[i-1] % 2 == 0  
    curr_even = recent[i] % 2 == 0  

    if prev_even != curr_even:  
        alternation += 1  

# excessive flipping  
if alternation >= 9:  
    confidence -= 35  

# stable movement  
if alternation <= 4:  
    confidence += 15  

# exhaustion protection  
streak = 0  

last_parity = recent[-1] % 2  

for d in reversed(recent):  

    if d % 2 == last_parity:  
        streak += 1  
    else:  
        break  

# avoid entering after overextended runs  
if streak >= 7:  
    confidence -= 25  

return contract_type, confidence

=========================================

BEST SIGNAL

=========================================

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

=========================================

BUY

=========================================

def buy_contract(symbol, contract_type):

global trade_active  
global buy_lock  

if buy_lock:  
    return  

if time.time() < pause_until:  
    return  

buy_lock = True  

try:  

    stake = MARTINGALE[min(step, len(MARTINGALE)-1)]  

    print("\n============================")  
    print("EVEN/ODD SNIPER ENTRY")  
    print(f"Market    : {symbol}")  
    print(f"Contract  : {contract_type}")  
    print(f"Stake     : ${stake}")  
    print("============================\n")  

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

    trade_active = True  

except Exception as e:  
    print("Buy Error:", e)

=========================================

RESULT PROCESSING

=========================================

def process_contract(data):

global trade_active  
global wins  
global losses  
global profit  
global step  
global cooldown  
global trade_count  
global buy_lock  
global loss_streak  
global pause_until  

if "profit" not in data:  
    return  

pnl = float(data["profit"])  

profit += pnl  
trade_count += 1  

print("\n============================")  

if pnl > 0:  

    wins += 1  
    step = 0  
    loss_streak = 0  

    print(f"WIN +${round(pnl,2)}")  

else:  

    losses += 1  
    step += 1  
    loss_streak += 1  

    print(f"LOSS ${round(pnl,2)}")  

print("============================")  

total = wins + losses  

wr = (wins / total) * 100 if total > 0 else 0  

print(f"Profit     : ${round(profit,2)}")  
print(f"Trades     : {trade_count}")  
print(f"Wins       : {wins}")  
print(f"Losses     : {losses}")  
print(f"Win Rate   : {round(wr,1)}%")  

# anti revenge protection  
if loss_streak >= 3:  

    print("PAUSING AFTER LOSS STREAK")  

    pause_until = time.time() + 45  
    loss_streak = 0  

trade_active = False  
buy_lock = False  
cooldown = BASE_COOLDOWN  

if profit >= TAKE_PROFIT:  

    print("TAKE PROFIT REACHED")  

    try:  
        ws.close()  
    except:  
        pass  

if profit <= STOP_LOSS:  

    print("STOP LOSS HIT")  

    try:  
        ws.close()  
    except:  
        pass

=========================================

MESSAGE

=========================================

def on_message(wsapp, message):

global cooldown  
global signal_buffer  

try:  

    data = json.loads(message)  

    if "authorize" in data:  

        print("Authorized")  
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
            f"BEST:{best_symbol} | {best_contract} | CONF:{best_confidence} | CD:{cooldown}",  
            end="\r"  
        )  

        # STABILITY CONFIRMATION  
        if (  
            best_confidence >= MIN_CONFIDENCE  
            and len(signal_buffer) == 3  
            and min(signal_buffer) >= MIN_CONFIDENCE  
            and not trade_active  
            and cooldown == 0  
            and time.time() >= pause_until  
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
    print("Message Error:", e)

=========================================

CONNECTION

=========================================

def on_open(wsapp):
print("Connected")
authorize()

def on_error(wsapp, error):
print("Error:", error)

def on_close(wsapp, a, b):
print("Reconnecting...")

=========================================

START

=========================================

print("============================")
print("EVEN/ODD QUALITY SNIPER BOT V2 ULTRA STABLE")
print("============================")
print("Quality Signals Over Quantity")
print("============================\n")

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

    print("Reconnect Error:", e)  

print("Retrying In 5 Seconds...")  
time.sleep(5)