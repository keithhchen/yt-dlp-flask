# Use an official Python runtime as a parent image
FROM python:3.12-slim

# Set the working directory in the container
WORKDIR /app

# Install system dependencies including ffmpeg
RUN apt-get update && \
    apt-get install -y \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Create temp_audio directory and set permissions
RUN mkdir -p /app/tmp && chmod 777 /app/tmp

# Install Python dependencies
COPY requirements.txt .

# Google Cloud credentials
COPY credentials.json /app/credentials.json
ENV GOOGLE_APPLICATION_CREDENTIALS=/app/credentials.json
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of your application code to the container
COPY . .

# Expose the port the app will run on
EXPOSE 5000

# Command to run the application
CMD ["python", "app.py"]
