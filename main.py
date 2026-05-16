from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
import uvicorn
import websocket
import json
import threading
import os
from collections import Counter, deque

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

# tick storage
digits_history = deque(maxlen=50)

# =========================================
# DERIV CONFIG
# =========================================

TOKEN = os.getenv("DERIV_TOKEN")
APP_ID = "1089"
SYMBOL = "R_50"

# =========================================
# DERIV ENGINE
# =========================================

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

        # authorize
        ws.send(json.dumps({
            "authorize": TOKEN
        }))

        auth_response = json.loads(ws.recv())

        if "error" in auth_response:
            status = "AUTH FAILED"
            return

        status = "CONNECTED TO DERIV"

        # subscribe ticks
        ws.send(json.dumps({
            "ticks": SYMBOL,
            "subscribe": 1
        }))

        while True:

            data = json.loads(ws.recv())

            if "tick" in data:

                price = data["tick"]["quote"]

                tick_price = str(price)

                # extract last digit
                digit = int(str(price)[-1])

                last_digit = digit

                digits_history.append(digit)

                # =================================
                # DIGIT ANALYSIS
                # =================================

                counter = Counter(digits_history)

                most_common_digit = counter.most_common(1)[0][0]
                frequency = counter.most_common(1)[0][1]

                # digit differ logic
                if digit != most_common_digit:

                    confidence = min(
                        int((frequency / len(digits_history)) * 100),
                        95
                    )

                    signal = f"DIFFER {most_common_digit}"

                else:

                    confidence = 20
                    signal = "WAITING..."

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

    return f"""
    <html>

    <head>

        <title>DIGIT DIFFER ENGINE V1</title>

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

        <h1>DIGIT DIFFER ENGINE V1</h1>

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

            <h3>Live Tick</h3>

            <p>{tick_price}</p>

            <p>Last Digit: {last_digit}</p>

        </div>

        <div class="card">

            <h3>Signal</h3>

            <p>{signal}</p>

            <p>
            Confidence: {confidence}%
            </p>

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
