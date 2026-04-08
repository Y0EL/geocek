import requests
import json
import os

class GatekeeperLayer:
    """
    Acts as the first line of defense before the heavy analysis starts.
    Validates if an image is AI generated utilizing The Hive AI V3 API.
    """
    def __init__(self, api_key: str):
        self.api_key = api_key
        self.endpoint = "https://api.thehive.ai/api/v3/hive/ai-generated-and-deepfake-content-detection"





    def is_ai_generated(self, image_path: str) -> bool:
        """
        Sends the local image file to The Hive AI's synchronous endpoint.
        Returns True if the image is flagged as AI generated, False otherwise.
        """
        if not os.path.exists(image_path):
            return False

        headers = {
            "accept": "application/json",
            "authorization": f"Bearer {self.api_key}"
        }

        with open(image_path, "rb") as image_file:
            # V3 does not require extra data fields, only media
            files = {
                "media": (os.path.basename(image_path), image_file, "image/jpeg")
            }
            
            try:
                response = requests.post(
                    self.endpoint, 
                    headers=headers, 
                    files=files, 
                    timeout=15
                )

                if response.status_code != 200:



                    print(f"[!] Gatekeeper API Errror: {response.status_code} - {response.text}")
                    # Fail open so legitimate requests don't get fully blocked by an API outage
                    return False
                
                data = response.json()
                
                # Parse the response payload for The Hive AI Generated Detection classes
                if 'status' in data and len(data['status']) > 0:
                    task_response = data['status'][0].get('response', {})
                    outputs = task_response.get('output', [])
                else: 
                     # For the direct model endpoint, the output array is usually returned directly in the response root
                    outputs = data.get('output', [])

                for output in outputs:
                    for cls in output.get('classes', []):
                        class_name = cls.get('class', '').lower()
                        score = cls.get('score', cls.get('value', 0))
                        
                        if class_name == 'ai_generated' and score > 0.60:
                            print(f"[!] AI-generated detected: {class_name} = {score:.3f}")
                            return True
                return False
            except Exception as e:
                print(f"[!] Gatekeeper Connection Error: {e}")
                return False
