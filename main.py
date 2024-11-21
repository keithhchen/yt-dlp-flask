import os
from flask import Flask, request, current_app
import yt_dlp
from google.cloud import storage, speech
import uuid
import traceback
from datetime import timedelta

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
    temp_file = f'/app/tmp/{uuid.uuid4()}'
    
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
        'postprocessor_args': [
            '-ar', '16000',
            '-ac', '1'    
        ],
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

def transcribe_audio_with_diarization(gcs_uri, language_code="en-US"):
    """Transcribe audio with speaker diarization and timestamps."""
    
    current_app.logger.info(f"Starting transcription for: {gcs_uri}")
    
    client = speech.SpeechClient()
    
    config = speech.RecognitionConfig(
        encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
        language_code=language_code,
        enable_automatic_punctuation=True,
        enable_word_time_offsets=True,
        diarization_config=speech.SpeakerDiarizationConfig(
            enable_speaker_diarization=True,
            min_speaker_count=2,
            max_speaker_count=2
        )
    )
    
    audio = speech.RecognitionAudio(uri=gcs_uri)
    
    # Start long-running transcription
    operation = client.long_running_recognize(
        config=config,
        audio=audio
    )
    
    current_app.logger.info("Waiting for transcription to complete...")
    response = operation.result(timeout=600)  # 10 minute timeout
    
    # Process results to combine words into sentences with speaker tags and timestamps
    transcript_lines = []
    
    for result in response.results:
        transcript = result.alternatives[0].transcript
        if not transcript.strip():  # Skip if transcript is empty or just whitespace
            continue
            
        # Get the first word's details for the timestamp and speaker
        first_word = result.alternatives[0].words[0]
        timestamp = f"[{format_timestamp(first_word.start_time.total_seconds())}]"
        speaker_tag = first_word.speaker_tag
        
        # Add the line with timestamp and speaker tag
        transcript_lines.append(
            f"{timestamp} Speaker {speaker_tag}: {transcript}"
        )
    
    # Convert response.results to a serializable format
    raw_results = []
    for result in response.results:
        raw_result = {
            'alternatives': [{
                'transcript': alt.transcript,
                'confidence': alt.confidence,
                'words': [{
                    'word': word.word,
                    'start_time': word.start_time.total_seconds(),
                    'end_time': word.end_time.total_seconds(),
                    'speaker_tag': word.speaker_tag
                } for word in alt.words]
            } for alt in result.alternatives]
        }
        raw_results.append(raw_result)

    return {
        'formatted_transcript': "\n".join(transcript_lines),
        'raw_results': raw_results
    }

def format_timestamp(seconds):
    """Convert seconds to HH:MM:SS format."""
    return str(timedelta(seconds=int(seconds)))

@app.route('/download-audio', methods=['GET'])
def download_audio_endpoint():
    video_url = request.args.get('url')
    language_code = request.args.get('lang', 'en-US')
    
    if not video_url:
        return {"error": "No URL provided"}, 400
    
    try:
        signed_url = download_audio(video_url)
        if not signed_url:
            return {"error": "Failed to generate download URL"}, 500
        
        # Extract the blob name from the signed URL
        blob_name = signed_url.split('/')[-1].split('?')[0]
        gcs_uri = f'gs://{BUCKET_NAME}/audio/{blob_name}'
        
        # Generate transcription
        transcript = transcribe_audio_with_diarization(gcs_uri, language_code)
            
        return {
            "download_url": signed_url,
            "gcs_uri": gcs_uri,
            "formatted_transcript": transcript['formatted_transcript'],
            "raw_results": transcript['raw_results']
        }
    
    except Exception as e:
        current_app.logger.error(f"Endpoint error: {str(e)}")
        return {
            "error": str(e),
            "traceback": traceback.format_exc()
        }, 500

def test_gcs_connection():
    try:
        # List a few blobs to test connection
        blobs = list(bucket.list_blobs(max_results=1))
        
        # Try to create and delete a test blob
        test_blob = bucket.blob('test-connection/test.txt')
        test_blob.upload_from_string('Test connection successful')
        test_blob.delete()
        
        return {
            "status": "success",
            "bucket": BUCKET_NAME,
            "connection": "verified",
            "existing_files": len(blobs)
        }
    except Exception as e:
        current_app.logger.error(f"GCS Connection error: {str(e)}")
        return {
            "status": "error",
            "message": str(e),
            "traceback": traceback.format_exc()
        }

@app.route('/test-connection', methods=['GET'])
def test_connection_endpoint():
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

# Only with python app.py
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
