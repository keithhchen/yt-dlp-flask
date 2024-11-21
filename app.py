import os
from flask import Flask, request, current_app
import yt_dlp
from google.cloud import storage
import uuid
import traceback

app = Flask(__name__)

BUCKET_NAME = 'keith_speech_to_text'
storage_client = storage.Client()
bucket = storage_client.bucket(BUCKET_NAME)

# Print all environment variables when the app starts
print("Starting Flask App with the following environment variables:")
for key, value in os.environ.items():
    print(f"{key}: {value}")

def download_audio(url):
    # Create a temporary local path for initial download
    temp_file = f'/app/tmp/{uuid.uuid4()}.wav'
    
    current_app.logger.info(f"Attempting to download: {url}")
    current_app.logger.info(f"Temp file path: {temp_file}")
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(temp_file), exist_ok=True)
    
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': temp_file,
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'wav',
            'preferredquality': '192',
        }],
        'verbose': True  # Add verbose output for debugging
    }

    try:
        # Download audio using yt-dlp
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            current_app.logger.info("Starting download with yt-dlp")
            info_dict = ydl.extract_info(url, download=True)
            
            # Check for both the original temp file and potential .wav extension
            actual_temp_file = temp_file
            if not os.path.exists(actual_temp_file):
                # Try with .wav extension if original doesn't exist
                wav_temp_file = f"{temp_file}.wav"
                if os.path.exists(wav_temp_file):
                    actual_temp_file = wav_temp_file
                else:
                    raise FileNotFoundError(f"Downloaded file not found at {temp_file} or {wav_temp_file}")
            
            current_app.logger.info(f"File downloaded successfully. Size: {os.path.getsize(actual_temp_file)}")
            
            # Use the actual_temp_file for upload
            blob_name = f'audio/{uuid.uuid4()}.wav'
            blob = bucket.blob(blob_name)
            current_app.logger.info(f"Uploading to GCS: {blob_name}")
            
            blob.upload_from_filename(actual_temp_file)
            
            # Generate signed URL
            url = blob.generate_signed_url(
                version="v4",
                expiration=3600,
                method="GET"
            )
            
            current_app.logger.info("Process completed successfully")
            return url
            
    except Exception as e:
        current_app.logger.error(f"Error in download_audio: {str(e)}")
        current_app.logger.error(traceback.format_exc())
        raise  # Re-raise the exception to be handled by the endpoint
        
    finally:
        # Clean up temp files
        for file_path in [temp_file, f"{temp_file}.wav"]:
            if os.path.exists(file_path):
                try:
                    os.remove(file_path)
                    current_app.logger.info(f"Cleaned up temp file: {file_path}")
                except Exception as e:
                    current_app.logger.error(f"Error cleaning up {file_path}: {str(e)}")

@app.route('/download-audio', methods=['GET'])
def download_audio_endpoint():
    video_url = request.args.get('url')
    
    if not video_url:
        return {"error": "No URL provided"}, 400
    
    try:
        signed_url = download_audio(video_url)
        if not signed_url:
            return {"error": "Failed to generate download URL"}, 500
        
        # Extract the blob name from the signed URL
        # The signed URL contains the bucket name and blob path
        blob_name = signed_url.split('/')[-1].split('?')[0]
        gcs_uri = f'gs://{BUCKET_NAME}/audio/{blob_name}'
            
        return {
            "download_url": signed_url,
            "gcs_uri": gcs_uri
        }
    
    except Exception as e:
        current_app.logger.error(f"Endpoint error: {str(e)}")
        return {
            "error": str(e),
            "traceback": traceback.format_exc()
        }, 500

# Only with python app.py
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
