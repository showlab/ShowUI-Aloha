import requests
import json
import base64
import logging


log = logging.getLogger(__name__)


def is_image_path(text):
    # Checking if the input text ends with typical image file extensions
    image_extensions = (".jpg", ".jpeg", ".png", ".gif", ".bmp", ".tiff", ".tif")
    if text.endswith(image_extensions):
        return True
    else:
        return False
    

def convert_screenshot_to_base64(screenshot_path):
    """
    Converts a screenshot file to a Base64-encoded string.

    Args:
        screenshot_path (str): Path to the screenshot file.

    Returns:
        str: Base64-encoded string of the image.
    """
    try:
        with open(screenshot_path, "rb") as image_file:
            base64_image = base64.b64encode(image_file.read()).decode("utf-8")
        return base64_image
    except FileNotFoundError:
        raise FileNotFoundError(f"The file at {screenshot_path} was not found.")
    except Exception as e:
        raise RuntimeError(f"An error occurred while converting the image: {e}")


def send_inference_request(payload, url: str = "http://localhost:7887/generate_action"):
    """
    Send payload to a locally deployed inference server and return its JSON.
    """
    
    payload["screenshot"] = convert_screenshot_to_base64(payload["screenshot_path"])
    del payload["screenshot_path"]

    # Set headers
    headers = {
        "Content-Type": "application/json"
    }
    
    # log.debug("sending payload %s", [f"{k}: {str(v)[:200]}" for k, v in payload.items() if k != "screenshot"])

    try:
        # Send POST request
        response = requests.post(url, json=payload, headers=headers)
        
        # Check if request was successful
        response.raise_for_status()
        
        # Parse response
        result = response.json()
        
        log.info("Status: %s", result.get("status"))
        if "generated_action" in result:
            log.info("Generated Action: %s", json.dumps(result["generated_action"], indent=2))
        
        return result

    except requests.exceptions.RequestException as e:
        log.error("Error making request: %s", e)
        if hasattr(e.response, 'text'):
            log.error("Server response: %s", e.response.text)
        return None
