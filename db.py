import requests  # Make sure to import the requests library
from utils import load_api_key
from google.cloud import firestore  

db = firestore.Client()

# Dify 知识库
dataset_id = '5d7b8d77-ef7e-46e5-b583-be8368718d83'

def create_document_vector(title, text):
    """Create a document in the specified dataset using the provided text."""
    api_key = load_api_key('dify_datasets_api_key')  # Load the API key
    url = f'https://api.dify.ai/v1/datasets/{dataset_id}/document/create-by-text'
    
    headers = {
        'Authorization': f'Bearer {api_key}',
        'Content-Type': 'application/json'
    }
    
    data = {
        "name": title,
        "text": text,
        "indexing_technique": "high_quality",
        "process_rule": {
            "mode": "automatic"
        }
    }
    
    response = requests.post(url, headers=headers, json=data)
    # {
    #     "document": {
    #         "id": "",
    #         "position": 1,
    #         "data_source_type": "upload_file",
    #         "data_source_info": {
    #             "upload_file_id": ""
    #         },
    #         "dataset_process_rule_id": "",
    #         "name": "text.txt",
    #         "created_from": "api",
    #         "created_by": "",
    #         "created_at": 1695690280,
    #         "tokens": 0,
    #         "indexing_status": "waiting",
    #         "error": null,
    #         "enabled": true,
    #         "disabled_at": null,
    #         "disabled_by": null,
    #         "archived": false,
    #         "display_status": "queuing",
    #         "word_count": 0,
    #         "hit_count": 0,
    #         "doc_form": "text_model"
    #     },
    #     "batch": ""
    # }
    if response.status_code == 200:
        return response.json()
    else:
        return {
            'error': str(response.json())
        }
    
def create_document_db(document_data):
    """Save the document data to Firestore."""
    # Assuming you want to save the document under a collection named 'documents'
    write_time, doc_ref = db.collection('articles').add(document_data)

    return doc_ref.id # { 'id', 'path' }
