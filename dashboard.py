from flask import (
    Flask,
    render_template_string,
    send_from_directory,
    jsonify,
    request,
    session,
    redirect,
    url_for,
)
import json
import os
import time
from datetime import datetime


app = Flask(__name__)
app.secret_key = "smart-littering-demo-secret-key"

INCIDENT_FILE = "incidents.json"
EVIDENCE_FOLDER = "evidence"
CAMERA_FILE = "cameras.json"
CAMERA_STATUS_FILE = "camera_status.json"

os.makedirs(EVIDENCE_FOLDER, exist_ok=True)


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def load_json_file(path, default):
    if not os.path.exists(path):
        return default

    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except (OSError, json.JSONDecodeError):
        return default


def save_json_file(path, data):
    with open(path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=4)


def load_incidents():
    incidents = load_json_file(INCIDENT_FILE, [])
    if not isinstance(incidents, list):
        return []

    changed = False

    for index, incident in enumerate(incidents):
        if not isinstance(incident, dict):
            continue

        if not incident.get("id"):
            incident["id"] = f"LEGACY-{index + 1}"
            changed = True

        if not incident.get("status"):
            incident["status"] = "Pending Verification"
            changed = True

    if changed:
        save_json_file(INCIDENT_FILE, incidents)

    return incidents


def save_incidents(incidents):
    save_json_file(INCIDENT_FILE, incidents)


# ============================================================
# LOGIN PAGE
# ============================================================

LOGIN_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>Authority Login</title>
    <style>
        body {
            margin: 0;
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            background: #f3f4f6;
            font-family: Arial, sans-serif;
        }
        .login-box {
            width: 360px;
            padding: 30px;
            background: white;
            border-radius: 14px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.12);
        }
        h1 { margin-top: 0; }
        input {
            width: 100%;
            padding: 12px;
            margin: 8px 0;
            border: 1px solid #ccc;
            border-radius: 7px;
            box-sizing: border-box;
        }
        button {
            width: 100%;
            padding: 12px;
            margin-top: 10px;
            border: none;
            border-radius: 7px;
            background: #111827;
            color: white;
            cursor: pointer;
        }
        .error {
            color: #dc2626;
            margin-top: 12px;
        }
        .demo {
            margin-top: 15px;
            padding: 10px;
            background: #f3f4f6;
            border-radius: 7px;
            font-size: 13px;
        }
    </style>
</head>
<body>
<div class="login-box">
    <h1>🔐 Authority Login</h1>
    <p>Smart Littering Monitoring</p>
    <form method="POST">
        <input type="text" name="username" placeholder="Username" required>
        <input type="password" name="password" placeholder="Password" required>
        <button type="submit">Login</button>
    </form>
    {% if error %}
        <div class="error">{{ error }}</div>
    {% endif %}
    <div class="demo">
        <b>Demo account</b><br>
        Username: admin<br>
        Password: admin123
    </div>
</div>
</body>
</html>
"""


# ============================================================
# MAIN DASHBOARD HTML
# ============================================================

HTML = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Smart Littering Dashboard</title>

    <!-- Leaflet -->
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
    <!-- Chart.js -->
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>

    <style>
        * { box-sizing: border-box; }
        body { margin: 0; font-family: Arial, sans-serif; background: #f3f4f6; color: #111827; }
        /* ================= HEADER ================= */
        .header { background: #111827; color: white; padding: 22px 30px; }
        .header-top { display: flex; justify-content: space-between; align-items: center; gap: 15px; flex-wrap: wrap; }
        .header h1 { margin: 0; font-size: 28px; }
        .header p { margin: 6px 0 0; color: #d1d5db; }
        .logout { color: white; text-decoration: none; background: #374151; padding: 8px 12px; border-radius: 6px; }
        /* ================= CONTAINER ================= */
        .container { max-width: 1200px; margin: auto; padding: 25px; }
        /* ================= STATS ================= */
        .stats { display: flex; gap: 20px; margin-bottom: 25px; flex-wrap: wrap; }
        .card { background: white; padding: 20px; border-radius: 12px; flex: 1; min-width: 200px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
        .card h3 { margin: 0; color: #6b7280; font-size: 14px; }
        .number { margin-top: 8px; font-size: 28px; font-weight: bold; }
        .online { color: green; }
        /* ================= MAP ================= */
        #map { height: 400px; width: 100%; border-radius: 12px; margin-bottom: 30px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); z-index: 1; }
        /* ================= CHART ================= */
        .chart-card { background: white; padding: 20px; border-radius: 12px; margin-bottom: 30px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
        .chart-container { position: relative; width: 100%; height: 350px; }
        /* ================= CAMERA ================= */
        .camera-card { background: white; padding: 18px; margin-bottom: 12px; border-radius: 10px; box-shadow: 0 2px 6px rgba(0,0,0,0.08); }
        .camera-online { border-left: 6px solid green; }
        .camera-offline { border-left: 6px solid red; }
        .camera-simulated { border-left: 6px solid orange; }
        /* ================= HOTSPOTS ================= */
        .hotspot { background: white; padding: 18px; margin-bottom: 12px; border-radius: 10px; box-shadow: 0 2px 6px rgba(0,0,0,0.08); }
        .hotspot-high { border-left: 6px solid red; }
        .hotspot-medium { border-left: 6px solid orange; }
        .hotspot-low { border-left: 6px solid green; }
        /* ================= INCIDENT ================= */
        .incident { background: white; margin-bottom: 20px; padding: 22px; border-radius: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.08); }
        .alert { color: #dc2626; font-size: 20px; font-weight: bold; margin-bottom: 15px; }
        .details { line-height: 1.8; }
        .incident-id { font-family: monospace; background: #f3f4f6; padding: 3px 7px; border-radius: 5px; }
        /* ================= EVIDENCE ================= */
        .evidence { width: 100%; max-width: 650px; border-radius: 10px; border: 1px solid #ddd; display: block; margin-top: 15px; }
        .video-evidence { width: 100%; max-width: 700px; margin-top: 15px; border-radius: 10px; border: 1px solid #ddd; background: black; display: block; }
        /* ================= STATUS ================= */
        .status { display: inline-block; padding: 5px 10px; border-radius: 20px; font-size: 13px; font-weight: bold; }
        .status-pending { background: #fef3c7; color: #92400e; }
        .status-verified { background: #dbeafe; color: #1e40af; }
        .status-action { background: #ede9fe; color: #6d28d9; }
        .status-resolved { background: #dcfce7; color: #166534; }
        /* ================= BUTTONS ================= */
        .actions { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 15px; }
        .btn { border: none; padding: 9px 14px; border-radius: 7px; cursor: pointer; font-size: 13px; font-weight: bold; }
        .btn:hover { opacity: 0.85; }
        .btn-verify { background: #2563eb; color: white; }
        .btn-action { background: #7c3aed; color: white; }
        .btn-resolve { background: #16a34a; color: white; }
        .btn-reset { background: #6b7280; color: white; }
        /* ================= EMPTY ================= */
        .empty { text-align: center; background: white; padding: 50px; border-radius: 12px; }
        .section-title { margin-top: 30px; }
    </style>
</head>

<body>
<div class="header">
    <div class="header-top">
        <div>
            <h1>🚨 Smart Littering Monitoring</h1>
            <p>AI-based littering incident dashboard</p>
        </div>
        <a href="/logout" class="logout">Logout</a>
    </div>
</div>

<div class="container">
    <!-- =====================================================
         MAIN STATS
    ====================================================== -->
    <div class="stats">
        <div class="card">
            <h3>Total Incidents</h3>
            <div class="number" id="incidentCount">{{ incidents|length }}</div>
        </div>
        <div class="card">
            <h3>System Status</h3>
            <div class="number online">● ONLINE</div>
        </div>
        <div class="card">
            <h3>Monitoring Cameras</h3>
            <div class="number" id="cameraCount">0</div>
        </div>
    </div>

    <!-- =====================================================
         ANALYTICS
    ====================================================== -->
    <div class="card" style="margin-bottom: 25px;">
        <h3>🔎 Filter Incidents</h3>
        <input type="text" id="searchInput" placeholder="Search camera, location, ID..." style="width:100%; padding:10px; margin:10px 0; border:1px solid #ccc; border-radius:7px;">
        <select id="statusFilter" style="padding:10px; margin-right:10px; border-radius:7px;">
            <option value="ALL">All Statuses</option>
            <option value="Pending Verification">Pending Verification</option>
            <option value="Verified">Verified</option>
            <option value="Action Taken">Action Taken</option>
            <option value="Resolved">Resolved</option>
        </select>
        <select id="wasteFilter" style="padding:10px; border-radius:7px;">
            <option value="ALL">All Waste Types</option>
            <option value="Plastic Bottle">Plastic Bottle</option>
        </select>
    </div>

    <h2 class="section-title">📊 Littering Analytics</h2>
    <div class="stats">
        <div class="card">
            <h3>Today</h3>
            <div class="number" id="todayCount">0</div>
        </div>
        <div class="card">
            <h3>This Week</h3>
            <div class="number" id="weekCount">0</div>
        </div>
        <div class="card">
            <h3>This Month</h3>
            <div class="number" id="monthCount">0</div>
        </div>
    </div>
    <div class="stats">
        <div class="card">
            <h3>🔥 Top Littering Hotspot</h3>
            <div class="number" id="topCamera">Loading...</div>
            <p id="topCameraCount">0 incidents</p>
        </div>
        <div class="card">
            <h3>🧴 Most Detected Waste</h3>
            <div class="number" id="topWaste">Loading...</div>
            <p id="topWasteCount">0 incidents</p>
        </div>
    </div>

    <!-- =====================================================
         TREND
    ====================================================== -->
    <h2 class="section-title">📈 Littering Trend</h2>
    <div class="chart-card">
        <div class="chart-container">
            <canvas id="trendChart"></canvas>
        </div>
    </div>

    <!-- =====================================================
         CAMERA MONITORING
    ====================================================== -->
    <h2 class="section-title">📷 Camera Monitoring</h2>
    <div id="cameras">
        <div class="camera-card">Loading camera status...</div>
    </div>

    <!-- =====================================================
         MAP
    ====================================================== -->
    <h2 class="section-title">📍 Littering Incident Map</h2>
    <div id="map"></div>

    <!-- =====================================================
         HOTSPOTS
    ====================================================== -->
    <h2 class="section-title">🔥 Littering Hotspots</h2>
    <div id="hotspots">
        <div class="hotspot">Loading hotspot data...</div>
    </div>

    <!-- =====================================================
         INCIDENTS
    ====================================================== -->
    <h2 class="section-title">Recent Incidents</h2>

    {% if incidents %}
        {% for incident in incidents|reverse %}
            {% set current_status = incident.get("status", "Pending Verification") %}
            
            <div class="incident" 
                 data-camera="{{ incident.get('camera', '') }}" 
                 data-location="{{ incident.get('location', '') }}" 
                 data-id="{{ incident.get('id', '') }}" 
                 data-status="{{ current_status }}" 
                 data-waste="{{ incident.get('waste', '') }}">

                <div class="alert">🚨 SUSPECTED LITTERING</div>

                <div class="details">
                    <b>Incident ID:</b>
                    <span class="incident-id">{{ incident.get("id", "NO-ID") }}</span><br>
                    
                    <b>Camera:</b> {{ incident.get("camera", "Unknown Camera") }}<br>
                    <b>Location:</b> {{ incident.get("location", "Unknown Location") }}<br>
                    <b>Time:</b> {{ incident.get("time", "Unknown") }}<br>
                    <b>Waste:</b> {{ incident.get("waste", "Unknown") }}<br>
                    <b>Status:</b>
                    {% if current_status == "Pending Verification" %}
                        <span class="status status-pending">{{ current_status }}</span>
                    {% elif current_status == "Verified" %}
                        <span class="status status-verified">{{ current_status }}</span>
                    {% elif current_status == "Action Taken" %}
                        <span class="status status-action">{{ current_status }}</span>
                    {% elif current_status == "Resolved" %}
                        <span class="status status-resolved">{{ current_status }}</span>
                    {% else %}
                        <span class="status status-pending">{{ current_status }}</span>
                    {% endif %}
                    <br>
                    
                    <b>Priority:</b>
                    {% if incident.priority == "HIGH" %}
                        <span class="status" style="background:#fee2e2;color:#991b1b;">🔴 HIGH</span>
                    {% elif incident.priority == "MEDIUM" %}
                        <span class="status" style="background:#fef3c7;color:#92400e;">🟡 MEDIUM</span>
                    {% else %}
                        <span class="status" style="background:#dcfce7;color:#166534;">🟢 LOW</span>
                    {% endif %}
                </div>

                <!-- STATUS BUTTONS -->
                <div class="actions">
                    <button class="btn btn-verify" onclick="updateStatus('{{ incident.get("id", "") }}', 'Verified')">✓ Verify</button>
                    <button class="btn btn-action" onclick="updateStatus('{{ incident.get("id", "") }}', 'Action Taken')">🔧 Action Taken</button>
                    <button class="btn btn-resolve" onclick="updateStatus('{{ incident.get("id", "") }}', 'Resolved')">✅ Resolve</button>
                    <button class="btn btn-reset" onclick="updateStatus('{{ incident.get("id", "") }}', 'Pending Verification')">↩ Reset</button>
                </div>

                <!-- IMAGE EVIDENCE -->
                {% if incident.get("image_name") %}
                    <h3>📷 Image Evidence</h3>
                    <img class="evidence" src="/evidence/{{ incident.image_name }}" alt="Littering Evidence">
                {% endif %}

                <!-- VIDEO EVIDENCE -->
                {% if incident.get("video_name") %}
                    <h3>🎥 Video Evidence</h3>
                    <video class="video-evidence" controls preload="metadata">
                        <source src="/evidence/{{ incident.video_name }}" type="video/mp4">
                        Your browser does not support video playback.
                    </video>
                {% endif %}
            </div>
        {% endfor %}
    {% else %}
        <div class="empty">
            <h2>✅ No incidents detected</h2>
            <p>The monitoring system is currently active.</p>
        </div>
    {% endif %}

</div>

<!-- =====================================================
     LEAFLET JS & CUSTOM SCRIPT
====================================================== -->
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script>
    const incidents = {{ incidents | tojson }};

    // MAP
    const defaultLat = 12.0657;
    const defaultLng = 75.3879;

    const map = L.map("map").setView([defaultLat, defaultLng], 16);

    L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
        maxZoom: 19,
        attribution: "&copy; OpenStreetMap contributors"
    }).addTo(map);

    const cameraMarker = L.marker([defaultLat, defaultLng]).addTo(map);
    cameraMarker.bindPopup("<b>📷 Camera 01</b><br>Monitoring Area");

    const markerGroup = L.featureGroup([cameraMarker]).addTo(map);

    incidents.forEach(function(incident) {
        const lat = Number(incident.latitude) || defaultLat;
        const lng = Number(incident.longitude) || defaultLng;

        const marker = L.marker([lat, lng]);

        marker.bindPopup(
            "<b>🚨 Suspected Littering</b><br>" +
            "Incident ID: " + (incident.id || "N/A") + "<br>" +
            "Camera: " + (incident.camera || "N/A") + "<br>" +
            "Location: " + (incident.location || "N/A") + "<br>" +
            "Time: " + (incident.time || "N/A") + "<br>" +
            "Waste: " + (incident.waste || "N/A") + "<br>" +
            "Status: " + (incident.status || "Pending Verification") + "<br>" +
            "Priority: " + (incident.priority || "LOW")
        );
        markerGroup.addLayer(marker);
    });

    if (incidents.length > 0) {
        map.fitBounds(markerGroup.getBounds().pad(0.1));
    }

    // CAMERA STATUS
    async function loadCameras() {
        try {
            const response = await fetch("/api/cameras");
            if (!response.ok) throw new Error("Camera API failed");
            
            const cameras = await response.json();
            document.getElementById("cameraCount").innerText = cameras.length;
            const container = document.getElementById("cameras");
            container.innerHTML = "";
            
            if (cameras.length === 0) {
                container.innerHTML = `<div class="camera-card">No cameras configured.</div>`;
                return;
            }

            cameras.forEach(function(camera) {
                let className = "camera-offline";
                let icon = "🔴";

                if (camera.status === "ONLINE") {
                    className = "camera-online";
                    icon = "🟢";
                } else if (camera.status === "SIMULATED") {
                    className = "camera-simulated";
                    icon = "🟡";
                }

                const div = document.createElement("div");
                div.className = "camera-card " + className;
                div.innerHTML = `<b>${icon} ${camera.id}</b><br>📍 ${camera.location}<br>Status: <b>${camera.status}</b>`;
                container.appendChild(div);
            });
        } catch (error) {
            console.error("Camera status error:", error);
            document.getElementById("cameras").innerHTML = `<div class="camera-card camera-offline">⚠️ Unable to load camera status.</div>`;
        }
    }

    loadCameras();
    setInterval(loadCameras, 5000);

    // HOTSPOTS
    async function loadHotspots() {
        try {
            const response = await fetch("/api/hotspots");
            if (!response.ok) throw new Error("Hotspot API failed");
            
            const hotspots = await response.json();
            const container = document.getElementById("hotspots");
            container.innerHTML = "";
            
            if (hotspots.length === 0) {
                container.innerHTML = `<div class="hotspot hotspot-low">✅ No littering hotspots yet.</div>`;
                return;
            }

            hotspots.forEach(function(hotspot) {
                let className = "hotspot-low";
                if (hotspot.count >= 10) className = "hotspot-high";
                else if (hotspot.count >= 5) className = "hotspot-medium";

                const div = document.createElement("div");
                div.className = "hotspot " + className;
                div.innerHTML = `<b>${hotspot.camera}</b><br>📍 ${hotspot.location}<br>🚨 ${hotspot.count} littering incidents`;
                container.appendChild(div);
            });
        } catch (error) {
            console.error("Hotspot error:", error);
        }
    }

    loadHotspots();
    setInterval(loadHotspots, 5000);

    // ANALYTICS
    let trendChart = null;
    async function loadAnalytics() {
        try {
            const response = await fetch("/api/analytics");
            if (!response.ok) throw new Error("Analytics API failed");
            
            const data = await response.json();
            document.getElementById("todayCount").innerText = data.today;
            document.getElementById("weekCount").innerText = data.week;
            document.getElementById("monthCount").innerText = data.month;
            document.getElementById("topCamera").innerText = data.top_camera;
            document.getElementById("topCameraCount").innerText = data.top_camera_count + " incidents";
            document.getElementById("topWaste").innerText = data.top_waste;
            document.getElementById("topWasteCount").innerText = data.top_waste_count + " incidents";

            const daily = data.daily || {};
            const labels = Object.keys(daily).sort();
            const values = labels.map(day => daily[day]);
            const canvas = document.getElementById("trendChart");

            if (trendChart) trendChart.destroy();

            trendChart = new Chart(canvas, {
                type: "line",
                data: {
                    labels: labels,
                    datasets: [{
                        label: "Littering Incidents",
                        data: values,
                        tension: 0.3,
                        fill: false,
                        borderWidth: 3,
                        pointRadius: 5
                    }]
                },
                options: {
                    responsive: true,
                    maintainAspectRatio: false,
                    scales: {
                        y: {
                            beginAtZero: true,
                            ticks: { precision: 0 }
                        }
                    }
                }
            });
        } catch (error) {
            console.error("Analytics error:", error);
        }
    }

    loadAnalytics();
    setInterval(loadAnalytics, 5000);

    // STATUS UPDATE
    async function updateStatus(incidentId, newStatus) {
        if (!incidentId) {
            alert("Incident ID is missing.");
            return;
        }

        try {
            const url = "/api/incidents/" + encodeURIComponent(incidentId) + "/status";
            const response = await fetch(url, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ status: newStatus })
            });
            const data = await response.json();

            if (!response.ok) throw new Error(data.error || "Status update failed");
            
            location.reload();
        } catch (error) {
            alert("Could not update status: " + error.message);
        }
    }

    // REAL-TIME INCIDENT MONITOR
    let previousCount = {{ incidents|length }};

    async function checkIncidents() {
        try {
            const response = await fetch("/api/incidents");
            if (!response.ok) throw new Error("Incident API failed");
            
            const data = await response.json();
            document.getElementById("incidentCount").innerText = data.count;

            if (data.count > previousCount) {
                previousCount = data.count;
                alert("🚨 NEW LITTERING INCIDENT!");
                location.reload();
            }
        } catch (error) {
            console.error("Incident check error:", error);
        }
    }

    setInterval(checkIncidents, 2000);
</script>
<script>
function filterIncidents() {
    const search = document.getElementById("searchInput").value.toLowerCase();
    const status = document.getElementById("statusFilter").value;
    const waste = document.getElementById("wasteFilter").value;
    const incidentsList = document.querySelectorAll(".incident");

    incidentsList.forEach(function(card) {
        const text = (card.dataset.camera + " " + card.dataset.location + " " + card.dataset.id).toLowerCase();
        
        const matchesSearch = text.includes(search);
        const matchesStatus = (status === "ALL" || card.dataset.status === status);
        const matchesWaste = (waste === "ALL" || card.dataset.waste === waste);

        if (matchesSearch && matchesStatus && matchesWaste) {
            card.style.display = "";
        } else {
            card.style.display = "none";
        }
    });
}

document.getElementById("searchInput").addEventListener("input", filterIncidents);
document.getElementById("statusFilter").addEventListener("change", filterIncidents);
document.getElementById("wasteFilter").addEventListener("change", filterIncidents);
</script>
</body>
</html>
"""


# ============================================================
# UTILITIES & ROUTES
# ============================================================

def calculate_priority(incident, incidents):
    camera = incident.get("camera", "Unknown Camera")
    location = incident.get("location", "Unknown Location")
    count = 0

    for item in incidents:
        if item.get("camera") == camera and item.get("location") == location:
            count += 1

    if count >= 5:
        return "HIGH"
    if count >= 3:
        return "MEDIUM"
    return "LOW"


@app.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = request.form.get("username", "")
        password = request.form.get("password", "")

        if username == "admin" and password == "admin123":
            session["logged_in"] = True
            return redirect(url_for("dashboard"))

        error = "Invalid username or password."

    return render_template_string(LOGIN_HTML, error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
def dashboard():
    if not session.get("logged_in"):
        return redirect(url_for("login"))

    incidents = load_incidents()
    
    # Calculate priorities and parse image/video paths
    for incident in incidents:
        incident["priority"] = calculate_priority(incident, incidents)

        image_path = incident.get("image", "")
        incident["image_name"] = os.path.basename(image_path.replace("\\", "/"))

        video_path = incident.get("video", "")
        incident["video_name"] = os.path.basename(video_path.replace("\\", "/"))

    return render_template_string(HTML, incidents=incidents)


# ============================================================
# APIs
# ============================================================

@app.route("/api/incidents")
def api_incidents():
    if not session.get("logged_in"):
        return jsonify({"error": "Unauthorized"}), 401

    incidents = load_incidents()
    return jsonify({
        "count": len(incidents),
        "incidents": incidents
    })


@app.route("/api/incidents/<path:incident_id>/status", methods=["POST"])
def update_incident_status(incident_id):
    if not session.get("logged_in"):
        return jsonify({"error": "Unauthorized"}), 401

    incidents = load_incidents()
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        data = {}

    new_status = data.get("status")
    allowed_statuses = ["Pending Verification", "Verified", "Action Taken", "Resolved"]

    if new_status not in allowed_statuses:
        return jsonify({"error": "Invalid status"}), 400

    for incident in incidents:
        current_id = str(incident.get("id", ""))
        if current_id == incident_id:
            incident["status"] = new_status
            save_incidents(incidents)
            return jsonify({
                "success": True,
                "id": incident_id,
                "status": new_status
            })

    return jsonify({"error": "Incident not found"}), 404


@app.route("/api/hotspots")
def api_hotspots():
    if not session.get("logged_in"):
        return jsonify({"error": "Unauthorized"}), 401

    incidents = load_incidents()
    hotspots = {}

    for incident in incidents:
        camera = incident.get("camera", "Unknown Camera")
        location = incident.get("location", "Unknown Location")
        key = camera + " | " + location

        if key not in hotspots:
            hotspots[key] = {
                "camera": camera,
                "location": location,
                "count": 0
            }

        hotspots[key]["count"] += 1

    results = list(hotspots.values())
    results.sort(key=lambda item: item["count"], reverse=True)

    return jsonify(results)


@app.route("/api/analytics")
def api_analytics():
    if not session.get("logged_in"):
        return jsonify({"error": "Unauthorized"}), 401

    incidents = load_incidents()
    now = datetime.now()

    today_count = 0
    week_count = 0
    month_count = 0

    camera_counts = {}
    waste_counts = {}
    daily_counts = {}

    for incident in incidents:
        time_text = incident.get("time", "")
        try:
            incident_time = datetime.strptime(time_text, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue

        if incident_time.date() == now.date():
            today_count += 1
            
        if (incident_time.isocalendar().week == now.isocalendar().week and 
            incident_time.year == now.year):
            week_count += 1
            
        if (incident_time.year == now.year and incident_time.month == now.month):
            month_count += 1

        camera = incident.get("camera", "Unknown Camera")
        camera_counts[camera] = camera_counts.get(camera, 0) + 1

        waste = incident.get("waste", "Unknown")
        waste_counts[waste] = waste_counts.get(waste, 0) + 1

        day = incident_time.strftime("%Y-%m-%d")
        daily_counts[day] = daily_counts.get(day, 0) + 1

    if camera_counts:
        top_camera = max(camera_counts, key=camera_counts.get)
        top_camera_count = camera_counts[top_camera]
    else:
        top_camera = "None"
        top_camera_count = 0

    if waste_counts:
        top_waste = max(waste_counts, key=waste_counts.get)
        top_waste_count = waste_counts[top_waste]
    else:
        top_waste = "None"
        top_waste_count = 0

    return jsonify({
        "total": len(incidents),
        "today": today_count,
        "week": week_count,
        "month": month_count,
        "top_camera": top_camera,
        "top_camera_count": top_camera_count,
        "top_waste": top_waste,
        "top_waste_count": top_waste_count,
        "daily": daily_counts
    })


@app.route("/api/cameras")
def api_cameras():
    if not session.get("logged_in"):
        return jsonify({"error": "Unauthorized"}), 401

    camera_config = load_json_file(CAMERA_FILE, {})
    camera_status = load_json_file(CAMERA_STATUS_FILE, {})

    if not isinstance(camera_config, dict):
        camera_config = {}
    if not isinstance(camera_status, dict):
        camera_status = {}

    now = time.time()
    result = []

    for camera_id, config in camera_config.items():
        if not isinstance(config, dict):
            config = {}

        status_info = camera_status.get(camera_id, {})
        if not isinstance(status_info, dict):
            status_info = {}

        last_seen = status_info.get("last_seen", 0)
        try:
            last_seen = float(last_seen)
        except (TypeError, ValueError):
            last_seen = 0

        manual_status = status_info.get("status", "")

        if now - last_seen <= 15:
            status = "ONLINE"
        elif manual_status == "SIMULATED":
            status = "SIMULATED"
        else:
            status = "OFFLINE"

        result.append({
            "id": camera_id,
            "location": config.get("location", "Unknown"),
            "latitude": config.get("latitude"),
            "longitude": config.get("longitude"),
            "status": status,
            "last_seen": last_seen
        })

    return jsonify(result)


@app.route("/evidence/<path:filename>")
def evidence(filename):
    return send_from_directory(EVIDENCE_FOLDER, filename)


# ============================================================
# START SERVER
# ============================================================

if __name__ == "__main__":
    print()
    print("======================================")
    print("       SMART LITTERING DASHBOARD")
    print("======================================")
    print()
    print("Dashboard:")
    print("http://127.0.0.1:5000")
    print()
    print("Camera API:")
    print("http://127.0.0.1:5000/api/cameras")
    print()
    print("Incident API:")
    print("http://127.0.0.1:5000/api/incidents")
    print()
    print("Analytics API:")
    print("http://127.0.0.1:5000/api/analytics")
    print()
    print("Waiting for incidents...")
    print()
if __name__ == "__main__":

    port = int(
        os.environ.get(
            "PORT",
            5000
        )
    )

    print()
    print("======================================")
    print("      SMART LITTERING DASHBOARD")
    print("======================================")
    print()
    print("Dashboard:")
    print(
        f"http://0.0.0.0:{port}"
    )
    print()
    print("Waiting for incidents...")
    print()

    app.run(
        host="0.0.0.0",
        port=port,
        debug=False
    )