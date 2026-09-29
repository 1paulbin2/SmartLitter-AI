import json
import os
import sys
import time

STATUS_FILE = "camera_status.json"

def load_status():
    if not os.path.exists(STATUS_FILE):
        return {}

    try:
        with open(STATUS_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
        
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_status(data):
    with open(STATUS_FILE, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4)

def heartbeat(camera_id):
    cameras = load_status()

    cameras[camera_id] = {
        "last_seen": time.time(),
        "status": "ONLINE"
    }

    save_status(cameras)
    print(f"Heartbeat sent: {camera_id}")

if __name__ == "__main__":
    camera_id = "Camera 01"

    # Allow passing a custom camera ID via command line arguments
    if len(sys.argv) > 1:
        camera_id = sys.argv[1]

    heartbeat(camera_id)