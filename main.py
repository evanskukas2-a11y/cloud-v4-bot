# =========================================
# V4 REAL FILTER ENGINE
# Replace ONLY the deriv_engine() function
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

        ws.send(json.dumps({
            "authorize": TOKEN
        }))

        auth = json.loads(ws.recv())

        if "error" in auth:

            status = "AUTH FAILED"

            return

        status = "CONNECTED TO DERIV"

        ws.send(json.dumps({
            "ticks": SYMBOL,
            "subscribe": 1
        }))

        while True:

            data = json.loads(ws.recv())

            if "tick" in data:

                price = data["tick"]["quote"]

                tick_price = str(price)

                digit = int(str(price)[-1])

                last_digit = digit

                digits_buffer.append(digit)

                # =====================================
                # WAIT FOR DATA
                # =====================================

                if len(digits_buffer) < 15:

                    signal = "COLLECTING DATA..."

                    continue

                # =====================================
                # COOLDOWN SYSTEM
                # =====================================

                if cooldown > 0:

                    cooldown -= 1

                    signal = "COOLDOWN"

                    confidence = 0

                    continue

                # =====================================
                # RECENT DIGITS
                # =====================================

                recent = list(digits_buffer)[-6:]

                last = recent[-1]

                repeat_count = recent.count(last)

                # =====================================
                # DIGIT PRESSURE ANALYSIS
                # =====================================

                counter = Counter(recent)

                most_common = counter.most_common(1)[0][0]

                frequency = counter.most_common(1)[0][1]

                # =====================================
                # EXHAUSTION LOGIC
                # =====================================

                if frequency >= 4:

                    confidence = min(
                        55 + (frequency * 5),
                        90
                    )

                    signal = f"DIFFER {most_common}"

                    # =================================
                    # TRADE SPACING
                    # =================================

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

                # =====================================
                # VOLATILITY BLOCK
                # =====================================

                if repeat_count >= 5:

                    signal = "VOLATILE MARKET"

                    confidence = 5

                    cooldown = 12

                time.sleep(0.3)

    except Exception as e:

        status = f"ERROR: {e}"
