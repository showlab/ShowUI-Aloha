import requests
import json
import base64

# This script is for testing the /generate_action endpoint of the server (app.py).


def create_dummy_screenshot(path: str) -> str:
    """Creates a minimal 1x1 black pixel PNG and base64 encodes it."""
    with open(path, "rb") as image_file:
        return base64.b64encode(image_file.read()).decode('utf-8')

def test_generate_action():
    """Sends a test request to the /generate_action endpoint."""
    # --- Configuration ---
    # The server from app.py is expected to be running on this address.
    url = "http://127.0.0.1:7887/generate_action"
    
    # Provide only trace_id now
    trace_id = "example_trace"
    
    # Task description for a computer use case.
    query = "Help me with my daily routine. I want to search for USD/SGD exchange rate."
    
    # A unique ID for this task execution.
    task_id = "test"
    
    # --- Payload Construction ---
    # This payload mimics the data sent from a client application.
    payload = {
        "task_id": task_id,
        "trace_id": trace_id,
        "query": query,
        "mode": "teach",
        "screenshot": create_dummy_screenshot("examples/chrome.png"),
        "action_history": []
    }
    
    headers = {'Content-Type': 'application/json'}
    
    # --- Sending Request ---
    print(f"Sending request to {url} with task_id: {task_id}")
    
    try:
        # Set a timeout for the request
        response = requests.post(url, data=json.dumps(payload), headers=headers, timeout=180)
        
        # --- Handling Response ---
        print(f"\n--- Response ---")
        print(f"Status Code: {response.status_code}")
        
        if response.ok:
            response_data = response.json()
            print("Response JSON:")
            print(json.dumps(response_data, indent=2))
        else:
            print("Error Response Body:")
            try:
                # Try to print JSON error response if possible
                print(json.dumps(response.json(), indent=2))
            except json.JSONDecodeError:
                # Otherwise, print raw text
                print(response.text)

    except requests.exceptions.RequestException as e:
        print(f"\nAn error occurred while making the request: {e}")
        print("Please ensure the server at 'app.py' is running and accessible.")

if __name__ == "__main__":
    test_generate_action() 