import os
import shutil
from typing import List
from src.config import settings
from src.utils.logger import setup_logger

logger = setup_logger("swarm-storage")

# Ensure local storage emulated directories exist
LOCAL_STORAGE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "storage"
)
os.makedirs(os.path.join(LOCAL_STORAGE_DIR, "master"), exist_ok=True)
os.makedirs(os.path.join(LOCAL_STORAGE_DIR, "output"), exist_ok=True)

# Cache Tigris Boto3 S3 client if live storage mode is enabled
_s3_client = None

def get_s3_client():
    global _s3_client
    if not settings.TIGRIS_LIVE_MODE:
        return None
    if _s3_client is None:
        import boto3
        _s3_client = boto3.client(
            "s3",
            endpoint_url=settings.TIGRIS_ENDPOINT,
            aws_access_key_id=settings.TIGRIS_ACCESS_KEY_ID,
            aws_secret_access_key=settings.TIGRIS_SECRET_ACCESS_KEY,
            region_name="auto"
        )
    return _s3_client


def upload_asset(bucket: str, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    """
    Upload an asset as bytes. If TIGRIS_LIVE_MODE is enabled, uploads to Tigris S3
    and additionally mirrors a copy to the local emulated storage folder for UI video/audio players.
    Otherwise, only writes to the local emulated storage folder.
    """
    logger.info(f"Uploading asset to {bucket}/{key} (Live={settings.TIGRIS_LIVE_MODE})")
    
    # Always mirror to local storage directory to support local stream/media rendering in UI and local FFmpeg
    local_path = os.path.join(LOCAL_STORAGE_DIR, bucket, key)
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    with open(local_path, "wb") as f:
        f.write(data)
    logger.debug(f"Mirrored asset locally to: {local_path}")

    if settings.TIGRIS_LIVE_MODE:
        s3 = get_s3_client()
        s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=data,
            ContentType=content_type
        )
        logger.info(f"Successfully uploaded asset to live Tigris bucket: s3://{bucket}/{key}")


def download_asset(bucket: str, key: str) -> bytes:
    """
    Download an asset as bytes. If TIGRIS_LIVE_MODE is enabled, downloads from Tigris S3,
    mirrors it locally, and returns the bytes. Otherwise, reads from local directory.
    """
    logger.info(f"Downloading asset from {bucket}/{key} (Live={settings.TIGRIS_LIVE_MODE})")
    
    if settings.TIGRIS_LIVE_MODE:
        try:
            s3 = get_s3_client()
            response = s3.get_object(Bucket=bucket, Key=key)
            data = response["Body"].read()
            
            # Mirror the downloaded file locally so local tools like FFmpeg can access it
            local_path = os.path.join(LOCAL_STORAGE_DIR, bucket, key)
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            with open(local_path, "wb") as f:
                f.write(data)
            logger.debug(f"Mirrored downloaded asset locally to: {local_path}")
            return data
        except Exception as e:
            logger.warning(f"Failed download from live S3 bucket '{bucket}/{key}': {e}. Attempting local emulator fallback...")
            
    local_path = os.path.join(LOCAL_STORAGE_DIR, bucket, key)
    if not os.path.exists(local_path):
        raise FileNotFoundError(f"Asset not found locally or in live Tigris: {local_path}")
    with open(local_path, "rb") as f:
        return f.read()


def list_assets(bucket: str, prefix: str = "") -> List[str]:
    """
    List asset keys with optional prefix from live Tigris S3 or local emulator.
    """
    logger.info(f"Listing assets in bucket {bucket} with prefix '{prefix}' (Live={settings.TIGRIS_LIVE_MODE})")
    
    if settings.TIGRIS_LIVE_MODE:
        try:
            s3 = get_s3_client()
            response = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
            contents = response.get("Contents", [])
            return [obj["Key"] for obj in contents]
        except Exception as e:
            logger.warning(f"Failed to list assets from live S3: {e}. Falling back to local emulated storage.")

    bucket_dir = os.path.join(LOCAL_STORAGE_DIR, bucket)
    if not os.path.exists(bucket_dir):
        return []
    
    keys = []
    for root, _, files in os.walk(bucket_dir):
        for file in files:
            full_path = os.path.join(root, file)
            rel_path = os.path.relpath(full_path, bucket_dir)
            if rel_path.startswith(prefix):
                keys.append(rel_path)
    return keys


def create_bucket_fork(source_bucket: str, fork_name: str) -> None:
    """
    Creates an isolated bucket fork.
    If TIGRIS_LIVE_MODE is enabled, calls Tigris' S3 custom headers for a zero-copy metadata clone,
    while also duplicating local directories to allow local processes to access them transparently.
    Otherwise, only performs a local directory clone.
    """
    logger.info(f"Creating bucket fork: {source_bucket} -> {fork_name} (Live={settings.TIGRIS_LIVE_MODE})")
    
    # Always duplicate local folders to emulate isolated environment for local media utilities
    source_dir = os.path.join(LOCAL_STORAGE_DIR, source_bucket)
    fork_dir = os.path.join(LOCAL_STORAGE_DIR, fork_name)
    os.makedirs(fork_dir, exist_ok=True)
    if os.path.exists(source_dir):
        # Clone all files under source directory to simulate zero-copy fork
        for item in os.listdir(source_dir):
            s = os.path.join(source_dir, item)
            d = os.path.join(fork_dir, item)
            if os.path.isdir(s):
                shutil.copytree(s, d, dirs_exist_ok=True)
            else:
                shutil.copy2(s, d)
    logger.debug(f"Local storage folder fork emulated at: {fork_dir}")

    if settings.TIGRIS_LIVE_MODE:
        s3 = get_s3_client()
        # Intercept the CreateBucket S3 call to inject Tigris' custom Zero-Copy Bucket Fork header
        def add_fork_headers(request, **kwargs):
            request.headers["X-Tigris-Fork-Source-Bucket"] = source_bucket
            
        s3.meta.events.register("before-send.s3.CreateBucket", add_fork_headers)
        try:
            s3.create_bucket(Bucket=fork_name)
            logger.info(f"Successfully created zero-copy Tigris bucket fork '{fork_name}' from '{source_bucket}'")
        finally:
            # Deregister to keep the events channel clean
            s3.meta.events.unregister("before-send.s3.CreateBucket", add_fork_headers)


def delete_bucket_fork(fork_name: str) -> None:
    """
    Deletes a bucket fork both in the live S3 storage and in local folders.
    """
    logger.info(f"Deleting bucket fork: {fork_name} (Live={settings.TIGRIS_LIVE_MODE})")
    
    # Always clean up local workspace folders
    fork_dir = os.path.join(LOCAL_STORAGE_DIR, fork_name)
    if os.path.exists(fork_dir):
        shutil.rmtree(fork_dir)
    logger.debug(f"Local folder fork removed: {fork_dir}")

    if settings.TIGRIS_LIVE_MODE:
        s3 = get_s3_client()
        # S3 buckets must be empty to be deleted. We empty it first.
        try:
            keys = list_assets(fork_name)
            if keys:
                s3.delete_objects(
                    Bucket=fork_name,
                    Delete={"Objects": [{"Key": k} for k in keys]}
                )
            s3.delete_bucket(Bucket=fork_name)
            logger.info(f"Successfully deleted live Tigris bucket fork: {fork_name}")
        except Exception as e:
            logger.error(f"Failed to delete live bucket fork '{fork_name}': {e}")
