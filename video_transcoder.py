from fastapi import APIRouter, UploadFile, File, HTTPException, Body
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from typing import Literal, Optional
from minio import Minio
from minio.error import S3Error
import subprocess
import os
import uuid
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

# Check if Celery is available
CELERY_AVAILABLE = False
transcode_video_task = None

def init_celery():
    """Initialize Celery connection"""
    global CELERY_AVAILABLE, transcode_video_task
    try:
        from celery_worker import transcode_video_task as _task
        transcode_video_task = _task
        CELERY_AVAILABLE = True
        logger.info("✅ Celery worker connection established")
    except ImportError as e:
        CELERY_AVAILABLE = False
        logger.warning(f"⚠️ Celery not available: {e}")


class TranscodeRequest(BaseModel):
    resolution: Literal[
        "3840:2160",  # 4K UHD
        "2560:1440",  # 2K QHD
        "1920:1080",  # 1080p Full HD
        "1280:720",   # 720p HD
        "854:480",    # 480p SD
        "640:360",    # 360p
        "426:240"     # 240p
    ] = "1280:720"
    format: Literal["dash", "hls", "mp4"] = "mp4"

router = APIRouter(prefix="/videos", tags=["videos"])

# MinIO Configuration
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT", "localhost:9000")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"

# Buckets
INPUT_BUCKET = "videobucket"
OUTPUT_BUCKET = "videobucket"

# Initialize MinIO client
minio_client = Minio(
    MINIO_ENDPOINT,
    access_key=MINIO_ACCESS_KEY,
    secret_key=MINIO_SECRET_KEY,
    secure=MINIO_SECURE
)


async def init_minio_buckets():
    """Create buckets if they don't exist and set public read policy"""
    try:
        import json
        
        for bucket in [INPUT_BUCKET, OUTPUT_BUCKET]:
            if not minio_client.bucket_exists(bucket):
                minio_client.make_bucket(bucket)
                logger.info(f"Created bucket: {bucket}")
            
            # Set bucket policy to allow public read access
            policy = {
                "Version": "2012-10-17",
                "Statement": [
                    {
                        "Effect": "Allow",
                        "Principal": {"AWS": "*"},
                        "Action": ["s3:GetObject"],
                        "Resource": [f"arn:aws:s3:::{bucket}/*"]
                    }
                ]
            }
            minio_client.set_bucket_policy(bucket, json.dumps(policy))
            logger.info(f"Set public read policy for bucket: {bucket}")
            
    except S3Error as e:
        logger.error(f"Error creating buckets: {e}")
        raise


# Note: The actual transcode_video_task is now in celery_worker.py
# We removed the duplicate function from here to avoid naming conflicts


@router.post("/upload")
async def upload_video(file: UploadFile = File(...)):
    """Upload video to MinIO storage"""
    try:
        # Validate file type
        if not file.content_type or not file.content_type.startswith("video/"):
            raise HTTPException(status_code=400, detail="File must be a video")
        
        file_id = str(uuid.uuid4())
        file_ext = Path(file.filename).suffix or ".mp4"
        object_name = f"{file_id}{file_ext}"
        
        # Upload to MinIO
        minio_client.put_object(
            INPUT_BUCKET,
            object_name,
            file.file,
            length=-1,
            part_size=10*1024*1024,
            content_type=file.content_type
        )
        
        logger.info(f"Uploaded file: {object_name}")
        return {
            "file_id": file_id,
            "filename": object_name,
            "message": "Video uploaded successfully"
        }
    except S3Error as e:
        logger.error(f"MinIO error: {e}")
        raise HTTPException(status_code=500, detail=f"Storage error: {str(e)}")
    except Exception as e:
        logger.error(f"Upload error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/transcode/{file_id}")
async def transcode_video(
    file_id: str,
    request: TranscodeRequest = TranscodeRequest()
):
    """Start video transcoding job with specified resolution and format (using Celery worker)"""
    try:
        input_name = None
        # Find the file with this ID
        objects = minio_client.list_objects(INPUT_BUCKET, prefix=file_id)
        for obj in objects:
            input_name = obj.object_name
            break
        
        if not input_name:
            raise HTTPException(status_code=404, detail="Video file not found")
        
        # Set appropriate file extension based on format
        if request.format == "hls":
            output_name = f"{file_id}_transcoded.m3u8"
        elif request.format == "dash":
            output_name = f"{file_id}_transcoded.mpd"
        else:
            output_name = f"{file_id}_transcoded.mp4"
        
        # Send task to Celery worker
        if CELERY_AVAILABLE:
            task = transcode_video_task.delay(input_name, output_name, request.resolution, request.format)
            task_id = task.id
        else:
            raise HTTPException(status_code=503, detail="Worker service not available")
        
        return {
            "message": "Transcoding started",
            "task_id": task_id,
            "file_id": file_id,
            "output_name": output_name,
            "resolution": request.resolution,
            "format": request.format,
            "status": "processing"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Transcode request error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stream/{filename}")
async def stream_video(filename: str, bucket: str = OUTPUT_BUCKET):
    """Stream video from MinIO"""
    max_retries = 3
    last_error = None
    
    for attempt in range(max_retries):
        try:
            # Validate bucket name
            if bucket not in [INPUT_BUCKET, OUTPUT_BUCKET]:
                bucket = OUTPUT_BUCKET
            
            # Check if file exists
            stat = minio_client.stat_object(bucket, filename)
            
            # Get video stream
            response = minio_client.get_object(bucket, filename)
            
            return StreamingResponse(
                response.stream(32*1024),
                media_type="video/mp4",
                headers={
                    "Content-Disposition": f"inline; filename={filename}",
                    "Content-Length": str(stat.size),
                    "Accept-Ranges": "bytes"
                }
            )
        except S3Error as e:
            if e.code == "NoSuchKey":
                raise HTTPException(status_code=404, detail="Video not found")
            
            last_error = e
            if e.code == "AccessDenied" and attempt < max_retries - 1:
                logger.warning(f"Access denied on attempt {attempt + 1}, retrying...")
                # Small delay before retry
                import asyncio
                await asyncio.sleep(0.5 * (attempt + 1))
                continue
            
            logger.error(f"Stream error: {e}")
            raise HTTPException(status_code=500, detail=str(e))
        except Exception as e:
            logger.error(f"Unexpected stream error: {e}")
            raise HTTPException(status_code=500, detail=str(e))
    
    # If we exhausted retries
    if last_error:
        logger.error(f"Stream failed after {max_retries} attempts: {last_error}")
        raise HTTPException(status_code=500, detail=f"Stream failed after retries: {str(last_error)}")


@router.get("/download/{filename}")
async def download_video(filename: str, bucket: str = OUTPUT_BUCKET):
    """Download video from MinIO"""
    try:
        if bucket not in [INPUT_BUCKET, OUTPUT_BUCKET]:
            bucket = OUTPUT_BUCKET
            
        stat = minio_client.stat_object(bucket, filename)
        response = minio_client.get_object(bucket, filename)
        
        return StreamingResponse(
            response.stream(32*1024),
            media_type="video/mp4",
            headers={
                "Content-Disposition": f"attachment; filename={filename}",
                "Content-Length": str(stat.size)
            }
        )
    except S3Error as e:
        if e.code == "NoSuchKey":
            raise HTTPException(status_code=404, detail="Video not found")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/list")
async def list_videos(bucket: str = OUTPUT_BUCKET):
    """List all videos in a bucket"""
    try:
        if bucket not in [INPUT_BUCKET, OUTPUT_BUCKET]:
            bucket = OUTPUT_BUCKET
        
        objects = minio_client.list_objects(bucket)
        files = [
            {
                "name": obj.object_name,
                "size": obj.size,
                "last_modified": obj.last_modified.isoformat()
            }
            for obj in objects
        ]
        
        return {"bucket": bucket, "count": len(files), "files": files}
    except S3Error as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/task/{task_id}")
async def check_task_status(task_id: str):
    """Check the status of a Celery transcoding task"""
    if not CELERY_AVAILABLE:
        raise HTTPException(status_code=503, detail="Worker service not available")
    
    from celery.result import AsyncResult
    from celery_worker import celery_app
    
    task = AsyncResult(task_id, app=celery_app)
    
    if task.state == 'PENDING':
        response = {
            'task_id': task_id,
            'state': task.state,
            'status': 'Task is waiting to be processed'
        }
    elif task.state == 'PROGRESS':
        response = {
            'task_id': task_id,
            'state': task.state,
            'status': task.info.get('status', ''),
        }
    elif task.state == 'SUCCESS':
        response = {
            'task_id': task_id,
            'state': task.state,
            'status': 'completed',
            'result': task.result
        }
    elif task.state == 'FAILURE':
        response = {
            'task_id': task_id,
            'state': task.state,
            'status': 'failed',
            'error': str(task.info)
        }
    else:
        response = {
            'task_id': task_id,
            'state': task.state,
            'status': str(task.info)
        }
    
    return response


@router.get("/status/{file_id}")
async def check_status(file_id: str, format: str = "mp4"):
    """Check if transcoded video is ready"""
    try:
        # Determine output name based on format
        if format == "hls":
            output_name = f"{file_id}_transcoded.m3u8"
        elif format == "dash":
            output_name = f"{file_id}_transcoded.mpd"
        else:
            output_name = f"{file_id}_transcoded.mp4"
        
        # Check if output exists
        try:
            minio_client.stat_object(OUTPUT_BUCKET, output_name)
            return {
                "file_id": file_id,
                "status": "completed",
                "output_name": output_name,
                "format": format,
                "stream_url": f"/videos/stream/{output_name}"
            }
        except S3Error as e:
            if e.code == "NoSuchKey":
                return {
                    "file_id": file_id,
                    "status": "processing",
                    "format": format,
                    "message": "Video is still being transcoded"
                }
            raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{filename}")
async def delete_video(filename: str, bucket: str = OUTPUT_BUCKET):
    """Delete a video from MinIO"""
    try:
        if bucket not in [INPUT_BUCKET, OUTPUT_BUCKET]:
            bucket = OUTPUT_BUCKET
            
        minio_client.remove_object(bucket, filename)
        return {
            "message": f"Deleted {filename} from {bucket}",
            "filename": filename,
            "bucket": bucket
        }
    except S3Error as e:
        if e.code == "NoSuchKey":
            raise HTTPException(status_code=404, detail="Video not found")
        raise HTTPException(status_code=500, detail=str(e))