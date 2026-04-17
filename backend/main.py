from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import sqlite3
import uvicorn
from contextlib import asynccontextmanager
import datetime
import os
import requests
from dotenv import load_dotenv

# Load env variables from root workspace directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, "..", ".env"))

OWM_API_KEY = os.getenv("OWM_API_KEY", "")
LATITUDE = os.getenv("LATITUDE", "")
LONGITUDE = os.getenv("LONGITUDE", "")

# Setup DB
def init_db():
    conn = sqlite3.connect("data.db")
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS telemetry
                      (id INTEGER PRIMARY KEY AUTOINCREMENT,
                       timestamp TEXT,
                       soil_moisture REAL,
                       temperature REAL,
                       humidity REAL,
                       ldr REAL,
                       rain_detected BOOLEAN,
                       pump_state TEXT)''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS config
                      (key TEXT PRIMARY KEY,
                       value TEXT)''')
    cursor.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('use_weather_api', 'false')")
    conn.commit()
    conn.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(lifespan=lifespan)
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: dict):
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except:
                pass # Handle dead sockets gracefully

manager = ConnectionManager()

class TelemetryData(BaseModel):
    soil_moisture: float
    temperature: float
    humidity: float
    ldr: float
    rain_detected: bool
    pump_state: str

class ConfigUpdate(BaseModel):
    use_weather_api: bool

# --- WebSocket Endpoint ---
@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # We don't expect messages from the client in this dashboard, so simply hold it open
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.post("/api/telemetry")
async def post_telemetry(data: TelemetryData):
    conn = sqlite3.connect("data.db")
    cursor = conn.cursor()
    timestamp = datetime.datetime.now().isoformat()
    cursor.execute('''INSERT INTO telemetry 
                      (timestamp, soil_moisture, temperature, humidity, ldr, rain_detected, pump_state)
                      VALUES (?, ?, ?, ?, ?, ?, ?)''', 
                   (timestamp, data.soil_moisture, data.temperature, data.humidity, data.ldr, data.rain_detected, data.pump_state))
    conn.commit()
    cursor.execute('SELECT id FROM telemetry ORDER BY id DESC LIMIT 1')
    new_id = cursor.fetchone()[0]
    conn.close()
    
    # Broadcast to all open WebSockets
    payload = {
        "id": new_id,
        "timestamp": timestamp,
        "soil_moisture": data.soil_moisture,
        "temperature": data.temperature,
        "humidity": data.humidity,
        "ldr": data.ldr,
        "rain_detected": data.rain_detected,
        "pump_state": data.pump_state
    }
    await manager.broadcast(payload)
    return {"status": "success"}

@app.get("/api/data")
async def get_data():
    conn = sqlite3.connect("data.db")
    cursor = conn.cursor()
    # Give back the last 30 for the initial chart load
    cursor.execute('SELECT * FROM telemetry ORDER BY id DESC LIMIT 30')
    rows = cursor.fetchall()
    conn.close()
    
    result = []
    for row in rows:
        result.append({
            "id": row[0],
            "timestamp": row[1],
            "soil_moisture": row[2],
            "temperature": row[3],
            "humidity": row[4],
            "ldr": row[5],
            "rain_detected": True if row[6] else False,
            "pump_state": row[7]
        })
    return {"data": result}

@app.get("/api/config")
async def get_config():
    conn = sqlite3.connect("data.db")
    cursor = conn.cursor()
    cursor.execute('SELECT value FROM config WHERE key = "use_weather_api"')
    row = cursor.fetchone()
    conn.close()
    return {"use_weather_api": row[0] == 'true' if row else False}

@app.post("/api/config")
async def update_config(config: ConfigUpdate):
    conn = sqlite3.connect("data.db")
    cursor = conn.cursor()
    val = 'true' if config.use_weather_api else 'false'
    cursor.execute('UPDATE config SET value = ? WHERE key = "use_weather_api"', (val,))
    conn.commit()
    conn.close()
    return {"status": "success", "use_weather_api": config.use_weather_api}

@app.get("/api/weather")
async def get_weather():
    if not OWM_API_KEY or not LATITUDE or not LONGITUDE:
        return {"error": "Missing config"}
        
    url = f"https://api.openweathermap.org/data/2.5/weather?lat={LATITUDE}&lon={LONGITUDE}&appid={OWM_API_KEY}&units=metric"
    try:
        res = requests.get(url, timeout=5)
        return res.json()
    except Exception as e:
        return {"error": str(e)}

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
