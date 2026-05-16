from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import uvicorn
import websocket
import json
import threading
import os

app = FastAPI()

status = "CONNECTING..."
profit = 0

# =========================
# DERIV CONNECTION
# =========================

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

# =========================
# START CONNECTION THREAD
# =========================

threading.Thread(target=deriv_connection, daemon=True).start()

# =========================
# DASHBOARD
# =========================

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
                border-radius:10px;
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
        </div>
<div class="card">

    <h3>Controls</h3>

    <button style="
        padding:12px 25px;
        border:none;
        border-radius:10px;
        background:green;
        color:white;
        font-size:16px;
        margin:10px;
    ">
        START BOT
    </button>

    <button style="
        padding:12px 25px;
        border:none;
        border-radius:10px;
        background:red;
        color:white;
        font-size:16px;
        margin:10px;
    ">
        STOP BOT
    </button>

</div>
        <div class="card">
            <h3>Profit</h3>
            <p>{profit}</p>
        </div>

    </body>

    </html>
    """

# =========================
# RUN SERVER
# =========================

if __name__ == "__main__":

    port = int(os.environ.get("PORT", 8000))

    uvicorn.run(app, host="0.0.0.0", port=port)
