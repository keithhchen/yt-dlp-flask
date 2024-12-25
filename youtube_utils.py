# youtube_utils.py

import os
import uuid
import traceback
from flask import current_app
import yt_dlp
from google.cloud import storage, speech
from datetime import timedelta
import re
from urllib.parse import urlparse, parse_qs
import json
import requests
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api.formatters import TextFormatter
from utils import load_api_key

BUCKET_NAME = 'keith_speech_to_text'
storage_client = storage.Client()
bucket = storage_client.bucket(BUCKET_NAME)

def download_audio(url):
    """从给定的 URL 下载音频并将其上传到 Google Cloud Storage。"""
    # Create a temporary local path for initial download
    temp_file = f'/app/tmp/{uuid.uuid4()}-192'
    
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
    """对音频进行转录，带有说话者区分和时间戳。"""
    
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
        'raw_transcript': raw_results
    }

def format_timestamp(seconds):
    """将秒转换为 HH:MM:SS 格式。"""
    return str(timedelta(seconds=int(seconds)))

def test_gcs_connection():
    """通过列出 blob 和创建测试 blob 来测试与 Google Cloud Storage 的连接。"""
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
    
def get_youtube_video_metadata(video_url):
    """使用 YouTube Data API 获取视频元数据包括题、描述、缩略图、频道标题、发布时间、标签和是否包含转录。"""
    # Parse the URL and extract the video ID from the query parameters
    parsed_url = urlparse(video_url)
    video_id = parse_qs(parsed_url.query).get('v')

    if not video_id or not video_id[0]:
        return {'error': 'Invalid YouTube URL'}

    video_id = video_id[0]  # Get the first video ID from the list

    # Load the API key
    api_key = load_api_key("youtube_api_key")
    url = f"https://www.googleapis.com/youtube/v3/videos?id={video_id}&key={api_key}&part=snippet,contentDetails"

    try:
        response = requests.get(url)
        response.raise_for_status()  # Raise an error for bad responses
        data = response.json()

        if 'items' not in data or not data['items']:
            return {
                'error': 'Video not found or no metadata available.'
            }

        video_info = data['items'][0]
        title = video_info['snippet'].get('title', 'Unknown Title')
        description = video_info['snippet'].get('description', 'No description available.')
        thumbnails = video_info['snippet'].get('thumbnails', {})
        channel_title = video_info['snippet'].get('channelTitle', 'Unknown Channel')
        published_at = video_info['snippet'].get('publishedAt', 'Unknown Publish Date')
        tags = video_info['snippet'].get('tags', [])

        return {
            'title': title,
            'description': description,
            'thumbnails': thumbnails,
            'channel_title': channel_title,
            'published_at': published_at,
            'tags': tags,
            'language': video_info['snippet'].get('defaultAudioLanguage', 'Unknown Language'),
        }
    except Exception as e:
        current_app.logger.error(f"Error retrieving metadata for video URL {video_url}: {str(e)}")
        return {
            'error': str(e)
        }

def get_youtube_transcript(video_url):
    """使用 youtube-transcript-api 获取 YouTube 视频的转录文本。"""
    # Parse the URL and extract the video ID from the query parameters
    parsed_url = urlparse(video_url)
    video_id = parse_qs(parsed_url.query).get('v')

    if not video_id or not video_id[0]:
        return {'error': 'Invalid YouTube URL'}

    video_id = video_id[0]  # Get the first video ID from the list

    try:
        # Fetch the transcript
        transcript = YouTubeTranscriptApi.get_transcript(video_id)
        
        # Optionally format the transcript
        formatter = TextFormatter()
        formatted_transcript = formatter.format_transcript(transcript)

        return {
            'formatted_transcript': formatted_transcript,
            'raw_transcript': transcript
        }
    except Exception as e:
        return {
            'error': str(e)
        }
