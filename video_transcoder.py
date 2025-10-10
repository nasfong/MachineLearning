from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks, Body
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


async def transcode_video_task(input_name: str, output_name: str, resolution: str, format: str = "mp4"):
    """Background task to transcode video using FFmpeg"""
    try:
        # Download from MinIO
        input_path = f"/tmp/{input_name}"
        
        minio_client.fget_object(INPUT_BUCKET, input_name, input_path)
        logger.info(f"Downloaded {input_name} for transcoding")
        
        # Build FFmpeg command based on format
        if format == "hls":
            # HLS output - creates .m3u8 playlist and .ts segments
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
            # DASH output - creates .mpd manifest and .m4s segments
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
            # MP4 output (default)
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
        
        logger.info(f"Starting transcoding: {input_name} -> {output_name} (format: {format})")
        process = subprocess.run(cmd, check=True, capture_output=True)
        
        # Upload transcoded video with retry logic
        max_retries = 3
        
        if format in ["hls", "dash"]:
            # For HLS/DASH, upload all generated files
            output_dir = Path(output_path).parent
            pattern = f"{Path(output_name).stem}*"
            files_to_upload = list(output_dir.glob(pattern))
            
            logger.info(f"Uploading {len(files_to_upload)} files for {format.upper()} format")
            
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
                        logger.info(f"Uploaded: {file_path.name}")
                        break
                    except S3Error as e:
                        if attempt < max_retries - 1:
                            logger.warning(f"Upload attempt {attempt + 1} failed for {file_path.name}, retrying: {e}")
                            continue
                        else:
                            logger.error(f"Upload failed after {max_retries} attempts for {file_path.name}")
                            raise
            
            # Cleanup all generated files
            for file_path in files_to_upload:
                if file_path.exists():
                    os.remove(file_path)
        else:
            # For MP4, upload single file
            for attempt in range(max_retries):
                try:
                    minio_client.fput_object(
                        OUTPUT_BUCKET,
                        output_name,
                        output_path,
                        content_type="video/mp4"
                    )
                    logger.info(f"Transcoding complete: {output_name}")
                    break
                except S3Error as e:
                    if attempt < max_retries - 1:
                        logger.warning(f"Upload attempt {attempt + 1} failed, retrying: {e}")
                        continue
                    else:
                        logger.error(f"Upload failed after {max_retries} attempts")
                        raise
            
            # Cleanup
            if os.path.exists(output_path):
                os.remove(output_path)
        
        # Cleanup input file
        os.remove(input_path)
        
    except subprocess.CalledProcessError as e:
        logger.error(f"FFmpeg error: {e.stderr.decode() if e.stderr else str(e)}")
        # Cleanup on error
        if os.path.exists(input_path):
            os.remove(input_path)
        if os.path.exists(output_path):
            os.remove(output_path)
        raise
    except Exception as e:
        logger.error(f"Transcoding error: {e}")
        raise


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
    background_tasks: BackgroundTasks,
    request: TranscodeRequest = TranscodeRequest()
):
    """Start video transcoding job with specified resolution and format"""
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
        
        # Add transcoding to background tasks
        background_tasks.add_task(transcode_video_task, input_name, output_name, request.resolution, request.format)
        
        return {
            "message": "Transcoding started",
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