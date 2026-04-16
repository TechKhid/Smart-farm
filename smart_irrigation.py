import network
import urequests
import time
import dht
import machine
from machine import Pin, ADC
import config
import json

# --- PIN DEFINITIONS ---
soil_adc = ADC(Pin(26))       # Soil moisture
ldr_adc = ADC(Pin(27))        # LDR light sensor
rain1 = Pin(14, Pin.IN, Pin.PULL_UP) # Rain digital
relay = Pin(16, Pin.OUT)      # Pump relay
dht_sensor = dht.DHT11(Pin(15)) # Temp/Hum

# --- CONSTANTS & THRESHOLDS ---
SOIL_DRY_LIMIT = 40000        # Example ADC value: higher is drier, turn ON pump
SOIL_MOIST_LIMIT = 25000      # Turn OFF pump
HEAT_OVERRIDE_TEMP = 35       # Celsius
LDR_NIGHT_THRESHOLD = 50000   # Higher = darker
RELAY_ACTIVE_LOW = True

# --- GLOBAL STATE ---
pump_state_str = "OFF"
use_weather_api = False
last_watered = 0
COOLDOWN_SEC = 300 # 5 minutes cooldown after watering
global_lat = config.LATITUDE
global_lon = config.LONGITUDE

# --- WIFI CONNECT ---
def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    if not wlan.isconnected():
        print(f"Connecting to network {config.WIFI_SSID}...")
        wlan.connect(config.WIFI_SSID, config.WIFI_PASSWORD)
        while not wlan.isconnected():
            time.sleep(1)
            print(".", end="")
    print("\nConnected to WiFi!", wlan.ifconfig()[0])
    return wlan

# --- PUMP CONTROL ---
def set_pump(state, reason=""):
    global pump_state_str
    if state == "ON":
        relay.value(0 if RELAY_ACTIVE_LOW else 1)
        pump_state_str = f"ON ({reason})"
        print(f"Pump is ON. Reason: {reason}")
    else:
        relay.value(1 if RELAY_ACTIVE_LOW else 0)
        pump_state_str = f"OFF ({reason})"
        print(f"Pump is OFF. Reason: {reason}")

def water_burst():
    set_pump("ON", "Short Burst")
    time.sleep(5)
    set_pump("OFF", "Cooldown")
    global last_watered
    last_watered = time.time()

def water_full():
    set_pump("ON", "Full Water")
    time.sleep(15)
    set_pump("OFF", "Cooldown")
    global last_watered
    last_watered = time.time()

# --- BACKEND COMMS ---
def sync_config():
    global use_weather_api
    try:
        res = urequests.get(f"{config.BACKEND_URL}/api/config", timeout=5)
        data = res.json()
        use_weather_api = data.get("use_weather_api", False)
        res.close()
    except Exception as e:
        pass # Ignore transient errors silently to avoid spam

def push_telemetry(soil, temp, hum, ldr, rain_det):
    try:
        payload = {
            "soil_moisture": float(soil),
            "temperature": float(temp),
            "humidity": float(hum),
            "ldr": float(ldr),
            "rain_detected": bool(rain_det),
            "pump_state": pump_state_str
        }
        res = urequests.post(f"{config.BACKEND_URL}/api/telemetry", json=payload, timeout=5)
        res.close()
    except Exception as e:
        print("Failed to push telemetry", e)

# --- WEATHER API ---
def check_weather_api():
    # Returns True if raining currently or heavily forecasted soon
    if not use_weather_api:
        return False
        
    print("Querying OpenWeatherMap...")
    
    if not global_lat or not global_lon:
        print("Location unknown, skipping weather API.")
        return False
        
    url = f"https://api.openweathermap.org/data/2.5/weather?lat={global_lat}&lon={global_lon}&appid={config.OWM_API_KEY}"
    try:
        res = urequests.get(url, timeout=5)
        data = res.json()
        res.close()
        
        weather_main = data.get("weather", [{}])[0].get("main", "")
        print(f"OWM reports: {weather_main}")
        if weather_main.lower() in ["rain", "drizzle", "thunderstorm", "snow"]:
            return True
            
        return False
    except Exception as e:
        print("Failed OWM fetch", e)
        return False

def get_location_by_ip():
    try:
        print("Detecting location via IP...")
        res = urequests.get("http://ip-api.com/json/", timeout=5)
        data = res.json()
        res.close()
        if data.get("status") == "success":
            lat = data.get("lat")
            lon = data.get("lon")
            print(f"Location detected: {data.get('city')}, {data.get('country')} (Lat: {lat}, Lon: {lon})")
            return lat, lon
    except Exception as e:
        print("Failed to get location by IP:", e)
    return None, None

# --- MAIN LOGIC ---
def main():
    connect_wifi()
    set_pump("OFF", "Boot")
    
    global global_lat, global_lon
    if not global_lat or not global_lon:
        global_lat, global_lon = get_location_by_ip()
    
    while True:
        try:
            # Sync dashboard config toggle
            sync_config()
            
            # Read Sensors
            soil_raw = soil_adc.read_u16()
            ldr_raw = ldr_adc.read_u16()
            rain_det_phys = (rain1.value() == 0) # LOW is wet
            
            # DHT11 Read (can be finicky)
            temp, hum = -99, -99
            try:
                dht_sensor.measure()
                temp = dht_sensor.temperature()
                hum = dht_sensor.humidity()
            except Exception as e:
                pass
            
            print(f"---\nSoil: {soil_raw}, Temp: {temp}C, LDR: {ldr_raw}, Rain(P): {rain_det_phys}, OWMToggle: {use_weather_api}")
            
            # Push Telemetry (do inside try block so failure doesn't crash main loop)
            push_telemetry(soil_raw, temp, hum, ldr_raw, rain_det_phys)
            
            # Cooldown logic enforcement
            time_since_watered = time.time() - last_watered
            if last_watered > 0 and time_since_watered < COOLDOWN_SEC:
                print(f"In cooldown. {COOLDOWN_SEC - time_since_watered}s remaining.")
                time.sleep(10)
                continue
                
            # PRIORITY 1: RAIN OVERRIDE (WITH API VERIFICATION)
            is_raining = rain_det_phys
            if is_raining and use_weather_api:
                print("Physical sensor detects rain. Verifying with OWM API...")
                api_rain = check_weather_api()
                if not api_rain:
                    print("API denies rain. Could be a false positive (dew). Evaluating further.")
                    is_raining = False # Override the physical sensor
            
            if is_raining:
                set_pump("OFF", "Rain Override")
            else:
                # PRIORITY 2: HYSTERESIS & HYDRATION
                if soil_raw > SOIL_DRY_LIMIT:
                    # Soil is very dry, check conditions for how much to water
                    if temp != -99 and temp > HEAT_OVERRIDE_TEMP:
                        print("Extreme heat override. Watering burst to avoid boiling roots/evaporation.")
                        water_burst()
                    elif ldr_raw > LDR_NIGHT_THRESHOLD:
                        print("Night time watering limits. Short burst to prevent fungus.")
                        water_burst()
                    else:
                        print("Optimal conditions. Full watering cycle.")
                        water_full()
                        
                elif soil_raw < SOIL_MOIST_LIMIT:
                    set_pump("OFF", "Adequately Moist")
                else:
                    print("Soil moisture in hysteresis deadband. Holding state.")
            
        except Exception as e:
            print("Main loop encountered error:", e)
            
        time.sleep(10) # Standard evaluation tick

if __name__ == "__main__":
    main()
