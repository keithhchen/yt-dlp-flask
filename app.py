import os
from flask import Flask, request, send_file, after_this_request
import yt_dlp

app = Flask(__name__)

# Directory to store downloaded audio files temporarily
TEMP_DIR = './temp_audio'
os.makedirs(TEMP_DIR, exist_ok=True)

# Configure yt-dlp options to download audio only
def download_audio(url):
    ydl_opts = {
        'format': 'bestaudio/best',  # Download the best audio quality
        'outtmpl': os.path.join(TEMP_DIR, '%(id)s.%(ext)s'),  # Save to the temporary directory
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',  # Convert to mp3 or other formats if needed
            'preferredcodec': 'mp3',
            'preferredquality': '192',  # You can adjust the quality
        }],
    }

    # Download audio using yt-dlp
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info_dict = ydl.extract_info(url, download=True)
        audio_file = ydl.prepare_filename(info_dict)
        audio_file = os.path.splitext(audio_file)[0] + '.mp3'
        return audio_file

# Define an HTTP route to handle the request and return the audio file
@app.route('/download-audio', methods=['GET'])
def download_audio_endpoint():
    video_url = request.args.get('url')
    
    if not video_url:
        return "Error: No URL provided.", 400
    
    audio_file_path = None
    try:
        # Download audio
        audio_file_path = download_audio(video_url)
        
        # Send the audio file as a response
        response = send_file(audio_file_path, as_attachment=True)
        
        # Ensure cleanup is called after response, using finally()
        def cleanup():
            try:
                if audio_file_path and os.path.exists(audio_file_path):
                    os.remove(audio_file_path)
                    print(f"File {audio_file_path} deleted successfully.")
            except Exception as e:
                print(f"Error deleting file {audio_file_path}: {e}")
        
        # Attach the cleanup function to run after the response is sent
        @after_this_request
        def after_request(response):
            cleanup()
            return response
        
        return response
    
    except Exception as e:
        return f"Error: {str(e)}", 500

    finally:
        # Ensures cleanup in case of failure to send response, but doesn't block response
        if audio_file_path and os.path.exists(audio_file_path):
            cleanup()

if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port=5000)
