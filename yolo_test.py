import cv2
from ultralytics import YOLO

# Load a small YOLO model
model = YOLO("yolo11n.pt")

camera = cv2.VideoCapture(0)

if not camera.isOpened():
    print("ERROR: Camera could not be opened.")
    exit()

print("AI Camera Started!")
print("Press Q to close.")

while True:

    success, frame = camera.read()

    if not success:
        break

    # Run YOLO
    results = model(frame, verbose=False)

    # Draw detected objects
    annotated_frame = results[0].plot()

    cv2.imshow("Smart Littering AI", annotated_frame)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

camera.release()
cv2.destroyAllWindows()