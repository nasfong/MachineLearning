FROM python:3.11-slim
WORKDIR /app

# Install FFmpeg for video transcoding (clean cache immediately to save space)
RUN apt-get update && \
    apt-get install -y --no-install-recommends ffmpeg && \
    apt-get clean && \
    rm -rf /var/cache/apt/archives/* /var/lib/apt/lists/* /tmp/* /var/tmp/*

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# ✅ copy contents of your local app/ into container /app/
COPY . . 

# Create temp directory for video processing
RUN mkdir -p /tmp && chmod 777 /tmp

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]