from fastapi import FastAPI
from fastapi.responses import HTMLResponse
import uvicorn

app = FastAPI()

profit = 0
status = "RUNNING"

@app.get("/", response_class=HTMLResponse)
def dashboard():

    return f"""
    <html>

    <head>
        <title>PRO BOT CLOUD V3</title>

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

            button {{
                padding:10px 20px;
                border:none;
                border-radius:10px;
                margin:10px;
                cursor:pointer;
            }}

        </style>

    </head>

    <body>

        <h1>PRO BOT CLOUD V3 FINAL</h1>

        <h2>
        THE VENTURED KINGS LTD — EVANS MUKUKA
        </h2>

        <div class="card">
            <h3>Status</h3>
            <p>{status}</p>
        </div>

        <div class="card">
            <h3>Profit</h3>
            <p>{profit}</p>
        </div>

        <button>START BOT</button>
        <button>STOP BOT</button>

    </body>

    </html>
    """

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
