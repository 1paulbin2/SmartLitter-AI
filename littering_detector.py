import cv2
import math
import time
from ultralytics import YOLO


class LitteringDetector:
    def __init__(self):

        # -----------------------------
        # Detection thresholds
        # -----------------------------

        self.NEAR_DISTANCE = 180
        self.FAR_DISTANCE = 260

        self.STATIONARY_MOVEMENT = 5

        # Number of frames required
        self.SEPARATION_FRAMES_REQUIRED = 10
        self.STATIONARY_FRAMES_REQUIRED = 20

        # -----------------------------
        # State
        # -----------------------------

        self.state = "WAITING"

        self.target_person_id = None
        self.target_bottle_id = None

        self.last_bottle_pos = None

        self.separated_frames = 0
        self.stationary_frames = 0

        self.alert_time = 0
        self.reset_cooldown = 5

        # Latest frame for evidence
        self.latest_frame = None

    # -----------------------------------------
    # Reset detector
    # -----------------------------------------

    def reset_state(self):

        self.state = "WAITING"

        self.target_person_id = None
        self.target_bottle_id = None

        self.last_bottle_pos = None

        self.separated_frames = 0
        self.stationary_frames = 0

    # -----------------------------------------
    # Distance
    # -----------------------------------------

    def calculate_distance(self, p1, p2):

        return math.sqrt(
            (p1[0] - p2[0]) ** 2 +
            (p1[1] - p2[1]) ** 2
        )

    # -----------------------------------------
    # Process frame
    # -----------------------------------------

    def process_frame(self, frame, results):

        self.latest_frame = frame.copy()

        display = results[0].plot()

        persons = {}
        bottles = {}

        # -----------------------------------------
        # Read detections
        # -----------------------------------------

        if results[0].boxes.id is not None:

            boxes = results[0].boxes.xyxy.cpu().numpy()
            ids = results[0].boxes.id.cpu().numpy()
            classes = results[0].boxes.cls.cpu().numpy()

            for box, track_id, class_id in zip(
                boxes,
                ids,
                classes
            ):

                x1, y1, x2, y2 = box

                cx = int((x1 + x2) / 2)
                cy = int((y1 + y2) / 2)

                track_id = int(track_id)
                class_id = int(class_id)

                if class_id == 0:

                    persons[track_id] = (cx, cy)

                elif class_id == 39:

                    bottles[track_id] = (cx, cy)

        # -----------------------------------------
        # Default values
        # -----------------------------------------

        distance = 0
        bottle_movement = 0

        # =========================================
        # STATE 1: WAITING
        # =========================================

        if self.state == "WAITING":

            for pid, p_pos in persons.items():

                for bid, b_pos in bottles.items():

                    dist = self.calculate_distance(
                        p_pos,
                        b_pos
                    )

                    if dist < self.NEAR_DISTANCE:

                        self.state = "HOLDING"

                        self.target_person_id = pid
                        self.target_bottle_id = bid

                        self.last_bottle_pos = b_pos

                        break

                if self.state == "HOLDING":
                    break

        # =========================================
        # STATE 2: HOLDING
        # =========================================

        elif self.state == "HOLDING":

            # Bottle MUST still exist
            if self.target_bottle_id not in bottles:

                self.reset_state()

            else:

                b_pos = bottles[self.target_bottle_id]

                self.last_bottle_pos = (
                    self.last_bottle_pos
                    if self.last_bottle_pos is not None
                    else b_pos
                )

                # Person may still exist
                if self.target_person_id in persons:

                    p_pos = persons[self.target_person_id]

                    distance = self.calculate_distance(
                        p_pos,
                        b_pos
                    )

                    # Bottle moved
                    bottle_movement = self.calculate_distance(
                        b_pos,
                        self.last_bottle_pos
                    )

                    # Update position
                    self.last_bottle_pos = b_pos

                    # Person and bottle separating
                    if distance > self.FAR_DISTANCE:

                        self.state = "SEPARATING"

                        self.separated_frames = 0

                else:

                    # Person disappeared before separation
                    # Don't immediately call it littering
                    self.reset_state()

        # =========================================
        # STATE 3: SEPARATING
        # =========================================

        elif self.state == "SEPARATING":

            # Bottle MUST remain visible
            if self.target_bottle_id not in bottles:

                self.reset_state()

            else:

                b_pos = bottles[self.target_bottle_id]

                # Person still visible?
                if self.target_person_id in persons:

                    p_pos = persons[self.target_person_id]

                    distance = self.calculate_distance(
                        p_pos,
                        b_pos
                    )

                else:

                    # Person left frame
                    # Treat as strong separation
                    distance = self.FAR_DISTANCE + 100

                # Bottle movement
                if self.last_bottle_pos:

                    bottle_movement = self.calculate_distance(
                        b_pos,
                        self.last_bottle_pos
                    )

                self.last_bottle_pos = b_pos

                # -------------------------------------
                # Check continued separation
                # -------------------------------------

                if distance > self.FAR_DISTANCE:

                    self.separated_frames += 1

                else:

                    # Person came back
                    self.state = "HOLDING"

                    self.separated_frames = 0

                # -------------------------------------
                # Separation confirmed
                # -------------------------------------

                if (
                    self.separated_frames
                    >= self.SEPARATION_FRAMES_REQUIRED
                ):

                    self.state = "DROPPED"

                    self.stationary_frames = 0

        # =========================================
        # STATE 4: DROPPED
        # =========================================

        elif self.state == "DROPPED":

            # IMPORTANT:
            # We only need the BOTTLE now.

            if self.target_bottle_id not in bottles:

                # Bottle disappeared from camera
                self.reset_state()

            else:

                b_pos = bottles[self.target_bottle_id]

                if self.last_bottle_pos:

                    bottle_movement = self.calculate_distance(
                        b_pos,
                        self.last_bottle_pos
                    )

                self.last_bottle_pos = b_pos

                # -------------------------------------
                # Bottle stationary?
                # -------------------------------------

                if (
                    bottle_movement
                    < self.STATIONARY_MOVEMENT
                ):

                    self.stationary_frames += 1

                else:

                    self.stationary_frames = 0

                # -------------------------------------
                # Stationary long enough
                # -------------------------------------

                if (
                    self.stationary_frames
                    >= self.STATIONARY_FRAMES_REQUIRED
                ):

                    self.state = "LITTERING"

                    self.alert_time = time.time()

                    # Save evidence
                    filename = (
                        f"littering_"
                        f"{int(self.alert_time)}.jpg"
                    )

                    cv2.imwrite(
                        filename,
                        self.latest_frame
                    )

                    print("\n" + "=" * 50)

                    print(
                        "🚨 SUSPECTED LITTERING DETECTED!"
                    )

                    print(
                        f"Evidence saved: {filename}"
                    )

                    print("=" * 50)

        # =========================================
        # STATE 5: LITTERING
        # =========================================

        elif self.state == "LITTERING":

            # Keep alert visible for cooldown
            if (
                time.time() - self.alert_time
                > self.reset_cooldown
            ):

                self.reset_state()

        # -----------------------------------------
        # Draw information
        # -----------------------------------------

        self.draw_ui(
            display,
            distance,
            bottle_movement
        )

        return display

    # -----------------------------------------
    # UI
    # -----------------------------------------

    def draw_ui(
        self,
        display,
        distance,
        bottle_movement
    ):

        cv2.putText(
            display,
            f"State: {self.state}",
            (30, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            1,
            (0, 255, 255),
            3
        )

        cv2.putText(
            display,
            f"Distance: {int(distance)}",
            (30, 80),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2
        )

        cv2.putText(
            display,
            f"Bottle movement: {int(bottle_movement)}",
            (30, 110),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2
        )

        if self.state == "LITTERING":

            cv2.putText(
                display,
                "!!! SUSPECTED LITTERING !!!",
                (30, 160),
                cv2.FONT_HERSHEY_SIMPLEX,
                1,
                (0, 0, 255),
                4
            )

            cv2.putText(
                display,
                "Evidence captured",
                (30, 200),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                (0, 0, 255),
                2
            )


# =============================================
# MAIN
# =============================================

def main():

    print("Loading YOLO...")

    model = YOLO("yolo11n.pt")

    camera = cv2.VideoCapture(0)

    if not camera.isOpened():

        print("ERROR: Camera could not be opened.")

        return

    detector = LitteringDetector()

    print()
    print("AI Smart Littering Detection Started")
    print("--------------------------------------")
    print("Press Q to quit.")

    while True:

        success, frame = camera.read()

        if not success:

            print("ERROR: Failed to read camera.")

            break

        results = model.track(
            frame,
            persist=True,
            classes=[0, 39],
            verbose=False
        )

        display = detector.process_frame(
            frame,
            results
        )

        cv2.imshow(
            "AI Smart Littering Detection",
            display
        )

        if cv2.waitKey(1) & 0xFF == ord("q"):

            break

    camera.release()

    cv2.destroyAllWindows()


if __name__ == "__main__":

    main()