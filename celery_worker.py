from celery import Celery
from minio import Minio
from minio.error import S3Error
import subprocess
import os
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# Celery configuration
celery_app = Celery(
    'video_transcoder',
    broker=os.getenv('REDIS_URL', 'redis://redis:6379/0'),
    backend=os.getenv('REDIS_URL', 'redis://redis:6379/0')
)

celery_app.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,  # 1 hour max
    task_soft_time_limit=3300,  # 55 minutes soft limit
)

# MinIO Configuration
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"

INPUT_BUCKET = "videobucket"
OUTPUT_BUCKET = "videobucket"

# Initialize MinIO client
minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_SECURE
)


@celery_app.task(bind=True, max_retries=3)
def transcode_video_task(self, input_name: str, output_name: str, resolution: str, format: str = "mp4"):
    """Celery task to transcode video using FFmpeg"""
    try:
        # Download from MinIO
        input_path = f"/tmp/{input_name}"
        
        logger.info(f"Task {self.request.id}: Downloading {input_name}")
        minio_client.fget_object(INPUT_BUCKET, input_name, input_path)
        
        # Build FFmpeg command based on format
        if format == "hls":
            output_path = f"/tmp/{Path(output_name).stem}.m3u8"
            cmd = [
                "ffmpeg", "-i", input_path,
                "-vf", f"scale={resolution}",
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "23",
                "-c:a", "aac",
                "-b:a", "128k",
                "-hls_time", "10",
                "-hls_playlist_type", "vod",
                "-hls_segment_filename", f"/tmp/{Path(output_name).stem}_%03d.ts",
                "-y",
                output_path
            ]
        elif format == "dash":
            output_path = f"/tmp/{Path(output_name).stem}.mpd"
            cmd = [
                "ffmpeg", "-i", input_path,
                "-vf", f"scale={resolution}",
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "23",
                "-c:a", "aac",
                "-b:a", "128k",
                "-f", "dash",
                "-seg_duration", "10",
                "-use_template", "1",
                "-use_timeline", "1",
                "-init_seg_name", f"{Path(output_name).stem}_init_$RepresentationID$.m4s",
                "-media_seg_name", f"{Path(output_name).stem}_chunk_$RepresentationID$_$Number$.m4s",
                "-y",
                output_path
            ]
        else:
            output_path = f"/tmp/{output_name}"
            cmd = [
                "ffmpeg", "-i", input_path,
                "-vf", f"scale={resolution}",
                "-c:v", "libx264",
                "-preset", "medium",
                "-crf", "23",
                "-c:a", "aac",
                "-b:a", "128k",
                "-movflags", "+faststart",
                "-y",
                output_path
            ]
        
        logger.info(f"Task {self.request.id}: Starting transcoding {format}")
        
        # Update task state to show progress
        self.update_state(state='PROGRESS', meta={'status': 'transcoding'})
        
        process = subprocess.run(cmd, check=True, capture_output=True)
        
        # Upload files
        max_retries = 3
        
        if format in ["hls", "dash"]:
            output_dir = Path(output_path).parent
            pattern = f"{Path(output_name).stem}*"
            files_to_upload = list(output_dir.glob(pattern))
            
            logger.info(f"Task {self.request.id}: Uploading {len(files_to_upload)} files")
            
            for file_path in files_to_upload:
                for attempt in range(max_retries):
                    try:
                        content_type = "application/vnd.apple.mpegurl" if file_path.suffix == ".m3u8" else \
                                     "application/dash+xml" if file_path.suffix == ".mpd" else \
                                     "video/mp2t" if file_path.suffix == ".ts" else \
                                     "application/octet-stream"
                        
                        minio_client.fput_object(
                            OUTPUT_BUCKET,
                            file_path.name,
                            str(file_path),
                            content_type=content_type
                        )
                        logger.info(f"Task {self.request.id}: Uploaded {file_path.name}")
                        break
                    except S3Error as e:
                        if attempt < max_retries - 1:
                            logger.warning(f"Upload attempt {attempt + 1} failed, retrying: {e}")
                            continue
                        else:
                            raise
            
            # Cleanup
            for file_path in files_to_upload:
                if file_path.exists():
                    os.remove(file_path)
        else:
            for attempt in range(max_retries):
                try:
                    minio_client.fput_object(
                        OUTPUT_BUCKET,
                        output_name,
                        output_path,
                        content_type="video/mp4"
                    )
                    logger.info(f"Task {self.request.id}: Upload complete")
                    break
                except S3Error as e:
                    if attempt < max_retries - 1:
                        logger.warning(f"Upload attempt {attempt + 1} failed, retrying: {e}")
                        continue
                    else:
                        raise
            
            if os.path.exists(output_path):
                os.remove(output_path)
        
        # Cleanup input
        os.remove(input_path)
        
        return {
            'status': 'completed',
            'output_name': output_name,
            'format': format
        }
        
    except subprocess.CalledProcessError as e:
        logger.error(f"Task {self.request.id}: FFmpeg error: {e.stderr.decode() if e.stderr else str(e)}")
        # Cleanup on error
        if 'input_path' in locals() and os.path.exists(input_path):
            os.remove(input_path)
        if 'output_path' in locals() and os.path.exists(output_path):
            os.remove(output_path)
        
        # Retry on failure
        raise self.retry(exc=e, countdown=60)  # Retry after 60 seconds
        
    except Exception as e:
        logger.error(f"Task {self.request.id}: Error: {e}")
        raise self.retry(exc=e, countdown=60)
