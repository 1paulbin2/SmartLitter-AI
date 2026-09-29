import cv2

camera = cv2.VideoCapture(0)

if not camera.isOpened():
    print("ERROR: Camera could not be opened.")
    exit()

print("Camera started successfully!")
print("Press Q to close.")

while True:
    success, frame = camera.read()

    if not success:
        print("Failed to read camera frame.")
        break

    cv2.imshow("Smart Littering - Camera Test", frame)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

camera.release()
cv2.destroyAllWindows()