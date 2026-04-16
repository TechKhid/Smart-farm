from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import sqlite3
import uvicorn
from contextlib import asynccontextmanager
import datetime
import os

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
    # Default config
    cursor.execute("INSERT OR IGNORE INTO config (key, value) VALUES ('use_weather_api', 'false')")
    conn.commit()
    conn.close()

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield

app = FastAPI(lifespan=lifespan)

# Get the absolute path to the templates directory
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATES_DIR = os.path.join(BASE_DIR, "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

class TelemetryData(BaseModel):
    soil_moisture: float
    temperature: float
    humidity: float
    ldr: float
    rain_detected: bool
    pump_state: str

class ConfigUpdate(BaseModel):
    use_weather_api: bool

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
    conn.close()
    return {"status": "success"}

@app.get("/api/data")
async def get_data():
    conn = sqlite3.connect("data.db")
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM telemetry ORDER BY id DESC LIMIT 20')
    rows = cursor.fetchall()
    conn.close()
    
    # Format for JSON response
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
    use_weather_api = row[0] == 'true' if row else False
    return {"use_weather_api": use_weather_api}

@app.post("/api/config")
async def update_config(config: ConfigUpdate):
    conn = sqlite3.connect("data.db")
    cursor = conn.cursor()
    val = 'true' if config.use_weather_api else 'false'
    cursor.execute('UPDATE config SET value = ? WHERE key = "use_weather_api"', (val,))
    conn.commit()
    conn.close()
    return {"status": "success", "use_weather_api": config.use_weather_api}

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
