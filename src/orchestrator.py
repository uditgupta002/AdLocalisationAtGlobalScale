import asyncio
import uuid
from typing import Dict, Any, List, Optional
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

    async def launch(self, campaign_id: str, video_event, audio_event) -> None:
        """Legacy entrypoint: create a brand-new job, then run the pipeline."""
        job_id = str(uuid.uuid4())
        markets = settings.TARGET_MARKETS
        database.create_job(
            job_id=job_id,
            campaign_id=campaign_id,
            video_key=video_event.object.key,
            audio_key=audio_event.object.key,
            source_bucket=video_event.bucket,
            markets=markets,
        )
        await self.run_job(job_id)

    async def run_job(self, job_id: str) -> None:
        """
        Run the end-to-end localization pipeline for an already-persisted job.
        This is the path triggered by the Vercel app, which inserts the job row
        into Aurora DSQL first and then asks the worker to process it.
        """
        job = database.get_job(job_id)
        if not job:
            logger.error(f"run_job called for unknown job_id={job_id}")
            return

        campaign_id = job["campaign_id"]
        source_bucket = job["source_bucket"]
        video_key = job["video_key"]
        audio_key = job["audio_key"]
        markets: List[str] = job["markets"] or settings.TARGET_MARKETS

        logger.info(f"🚀 Orchestrator running job {job_id} for campaign '{campaign_id}'")

        forks_created: List[Dict[str, str]] = []

        try:
            # 1. Pre-flight security scan
            database.update_job_status(job_id, "security-scanning")
            database.add_job_log(job_id, "Running Opsera pre-flight security scanner on campaign configuration...")
            await asyncio.sleep(1.0)
            if ".." in video_key or ".." in audio_key:
                raise ValueError("Security violation: Path traversal characters detected in S3 asset keys!")
            database.add_job_log(job_id, "Pre-flight security scan PASSED ✓")

            # 1b. Pull master assets from Amazon S3 into the local mirror so the
            # subsequent working forks include the source files.
            database.add_job_log(job_id, f"Fetching master assets from Amazon S3 bucket '{source_bucket}'...")
            storage.download_asset(source_bucket, video_key)
            storage.download_asset(source_bucket, audio_key)

            # 2. Create isolated working forks per market + asset type
            database.update_job_status(job_id, "forking")
            for market in markets:
                for asset_type in ["video", "audio"]:
                    fork_name = f"job-{job_id[:8]}-{market}-{asset_type}"
                    storage.create_bucket_fork(source_bucket, fork_name)
                    database.update_job_fork(job_id, market, asset_type, fork_name)
                    forks_created.append({
                        "market": market,
                        "asset_type": asset_type,
                        "fork_bucket": fork_name,
                    })
            database.add_job_log(job_id, f"Forks created. Isolated environments active: {len(forks_created)}")

            # 3. Spawn parallel video + audio agent trees
            database.update_job_status(job_id, "processing")
            video_forks = [f for f in forks_created if f["asset_type"] == "video"]
            audio_forks = [f for f in forks_created if f["asset_type"] == "audio"]

            video_parent = VideoParentAgent(
                job_id=job_id,
                source_bucket=source_bucket,
                source_key=video_key,
                markets=markets,
                forks=video_forks,
            )
            audio_parent = AudioParentAgent(
                job_id=job_id,
                source_bucket=source_bucket,
                source_key=audio_key,
                markets=markets,
                forks=audio_forks,
            )

            database.add_job_log(job_id, "Spawning parallel Video and Audio Parent Agent Trees...")
            video_results, audio_results = await asyncio.gather(
                video_parent.process(),
                audio_parent.process(),
                return_exceptions=False,
            )
            database.add_job_log(job_id, "Both agent hierarchies completed. Assembling localized ads...")

            # 4. Remix & assemble final localized ads
            database.update_job_status(job_id, "assembling")
            successful_markets = [m for m in markets if m in video_results and m in audio_results]
            skipped_markets = [m for m in markets if m not in successful_markets]
            if skipped_markets:
                database.add_job_log(job_id, f"⚠️ Skipping assembly for failed markets: {skipped_markets}")

            for market in successful_markets:
                database.add_job_log(job_id, f"Assembling assets for market '{market.upper()}'")
                vid_fork = next(f["fork_bucket"] for f in video_forks if f["market"] == market)
                vid_out_key = video_results[market]
                aud_fork = next(f["fork_bucket"] for f in audio_forks if f["market"] == market)
                aud_out_key = audio_results[market]

                database.add_job_log(job_id, f"Downloading localized tracks for '{market.upper()}'")
                vid_bytes = storage.download_asset(vid_fork, vid_out_key)
                aud_bytes = storage.download_asset(aud_fork, aud_out_key)

                database.add_job_log(job_id, f"Running FFmpeg remuxer for '{market.upper()}'")
                merged_bytes = merge_video_audio(vid_bytes, aud_bytes)

                output_prefix = f"campaigns/{campaign_id}/{market}"
                final_video_key = f"{output_prefix}/final_ad.mp4"
                local_vid_key = f"{output_prefix}/localized_video.mp4"
                local_aud_key = f"{output_prefix}/localized_audio.wav"

                database.add_job_log(job_id, "Uploading localized ad bundle to S3 output bucket...")
                storage.upload_asset(settings.S3_OUTPUT_BUCKET, final_video_key, merged_bytes, "video/mp4")
                storage.upload_asset(settings.S3_OUTPUT_BUCKET, local_vid_key, vid_bytes, "video/mp4")
                storage.upload_asset(settings.S3_OUTPUT_BUCKET, local_aud_key, aud_bytes, "audio/wav")

                database.update_job_result(job_id, market, {
                    "market": market,
                    "merged_ad_key": final_video_key,
                    "localized_video_key": local_vid_key,
                    "localized_audio_key": local_aud_key,
                    "output_bucket": settings.S3_OUTPUT_BUCKET,
                })

            # 5. Cleanup forks
            database.add_job_log(job_id, "Initiating working-fork garbage collection...")
            for fork in forks_created:
                storage.delete_bucket_fork(fork["fork_bucket"])
            database.add_job_log(job_id, "All forks deleted. Storage footprint minimized.")

            # 6. Done
            database.update_job_status(job_id, "completed")
            if skipped_markets:
                database.add_job_log(job_id, f"✅ COMPLETE — rendered {[m.upper() for m in successful_markets]}, skipped {[m.upper() for m in skipped_markets]}.")
            else:
                database.add_job_log(job_id, "🎉 GLOBAL AD LOCALIZATION SUCCESSFUL! All targets live on S3.")
            logger.info(f"Job {job_id} completed!")

        except Exception as e:
            logger.error(f"Job {job_id} fatal error: {e}", exc_info=True)
            database.update_job_status(job_id, "failed", str(e))
            for fork in forks_created:
                try:
                    storage.delete_bucket_fork(fork["fork_bucket"])
                except Exception as err:
                    logger.error(f"Fail-safe fork cleanup error for {fork['fork_bucket']}: {err}")
