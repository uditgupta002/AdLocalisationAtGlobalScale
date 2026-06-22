import re
import asyncio
from typing import Dict, Optional
from src.webhook import TigrisEvent
from src.utils.logger import setup_logger

logger = setup_logger("swarm-router")

# Track paired campaign assets
# Format: { campaign_id: { "video": TigrisEvent, "audio": TigrisEvent } }
_pending_pairs: Dict[str, Dict[str, TigrisEvent]] = {}
_lock = asyncio.Lock()


def classify_asset(key: str) -> str:
    """
    Categorizes asset key as video, audio, or unknown based on extensions or path prefixes.
    """
    video_exts = {".mp4", ".mov", ".avi", ".webm", ".mkv"}
    audio_exts = {".mp3", ".wav", ".aac", ".flac", ".ogg", ".m4a"}
    
    ext = re.search(r"\.[a-zA-Z0-9]+$", key)
    if ext:
        ext_str = ext.group(0).lower()
        if ext_str in video_exts:
            return "video"
        if ext_str in audio_exts:
            return "audio"
            
    # Fallback to key paths
    if "video/" in key:
        return "video"
    if "audio/" in key:
        return "audio"
        
    return "unknown"


def extract_campaign_id(key: str) -> str:
    """
    Extracts deterministic campaign ID from the asset key.
    Expected: campaigns/{campaign_id}/video/master.mp4
    """
    match = re.match(r"^campaigns/([^/]+)/", key)
    if match:
        return match.group(1)
        
    # Fallback: Split by directories
    parts = [p for p in key.split("/") if p]
    if len(parts) > 1:
        return parts[1] if parts[0] == "campaigns" else parts[0]
    return "default_campaign"


async def route_object_event(event: TigrisEvent) -> None:
    """
    Downstream router of incoming Tigris assets.
    Saves and pairs assets for each campaign, launching the orchestrator 
    when both master video + audio have successfully landed.
    """
    key = event.object.key
    asset_type = classify_asset(key)
    
    if asset_type == "unknown":
        logger.warning(f"Ignoring asset with unknown classification: {key}")
        return
        
    campaign_id = extract_campaign_id(key)
    logger.info(f"Classified asset: type='{asset_type}', campaign='{campaign_id}', key='{key}'")
    
    async with _lock:
        if campaign_id not in _pending_pairs:
            _pending_pairs[campaign_id] = {}
            
        pair = _pending_pairs[campaign_id]
        pair[asset_type] = event
        
        # Check if pair is complete
        if "video" in pair and "audio" in pair:
            video_event = pair["video"]
            audio_event = pair["audio"]
            # Complete pair found, remove from tracking map
            del _pending_pairs[campaign_id]
            
            logger.info(f"🎉 Complete asset pair matched for campaign '{campaign_id}'! Launching orchestrator...")
            
            # Spawn the orchestrator asynchronously
            from src.orchestrator import Orchestrator
            orchestrator = Orchestrator()
            asyncio.create_task(orchestrator.launch(
                campaign_id=campaign_id,
                video_event=video_event,
                audio_event=audio_event
            ))
        else:
            waiting_for = "audio" if asset_type == "video" else "video"
            logger.info(f"Campaign '{campaign_id}' paired state: {asset_type} received. Waiting for {waiting_for}...")
            
            # Spawn a monitoring task to alert if campaign pairing times out (e.g., after 5 minutes)
            asyncio.create_task(monitor_pairing_timeout(campaign_id, 300))


async def monitor_pairing_timeout(campaign_id: str, timeout_seconds: int):
    """
    Alerts if the paired files are not uploaded within the timeout threshold.
    """
    await asyncio.sleep(timeout_seconds)
    async with _lock:
        if campaign_id in _pending_pairs:
            pair = _pending_pairs[campaign_id]
            missing = "audio" if "video" in pair else "video"
            logger.warning(
                f"🚨 Pairing Timeout: Campaign '{campaign_id}' has been waiting over {timeout_seconds}s "
                f"for the '{missing}' asset to arrive!"
            )
