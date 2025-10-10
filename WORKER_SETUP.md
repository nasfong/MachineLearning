# Video Transcoding Worker Setup

## Architecture

```
┌─────────────┐      ┌─────────────┐      ┌──────────────┐
│   FastAPI   │─────▶│    Redis    │◀─────│Celery Worker │
│     API     │      │    Queue    │      │   (FFmpeg)   │
└─────────────┘      └─────────────┘      └──────────────┘
      │                                           │
      └───────────────┬───────────────────────────┘
                      ▼
                ┌──────────┐
                │  MinIO   │
                │ Storage  │
                └──────────┘
```

## Services

1. **FastAPI API** (`ml-api`) - Main API server
2. **Redis** (`ml-redis`) - Message broker & result backend
3. **Celery Worker** (`ml-worker`) - Video transcoding worker
4. **MinIO** - S3-compatible storage (external)

## Benefits

✅ **Scalable** - Add more workers during high demand
✅ **Fault Tolerant** - Workers can restart without losing jobs
✅ **Non-blocking** - API responds immediately
✅ **Persistent** - Jobs survive container restarts
✅ **Retryable** - Auto-retry failed jobs (max 3 attempts)
✅ **Monitorable** - Track job status via task IDs

## Setup

### 1. Start all services:

```bash
docker compose up -d
```

This starts:
- FastAPI API (port 8000)
- Redis (port 6379)
- Celery Worker (2 concurrent workers)

### 2. Check logs:

```bash
# API logs
docker logs -f ml-api

# Worker logs
docker logs -f ml-worker

# Redis logs
docker logs -f ml-redis
```

### 3. Scale workers (if needed):

```bash
# Scale to 3 workers
docker compose up -d --scale celery-worker=3

# Scale to 5 workers
docker compose up -d --scale celery-worker=5
```

## API Usage

### 1. Upload Video

```bash
POST /videos/upload
Content-Type: multipart/form-data

file: <video_file>
```

Response:
```json
{
  "file_id": "abc123...",
  "filename": "abc123.mp4",
  "message": "Video uploaded successfully"
}
```

### 2. Start Transcoding

```bash
POST /videos/transcode/{file_id}
Content-Type: application/json

{
  "resolution": "1920:1080",
  "format": "hls"
}
```

Response:
```json
{
  "message": "Transcoding started",
  "task_id": "550e8400-e29b-41d4-a716-446655440000",
  "file_id": "abc123...",
  "output_name": "abc123_transcoded.m3u8",
  "resolution": "1920:1080",
  "format": "hls",
  "status": "processing"
}
```

### 3. Check Task Status (Real-time)

```bash
GET /videos/task/{task_id}
```

Response (Processing):
```json
{
  "task_id": "550e8400-...",
  "state": "PROGRESS",
  "status": "transcoding"
}
```

Response (Completed):
```json
{
  "task_id": "550e8400-...",
  "state": "SUCCESS",
  "status": "completed",
  "result": {
    "status": "completed",
    "output_name": "abc123_transcoded.m3u8",
    "format": "hls"
  }
}
```

Response (Failed):
```json
{
  "task_id": "550e8400-...",
  "state": "FAILURE",
  "status": "failed",
  "error": "FFmpeg error: ..."
}
```

### 4. Check File Status (Legacy)

```bash
GET /videos/status/{file_id}?format=hls
```

### 5. Stream/Download

```bash
# Stream
GET /videos/stream/{filename}

# Download
GET /videos/download/{filename}
```

## Monitoring

### Monitor Celery Workers

```bash
# Install flower (Celery monitoring tool)
pip install flower

# Run flower
celery -A celery_worker flower --port=5555
```

Then open: http://localhost:5555

### Monitor Redis

```bash
# Connect to Redis CLI
docker exec -it ml-redis redis-cli

# Check queue length
LLEN celery

# Monitor commands in real-time
MONITOR
```

## Configuration

### Environment Variables

- `REDIS_URL` - Redis connection URL (default: `redis://redis:6379/0`)
- `MINIO_ENDPOINT` - MinIO endpoint
- `MINIO_ACCESS_KEY` - MinIO access key
- `MINIO_SECRET_KEY` - MinIO secret key
- `MINIO_SECURE` - Use HTTPS (true/false)

### Worker Concurrency

Edit `docker-compose.yml`:

```yaml
celery-worker:
  command: celery -A celery_worker worker --loglevel=info --concurrency=4
  #                                                              ↑ change this
```

### Task Timeout

Edit `celery_worker.py`:

```python
celery_app.conf.update(
    task_time_limit=3600,      # 1 hour max (hard limit)
    task_soft_time_limit=3300, # 55 minutes (soft limit)
)
```

## Production Considerations

### 1. Use Separate Worker Image

Create `Dockerfile.worker` with FFmpeg optimizations:

```dockerfile
FROM python:3.11-slim

# Install FFmpeg with hardware acceleration
RUN apt-get update && apt-get install -y \\
    ffmpeg \\
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY celery_worker.py .
```

### 2. Add Resource Limits

```yaml
celery-worker:
  deploy:
    resources:
      limits:
        cpus: '2'
        memory: 2G
      reservations:
        cpus: '1'
        memory: 512M
```

### 3. Use Redis Persistence

Already configured with `--appendonly yes`

### 4. Add Health Checks

```yaml
celery-worker:
  healthcheck:
    test: ["CMD", "celery", "-A", "celery_worker", "inspect", "ping"]
    interval: 30s
    timeout: 10s
    retries: 3
```

### 5. Use External Redis (Production)

Update `docker-compose.yml`:

```yaml
environment:
  - REDIS_URL=redis://your-production-redis:6379/0
```

## Troubleshooting

### Worker not processing tasks

```bash
# Check worker is running
docker ps | grep ml-worker

# Check worker logs
docker logs ml-worker

# Restart worker
docker restart ml-worker
```

### Redis connection issues

```bash
# Test Redis connection
docker exec ml-api redis-cli -h redis ping

# Should return: PONG
```

### Task stuck in PENDING

- Worker might not be running
- Redis connection issue
- Check worker logs for errors

### FFmpeg errors

- Check input video format
- Verify MinIO credentials
- Check disk space in `/tmp`

## Rollback to Background Tasks

If you want to rollback to FastAPI background tasks, just remove Celery:

1. Remove `celery-worker` service from `docker-compose.yml`
2. Remove `redis` service
3. Remove Celery imports from `video_transcoder.py`
4. Set `CELERY_AVAILABLE = False`

The API will automatically fall back to the old behavior.
