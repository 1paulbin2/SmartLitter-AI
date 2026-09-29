import os
import smtplib
from email.message import EmailMessage

from dotenv import load_dotenv


# Load .env
load_dotenv()


SMTP_SERVER = os.getenv(
    "SMTP_SERVER",
    "smtp.gmail.com"
)

SMTP_PORT = int(
    os.getenv(
        "SMTP_PORT",
        "587"
    )
)

SENDER_EMAIL = os.getenv(
    "SENDER_EMAIL"
)

SENDER_PASSWORD = os.getenv(
    "SENDER_PASSWORD"
)

AUTHORITY_EMAIL = os.getenv(
    "AUTHORITY_EMAIL"
)


def send_littering_alert(incident):
    """
    Send an email notification for a littering incident.

    Returns:
        True  -> email sent
        False -> email failed
    """

    if not SENDER_EMAIL:
        print("ERROR: SENDER_EMAIL not configured.")
        return False

    if not SENDER_PASSWORD:
        print("ERROR: SENDER_PASSWORD not configured.")
        return False

    if not AUTHORITY_EMAIL:
        print("ERROR: AUTHORITY_EMAIL not configured.")
        return False

    incident_id = incident.get(
        "id",
        "Unknown"
    )

    camera = incident.get(
        "camera",
        "Unknown Camera"
    )

    location = incident.get(
        "location",
        "Unknown Location"
    )

    time_text = incident.get(
        "time",
        "Unknown"
    )

    waste = incident.get(
        "waste",
        "Unknown"
    )

    message = EmailMessage()

    message["Subject"] = (
        "🚨 Suspected Littering Detected"
    )

    message["From"] = SENDER_EMAIL

    message["To"] = AUTHORITY_EMAIL

    message.set_content(
        f"""
SMART LITTERING MONITORING SYSTEM

🚨 SUSPECTED LITTERING DETECTED

Incident ID: {incident_id}
Camera: {camera}
Location: {location}
Time: {time_text}
Waste: {waste}

Status:
Pending Verification

Please open the monitoring dashboard to
review the evidence and take appropriate action.

Smart Littering Monitoring System
"""
    )

    # Attach image evidence if available
    image_path = incident.get(
        "image",
        ""
    )

    if (
        image_path
        and
        os.path.exists(image_path)
    ):

        try:

            with open(
                image_path,
                "rb"
            ) as image_file:

                image_data = (
                    image_file.read()
                )

            message.add_attachment(
                image_data,
                maintype="image",
                subtype="jpeg",
                filename=os.path.basename(
                    image_path
                )
            )

        except Exception as error:

            print(
                "Could not attach image:",
                error
            )

    # Send email
    try:

        with smtplib.SMTP(
            SMTP_SERVER,
            SMTP_PORT
        ) as server:

            server.starttls()

            server.login(
                SENDER_EMAIL,
                SENDER_PASSWORD
            )

            server.send_message(
                message
            )

        print(
            "✅ Authority email sent successfully."
        )

        return True

    except Exception as error:

        print(
            "❌ Email sending failed:"
        )

        print(
            error
        )

        return False


if __name__ == "__main__":

    # Test incident
    test_incident = {

        "id":
            "TEST-001",

        "camera":
            "Camera 01",

        "location":
            "VJEC Main Gate",

        "time":
            "2026-08-28 18:30:00",

        "waste":
            "Plastic Bottle",

        "image":
            ""

    }

    print(
        "Sending test email..."
    )

    send_littering_alert(
        test_incident
    )