# VoltFleet Pro — Multi-page EV Fleet Management

## Run on Windows

1. Install Python 3.10+.
2. Extract ZIP; open the `Smart_EV_Fleet` folder in VS Code.
3. Run `python -m pip install -r requirements.txt`.
4. Double-click `start_windows.bat`, or run `python -m uvicorn main:app --host 0.0.0.0 --port 8000` in that directory.
5. Visit **http://localhost:8000**. Use the left menu to open separate Overview, Tracking, Fleet, Task Dispatch, Route Planner, Charging Stations, Rescue, Alerts and Settings pages.
6. Press **Start demo** to simulate moving demo EVs. SQLite records persist in `data/fleet.db`.

## Google Maps Platform (optional)

A real Google key is **not shipped**; Google Cloud requires your own API credentials, enabled services, billing and usage quotas. For a new Cloud project, use **Maps JavaScript API**, **Places API (New)**, and **Routes API** (not legacy Directions API).

1. In [Google Cloud Console](https://console.cloud.google.com/apis/library) create a project, enable billing and those three APIs.
2. Create **three restricted API keys**: browser key restricted by HTTP referrer and Maps JavaScript API; server key restricted to Places API (New); server key restricted to Routes API. For server keys restrict to trusted IP addresses where practical. Avoid making private keys available on the frontend.
3. Copy `.env.example` to `.env` and fill in variables (Windows `start_windows.bat` reads `.env`). You can also set environment variables explicitly.
   - `GOOGLE_MAPS_BROWSER_KEY=...` draws Google Maps in the UI.
   - `GOOGLE_PLACES_SERVER_KEY=...` searches actual charging stations near selected vehicle (Google Places Nearby Search New).
   - `GOOGLE_ROUTES_SERVER_KEY=...` calculates driving route geometry and road time via Routes API.
4. Restart app, open **API & Settings** and check statuses. If using `localhost`, allow HTTP referrers `http://localhost:8000/*` and `http://127.0.0.1:8000/*` on the browser key.

Without keys, the app works with OpenStreetMap tiles and a publicly provided demo OSRM road-routing service when reachable. The charger page **does not invent or use fabricated stations**; it clearly indicates the Places key is missing.

Google Maps Platform may charge fees; monitor costs/quotas. Places list shows found stations, not actual available connectors or live occupancy. Google Maps terms and attribution apply to Places data.

## ESP32 telemetry integration (later)

`POST http://YOUR_LAPTOP_IP:8000/api/telemetry` with header `x-api-key: demo-esp32-key` (change `FLEET_API_KEY` before network deployment). Example:

```json
{"vehicle_id":"EV-ESP32-01","latitude":30.901,"longitude":75.8573,"speed":18.5}
```

Optional `battery` must come from genuine EV BMS measurements. GPS module alone cannot measure EV SOC. API adds hardware vehicle if needed and updates its GPS coordinates; dashboard polls every 5 seconds. The laptop and ESP32 must be reachable over the same network; production needs authenticated HTTPS and hardened deployment. Demo GPS tracks are simulated, not live vehicles.

## Features

- Multi-page responsive dark glass-style dashboard with sidebar navigation
- Fleet monitoring with vehicles, simulated SOC/speed, fresh GPS and battery alerts
- Delivery task creation, auto-nearest available EV assignment, completion
- Route planner with Google Routes API when configured; OSRM demo fallback
- Selected vehicle charging search with Google Places API New and Google Maps links
- Breakdown reporting, task reassignment to nearest eligible available fleet EV
- Nearby available fleet vehicle list, event history, hardware telemetry API

## Known limitations

- No real-time charger occupancy/connector verification, reservations or dispatch/SOS call service.
- Auto-reassignment uses **straight-line distance** and minimum battery rules, not road-time, load, real SoC, energy feasibility, charger plug compatibility or advanced ML optimization.
- Demo data is centered on sample sites in Ludhiana and may be replaced using application data/API.
- Intended as a **college prototype**. Production use requires secure auth for all endpoints, robust GPS freshness/validation, auditability, and BMS integrations.
