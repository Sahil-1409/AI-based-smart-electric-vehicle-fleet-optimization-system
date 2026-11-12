
import serial
import requests
import time

PORT = "COM5"
API_URL = "http://127.0.0.1:8001/api/telemetry"
API_KEY = "demo-esp32-key"

print("Starting ESP32 GPS Bridge...")

with serial.Serial(PORT, 115200, timeout=2) as esp:
    print("ESP32 connected on", PORT)

    while True:
        line = esp.readline().decode(
            "utf-8", errors="ignore"
        ).strip()

        if not line.startswith("GPS,"):
            if line:
                print(line)
            continue

        try:
            _, lat, lon, speed = line.split(",")

            payload = {
                "vehicle_id": "EV-ESP32-01",
                "latitude": float(lat),
                "longitude": float(lon),
                "speed": float(speed)
            }

            response = requests.post(
                API_URL,
                json=payload,
                headers={"x-api-key": API_KEY},
                timeout=5
            )

            print(
                "Server Response:",
                response.status_code,
                response.text[:200]
            )

        except Exception as e:
            print("Error:", e)

        time.sleep(0.1)
