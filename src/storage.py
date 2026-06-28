import os
import shutil
from typing import List
from src.config import settings
from src.utils.logger import setup_logger

logger = setup_logger("swarm-storage")

# Local filesystem emulation. Heavy media tooling (FFmpeg, Demucs) operates on
# real files, so every asset is mirrored to disk. Durable input/output also
# lives in Amazon S3 when S3_LIVE_MODE is enabled.
LOCAL_STORAGE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "storage"
)
os.makedirs(os.path.join(LOCAL_STORAGE_DIR, "master"), exist_ok=True)
os.makedirs(os.path.join(LOCAL_STORAGE_DIR, "output"), exist_ok=True)

_s3_client = None


def _is_durable_bucket(bucket: str) -> bool:
    """Only the master + output buckets are real S3 buckets; forks are local."""
    return bucket in (settings.S3_MASTER_BUCKET, settings.S3_OUTPUT_BUCKET)


def get_s3_client():
    global _s3_client
    if not settings.S3_LIVE_MODE:
        return None
    if _s3_client is None:
        import boto3

        kwargs = {"region_name": settings.APP_AWS_REGION}
        if settings.APP_AWS_ACCESS_KEY_ID and settings.APP_AWS_SECRET_ACCESS_KEY:
            kwargs["aws_access_key_id"] = settings.APP_AWS_ACCESS_KEY_ID
            kwargs["aws_secret_access_key"] = settings.APP_AWS_SECRET_ACCESS_KEY
        _s3_client = boto3.client("s3", **kwargs)
    return _s3_client


def upload_asset(bucket: str, key: str, data: bytes, content_type: str = "application/octet-stream") -> None:
    logger.info(f"Uploading asset to {bucket}/{key} (S3Live={settings.S3_LIVE_MODE})")

    local_path = os.path.join(LOCAL_STORAGE_DIR, bucket, key)
    os.makedirs(os.path.dirname(local_path), exist_ok=True)
    with open(local_path, "wb") as f:
        f.write(data)
    logger.debug(f"Mirrored asset locally to: {local_path}")

    if settings.S3_LIVE_MODE and _is_durable_bucket(bucket):
        s3 = get_s3_client()
        s3.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)
        logger.info(f"Uploaded to Amazon S3: s3://{bucket}/{key}")


def get_presigned_url(bucket: str, key: str, expires_in: int = 3600) -> str:
    if settings.S3_LIVE_MODE and _is_durable_bucket(bucket):
        s3 = get_s3_client()
        if s3:
            try:
                return s3.generate_presigned_url(
                    "get_object",
                    Params={"Bucket": bucket, "Key": key},
                    ExpiresIn=expires_in,
                )
            except Exception as e:
                logger.error(f"Failed to generate presigned URL: {e}")
    return None


def download_asset(bucket: str, key: str) -> bytes:
    logger.info(f"Downloading asset from {bucket}/{key} (S3Live={settings.S3_LIVE_MODE})")

    if settings.S3_LIVE_MODE and _is_durable_bucket(bucket):
        try:
            s3 = get_s3_client()
            response = s3.get_object(Bucket=bucket, Key=key)
            data = response["Body"].read()
            local_path = os.path.join(LOCAL_STORAGE_DIR, bucket, key)
            os.makedirs(os.path.dirname(local_path), exist_ok=True)
            with open(local_path, "wb") as f:
                f.write(data)
            logger.debug(f"Mirrored downloaded asset locally to: {local_path}")
            return data
        except Exception as e:
            logger.warning(f"S3 download failed for '{bucket}/{key}': {e}. Trying local fallback...")

    local_path = os.path.join(LOCAL_STORAGE_DIR, bucket, key)
    if not os.path.exists(local_path):
        raise FileNotFoundError(f"Asset not found locally or in S3: {local_path}")
    with open(local_path, "rb") as f:
        return f.read()


def list_assets(bucket: str, prefix: str = "") -> List[str]:
    logger.info(f"Listing assets in {bucket} prefix='{prefix}' (S3Live={settings.S3_LIVE_MODE})")

    if settings.S3_LIVE_MODE and _is_durable_bucket(bucket):
        try:
            s3 = get_s3_client()
            response = s3.list_objects_v2(Bucket=bucket, Prefix=prefix)
            return [obj["Key"] for obj in response.get("Contents", [])]
        except Exception as e:
            logger.warning(f"S3 list failed: {e}. Falling back to local storage.")

    bucket_dir = os.path.join(LOCAL_STORAGE_DIR, bucket)
    if not os.path.exists(bucket_dir):
        return []
    keys = []
    for root, _, files in os.walk(bucket_dir):
        for file in files:
            rel_path = os.path.relpath(os.path.join(root, file), bucket_dir)
            if rel_path.startswith(prefix):
                keys.append(rel_path)
    return keys


def create_bucket_fork(source_bucket: str, fork_name: str) -> None:
    """
    Create an isolated working sandbox for a market/asset pair. On AWS we keep
    forks as local working directories cloned from the source (S3 has no
    zero-copy bucket fork), which is where FFmpeg/Demucs read and write.
    """
    logger.info(f"Creating fork: {source_bucket} -> {fork_name}")
    source_dir = os.path.join(LOCAL_STORAGE_DIR, source_bucket)
    fork_dir = os.path.join(LOCAL_STORAGE_DIR, fork_name)
    os.makedirs(fork_dir, exist_ok=True)
    if os.path.exists(source_dir):
        for item in os.listdir(source_dir):
            s = os.path.join(source_dir, item)
            d = os.path.join(fork_dir, item)
            if os.path.isdir(s):
                shutil.copytree(s, d, dirs_exist_ok=True)
            else:
                shutil.copy2(s, d)
    logger.debug(f"Local fork created at: {fork_dir}")


def delete_bucket_fork(fork_name: str) -> None:
    logger.info(f"Deleting fork: {fork_name}")
    fork_dir = os.path.join(LOCAL_STORAGE_DIR, fork_name)
    if os.path.exists(fork_dir):
        shutil.rmtree(fork_dir)
    logger.debug(f"Local fork removed: {fork_dir}")
