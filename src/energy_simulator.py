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

BLOCKBAX_API_TOKEN = os.getenv("BLOCKBAX_API_TOKEN")
BLOCKBAX_PROJECT_ID = os.getenv("BLOCKBAX_PROJECT_ID")
WEATHER_STATION_SUBJECT_TYPE_ID = os.getenv("WEATHER_STATION_SUBJECT_TYPE_ID")
WEATHERAPI_KEY = os.getenv("WEATHERAPI_KEY")
BLOCKBAX_WEATHER_INBOUND_URL = os.getenv("BLOCKBAX_WEATHER_INBOUND_URL")
PROPERTY_TYPE_ID = os.getenv("PROPERTY_TYPE_ID")
INVERTER_SUBJECT_TYPE_ID = os.getenv("INVERTER_SUBJECT_TYPE_ID")
TURBINE_SUBJECT_TYPE_ID = os.getenv("TURBINE_SUBJECT_TYPE_ID")

SENML_INBOUND_URL = os.getenv("BLOCKBAX_INVERTER_INBOUND_URL")
SENML_API_KEY = os.getenv("BLOCKBAX_API_TOKEN")
TURBINE_ENDPOINT_URL = os.getenv("TURBINE_ENDPOINT_URL")

def get_parks():
    url = f"https://api.blockbax.com/v1/projects/{BLOCKBAX_PROJECT_ID}/subjects"
    params = {
        "subjectTypeIds": WEATHER_STATION_SUBJECT_TYPE_ID
    }
    headers = {
        "Authorization": f"ApiKey {BLOCKBAX_API_TOKEN}",
        "Content-Type": "application/json"
    }
    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        parks = response.json()["result"]
        park_locations = {}

        for park in parks:
            lat, lon = None, None
            for prop in park.get("properties", []):
                if prop.get("typeId") == "617c9f18-2087-4994-86ac-0fbc56cd3e47":
                    loc = prop.get("location", {})
                    lat, lon = loc.get("lat"), loc.get("lon")
                    break
            park_locations[park["externalId"]] = {
                "id": park["id"],
                "parent_id": park.get("parentSubjectId"),
                "name": park["name"],
                "lat": lat,
                "lon": lon
            }
        return park_locations
    except requests.RequestException as e:
        logging.error(f"Error fetching subjects: {e}")
        return {}


# New function to fetch inverters by subject type
def get_inverters():
    """
    Fetch inverter subjects from Blockbax using the inverter subject type ID.
    Returns a dict mapping externalId to {id, parent_id}.
    """
    url = f"https://api.blockbax.com/v1/projects/{BLOCKBAX_PROJECT_ID}/subjects"
    params = {"subjectTypeIds": INVERTER_SUBJECT_TYPE_ID}
    headers = {
        "Authorization": f"ApiKey {BLOCKBAX_API_TOKEN}",
        "Content-Type": "application/json"
    }
    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        items = response.json().get("result", [])
        inverter_map = {}
        for inv in items:
            inverter_map[inv["externalId"]] = {
                "id": inv["id"],
                "parent_id": inv.get("parentSubjectId")
            }
        return inverter_map
    except requests.RequestException as e:
        logging.error(f"Error fetching inverters: {e}")
        return {}

def get_turbines():
    """
    Fetch turbine subjects from Blockbax using the turbine subject type ID.
    Returns a dict mapping externalId to {id, parent_id}.
    """
    url = f"https://api.blockbax.com/v1/projects/{BLOCKBAX_PROJECT_ID}/subjects"
    params = {"subjectTypeIds": TURBINE_SUBJECT_TYPE_ID}
    headers = {
        "Authorization": f"ApiKey {BLOCKBAX_API_TOKEN}",
        "Content-Type": "application/json"
    }
    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        response.raise_for_status()
        items = response.json().get("result", [])
        turbine_map = {}
        for turb in items:
            turbine_map[turb["externalId"]] = {
                "id": turb["id"],
                "parent_id": turb.get("parentSubjectId")
            }
        return turbine_map
    except requests.RequestException as e:
        logging.error(f"Error fetching turbines: {e}")
        return {}

def simulate_inverter_senml(external_id, ambient_temp, irradiance, max_kw=8.0):
    """
    Build a SenML entry for one inverter based on irradiance and ambient temp.
    """
    eta = random.uniform(0.95, 0.99)
    output_kw = round(max_kw * (irradiance / 1000) * eta, 2)
    dc_voltage = round(random.uniform(0.95, 1.05) * 600, 1)
    dc_current = round((output_kw * 1000) / dc_voltage, 2) if dc_voltage else 0
    temp = round(ambient_temp + (output_kw / max_kw) * 20, 1)
    status = "OFF" if irradiance == 0 else ("ERROR" if random.random() < 0.005 else "ON")

    return {
        "bn": external_id,
        "bt": int(time.time()),
        "e": [
            {"n": "inverter_output_power_kw", "u": "kW", "v": output_kw},
            {"n": "inverter_dc_voltage",   "u": "V",  "v": dc_voltage},
            {"n": "inverter_dc_current",   "u": "A",  "v": dc_current},
            {"n": "inverter_temperature",  "u": "Cel","v": temp},
            {"n": "inverter_status",       "vs": status}
        ]
    }

def simulate_turbine_senml(external_id, wind_speed, ambient_temp, rated_power_kw=3000):
    """
    Build a SenML entry for one wind turbine.
    Simulation based on Vestas V112-3.0 MW turbine:
    - cut-in ~3.5 m/s, rated ~12 m/s, cut-out ~25 m/s.
    """
    # Microclimate variation: small Gaussian noise (±0.2 m/s) for wind, ±0.5°C for temp
    wind_speed = max(0, wind_speed + random.gauss(0, 0.2))
    ambient_temp = ambient_temp + random.gauss(0, 0.5)

    # Scenario: overspeed shutdown if wind_speed > 25 m/s
    if wind_speed > 25:
        output_kw = 0.0
    # Cut-in / rated curve
    elif wind_speed < 3.5:
        output_kw = 0.0
    elif wind_speed < 12:
        output_kw = round((wind_speed - 3.5) / (12 - 3.5) * rated_power_kw, 2)
    else:
        output_kw = rated_power_kw

    # Rotor speed approx (max ~15 rpm at rated)
    rotor_speed = round(min(wind_speed / 12 * 15, 15), 2)

    # Pitch angle: 0° below rated, linearly to 15° at cut-out
    if wind_speed < 12:
        pitch = 0.0
    else:
        pitch = round((wind_speed - 12) / (25 - 12) * 15, 2)

    # Motor temperature: ambient + load-based rise (up to +40°C)
    temp = round(ambient_temp + (output_kw / rated_power_kw) * 40, 1)

    # Vibration: base 0.2 mm/s + load factor
    vibration = round(0.2 + (output_kw / rated_power_kw) * 0.5, 3)

    # Determine operating state
    if wind_speed > 25:
        state = "SHUTDOWN"
    elif wind_speed < 3.5:
        state = "OFF"
    elif random.random() < 0.005:
        state = "ERROR"
    else:
        state = "ON"

    # Compute theoretical output for curtailment calculation
    if wind_speed < 3.5 or wind_speed > 25:
        theoretical_output = 0.0
    elif wind_speed < 12:
        theoretical_output = round((wind_speed - 3.5) / (12 - 3.5) * rated_power_kw, 2)
    else:
        theoretical_output = rated_power_kw

    # Curtailment factor: fraction of available power not generated
    curtailment_factor = round((theoretical_output - output_kw) / theoretical_output, 3) if theoretical_output > 0 else 0.0

    # Operating hours: 0.25h per 15-minute interval when ON
    operating_hours = 0.25 if state == "ON" else 0.0

    return {
        "bn": external_id,
        "bt": int(time.time()),
        "e": [
            {"n": "turbine_power_output_kw", "u": "kW",    "v": output_kw},
            {"n": "turbine_wind_speed",      "u": "m/s",   "v": wind_speed},
            {"n": "turbine_rotor_speed",     "u": "rpm",   "v": rotor_speed},
            {"n": "turbine_pitch_angle",     "u": "deg",   "v": pitch},
            {"n": "turbine_motor_temp",      "u": "Cel",   "v": temp},
            {"n": "turbine_vibration",       "u": "mm/s",  "v": vibration},
            {"n": "turbine_status",          "vs": state},
            {"n": "turbine_hours",           "u": "h",     "v": operating_hours},
            {"n": "curtailment_factor",      "v": curtailment_factor}
        ]
    }

def get_weather_data(lat, lon):
    url = "https://api.weatherapi.com/v1/current.json"
    params = {
        "key": WEATHERAPI_KEY,
        "q": f"{lat},{lon}"
    }
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json().get("current", {})
        hour = datetime.now(timezone.utc).hour
        max_irradiance = 1000  # W/m² under clear sky at noon
        if 6 <= hour <= 20:
            sun_factor = max(0, -abs(hour - 13) + 7) / 7
        else:
            sun_factor = 0
        cloud_factor = (100 - data.get("cloud", 0)) / 100
        solar_irradiance = round(max_irradiance * sun_factor * cloud_factor, 2)
        condition = data.get("condition", {})
        icon_path = condition.get("icon", "")
        icon_url = None
        if icon_path:
            icon_url = "https:" + icon_path.replace("/64x64/", "/128x128/")
        return {
            "temperature": data.get("temp_c"),
            "wind_speed_mps": round(data.get("wind_kph", 0) / 3.6, 2),
            "cloud_coverage": data.get("cloud"),
            "solar_irradiance": solar_irradiance,
            "icon_url": icon_url
        }
    except requests.RequestException as e:
        logging.error(f"Error fetching weather data: {e}")
        return None

def send_weather_to_blockbax(external_id, weather):
    payload = {
        "subject": {"externalId": external_id},
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
    print(f"Payload for {external_id}:\n{json.dumps(payload, indent=2)}")
    headers = {
        "Authorization": f"ApiKey {BLOCKBAX_API_TOKEN}",
        "Content-Type": "application/json"
    }
    try:
        response = requests.post(BLOCKBAX_WEATHER_INBOUND_URL, json=payload, headers=headers, timeout=10)
        response.raise_for_status()
        logging.info(f"Sent data to Blockbax for {external_id}")
    except requests.RequestException as e:
        logging.error(f"Failed to send data for {external_id}: {e}")

def main():
    stations = get_parks()
    inverters = get_inverters()
    logging.info(f"Fetched {len(inverters)} inverter subjects")
    turbines = get_turbines()
    logging.info(f"Fetched {len(turbines)} turbine subjects")

    # Map station internal ID to its externalId for inverter-weather join
    station_id_to_external = {info["parent_id"]: ext_id for ext_id, info in stations.items()}

    payloads = []
    weather_map = {}
    for external_id, info in stations.items():
        lat, lon = info.get("lat"), info.get("lon")
        if lat is None or lon is None:
            logging.warning(f"Missing location for station {external_id}")
            continue
        weather = get_weather_data(lat, lon)
        if weather:
            entry = {
                "subject": {"externalId": external_id},
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
            payloads.append(entry)
            weather_map[external_id] = weather

    if payloads:
        headers = {
            "Authorization": f"ApiKey {BLOCKBAX_API_TOKEN}",
            "Content-Type": "application/json"
        }
        try:
            response = requests.post(BLOCKBAX_WEATHER_INBOUND_URL, json=payloads, headers=headers, timeout=10)
            response.raise_for_status()
            logging.info("Sent bulk weather data to Blockbax")
        except requests.RequestException as e:
            logging.error(f"Failed to send bulk weather data: {e}")

        # Patch a property for each station using the new property type
        logging.info(f"Patching property {PROPERTY_TYPE_ID} for each station")
        patch_headers = {
            "Authorization": f"ApiKey {BLOCKBAX_API_TOKEN}",
            "Content-Type": "application/json"
        }
        for external_id, info in stations.items():
            parent_id = info.get("parent_id")
            weather = weather_map.get(external_id)
            if not weather or not parent_id:
                continue
            # Patch the icon URL property on the parent subject
            value = weather.get("icon_url")
            if not value:
                continue
            patch_url = f"https://api.blockbax.com/v1/projects/{BLOCKBAX_PROJECT_ID}/subjects/{parent_id}/properties"
            patch_payload = {"values": {PROPERTY_TYPE_ID: {"text": value}}}
            try:
                resp = requests.patch(patch_url, json=patch_payload, headers=patch_headers, timeout=10)
                resp.raise_for_status()
                logging.info(f"Patched {external_id}: {resp.status_code}")
            except requests.RequestException as e:
                logging.error(f"Failed to patch {external_id}: {e}")


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

    # Helper to flatten a SenML list into preset conversion format
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

# Reminder: Please set the TURBINE_ENDPOINT_URL environment variable in your .env file if you want to use the additional endpoint.