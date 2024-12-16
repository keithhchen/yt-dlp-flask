import os
from flask import Flask, request, current_app
from google.cloud import storage, speech
import traceback
from datetime import timedelta
from youtube_utils import get_youtube_video_metadata, download_audio, transcribe_audio_with_diarization, test_gcs_connection, download_youtube_transcription

app = Flask(__name__)

BUCKET_NAME = 'keith_speech_to_text'
storage_client = storage.Client()
bucket = storage_client.bucket(BUCKET_NAME)

# Print all environment variables when the app starts
print("Starting Flask App with the following environment variables:")
for key, value in os.environ.items():
    print(f"{key}: {value}")

@app.route('/audio', methods=['GET'])
def download_audio_endpoint():
    """下载音频的端点，从视频 URL 返回签名 URL 和转录文本。"""
    video_url = request.args.get('url')
    language_code = request.args.get('lang', 'en-US')  # en-US, zh-CN
    
    if not video_url:
        return {"error": "No URL provided"}, 400
    
    def fetch_metadata_and_audio():
        metadata = get_youtube_video_metadata(video_url)
        signed_url = download_audio(video_url)
        return metadata, signed_url

    try:
        metadata, signed_url = fetch_metadata_and_audio()
        
        # Extract the blob name from the signed URL
        blob_name = signed_url.split('/')[-1].split('?')[0]
        gcs_uri = f'gs://{BUCKET_NAME}/audio/{blob_name}'
        
        # Generate transcription
        transcript = transcribe_audio_with_diarization(gcs_uri, language_code)
            
        return {
            "download_url": signed_url,
            "gcs_uri": gcs_uri,
            "formatted_transcript": transcript['formatted_transcript'],
            "raw_results": transcript['raw_results'],
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
    """从给定的 Google Cloud Storage URI 转录音频的端点。"""
    gcs_uri = request.args.get('gcs_uri')
    language_code = request.args.get('lang', 'en-US')
    
    if not gcs_uri:
        return {"error": "No GCS URI provided"}, 400
        
    try:
        result = transcribe_audio_with_diarization(gcs_uri, language_code)
        return result
    except Exception as e:
        current_app.logger.error(f"Transcription endpoint error: {str(e)}")
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

# Only with python app.py
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
