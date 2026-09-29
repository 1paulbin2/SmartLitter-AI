import json
import os
import time
from datetime import datetime

INCIDENT_FILE = "incidents.json"


def load_incidents():
    if not os.path.exists(INCIDENT_FILE):
        return []

    try:
        with open(INCIDENT_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)

        return data if isinstance(data, list) else []

    except (json.JSONDecodeError, OSError):
        return []


def save_incidents(incidents):
    with open(
        INCIDENT_FILE,
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            incidents,
            file,
            indent=4
        )


def create_demo_incident():
    incidents = load_incidents()

    incident_number = len(incidents) + 1

    # Rotate locations to demonstrate hotspots
    locations = [
        {
            "camera": "Camera 01",
            "location": "VJEC Main Gate",
            "latitude": 12.0657,
            "longitude": 75.3879
        },
        {
            "camera": "Camera 02",
            "location": "VJEC Bus Stop",
            "latitude": 12.0665,
            "longitude": 75.3890
        },
        {
            "camera": "Camera 03",
            "location": "VJEC Parking Area",
            "latitude": 12.0649,
            "longitude": 75.3868
        }
    ]

    location = locations[
        (incident_number - 1) % len(locations)
    ]

    incident = {
        "camera": location["camera"],
        "location": location["location"],
        "latitude": location["latitude"],
        "longitude": location["longitude"],
        "time": datetime.now().strftime(
            "%Y-%m-%d %H:%M:%S"
        ),
        "waste": "Plastic Bottle",
        "image": "",
        "status": "Pending Verification",
        "source": "DEMO"
    }

    incidents.append(incident)

    save_incidents(incidents)

    print()
    print("======================================")
    print("DEMO INCIDENT CREATED")
    print("======================================")
    print(f"Camera:   {incident['camera']}")
    print(f"Location: {incident['location']}")
    print(f"Waste:    {incident['waste']}")
    print(f"Time:     {incident['time']}")
    print("Status:   Pending Verification")
    print("======================================")
    print()


if __name__ == "__main__":
    create_demo_incident()