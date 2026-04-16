from machine import Pin, ADC
import time
import dht

# --- Pin setup ---
soil_adc    = ADC(Pin(26))       # Analog soil moisture
ldr_adc     = ADC(Pin(27))       # Analog LDR sensor (Light)
rain1       = Pin(14, Pin.IN, Pin.PULL_UP)  # Rain sensor 1 (DO)
relay       = Pin(16, Pin.OUT)
dht_sensor  = dht.DHT11(Pin(15)) # DHT11 Temp/Humidity sensor

# --- Config ---
SOIL_DRY_THRESHOLD = 10000   # ADC value above this = dry (0–65535)
CHECK_INTERVAL     = 5      # Seconds between checks
RELAY_ACTIVE_LOW   = True    # Set False if your relay triggers on HIGH

def pump_on():
    relay.value(0 if RELAY_ACTIVE_LOW else 1)
    print("Pump: ON")

def pump_off():
    relay.value(1 if RELAY_ACTIVE_LOW else 0)
    print("Pump: OFF")

def is_raining():
    # LOW signal = rain detected (typical DO behaviour)
    r1 = rain1.value() == 0
    return r1 

def soil_is_dry():
    reading = soil_adc.read_u16()
    print(f"Soil ADC: {reading}")
    return reading > SOIL_DRY_THRESHOLD

# --- Main loop ---
pump_off()  # Safe state on boot

while True:
    if is_raining():
        print("Rain detected — overriding, pump stays OFF")
    #     pump_off()
    # elif soil_is_dry():
    #     print("Soil dry, no rain — pump ON")
    #     pump_on()
    # else:
    #     print("Soil moist, pump OFF")
    #     pump_off()
    reading = soil_adc.read_u16()
    print(f"Soil ADC: {reading}")
    
    ldr_reading = ldr_adc.read_u16()
    print(f"LDR ADC: {ldr_reading}")
    
    try:
        
        dht_sensor.measure()
        print(f"DHT11 - Temp: {dht_sensor.temperature()}C, Hum: {dht_sensor.humidity()}%")
    except Exception as e:
        print("Failed to read DHT11 sensor")
        
    relay.value(1)
    print("Pump: OFF")
    time.sleep(CHECK_INTERVAL)
    relay.value(0)
    print("Pump: ON")
    time.sleep(CHECK_INTERVAL)