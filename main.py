import os
import json
from flask import Flask, request, current_app, jsonify
from google.cloud import storage
import traceback
from youtube_utils import get_youtube_video_metadata, download_audio, transcribe_audio_with_diarization, test_gcs_connection, get_youtube_transcript
import db
from datetime import datetime


app = Flask(__name__)

BUCKET_NAME = 'keith_speech_to_text'
storage_client = storage.Client()
bucket = storage_client.bucket(BUCKET_NAME)

# Print all environment variables when the app starts
print("Starting Flask App with the following environment variables:")
for key, value in os.environ.items():
    print(f"{key}: {value}")

@app.route('/audio-file', methods=['GET'])
def audio_file_endpoint():
    """下载音频的端点，从视频 URL 返回签名 URL 和转录文本。"""
    video_url = request.args.get('url')
    return download_audio(video_url)

@app.route('/v', methods=['GET'])
def download_audio_endpoint():
    """下载音频的端点，从视频 URL 返回转录文本和其他视频信息。"""
    video_url = request.args.get('url')
    language_code = request.args.get('lang', 'en-US')  # en-US, zh-CN
    
    if not video_url:
        return {"error": "No URL provided"}, 400
    
    try:
        metadata = get_youtube_video_metadata(video_url)
        transcription_result = get_youtube_transcript(video_url)

        signed_url = ""
        gcs_uri = ""
        
        if 'error' in transcription_result:
            current_app.logger.info("Transcribing from audio")
            signed_url = download_audio(video_url)
            # Extract the blob name from the signed URL
            blob_name = signed_url.split('/')[-1].split('?')[0]
            gcs_uri = f'gs://{BUCKET_NAME}/audio/{blob_name}'
            
            # Generate transcription
            transcription_result = transcribe_audio_with_diarization(gcs_uri)
        else:
            current_app.logger.info("Found native transcripts")
            
        return {
            "download_url": signed_url,
            "gcs_uri": gcs_uri,
            "formatted_transcript": transcription_result['formatted_transcript'],
            # "raw_transcript": transcription_result['raw_transcript'],
            "title": metadata['title'],
            "description": metadata['description'],
            "thumbnails": metadata['thumbnails'],
            "channel_title": metadata['channel_title'],
            "published_at": metadata['published_at'],
            "tags": metadata['tags'],
            "language": metadata['language']
        }
    
    except Exception as e:
        current_app.logger.error(f"Endpoint error: {str(e)}")
        return {
            "error": str(e),
            "traceback": traceback.format_exc()
        }, 500

@app.route('/test-connection', methods=['GET'])
def test_connection_endpoint():
    """测试与 Google Cloud Storage 的连接的端点。"""
    try:
        result = test_gcs_connection()
        if "error" in result.get("status", ""):
            return result, 500
        return result
    except Exception as e:
        current_app.logger.error(f"Test connection endpoint error: {str(e)}")
        return {
            "status": "error",
            "message": str(e),
            "traceback": traceback.format_exc()
        }, 500

@app.route('/transcribe', methods=['GET'])
def transcribe_endpoint():
    """从视频 URL 返回官方字幕或转录文本"""
    video_url = request.args.get('url')
    
    if not video_url:
        return {"error": "No URL provided"}, 400
    
    try:
        transcription_result = get_youtube_transcript(video_url)

        signed_url = ""
        gcs_uri = ""
        
        if 'error' in transcription_result:
            current_app.logger.info("Transcribing from audio")
            signed_url = download_audio(video_url)
            # Extract the blob name from the signed URL
            blob_name = signed_url.split('/')[-1].split('?')[0]
            gcs_uri = f'gs://{BUCKET_NAME}/audio/{blob_name}'
            
            # Generate transcription
            transcription_result = transcribe_audio_with_diarization(gcs_uri)
        else:
            current_app.logger.info("Found native transcripts")
            
        return {
            "download_url": signed_url,
            "gcs_uri": gcs_uri,
            "formatted_transcript": transcription_result['formatted_transcript'],
            # "raw_transcript": transcription_result['raw_transcript'],
        }
    
    except Exception as e:
        current_app.logger.error(f"Endpoint error: {str(e)}")
        return {
            "error": str(e),
            "traceback": traceback.format_exc()
        }, 500


@app.route('/video-metadata', methods=['GET'])
def video_metadata_endpoint():
    """获取 YouTube 视频的元数据。"""
    video_url = request.args.get('url')
    
    if not video_url:
        return {"error": "No URL provided"}, 400
    
    metadata = get_youtube_video_metadata(video_url)
    return metadata

@app.route('/video-transcript', methods=['GET'])
def video_transcript_endpoint():
    """获取 YouTube 视频的转录文本。"""
    video_url = request.args.get('url')
    return get_youtube_transcript(video_url)

@app.route('/create-document', methods=['POST'])
def create_document_endpoint():
    """Endpoint to create a document vector from the provided text."""
    # Extract "text" from the POST body
    data = request.form  # Get the JSON data from the request
    content = data.get('content')  # Extract the "text" field
    title = data.get('title')  # Extract the "text" field
    llm_processed = data.get('llm_processed', '')
    metadata = data.get('metadata', {})  # Use an empty dict if metadata is not provided
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)  # Attempt to parse the JSON string into a dictionary
        except json.JSONDecodeError:
            pass  # Keep metadata as is if parsing fails
    user_id = data.get('user_id', 0)

    if not content:
        return {'error': 'Content is required'}, 400 

    if not title:
        return {'error': 'Title is required'}, 400 

    document = {
        "title": title,
        "user_id": user_id,
        "content": content,
        "metadata": metadata,
        "llm_processed": llm_processed,
        "timestamp": datetime.now()
    }
    # Call the create_document_vector function with the extracted text
    document_vector = db.create_document_vector(title, content)
    vector_id = document_vector['document']['id']
    # Check for errors in the response
    if 'error' in document_vector:
        return {
                "error": str(document_vector),
                "traceback": traceback.format_exc()
            }, 500
    current_app.logger.info(f'Vector ID: {vector_id}')
    # Save to Firestore and return the document ID
    db_id = db.create_document_db(document)
    current_app.logger.info(f'Database ID: {db_id}')
    return {
        "document": document, 
        "db_id": db_id
    }

# Only with python app.py
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
