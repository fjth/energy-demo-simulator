import os
import requests
from dotenv import load_dotenv
from datetime import datetime, timezone
import logging
import json
import time
import random

load_dotenv()

logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s:%(message)s')

# Environment variables
BLOCKBAX_API_TOKEN               = os.getenv("BLOCKBAX_API_TOKEN")
BLOCKBAX_PROJECT_ID              = os.getenv("BLOCKBAX_PROJECT_ID")
WEATHER_STATION_SUBJECT_TYPE_ID  = os.getenv("WEATHER_STATION_SUBJECT_TYPE_ID")
WEATHERAPI_KEY                   = os.getenv("WEATHERAPI_KEY")
BLOCKBAX_WEATHER_INBOUND_URL     = os.getenv("BLOCKBAX_WEATHER_INBOUND_URL")
PROPERTY_TYPE_ID                 = os.getenv("PROPERTY_TYPE_ID")
INVERTER_SUBJECT_TYPE_ID         = os.getenv("INVERTER_SUBJECT_TYPE_ID")
TURBINE_SUBJECT_TYPE_ID          = os.getenv("TURBINE_SUBJECT_TYPE_ID")
SENML_INBOUND_URL                = os.getenv("BLOCKBAX_INVERTER_INBOUND_URL")
SENML_API_KEY                    = os.getenv("BLOCKBAX_API_TOKEN")
TURBINE_ENDPOINT_URL             = os.getenv("TURBINE_ENDPOINT_URL")
POWER_OUTPUT_AVG_PROPERTY_TYPE_ID= os.getenv("POWER_OUTPUT_AVG_PROPERTY_TYPE_ID")

def get_parks():
    url = f"https://api.blockbax.com/v1/projects/{BLOCKBAX_PROJECT_ID}/subjects"
    params = {"subjectTypeIds": WEATHER_STATION_SUBJECT_TYPE_ID}
    headers = {"Authorization": f"ApiKey {BLOCKBAX_API_TOKEN}", "Content-Type": "application/json"}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        parks = resp.json().get("result", [])
        parks_map = {}
        for p in parks:
            lat = lon = None
            for prop in p.get("properties", []):
                if prop.get("typeId") == "617c9f18-2087-4994-86ac-0fbc56cd3e47":
                    loc = prop.get("location", {})
                    lat, lon = loc.get("lat"), loc.get("lon")
                    break
            parks_map[p["externalId"]] = {
                "id": p["id"],
                "parent_id": p.get("parentSubjectId"),
                "name": p["name"],
                "lat": lat,
                "lon": lon
            }
        return parks_map
    except requests.RequestException as e:
        logging.error(f"Error fetching parks: {e}")
        return {}

def get_inverters():
    url = f"https://api.blockbax.com/v1/projects/{BLOCKBAX_PROJECT_ID}/subjects"
    params = {"subjectTypeIds": INVERTER_SUBJECT_TYPE_ID}
    headers = {"Authorization": f"ApiKey {BLOCKBAX_API_TOKEN}", "Content-Type": "application/json"}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        items = resp.json().get("result", [])
        inv_map = {
            item["externalId"]: {
                "id": item["id"],
                "parent_id": item.get("parentSubjectId")
            } for item in items
        }
        return inv_map
    except requests.RequestException as e:
        logging.error(f"Error fetching inverters: {e}")
        return {}

def get_turbines():
    url = f"https://api.blockbax.com/v1/projects/{BLOCKBAX_PROJECT_ID}/subjects"
    params = {"subjectTypeIds": TURBINE_SUBJECT_TYPE_ID}
    headers = {"Authorization": f"ApiKey {BLOCKBAX_API_TOKEN}", "Content-Type": "application/json"}
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        items = resp.json().get("result", [])
        return {
            t["externalId"]: {
                "id": t["id"],
                "parent_id": t.get("parentSubjectId")
            } for t in items
        }
    except requests.RequestException as e:
        logging.error(f"Error fetching turbines: {e}")
        return {}

def simulate_inverter_senml(external_id, ambient_temp, irradiance, max_kw=8.0):
    dc_power_kw = round(max_kw * (irradiance / 1000) * random.uniform(0.98, 1.02), 2)
    dc_voltage  = round(random.uniform(0.95, 1.05) * 600, 1)
    dc_current  = round((dc_power_kw * 1000) / dc_voltage, 2) if dc_voltage else 0
    eta         = random.uniform(0.94, 0.98)
    output_kw   = round(dc_power_kw * eta, 2)
    # Performance Ratio (PR) = AC output / (rated capacity * (irradiance/1000)), as a percentage
    performance_ratio = 0.0
    if irradiance and irradiance > 0:
        # Calculate as a percentage
        performance_ratio = round(
            (output_kw / (max_kw * (irradiance / 1000))) * 100,
            2
        )
    temp        = round(ambient_temp + (output_kw / max_kw) * 20, 1)
    status      = "OFF" if irradiance == 0 else ("ERROR" if random.random() < 0.005 else "ON")

    return {
        "bn": external_id,
        "bt": int(time.time()),
        "e": [
            {"n": "inverter_output_power_kw", "u": "kW", "v": output_kw},
            {"n": "inverter_dc_voltage",      "u": "V",  "v": dc_voltage},
            {"n": "inverter_dc_current",      "u": "A",  "v": dc_current},
            {"n": "inverter_temperature",     "u": "Cel","v": temp},
            {"n": "inverter_status",          "vs": status},
            {"n": "performance_ratio", "u": "%", "v": performance_ratio}
        ]
    }

def simulate_turbine_senml(external_id, wind_speed, ambient_temp, rated_power_kw=3000):
    wind_speed  = max(0, wind_speed + random.gauss(0, 0.2))
    ambient_temp= ambient_temp + random.gauss(0, 0.5)

    # power curve
    if wind_speed > 25 or wind_speed < 3.5:
        output_kw = 0.0
    elif wind_speed < 12:
        output_kw = round((wind_speed - 3.5) / (12 - 3.5) * rated_power_kw, 2)
    else:
        output_kw = rated_power_kw

    rotor_speed = round(min(wind_speed / 12 * 15, 15), 2)
    pitch       = 0.0 if wind_speed < 12 else round((wind_speed - 12) / (25 - 12) * 15, 2)
    temp        = round(ambient_temp + (output_kw / rated_power_kw) * 40, 1)
    vibration   = round(0.2 + (output_kw / rated_power_kw) * 0.5, 3)

    if wind_speed > 25:
        state = "SHUTDOWN"
    elif wind_speed < 3.5:
        state = "OFF"
    elif random.random() < 0.005:
        state = "ERROR"
    else:
        state = "ON"

    # curtailment
    if wind_speed < 3.5 or wind_speed > 25:
        theoretical = 0.0
    elif wind_speed < 12:
        theoretical = round((wind_speed - 3.5) / (12 - 3.5) * rated_power_kw, 2)
    else:
        theoretical = rated_power_kw

    curtailment = round((theoretical - output_kw) / theoretical, 3) if theoretical > 0 else 0.0
    hours       = 0.25 if state == "ON" else 0.0

    return {
        "bn": external_id,
        "bt": int(time.time()),
        "e": [
            {"n": "turbine_power_output_kw", "u": "kW",  "v": output_kw},
            {"n": "turbine_wind_speed",      "u": "m/s","v": wind_speed},
            {"n": "turbine_rotor_speed",     "u": "rpm","v": rotor_speed},
            {"n": "turbine_pitch_angle",     "u": "deg","v": pitch},
            {"n": "turbine_motor_temp",      "u": "Cel","v": temp},
            {"n": "turbine_vibration",       "u": "mm/s","v": vibration},
            {"n": "turbine_status",          "vs": state},
            {"n": "turbine_hours",           "u": "h",  "v": hours},
            {"n": "curtailment_factor",      "v": curtailment}
        ]
    }

def get_weather_data(lat, lon):
    url    = "https://api.weatherapi.com/v1/current.json"
    params = {"key": WEATHERAPI_KEY, "q": f"{lat},{lon}"}
    try:
        r = requests.get(url, params=params, timeout=10)
        r.raise_for_status()
        c = r.json().get("current", {})
        hour = datetime.now(timezone.utc).hour
        sun = max(0, -abs(hour - 13) + 7) / 7 if 6 <= hour <= 20 else 0
        cloud = (100 - c.get("cloud", 0)) / 100
        irradiance = round(1000 * sun * cloud, 2)
        icon = c.get("condition", {}).get("icon","").replace("/64x64/","/128x128/")
        return {
            "temperature": c.get("temp_c"),
            "wind_speed_mps": round(c.get("wind_kph",0)/3.6,2),
            "cloud_coverage": c.get("cloud"),
            "solar_irradiance": irradiance,
            "icon_url": "https:"+icon if icon else None
        }
    except:
        logging.error("Error fetching weather")
        return None

def main():
    stations  = get_parks()
    inverters = get_inverters()
    logging.info(f"Fetched {len(inverters)} inverter subjects")
    turbines  = get_turbines()
    logging.info(f"Fetched {len(turbines)} turbine subjects")

    station_id_to_external = {info["parent_id"]: ext for ext,info in stations.items()}

    weather_map = {}
    for ext_id, info in stations.items():
        if info["lat"] is not None and info["lon"] is not None:
            weather = get_weather_data(info["lat"], info["lon"])
            if weather:
                weather_map[ext_id] = weather

    # Send weather measurements and patch icons
    weather_payloads = []
    for ext_id, weather in weather_map.items():
        entry = {
            "subject": {"externalId": ext_id},
            "measurements": [
                {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "fields": {
                        "temperature": weather["temperature"],
                        "wind_speed_mps": weather["wind_speed_mps"],
                        "cloud_coverage": weather["cloud_coverage"],
                        "solar_irradiance": weather["solar_irradiance"]
                    }
                }
            ]
        }
        weather_payloads.append(entry)

    if weather_payloads:
        headers_w = {
            "Authorization": f"ApiKey {BLOCKBAX_API_TOKEN}",
            "Content-Type": "application/json"
        }
        try:
            resp = requests.post(BLOCKBAX_WEATHER_INBOUND_URL, json=weather_payloads, headers=headers_w, timeout=10)
            resp.raise_for_status()
            logging.info("Sent weather data to Blockbax")
        except requests.RequestException as e:
            logging.error(f"Failed to send weather data: {e}")

        # Patch weather icon property per park
        patch_h = {
            "Authorization": f"ApiKey {BLOCKBAX_API_TOKEN}",
            "Content-Type": "application/json"
        }
        for ext_id, info in stations.items():
            parent = info.get("parent_id")
            weather = weather_map.get(ext_id)
            if not parent or not weather or not weather.get("icon_url"):
                continue
            url = f"https://api.blockbax.com/v1/projects/{BLOCKBAX_PROJECT_ID}/subjects/{parent}/properties"
            payload = {"values": {PROPERTY_TYPE_ID: {"text": weather["icon_url"]}}}
            try:
                p = requests.patch(url, json=payload, headers=patch_h, timeout=10)
                p.raise_for_status()
                logging.info(f"Patched icon for {ext_id}")
            except requests.RequestException as e:
                logging.error(f"Failed to patch icon for {ext_id}: {e}")

    # Build separate SenML payloads for inverters and turbines
    inverter_senml = []
    for inv_ext_id, inv_info in inverters.items():
        parent_internal = inv_info.get("parent_id")
        station_ext = station_id_to_external.get(parent_internal)
        weather = weather_map.get(station_ext)
        if not weather:
            logging.warning(f"No weather data for inverter {inv_ext_id}")
            continue
        inverter_senml.append(
            simulate_inverter_senml(
                inv_ext_id,
                weather["temperature"],
                weather["solar_irradiance"]
            )
        )

    turbine_senml = []
    for turb_ext_id, turb_info in turbines.items():
        parent_internal = turb_info.get("parent_id")
        station_ext = station_id_to_external.get(parent_internal)
        weather = weather_map.get(station_ext)
        if not weather:
            logging.warning(f"No weather data for turbine {turb_ext_id}")
            continue
        turbine_senml.append(
            simulate_turbine_senml(
                turb_ext_id,
                weather["wind_speed_mps"],
                weather["temperature"]
            )
        )

    # --- NEW: patch average BEFORE sending measurements ---
    logging.info("Patching average power output per park")
    headers_avg = {
        "Authorization": f"ApiKey {BLOCKBAX_API_TOKEN}",
        "Content-Type": "application/json"
    }
    power_by_parent = {}
    for rec in inverter_senml:
        parent = inverters[rec["bn"]]["parent_id"]
        for e in rec["e"]:
            if e["n"]=="inverter_output_power_kw":
                power_by_parent.setdefault(parent,[]).append(e["v"])
                break
    for rec in turbine_senml:
        parent = turbines[rec["bn"]]["parent_id"]
        for e in rec["e"]:
            if e["n"]=="turbine_power_output_kw":
                power_by_parent.setdefault(parent,[]).append(e["v"])
                break
    for parent, vals in power_by_parent.items():
        avg = round(sum(vals)/len(vals),2)
        url = f"https://api.blockbax.com/v1/projects/{BLOCKBAX_PROJECT_ID}/subjects/{parent}/properties"
        payload = {"values": {POWER_OUTPUT_AVG_PROPERTY_TYPE_ID: {"number": avg}}}
        try:
            r = requests.patch(url, json=payload, headers=headers_avg, timeout=10)
            r.raise_for_status()
            logging.info(f"Patched avg power for {parent}: {avg}")
        except:
            logging.error(f"Failed to patch avg power for {parent}")

    # Helper to flatten a SenML list into the preset conversion format
    def flatten_senml_list(senml_list):
        flat = []
        for rec in senml_list:
            bn = rec.get("bn")
            bt = rec.get("bt")
            flat.append({"bn": bn})
            for e in rec.get("e", []):
                elem = {"n": e.get("n")}
                if "v" in e:
                    elem["v"] = e["v"]
                if "vs" in e:
                    elem["vs"] = e["vs"]
                if "vb" in e:
                    elem["vb"] = e["vb"]
                if "vd" in e:
                    elem["vd"] = e["vd"]
                elem["t"] = int(bt)
                flat.append(elem)
        return flat

    # Send inverters to the inverter endpoint
    if inverter_senml:
        flat_inverter = flatten_senml_list(inverter_senml)
        headers_inv = {
            "Authorization": f"ApiKey {SENML_API_KEY}",
            "Content-Type": "application/senml+json"
        }
        try:
            resp = requests.post(SENML_INBOUND_URL, json=flat_inverter, headers=headers_inv, timeout=10)
            resp.raise_for_status()
            logging.info(f"Sent inverter SenML payload with {len(flat_inverter)} entries")
        except requests.RequestException as e:
            logging.error(f"Failed to send inverter SenML payload: {e}")

    # Send turbines to the turbine endpoint
    if turbine_senml:
        flat_turbine = flatten_senml_list(turbine_senml)
        headers_turb = {
            "Authorization": f"ApiKey {BLOCKBAX_API_TOKEN}",
            "Content-Type": "application/senml+json"
        }
        try:
            resp2 = requests.post(TURBINE_ENDPOINT_URL, json=flat_turbine, headers=headers_turb, timeout=10)
            resp2.raise_for_status()
            logging.info(f"Sent turbine SenML payload with {len(flat_turbine)} entries")
        except requests.RequestException as e:
            logging.error(f"Failed to send turbine SenML payload: {e}")

if __name__ == "__main__":
    main()