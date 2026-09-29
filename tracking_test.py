

import cv2
import time
from ultralytics import YOLO

def main():
    # -----------------------------
    # Configuration
    # -----------------------------
    MODEL_NAME = "yolo11n.pt"
    CAMERA_ID = 0
    TARGET_CLASSES = [0, 39]  # 0: person, 39: bottle
    
    # -----------------------------
    # Initialization
    # -----------------------------
    try:
        model = YOLO(MODEL_NAME)
    except Exception as e:
        print(f"ERROR: Failed to load model '{MODEL_NAME}'.\nDetails: {e}")
        return

    camera = cv2.VideoCapture(CAMERA_ID)
    
    # Optional: Force a specific resolution for consistent performance
    # camera.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
    # camera.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

    if not camera.isOpened():
        print(f"ERROR: Camera {CAMERA_ID} could not be opened.")
        return

    print("Tracking started!")
    print("Press 'Q' in the video window to quit.")

    prev_time = 0

    # -----------------------------
    # Main Loop
    # -----------------------------
    try:
        while True:
            success, frame = camera.read()
            if not success:
                print("WARNING: Dropped frame or camera disconnected.")
                break

            # YOLO tracking
            results = model.track(
                frame,
                persist=True,
                classes=TARGET_CLASSES,
                verbose=False
            )

            # Generate annotated frame
            annotated_frame = results[0].plot()

            # Calculate and display FPS
            current_time = time.time()
            fps = 1 / (current_time - prev_time) if prev_time > 0 else 0
            prev_time = current_time

            cv2.putText(
                annotated_frame,
                f"FPS: {int(fps)}",
                (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX,
                1.0,
                (0, 255, 0), # Green text
                2,
                cv2.LINE_AA
            )

            # Display the output
            cv2.imshow("Littering Detection - Tracking", annotated_frame)

            # Exit condition
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
                
    except KeyboardInterrupt:
        print("\nTracking interrupted by user (Ctrl+C).")
    finally:
        # -----------------------------
        # Cleanup (Guaranteed Execution)
        # -----------------------------
        camera.release()
        cv2.destroyAllWindows()
        print("Camera released and windows closed.")

if __name__ == "__main__":
    main()
