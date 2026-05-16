from fastapi import FastAPI
from fastapi.responses import HTMLResponse, RedirectResponse
import uvicorn
import websocket
import json
import threading
import os

app = FastAPI()

# =========================================
# GLOBAL STATE
# =========================================

status = "CONNECTING..."
profit = 0
bot_running = False

# =========================================
# DERIV CONNECTION
# =========================================

TOKEN = os.getenv("DERIV_TOKEN")
APP_ID = "1089"

def deriv_connection():

    global status

    try:

        ws = websocket.create_connection(
            f"wss://ws.derivws.com/websockets/v3?app_id={APP_ID}"
        )

        ws.send(json.dumps({
            "authorize": TOKEN
        }))

        response = json.loads(ws.recv())

        if "error" in response:
            status = "AUTH FAILED"

        else:
            status = "CONNECTED TO DERIV"

    except Exception as e:

        status = f"ERROR: {e}"

# =========================================
# START DERIV CONNECTION
# =========================================

threading.Thread(
    target=deriv_connection,
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

        <title>PRO BOT CLOUD V4</title>

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

        <h1>PRO BOT CLOUD V4</h1>

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

            <h3>Profit</h3>

            <p>{profit}</p>

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
