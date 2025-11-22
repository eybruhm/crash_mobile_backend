# core/services.py
import requests, os, qrcode, base64
from io import BytesIO

# Load the API Key from settings
GOOGLE_MAPS_API_KEY = os.getenv('GOOGLE_MAPS_API_KEY')

def generate_directions_and_qr(start_lat, start_lng, end_lat, end_lng):
    """
    Generates Google Maps URL, calls API (optional), and creates Base64 QR code.
    """
    if not GOOGLE_MAPS_API_KEY:
        raise ValueError("Google Maps API key is not configured.")

    # 1. Construct the Google Maps Directions URL
    # We use a universal link structure for direct use in mobile browsers via QR code.
    # Format: https://www.google.com/maps/dir/Start_LAT,Start_LNG/End_LAT,End_LNG
    maps_url = (
        f"https://www.google.com/maps/dir/{start_lat},{start_lng}/{end_lat},{end_lng}"
    )

    # 2. OPTIONAL: Call Google Directions API for ETA/Distance (requires API Key)
    # Note: This consumes an API credit. We focus on the URL for the QR code.
    # You can add the ETA/Distance logic here later.

    # 3. Generate QR Code Image (in memory)
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=10,
        border=4,
    )
    qr.add_data(maps_url)
    qr.make(fit=True)

    # Create the image using Pillow
    img = qr.make_image(fill_color="black", back_color="white")

    # Save the image data into a buffer (BytesIO)
    buffer = BytesIO()
    img.save(buffer, format="PNG")

    # 4. Convert to Base64
    base64_encoded_data = base64.b64encode(buffer.getvalue()).decode()

    # Prepend the required Data URL header for HTML <img> tags
    qr_data_url = f"data:image/png;base64,{base64_encoded_data}"

    return {
        'directions_url': maps_url,
        'qr_code_base64': qr_data_url,
        # 'distance': 'X km', # Placeholder for optional API call result
        # 'duration': 'Y mins', # Placeholder for optional API call result
    }