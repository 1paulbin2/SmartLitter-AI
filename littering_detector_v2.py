import argparse
import json
import math
import os
import subprocess
import threading
import time
import uuid
from collections import deque

import cv2
from ultralytics import YOLO

# Email notification
try:
    from email_notifier import send_littering_alert
except ImportError:
    send_littering_alert = None


# ============================================================
# CONSTANTS
# ============================================================

PERSON_CLASS_ID = 0
BOTTLE_CLASS_ID = 39

CAMERA_CONFIG_FILE = "cameras.json"
CAMERA_STATUS_FILE = "camera_status.json"
INCIDENT_FILE = "incidents.json"

# Camera heartbeat
HEARTBEAT_INTERVAL = 5

# ------------------------------------------------------------
# Evidence video
# ------------------------------------------------------------

EVIDENCE_WIDTH = 854
EVIDENCE_HEIGHT = 480

PRE_EVENT_SECONDS = 5
POST_EVENT_SECONDS = 3

# Rolling buffer check interval
BUFFER_CLEANUP_INTERVAL = 0.5


# ============================================================
# JSON HELPERS
# ============================================================

def load_json_file(path, default):
    """Safely load a JSON file."""

    if not os.path.exists(path):
        return default

    try:
        with open(
            path,
            "r",
            encoding="utf-8"
        ) as file:
            data = json.load(file)

        return data

    except (
        FileNotFoundError,
        json.JSONDecodeError,
        OSError
    ):
        return default


def save_json_file(path, data):
    """Safely save JSON data."""

    try:

        with open(
            path,
            "w",
            encoding="utf-8"
        ) as file:

            json.dump(
                data,
                file,
                indent=4
            )

        return True

    except OSError as error:

        print(
            "JSON save error:",
            error
        )

        return False


# ============================================================
# CAMERA CONFIGURATION
# ============================================================

def load_camera_config(camera_id):
    """Load camera location and coordinates."""

    cameras = load_json_file(
        CAMERA_CONFIG_FILE,
        {}
    )

    if not isinstance(
        cameras,
        dict
    ):
        cameras = {}

    config = cameras.get(
        camera_id,
        {}
    )

    if not isinstance(
        config,
        dict
    ):
        config = {}

    return {
        "location": config.get(
            "location",
            "Unknown Location"
        ),
        "latitude": config.get(
            "latitude"
        ),
        "longitude": config.get(
            "longitude"
        )
    }


# ============================================================
# CAMERA HEARTBEAT
# ============================================================

def send_heartbeat(camera_id):
    """Update camera last-seen information."""

    try:

        status_data = load_json_file(
            CAMERA_STATUS_FILE,
            {}
        )

        if not isinstance(
            status_data,
            dict
        ):
            status_data = {}

        status_data[camera_id] = {
            "last_seen": time.time(),
            "status": "ONLINE"
        }

        save_json_file(
            CAMERA_STATUS_FILE,
            status_data
        )

    except Exception as error:

        print(
            "Heartbeat error:",
            error
        )


def heartbeat_loop(
    camera_id,
    stop_event
):
    """Send periodic camera heartbeats."""

    while not stop_event.is_set():

        send_heartbeat(
            camera_id
        )

        stop_event.wait(
            HEARTBEAT_INTERVAL
        )


# ============================================================
# GEOMETRY
# ============================================================

def iou(box_a, box_b):
    """Intersection over Union."""

    xa = max(
        box_a[0],
        box_b[0]
    )

    ya = max(
        box_a[1],
        box_b[1]
    )

    xb = min(
        box_a[2],
        box_b[2]
    )

    yb = min(
        box_a[3],
        box_b[3]
    )

    inter_w = max(
        0.0,
        xb - xa
    )

    inter_h = max(
        0.0,
        yb - ya
    )

    inter_area = (
        inter_w *
        inter_h
    )

    area_a = (
        max(
            0.0,
            box_a[2] - box_a[0]
        )
        *
        max(
            0.0,
            box_a[3] - box_a[1]
        )
    )

    area_b = (
        max(
            0.0,
            box_b[2] - box_b[0]
        )
        *
        max(
            0.0,
            box_b[3] - box_b[1]
        )
    )

    union = (
        area_a
        +
        area_b
        -
        inter_area
    )

    if union <= 0:
        return 0.0

    return (
        inter_area /
        union
    )


# ============================================================
# INCIDENT VIDEO ATTACHMENT
# ============================================================

def attach_video_to_incident(
    incident_id,
    video_filename
):
    """
    Attach the finished video to the exact incident ID.
    """

    incidents = load_json_file(
        INCIDENT_FILE,
        []
    )

    if not isinstance(
        incidents,
        list
    ):
        return False

    for incident in incidents:

        current_id = str(
            incident.get(
                "id",
                ""
            )
        )

        if current_id == str(
            incident_id
        ):

            incident["video"] = (
                video_filename
            )

            save_json_file(
                INCIDENT_FILE,
                incidents
            )

            print(
                "🎥 Video attached to:",
                incident_id
            )

            return True

    print(
        "WARNING: Incident not found:",
        incident_id
    )

    return False


# ============================================================
# EVIDENCE VIDEO RECORDER
# ============================================================

class EvidenceRecorder:
    """
    Non-blocking evidence recorder.

    Main camera thread:
        - stores small resized frames
        - detects event
        - continues immediately

    Background worker:
        - writes temporary MP4
        - runs FFmpeg
        - attaches video to exact incident ID
    """

    def __init__(
        self,
        output_dir="evidence"
    ):

        self.output_dir = output_dir

        os.makedirs(
            self.output_dir,
            exist_ok=True
        )

        # (timestamp, frame)
        self.buffer = deque()

        self.pre_event_seconds = (
            PRE_EVENT_SECONDS
        )

        self.post_event_seconds = (
            POST_EVENT_SECONDS
        )

        self.recording = False

        self.recording_incident_id = None

        self.post_deadline = None

        self.event_frames = []

        self.lock = threading.Lock()

        self.last_cleanup = 0.0


    # ========================================================
    # ADD FRAME
    # ========================================================

    def add_frame(
        self,
        frame
    ):
        """
        Add a resized frame.

        IMPORTANT:
        No video encoding or FFmpeg happens here.
        """

        now = time.time()

        # Resize BEFORE adding to buffer.
        # This greatly reduces RAM usage.
        resized = cv2.resize(
            frame,
            (
                EVIDENCE_WIDTH,
                EVIDENCE_HEIGHT
            ),
            interpolation=cv2.INTER_AREA
        )

        with self.lock:

            self.buffer.append(
                (
                    now,
                    resized
                )
            )

            # ----------------------------------------------
            # Remove frames older than the pre-event window
            # ----------------------------------------------

            if (
                now - self.last_cleanup
                >= BUFFER_CLEANUP_INTERVAL
            ):

                cutoff = (
                    now -
                    self.pre_event_seconds
                )

                while (
                    self.buffer
                    and
                    self.buffer[0][0]
                    < cutoff
                ):

                    self.buffer.popleft()

                self.last_cleanup = now


            # ----------------------------------------------
            # Active recording
            # ----------------------------------------------

            if self.recording:

                self.event_frames.append(
                    (
                        now,
                        resized.copy()
                    )
                )

                if (
                    self.post_deadline
                    is not None
                    and
                    now >= self.post_deadline
                ):

                    frames_to_save = list(
                        self.event_frames
                    )

                    incident_id = (
                        self.recording_incident_id
                    )

                    # Reset recording state BEFORE
                    # starting worker.
                    self.recording = False

                    self.recording_incident_id = None

                    self.post_deadline = None

                    self.event_frames = []

                    # --------------------------------------
                    # IMPORTANT:
                    # Background thread only
                    # --------------------------------------

                    threading.Thread(
                        target=self._save_video_background,
                        args=(
                            frames_to_save,
                            incident_id
                        ),
                        daemon=True
                    ).start()


    # ========================================================
    # START EVENT
    # ========================================================

    def start_event(
        self,
        incident_id
    ):
        """
        Start an evidence recording tied to a specific
        incident ID.
        """

        with self.lock:

            if self.recording:

                print(
                    "⚠️ Evidence recording already active."
                )

                return False

            self.recording = True

            self.recording_incident_id = (
                str(incident_id)
            )

            # Include previous buffered frames
            self.event_frames = [
                (
                    ts,
                    frame.copy()
                )
                for ts, frame in self.buffer
            ]

            self.post_deadline = (
                time.time()
                +
                self.post_event_seconds
            )

            print(
                "🎥 Evidence recording started for:",
                incident_id
            )

            return True


    # ========================================================
    # BACKGROUND VIDEO WORKER
    # ========================================================

    def _save_video_background(
        self,
        frames,
        incident_id
    ):
        """
        Runs completely outside the camera loop.
        """

        try:

            if not frames:

                print(
                    "⚠️ No frames available for:",
                    incident_id
                )

                return


            unique_id = (
                uuid.uuid4()
                .hex[:8]
                .upper()
            )


            timestamp = time.strftime(
                "%Y%m%d_%H%M%S"
            )


            temp_filename = os.path.join(
                self.output_dir,
                (
                    f"temp_"
                    f"{timestamp}_"
                    f"{unique_id}.mp4"
                )
            )


            final_filename = os.path.join(
                self.output_dir,
                (
                    f"littering_"
                    f"{timestamp}_"
                    f"{unique_id}.mp4"
                )
            )


            # ------------------------------------------------
            # Write temporary MP4
            # ------------------------------------------------

            first_frame = frames[0][1]

            height, width = (
                first_frame.shape[:2]
            )


            # Keep playback smooth and simple.
            # The camera loop is NOT involved here.

            fps = 15.0


            writer = cv2.VideoWriter(
                temp_filename,
                cv2.VideoWriter_fourcc(
                    *"mp4v"
                ),
                fps,
                (
                    width,
                    height
                )
            )


            if not writer.isOpened():

                print(
                    "❌ Could not open video writer."
                )

                return


            for _timestamp, frame in frames:

                writer.write(
                    frame
                )


            writer.release()


            if not os.path.exists(
                temp_filename
            ):

                print(
                    "❌ Temporary video not created."
                )

                return


            # ------------------------------------------------
            # FFmpeg
            # ------------------------------------------------

            print(
                "🔄 Converting video for:",
                incident_id
            )


            command = [

                "ffmpeg",

                "-y",

                "-loglevel",
                "error",

                "-i",
                temp_filename,

                "-c:v",
                "libx264",

                "-preset",
                "veryfast",

                "-crf",
                "28",

                "-pix_fmt",
                "yuv420p",

                "-movflags",
                "+faststart",

                final_filename

            ]


            result = subprocess.run(

                command,

                stdout=subprocess.DEVNULL,

                stderr=subprocess.PIPE,

                text=True

            )


            # ------------------------------------------------
            # Remove temporary file
            # ------------------------------------------------

            try:

                os.remove(
                    temp_filename
                )

            except OSError:

                pass


            if result.returncode != 0:

                print(
                    "❌ FFmpeg conversion failed."
                )

                print(
                    result.stderr
                )

                return


            # ------------------------------------------------
            # Verify final file
            # ------------------------------------------------

            if (
                not os.path.exists(
                    final_filename
                )
                or
                os.path.getsize(
                    final_filename
                ) <= 0
            ):

                print(
                    "❌ Final video is invalid."
                )

                return


            print(
                "✅ Browser-compatible video saved:"
            )

            print(
                final_filename
            )


            # ------------------------------------------------
            # Attach to exact incident
            # ------------------------------------------------

            attach_video_to_incident(
                incident_id,
                final_filename
            )


        except Exception as error:

            print(
                "❌ Background video error:",
                error
            )


# ============================================================
# LITTERING DETECTOR
# ============================================================

class LitteringDetector:

    def __init__(
        self,
        camera_id="Camera 01",
        near_distance=220,
        far_distance=250,
        downward_velocity=120,
        still_velocity=144,
        near_time=0.25,
        separation_time=0.35,
        stationary_time=0.7,
        person_away_time=0.5,
        bottle_lost_timeout=2.0,
        min_hold_displacement=40,
        reference_person_height=500,
        scale_adaptive=True,
        velocity_smoothing=0.6,
        person_conf=0.25,
        bottle_conf=0.35,
        evidence_dir="evidence"
    ):

        self.camera_id = camera_id

        self.camera_config = (
            load_camera_config(
                camera_id
            )
        )

        # Distance
        self.NEAR_DISTANCE = (
            near_distance
        )

        self.FAR_DISTANCE = (
            far_distance
        )

        # Velocity
        self.DOWNWARD_VELOCITY = (
            downward_velocity
        )

        self.STILL_VELOCITY = (
            still_velocity
        )

        # Time
        self.NEAR_TIME = (
            near_time
        )

        self.SEPARATION_TIME = (
            separation_time
        )

        self.STATIONARY_TIME = (
            stationary_time
        )

        self.PERSON_AWAY_TIME = (
            person_away_time
        )

        self.BOTTLE_LOST_TIMEOUT = (
            bottle_lost_timeout
        )

        # Hold verification
        self.MIN_HOLD_DISPLACEMENT = (
            min_hold_displacement
        )

        self.REFERENCE_PERSON_HEIGHT = (
            reference_person_height
        )

        self.SCALE_ADAPTIVE = (
            scale_adaptive
        )

        self.VELOCITY_SMOOTHING = (
            velocity_smoothing
        )

        # Confidence
        self.PERSON_CONF = (
            person_conf
        )

        self.BOTTLE_CONF = (
            bottle_conf
        )

        # Evidence
        self.evidence_dir = evidence_dir

        os.makedirs(
            self.evidence_dir,
            exist_ok=True
        )

        self.reset()


    # ========================================================
    # RESET
    # ========================================================

    def reset(self):

        self.state = "WAITING"

        self.tracked_bottle_id = None

        self.bottle_pos = None

        self.bottle_box = None

        self.previous_bottle_pos = None

        self.previous_frame_time = None

        self.last_bottle_seen_time = None

        self.near_start = None

        self.separation_start = None

        self.stationary_start = None

        self.person_away_start = None

        self.alert_time = 0

        # Hold displacement
        self.holding_start_pos = None

        self.max_hold_displacement = 0.0

        # Smoothed velocity
        self.smoothed_velocity_y = 0.0

        self.smoothed_velocity_total = 0.0

        # Scale
        self.last_scale = 1.0


    # ========================================================
    # DISTANCE
    # ========================================================

    @staticmethod
    def distance(
        p1,
        p2
    ):

        return math.hypot(
            p1[0] - p2[0],
            p1[1] - p2[1]
        )


    # ========================================================
    # PARSE DETECTIONS
    # ========================================================

    def parse_detections(
        self,
        results
    ):

        persons = []

        bottles = []

        boxes_obj = results[0].boxes


        if (
            boxes_obj is None
            or
            len(boxes_obj) == 0
        ):

            return (
                persons,
                bottles
            )


        xyxy = (
            boxes_obj.xyxy
            .cpu()
            .numpy()
        )


        classes = (
            boxes_obj.cls
            .cpu()
            .numpy()
        )


        confs = (
            boxes_obj.conf
            .cpu()
            .numpy()
        )


        if boxes_obj.id is not None:

            ids = (
                boxes_obj.id
                .cpu()
                .numpy()
            )

        else:

            ids = [
                None
            ] * len(xyxy)


        for (
            box,
            cls,
            conf,
            track_id
        ) in zip(
            xyxy,
            classes,
            confs,
            ids
        ):

            x1, y1, x2, y2 = box


            center = (
                int(
                    (x1 + x2) / 2
                ),
                int(
                    (y1 + y2) / 2
                )
            )


            item = {

                "id":
                    (
                        None
                        if track_id is None
                        else int(track_id)
                    ),

                "center":
                    center,

                "box":
                    (
                        x1,
                        y1,
                        x2,
                        y2
                    ),

                "conf":
                    float(conf),

                "height":
                    float(
                        y2 - y1
                    )
            }


            if int(cls) == PERSON_CLASS_ID:

                if (
                    item["conf"]
                    >=
                    self.PERSON_CONF
                ):

                    persons.append(
                        item
                    )


            elif int(cls) == BOTTLE_CLASS_ID:

                if (
                    item["conf"]
                    >=
                    self.BOTTLE_CONF
                ):

                    bottles.append(
                        item
                    )


        return (
            persons,
            bottles
        )


    # ========================================================
    # SELECT BOTTLE
    # ========================================================

    def select_bottle(
        self,
        bottles,
        persons
    ):

        if not bottles:

            return None


        # 1. Existing track ID
        if (
            self.tracked_bottle_id
            is not None
        ):

            for bottle in bottles:

                if (
                    bottle["id"]
                    ==
                    self.tracked_bottle_id
                ):

                    return bottle


        # 2. IoU
        if (
            self.bottle_box
            is not None
        ):

            best_bottle = max(

                bottles,

                key=lambda b:
                    iou(
                        b["box"],
                        self.bottle_box
                    )

            )


            if (
                iou(
                    best_bottle["box"],
                    self.bottle_box
                )
                >
                0.1
            ):

                return best_bottle


        # 3. Nearest previous position
        if (
            self.bottle_pos
            is not None
        ):

            return min(

                bottles,

                key=lambda b:
                    self.distance(
                        b["center"],
                        self.bottle_pos
                    )

            )


        # 4. Only bottle
        if (
            len(bottles)
            ==
            1
        ):

            return bottles[0]


        # 5. Nearest person
        if persons:

            def nearest_person_distance(
                bottle
            ):

                return min(

                    self.distance(
                        bottle["center"],
                        person["center"]
                    )

                    for person in persons

                )


            return min(

                bottles,

                key=nearest_person_distance

            )


        return bottles[0]


    # ========================================================
    # NEAREST PERSON
    # ========================================================

    @staticmethod
    def nearest_person(
        bottle_pos,
        persons
    ):

        if not persons:

            return (
                None,
                float("inf")
            )


        best_person = min(

            persons,

            key=lambda p:
                LitteringDetector.distance(
                    bottle_pos,
                    p["center"]
                )

        )


        best_distance = (
            LitteringDetector.distance(
                bottle_pos,
                best_person["center"]
            )
        )


        return (
            best_person,
            best_distance
        )


    # ========================================================
    # SCALE
    # ========================================================

    def get_scale_factor(
        self,
        person
    ):

        if not self.SCALE_ADAPTIVE:

            return 1.0


        if (
            person is None
            or
            person["height"] <= 0
        ):

            return self.last_scale


        scale = (
            person["height"]
            /
            self.REFERENCE_PERSON_HEIGHT
        )


        scale = max(
            0.4,
            min(
                scale,
                2.5
            )
        )


        self.last_scale = scale


        return scale


    # ========================================================
    # DRAW BOXES
    # ========================================================

    def draw_boxes(
        self,
        display,
        items,
        color,
        label
    ):

        for item in items:

            x1, y1, x2, y2 = map(
                int,
                item["box"]
            )


            cv2.rectangle(

                display,

                (x1, y1),

                (x2, y2),

                color,

                2

            )


            if item["id"] is None:

                tag = label

            else:

                tag = (
                    f"{label} "
                    f"#{item['id']}"
                )


            cv2.putText(

                display,

                (
                    f"{tag} "
                    f"{item['conf']:.2f}"
                ),

                (
                    x1,
                    max(
                        20,
                        y1 - 10
                    )
                ),

                cv2.FONT_HERSHEY_SIMPLEX,

                0.6,

                color,

                2

            )


    # ========================================================
    # DRAW STATUS
    # ========================================================

    def draw_status(
        self,
        display
    ):

        if (
            self.state
            ==
            "LITTERING"
        ):

            color = (
                0,
                0,
                255
            )

        else:

            color = (
                0,
                255,
                255
            )


        cv2.putText(

            display,

            f"STATE: {self.state}",

            (30, 40),

            cv2.FONT_HERSHEY_SIMPLEX,

            1,

            color,

            3

        )


        if (
            self.state
            ==
            "LITTERING"
        ):

            cv2.putText(

                display,

                "!!! SUSPECTED LITTERING !!!",

                (30, 240),

                cv2.FONT_HERSHEY_SIMPLEX,

                1,

                (0, 0, 255),

                4

            )


            cv2.putText(

                display,

                "Incident recorded",

                (30, 280),

                cv2.FONT_HERSHEY_SIMPLEX,

                0.8,

                (0, 0, 255),

                2

            )


    # ========================================================
    # BACKGROUND EMAIL
    # ========================================================

    @staticmethod
    def send_email_background(
        incident
    ):

        if send_littering_alert is None:

            return


        try:

            send_littering_alert(
                incident
            )

        except Exception as error:

            print(
                "Email notification error:",
                error
            )


    # ========================================================
    # CREATE INCIDENT
    # ========================================================

    def create_incident(
        self,
        display
    ):

        incident_id = (

            "INC-"

            +

            time.strftime(
                "%Y%m%d-%H%M%S"
            )

            +

            "-"

            +

            uuid.uuid4()
            .hex[:6]
            .upper()

        )


        image_filename = os.path.join(

            self.evidence_dir,

            (
                "littering_"
                +
                time.strftime(
                    "%Y%m%d_%H%M%S"
                )
                +
                "_"
                +
                uuid.uuid4()
                .hex[:6]
                +
                ".jpg"
            )

        )


        image_saved = cv2.imwrite(

            image_filename,

            display

        )


        if not image_saved:

            image_filename = ""


        incident = {

            "id":
                incident_id,

            "camera":
                self.camera_id,

            "location":
                self.camera_config[
                    "location"
                ],

            "latitude":
                self.camera_config[
                    "latitude"
                ],

            "longitude":
                self.camera_config[
                    "longitude"
                ],

            "time":
                time.strftime(
                    "%Y-%m-%d %H:%M:%S"
                ),

            "waste":
                "Plastic Bottle",

            "image":
                image_filename,

            "video":
                "",

            "status":
                "Pending Verification"

        }


        incidents = load_json_file(

            INCIDENT_FILE,

            []

        )


        if not isinstance(

            incidents,

            list

        ):

            incidents = []


        incidents.append(
            incident
        )


        save_json_file(

            INCIDENT_FILE,

            incidents

        )


        # ----------------------------------------------------
        # IMPORTANT:
        # Email is sent in background
        # ----------------------------------------------------

        threading.Thread(

            target=self.send_email_background,

            args=(
                incident.copy(),
            ),

            daemon=True

        ).start()


        print()

        print(
            "========================================"
        )

        print(
            "🚨 SUSPECTED LITTERING DETECTED"
        )

        print(
            "Incident ID:",
            incident_id
        )

        print(
            "Camera:",
            self.camera_id
        )

        print(
            "Location:",
            self.camera_config[
                "location"
            ]
        )

        print(
            "Evidence image:",
            image_filename
        )

        print(
            "========================================"
        )

        print()


        return incident_id


    # ========================================================
    # PROCESS FRAME
    # ========================================================

    def process(
        self,
        frame,
        results
    ):

        display = frame.copy()

        current_time = time.time()

        new_incident_id = None


        persons, bottles = (
            self.parse_detections(
                results
            )
        )


        # Draw detections
        self.draw_boxes(
            display,
            persons,
            (255, 0, 0),
            "PERSON"
        )


        self.draw_boxes(
            display,
            bottles,
            (0, 255, 0),
            "BOTTLE"
        )


        # ====================================================
        # NO BOTTLE
        # ====================================================

        if not bottles:

            if (

                self.last_bottle_seen_time
                is not None

                and

                current_time
                -
                self.last_bottle_seen_time
                >
                self.BOTTLE_LOST_TIMEOUT

            ):

                if (
                    self.state
                    !=
                    "WAITING"
                ):

                    print(
                        "Bottle lost. Resetting."
                    )


                self.reset()


            self.draw_status(
                display
            )


            return (
                display,
                new_incident_id
            )


        # ====================================================
        # SELECT BOTTLE
        # ====================================================

        bottle = self.select_bottle(
            bottles,
            persons
        )


        if bottle is None:

            self.draw_status(
                display
            )

            return (
                display,
                new_incident_id
            )


        self.tracked_bottle_id = (
            bottle["id"]
        )


        self.bottle_pos = (
            bottle["center"]
        )


        self.bottle_box = (
            bottle["box"]
        )


        self.last_bottle_seen_time = (
            current_time
        )


        # ====================================================
        # TIME DIFFERENCE
        # ====================================================

        dt = None


        if (
            self.previous_frame_time
            is not None
        ):

            dt = (
                current_time
                -
                self.previous_frame_time
            )


        # ====================================================
        # MOVEMENT
        # ====================================================

        movement_y = 0.0

        total_movement = 0.0


        if (
            self.previous_bottle_pos
            is not None
        ):

            movement_y = (
                self.bottle_pos[1]
                -
                self.previous_bottle_pos[1]
            )


            total_movement = (
                self.distance(
                    self.bottle_pos,
                    self.previous_bottle_pos
                )
            )


        # ====================================================
        # VELOCITY
        # ====================================================

        if (
            dt is not None
            and
            dt > 0
        ):

            raw_velocity_y = (
                movement_y
                /
                dt
            )


            raw_velocity_total = (
                total_movement
                /
                dt
            )

        else:

            raw_velocity_y = 0.0

            raw_velocity_total = 0.0


        # EMA smoothing

        alpha = (
            self.VELOCITY_SMOOTHING
        )


        self.smoothed_velocity_y = (

            alpha
            *
            raw_velocity_y

            +

            (1 - alpha)
            *
            self.smoothed_velocity_y

        )


        self.smoothed_velocity_total = (

            alpha
            *
            raw_velocity_total

            +

            (1 - alpha)
            *
            self.smoothed_velocity_total

        )


        velocity_y = (
            self.smoothed_velocity_y
        )


        velocity_total = (
            self.smoothed_velocity_total
        )


        self.previous_bottle_pos = (
            self.bottle_pos
        )


        self.previous_frame_time = (
            current_time
        )


        # ====================================================
        # PERSON
        # ====================================================

        person, nearest_person_distance = (
            self.nearest_person(
                self.bottle_pos,
                persons
            )
        )


        scale = (
            self.get_scale_factor(
                person
            )
        )


        effective_near = (
            self.NEAR_DISTANCE
            *
            scale
        )


        effective_far = (
            self.FAR_DISTANCE
            *
            scale
        )


        effective_downward_velocity = (
            self.DOWNWARD_VELOCITY
            *
            scale
        )


        effective_still_velocity = (
            self.STILL_VELOCITY
            *
            scale
        )


        effective_min_hold_displacement = (
            self.MIN_HOLD_DISPLACEMENT
            *
            scale
        )


        # ====================================================
        # WAITING
        # ====================================================

        if (
            self.state
            ==
            "WAITING"
        ):

            if (
                nearest_person_distance
                <
                effective_near
            ):

                if (
                    self.near_start
                    is None
                ):

                    self.near_start = (
                        current_time
                    )

                elif (
                    current_time
                    -
                    self.near_start
                    >=
                    self.NEAR_TIME
                ):

                    self.state = (
                        "HOLDING"
                    )

                    self.holding_start_pos = (
                        self.bottle_pos
                    )

                    self.max_hold_displacement = (
                        0.0
                    )

                    print(
                        "Bottle is near person."
                    )

            else:

                self.near_start = None


        # ====================================================
        # HOLDING
        # ====================================================

        elif (
            self.state
            ==
            "HOLDING"
        ):

            # Track bottle movement
            if (
                self.holding_start_pos
                is not None
            ):

                displacement = (
                    self.distance(
                        self.bottle_pos,
                        self.holding_start_pos
                    )
                )


                self.max_hold_displacement = max(

                    self.max_hold_displacement,

                    displacement

                )


            bottle_moving_down = (

                velocity_y
                >
                effective_downward_velocity

            )


            bottle_far = (

                nearest_person_distance
                >
                effective_far

            )


            hold_confirmed = (

                self.max_hold_displacement
                >=
                effective_min_hold_displacement

            )


            valid_release = (

                bottle_moving_down

                or

                (
                    bottle_far
                    and
                    hold_confirmed
                )

            )


            if valid_release:

                if (
                    self.separation_start
                    is None
                ):

                    self.separation_start = (
                        current_time
                    )

                elif (

                    current_time
                    -
                    self.separation_start
                    >=
                    self.SEPARATION_TIME

                ):

                    self.state = (
                        "DROPPED"
                    )

                    self.stationary_start = (
                        None
                    )

                    self.person_away_start = (
                        None
                    )

                    print(
                        "Bottle separated."
                    )

            else:

                self.separation_start = None


                if (
                    bottle_far
                    and
                    not hold_confirmed
                ):

                    if (
                        self.person_away_start
                        is None
                    ):

                        self.person_away_start = (
                            current_time
                        )

                    elif (

                        current_time
                        -
                        self.person_away_start
                        >=
                        self.SEPARATION_TIME * 2

                    ):

                        self.state = (
                            "WAITING"
                        )

                        self.near_start = None

                        self.person_away_start = (
                            None
                        )

                        print(
                            "No genuine hold detected."
                        )

                else:

                    self.person_away_start = (
                        None
                    )


        # ====================================================
        # DROPPED
        # ====================================================

        elif (
            self.state
            ==
            "DROPPED"
        ):

            # Bottle stationary
            if (
                velocity_total
                <=
                effective_still_velocity
            ):

                if (
                    self.stationary_start
                    is None
                ):

                    self.stationary_start = (
                        current_time
                    )

            else:

                self.stationary_start = (
                    None
                )


            # Person away
            if (

                not persons

                or

                nearest_person_distance
                >
                effective_far

            ):

                if (
                    self.person_away_start
                    is None
                ):

                    self.person_away_start = (
                        current_time
                    )

            else:

                self.person_away_start = (
                    None
                )


            bottle_stationary = (

                self.stationary_start
                is not None

                and

                current_time
                -
                self.stationary_start
                >=
                self.STATIONARY_TIME

            )


            person_away = (

                self.person_away_start
                is not None

                and

                current_time
                -
                self.person_away_start
                >=
                self.PERSON_AWAY_TIME

            )


            if (
                bottle_stationary
                and
                person_away
            ):

                self.state = (
                    "LITTERING"
                )


                self.alert_time = (
                    current_time
                )


                new_incident_id = (
                    self.create_incident(
                        display
                    )
                )


        # ====================================================
        # LITTERING
        # ====================================================

        elif (
            self.state
            ==
            "LITTERING"
        ):

            cv2.putText(

                display,

                "!!! SUSPECTED LITTERING !!!",

                (30, 240),

                cv2.FONT_HERSHEY_SIMPLEX,

                1,

                (0, 0, 255),

                4

            )


            cv2.putText(

                display,

                "Incident recorded",

                (30, 280),

                cv2.FONT_HERSHEY_SIMPLEX,

                0.8,

                (0, 0, 255),

                2

            )


        # ====================================================
        # DEBUG
        # ====================================================

        if math.isinf(
            nearest_person_distance
        ):

            distance_text = "N/A"

        else:

            distance_text = str(

                int(
                    nearest_person_distance
                )

            )


        cv2.putText(

            display,

            (
                f"Distance: "
                f"{distance_text} "
                f"(scale {scale:.2f})"
            ),

            (30, 80),

            cv2.FONT_HERSHEY_SIMPLEX,

            0.7,

            (255, 255, 255),

            2

        )


        cv2.putText(

            display,

            (
                f"Vel Y: "
                f"{int(velocity_y)} px/s"
            ),

            (30, 110),

            cv2.FONT_HERSHEY_SIMPLEX,

            0.7,

            (255, 255, 255),

            2

        )


        cv2.putText(

            display,

            (
                f"Vel Total: "
                f"{int(velocity_total)} px/s"
            ),

            (30, 140),

            cv2.FONT_HERSHEY_SIMPLEX,

            0.7,

            (255, 255, 255),

            2

        )


        cv2.putText(

            display,

            (
                f"Hold disp: "
                f"{int(self.max_hold_displacement)}px"
            ),

            (30, 170),

            cv2.FONT_HERSHEY_SIMPLEX,

            0.7,

            (255, 255, 255),

            2

        )


        cv2.putText(

            display,

            (
                f"Camera: "
                f"{self.camera_id}"
            ),

            (30, 200),

            cv2.FONT_HERSHEY_SIMPLEX,

            0.7,

            (255, 255, 255),

            2

        )


        self.draw_status(
            display
        )


        return (
            display,
            new_incident_id
        )


# ============================================================
# ARGUMENTS
# ============================================================

def parse_args():

    parser = argparse.ArgumentParser(
        description=(
            "AI Smart Littering Detection"
        )
    )


    parser.add_argument(

        "--source",

        default="0",

        help=(
            "Camera index "
            "(0 for laptop camera) "
            "or video file path"
        )

    )


    parser.add_argument(

        "--camera-id",

        default="Camera 01",

        help="Camera identifier"

    )


    parser.add_argument(

        "--model",

        default="yolo11n.pt",

        help="YOLO model weights"

    )


    parser.add_argument(

        "--conf",

        type=float,

        default=0.25,

        help=(
            "Person detection confidence"
        )

    )


    parser.add_argument(

        "--bottle-conf",

        type=float,

        default=0.35,

        help=(
            "Bottle detection confidence"
        )

    )


    parser.add_argument(

        "--min-hold-displacement",

        type=float,

        default=40,

        help=(
            "Minimum bottle movement"
            " while held"
        )

    )


    parser.add_argument(

        "--reference-person-height",

        type=float,

        default=500,

        help=(
            "Reference person bounding-box"
            " height"
        )

    )


    parser.add_argument(

        "--disable-scale-adaptive",

        action="store_true",

        help=(
            "Disable scale-adaptive thresholds"
        )

    )


    parser.add_argument(

        "--velocity-smoothing",

        type=float,

        default=0.6,

        help=(
            "Velocity EMA smoothing factor"
        )

    )


    parser.add_argument(

        "--output-dir",

        default="evidence",

        help="Evidence output directory"

    )


    return parser.parse_args()


# ============================================================
# MAIN
# ============================================================

def main():

    args = parse_args()


    # --------------------------------------------------------
    # Source
    # --------------------------------------------------------

    if args.source.isdigit():

        source = int(
            args.source
        )

    else:

        source = args.source


    # --------------------------------------------------------
    # Model
    # --------------------------------------------------------

    print(
        "Loading YOLO model..."
    )


    try:

        model = YOLO(
            args.model
        )

    except Exception as error:

        print(
            "ERROR loading YOLO:",
            error
        )

        return


    # --------------------------------------------------------
    # Camera
    # --------------------------------------------------------

    camera = cv2.VideoCapture(
        source
    )


    if not camera.isOpened():

        print(
            "ERROR: Could not open camera."
        )

        return


    # Use a smaller capture size
    # to reduce CPU load.
    camera.set(
        cv2.CAP_PROP_FRAME_WIDTH,
        854
    )

    camera.set(
        cv2.CAP_PROP_FRAME_HEIGHT,
        480
    )


    # --------------------------------------------------------
    # Detector
    # --------------------------------------------------------

    detector = LitteringDetector(

        camera_id=args.camera_id,

        evidence_dir=args.output_dir,

        person_conf=args.conf,

        bottle_conf=args.bottle_conf,

        min_hold_displacement=(
            args.min_hold_displacement
        ),

        reference_person_height=(
            args.reference_person_height
        ),

        scale_adaptive=(
            not args.disable_scale_adaptive
        ),

        velocity_smoothing=(
            args.velocity_smoothing
        )

    )


    # --------------------------------------------------------
    # Recorder
    # --------------------------------------------------------

    recorder = EvidenceRecorder(

        output_dir=args.output_dir

    )


    # --------------------------------------------------------
    # Heartbeat
    # --------------------------------------------------------

    stop_heartbeat = (
        threading.Event()
    )


    heartbeat_thread = threading.Thread(

        target=heartbeat_loop,

        args=(

            args.camera_id,

            stop_heartbeat

        ),

        daemon=True

    )


    heartbeat_thread.start()


    # --------------------------------------------------------
    # YOLO confidence
    # --------------------------------------------------------

    yolo_conf = min(

        args.conf,

        args.bottle_conf

    )


    # --------------------------------------------------------
    # Startup
    # --------------------------------------------------------

    print()

    print(
        "========================================"
    )

    print(
        "AI SMART LITTERING DETECTION"
    )

    print(
        "========================================"
    )

    print(
        "Camera ID:",
        args.camera_id
    )

    print(
        "Location:",
        detector.camera_config[
            "location"
        ]
    )

    print(
        "Resolution:",
        "854x480"
    )

    print(
        "Press Q to quit."
    )

    print(
        "========================================"
    )

    print()


    try:

        while True:

            # =================================================
            # READ FRAME
            # =================================================

            success, frame = (
                camera.read()
            )


            if not success:

                print(
                    "Camera frame error."
                )

                break


            # =================================================
            # ROLLING BUFFER
            # =================================================

            # This does NOT encode video.
            recorder.add_frame(
                frame
            )


            # =================================================
            # YOLO
            # =================================================

            results = model.track(

                frame,

                conf=yolo_conf,

                classes=[

                    PERSON_CLASS_ID,

                    BOTTLE_CLASS_ID

                ],

                persist=True,

                imgsz=640,

                verbose=False

            )


            # =================================================
            # DETECTION
            # =================================================

            display, new_incident_id = (
                detector.process(
                    frame,
                    results
                )
            )


            # =================================================
            # START EVENT RECORDING
            # =================================================

            if (
                new_incident_id
                is not None
            ):

                recorder.start_event(
                    new_incident_id
                )


            # =================================================
            # DISPLAY
            # =================================================

            cv2.imshow(

                "AI Smart Littering Detection",

                display

            )


            # =================================================
            # QUIT
            # =================================================

            key = (
                cv2.waitKey(1)
                &
                0xFF
            )


            if key == ord("q"):

                print(
                    "Closing program..."
                )

                break


    except KeyboardInterrupt:

        print(
            "Interrupted by user."
        )


    except Exception as error:

        print()

        print(
            "PROGRAM ERROR:"
        )

        print(
            error
        )

        print()


    finally:

        stop_heartbeat.set()

        camera.release()

        cv2.destroyAllWindows()

        print(
            "Camera released."
        )


# ============================================================
# START
# ============================================================

if __name__ == "__main__":

    main()