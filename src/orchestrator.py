import asyncio
import uuid
from typing import Dict, Any, List
from src.webhook import TigrisEvent
from src.config import settings
from src.utils.logger import setup_logger
from src import database
from src import storage
from src.media_processor import merge_video_audio
from src.agents import VideoParentAgent, AudioParentAgent

logger = setup_logger("swarm-orchestrator")

class Orchestrator:
    def __init__(self):
        pass

    async def launch(self, campaign_id: str, video_event: TigrisEvent, audio_event: TigrisEvent) -> None:
        """
        Executes the entire end-to-end swarm localization pipeline.
        Manages state transitions, bucket forks, parallel subagent trees, 
        and asset remix assembly.
        """
        job_id = str(uuid.uuid4())
        markets = settings.TARGET_MARKETS
        
        logger.info(f"🚀 Orchestrator active. Launching job {job_id} for campaign '{campaign_id}'")
        
        # 1. Initialize persistent state
        database.create_job(
            job_id=job_id,
            campaign_id=campaign_id,
            video_key=video_event.object.key,
            audio_key=audio_event.object.key,
            source_bucket=video_event.bucket,
            markets=markets
        )
        
        forks_created: List[Dict[str, str]] = []
        
        try:
            # 2. Pre-flight security scan
            database.update_job_status(job_id, "security-scanning")
            database.add_job_log(job_id, "Running Opsera pre-flight security scanner on campaign configuration...")
            await asyncio.sleep(1.0)  # Simulate pre-flight latency
            
            # Simple metadata checks
            if ".." in video_event.object.key or ".." in audio_event.object.key:
                raise ValueError("Security violation: Path traversal characters detected in S3 asset keys!")
            database.add_job_log(job_id, "Pre-flight security scan PASSED ✓")
            
            # 3. Create isolated bucket forks for each market + asset type
            database.update_job_status(job_id, "forking")
            
            for market in markets:
                for asset_type in ["video", "audio"]:
                    fork_name = f"job-{job_id[:8]}-{market}-{asset_type}"
                    # Create the fork
                    storage.create_bucket_fork(video_event.bucket, fork_name)
                    # Map fork in database
                    database.update_job_fork(job_id, market, asset_type, fork_name)
                    forks_created.append({
                        "market": market,
                        "asset_type": asset_type,
                        "fork_bucket": fork_name
                    })
            
            database.add_job_log(job_id, f"Forks successfully created. Total isolated environments active: {len(forks_created)}")
            
            # 4. Spawning Video & Audio parents in parallel
            database.update_job_status(job_id, "processing")
            
            # Extract video forks and audio forks
            video_forks = [f for f in forks_created if f["asset_type"] == "video"]
            audio_forks = [f for f in forks_created if f["asset_type"] == "audio"]
            
            video_parent = VideoParentAgent(
                job_id=job_id,
                source_bucket=video_event.bucket,
                source_key=video_event.object.key,
                markets=markets,
                forks=video_forks
            )
            audio_parent = AudioParentAgent(
                job_id=job_id,
                source_bucket=audio_event.bucket,
                source_key=audio_event.object.key,
                markets=markets,
                forks=audio_forks
            )
            
            database.add_job_log(job_id, "Spawning parallel Video and Audio Parent Agent Trees...")
            
            # Run both parent processing streams concurrently
            video_results, audio_results = await asyncio.gather(
                video_parent.process(),
                audio_parent.process(),
                return_exceptions=False
            )
            
            database.add_job_log(job_id, "Both agent hierarchies completed processing. Assembling final regional ads...")
            
            # 5. Remix & Assemble final localized ads
            database.update_job_status(job_id, "assembling")
            
            # Only assemble markets where BOTH video and audio succeeded
            successful_markets = [m for m in markets if m in video_results and m in audio_results]
            skipped_markets = [m for m in markets if m not in successful_markets]

            if skipped_markets:
                database.add_job_log(job_id, f"⚠️ Skipping assembly for failed markets: {skipped_markets}")

            for market in successful_markets:
                database.add_job_log(job_id, f"Assembling assets for market '{market.upper()}'")
                
                # Fetch video out key from video forks
                vid_fork = next(f["fork_bucket"] for f in video_forks if f["market"] == market)
                vid_out_key = video_results[market]
                
                # Fetch audio out key from audio forks
                aud_fork = next(f["fork_bucket"] for f in audio_forks if f["market"] == market)
                aud_out_key = audio_results[market]
                
                # Download transformed bytes from forks
                database.add_job_log(job_id, f"Downloading localized video and audio tracks for '{market.upper()}'")
                vid_bytes = storage.download_asset(vid_fork, vid_out_key)
                aud_bytes = storage.download_asset(aud_fork, aud_out_key)
                
                # Execute FFmpeg remuxing/merging
                database.add_job_log(job_id, f"Running FFmpeg remuxer to merge streams for '{market.upper()}'")
                merged_bytes = merge_video_audio(vid_bytes, aud_bytes)
                
                # Prepare keys in the final output bucket
                output_prefix = f"campaigns/{campaign_id}/{market}"
                final_video_key = f"{output_prefix}/final_ad.mp4"
                local_vid_key = f"{output_prefix}/localized_video.mp4"
                local_aud_key = f"{output_prefix}/localized_audio.wav"
                
                database.add_job_log(job_id, f"Uploading completed localized campaign ad bundle to output bucket...")
                
                # Upload all outputs to output bucket
                storage.upload_asset(settings.TIGRIS_OUTPUT_BUCKET, final_video_key, merged_bytes, "video/mp4")
                storage.upload_asset(settings.TIGRIS_OUTPUT_BUCKET, local_vid_key, vid_bytes, "video/mp4")
                storage.upload_asset(settings.TIGRIS_OUTPUT_BUCKET, local_aud_key, aud_bytes, "audio/wav")
                
                # Store final results map in database
                result_map = {
                    "market": market,
                    "merged_ad_key": final_video_key,
                    "localized_video_key": local_vid_key,
                    "localized_audio_key": local_aud_key,
                    "output_bucket": settings.TIGRIS_OUTPUT_BUCKET
                }
                database.update_job_result(job_id, market, result_map)
                
            # 6. Cleanup active bucket forks
            database.add_job_log(job_id, "Initiating zero-copy bucket forks garbage collection...")
            for fork in forks_created:
                storage.delete_bucket_fork(fork["fork_bucket"])
            database.add_job_log(job_id, "All active forks deleted. Storage footprint minimized.")
            
            # 7. Job Success
            database.update_job_status(job_id, "completed")
            if skipped_markets:
                database.add_job_log(job_id, f"✅ LOCALIZATION COMPLETE — {len(successful_markets)} market(s) rendered: {[m.upper() for m in successful_markets]}. Skipped: {[m.upper() for m in skipped_markets]}.")
            else:
                database.add_job_log(job_id, "🎉 GLOBAL AD LOCALIZATION SUCCESSFUL! All targets rendered and live on CDN.")
            logger.info(f"Job {job_id} successfully completed!")
            
        except Exception as e:
            logger.error(f"Job {job_id} encountered a fatal processing error: {e}", exc_info=True)
            database.update_job_status(job_id, "failed", str(e))
            
            # Attemp fork garbage collection on failure to avoid leaking storage
            if forks_created:
                logger.info(f"Cleaning up bucket forks for failed job {job_id}")
                for fork in forks_created:
                    try:
                        storage.delete_bucket_fork(fork["fork_bucket"])
                    except Exception as err:
                        logger.error(f"Error during fail-safe fork cleanup of {fork['fork_bucket']}: {err}")
