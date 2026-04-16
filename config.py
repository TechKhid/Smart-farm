def load_env():
    env_vars = {}
    try:
        with open(".env", "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" in line:
                    key, val = line.split("=", 1)
                    env_vars[key.strip()] = val.strip().strip("'\"")
    except Exception as e:
        print("Could not load .env file. Using defaults.", e)
    return env_vars

env = load_env()

WIFI_SSID = env.get("WIFI_SSID", "")
WIFI_PASSWORD = env.get("WIFI_PASSWORD", "")
OWM_API_KEY = env.get("OWM_API_KEY", "")
BACKEND_URL = env.get("BACKEND_URL", "http://192.168.1.100:8000")

# If omitted, IP address will be used to automatically detect location
LATITUDE = env.get("LATITUDE", None)
LONGITUDE = env.get("LONGITUDE", None)
