import os
import json


def load_api_key(api_key_name):
    credentials_path = os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
    if not credentials_path:
        raise ValueError("GOOGLE_APPLICATION_CREDENTIALS environment variable is not set.")
    
    # Load the JSON credentials file
    with open(credentials_path, 'r') as file:
        credentials = json.load(file)
    
    return credentials.get(api_key_name)
