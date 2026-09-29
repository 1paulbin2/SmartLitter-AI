import cv2
from ultralytics import YOLO
import math

class MovementTracker:
    def __init__(self):
        self.previous_positions = {}
        self.smoothed_movements = {}
        # Smoothing factor for Exponential Moving Average (0.0 to 1.0)
        # Lower = smoother but lags slightly. Higher = faster response but more jitter.
        self.ema_alpha = 0.3 
        # Ignore micro-movements caused by bounding box jitter (in pixels)
        self.jitter_threshold = 2.0 

    def process_frame(self, results):
        # Plot boxes but hide YOLO's default labels to prevent overlapping text
        annotated = results[0].plot(labels=False)
        
        current_ids = set()

        if results[0].boxes.id is not None:
            boxes = results[0].boxes.xyxy.cpu().numpy()
            ids = results[0].boxes.id.cpu().numpy()
            classes = results[0].boxes.cls.cpu().numpy()

            for box, track_id, class_id in zip(boxes, ids, classes):
                x1, y1, x2, y2 = box
                cx = int((x1 + x2) / 2)
                cy = int((y1 + y2) / 2)
                track_id = int(track_id)
                
                current_ids.add(track_id)

                # 1. Calculate raw frame-to-frame movement
                raw_movement = 0.0
                if track_id in self.previous_positions:
                    old_x, old_y = self.previous_positions[track_id]
                    raw_movement = math.sqrt((cx - old_x) ** 2 + (cy - old_y) ** 2)
                    
                    # Filter out tiny jitters
                    if raw_movement < self.jitter_threshold:
                        raw_movement = 0.0

                self.previous_positions[track_id] = (cx, cy)

                # 2. Apply Exponential Moving Average (EMA) for smooth readings
                if track_id in self.smoothed_movements:
                    current_smoothed = self.smoothed_movements[track_id]
                    new_smoothed = (self.ema_alpha * raw_movement) + ((1 - self.ema_alpha) * current_smoothed)
                    self.smoothed_movements[track_id] = new_smoothed
                else:
                    self.smoothed_movements[track_id] = raw_movement

                # 3. Draw clean UI
                display_movement = self.smoothed_movements[track_id]
                object_name = "Person" if int(class_id) == 0 else "Bottle"
                
                # Determine color based on movement (Red if moving fast, Green if still)
                color = (0, 0, 255) if display_movement > 5.0 else (0, 255, 0)

                cv2.putText(
                    annotated,
                    f"{object_name} {track_id} | Spd: {display_movement:.1f}",
                    (int(x1), int(y1) - 10),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.6,
                    color,
                    2
                )

        # 4. Memory Cleanup: Remove IDs that are no longer in the frame
        self._cleanup_missing_ids(current_ids)

        return annotated

    def _cleanup_missing_ids(self, current_ids):
        """Prevents memory leaks by deleting data for objects that left the screen."""
        missing_ids = [tid for tid in self.previous_positions.keys() if tid not in current_ids]
        for tid in missing_ids:
            del self.previous_positions[tid]
            if tid in self.smoothed_movements:
                del self.smoothed_movements[tid]


def main():
    model = YOLO("yolo11n.pt")
    camera = cv2.VideoCapture(0)

    if not camera.isOpened():
        print("ERROR: Camera could not be opened.")
        return

    tracker = MovementTracker()

    print("Movement tracking started.")
    print("Press Q to quit.")

    while True:
        success, frame = camera.read()
        if not success:
            break

        results = model.track(frame, persist=True, classes=[0, 39], verbose=False)
        
        annotated_frame = tracker.process_frame(results)

        cv2.imshow("Movement Analysis", annotated_frame)

        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    camera.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()