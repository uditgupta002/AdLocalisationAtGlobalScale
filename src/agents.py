import asyncio
import json
from abc import ABC, abstractmethod
from typing import List, Dict, Any
from src.config import get_market_config
from src.database import add_job_log, update_job_agent
from src.storage import download_asset, upload_asset
from src.media_processor import apply_video_transformation, apply_audio_dubbing_mock

class BaseAgent(ABC):
    def __init__(self, job_id: str, agent_id: str, market: str = None):
        self.job_id = job_id
        self.agent_id = agent_id
        self.market = market

    def log(self, message: str) -> None:
        prefix = f"[{self.agent_id}]"
        if self.market:
            prefix += f" [{self.market.upper()}]"
        add_job_log(self.job_id, f"{prefix} {message}")

    @abstractmethod
    async def process(self) -> Any:
        pass

    async def scan_script_opsera(self, script_content: str, script_type: str) -> bool:
        """
        Simulates Opsera script vulnerability validation.
        If it contains suspicious domains or passwords, it raises an error.
        Otherwise, passes instantly.
        """
        self.log(f"Opsera scanning script configuration of type: '{script_type}'")
        await asyncio.sleep(0.5)  # Simulate API latency
        
        # Simple security rules
        suspicious = ["eval(", "http://malicious.com", "api_key = \"secret\""]
        for pattern in suspicious:
            if pattern in script_content:
                self.log(f"🚨 Opsera Violation Detected: Found insecure pattern '{pattern}'!")
                return False
                
        self.log("Opsera compliance checks completed: PASSED ✓")
        return True


class VideoSubagent(BaseAgent):
    def __init__(self, job_id: str, market: str, source_bucket: str, source_key: str, fork_bucket: str):
        super().__init__(job_id, f"video-agent-{market}", market)
        self.source_bucket = source_bucket
        self.source_key = source_key
        self.fork_bucket = fork_bucket

    async def process(self) -> str:
        self.log("Starting visual media transformation...")
        update_job_agent(self.job_id, self.agent_id, "running")
        
        try:
            # 0. Apify Web Intelligence Scraper
            self.log(f"Launching Apify regional trend crawler on target market sources...")
            await asyncio.sleep(0.8)  # Simulate crawl latency
            self.log("Apify Scraper completed: Extracted local design trends and font mappings successfully!")
            
            # 1. Generate Strategy Script and scan via Opsera
            market_profile = get_market_config(self.market)
            script = json.dumps({
                "market": self.market,
                "strategy": "visual-refinement",
                "trans_overlays": market_profile["translations"],
                "font": market_profile["font_family"]
            })
            
            security_pass = await self.scan_script_opsera(script, "video-strategy")
            if not security_pass:
                raise PermissionError("Security validator rejected the transformation strategy script")
            
            # 2. Download source asset from our isolated fork
            self.log(f"Downloading master video from fork bucket: '{self.fork_bucket}'")
            input_bytes = download_asset(self.fork_bucket, self.source_key)
            
            # 3. Apply transformation (text overlay and color correction)
            text_overlay = list(market_profile["translations"].values())[0]  # E.g., Japan: "わたしは、もっと好きだ"
            
            self.log("Executing video rendering engine (mock RunwayML + Shotstack)")
            await asyncio.sleep(1.0)  # Simulate rendering overhead
            
            # Japan gets MCD Red theme, India gets Saffron/Green, Germany gets warm color grading, English gets modern dark cyan theme
            if self.market == "japan":
                output_bytes = apply_video_transformation(
                    video_data=input_bytes,
                    text_overlay=text_overlay,
                    font_color="white",
                    bg_color="red",
                    brightness=0.03,
                    saturation=1.1
                )
            elif self.market == "india":
                output_bytes = apply_video_transformation(
                    video_data=input_bytes,
                    text_overlay=text_overlay,
                    font_color="orange",  # Saffron
                    bg_color="darkgreen", # Forest Green
                    brightness=0.02,
                    saturation=1.15
                )
            elif self.market == "english":
                output_bytes = apply_video_transformation(
                    video_data=input_bytes,
                    text_overlay=text_overlay,
                    font_color="cyan",
                    bg_color="blue",
                    brightness=0.05,
                    saturation=1.20
                )
            else:  # germany
                output_bytes = apply_video_transformation(
                    video_data=input_bytes,
                    text_overlay=text_overlay,
                    font_color="yellow",
                    bg_color="black",
                    brightness=0.0,
                    saturation=0.95
                )
            
            # 4. Upload results back to our fork under "output/"
            out_key = f"output/{self.market}_video.mp4"
            self.log(f"Uploading transformed video to fork: '{out_key}'")
            upload_asset(self.fork_bucket, out_key, output_bytes, "video/mp4")
            
            update_job_agent(self.job_id, self.agent_id, "completed")
            return out_key
            
        except Exception as e:
            self.log(f"Agent failed: {e}")
            update_job_agent(self.job_id, self.agent_id, "failed")
            raise e


class VideoParentAgent(BaseAgent):
    def __init__(self, job_id: str, source_bucket: str, source_key: str, markets: List[str], forks: List[Dict[str, str]]):
        super().__init__(job_id, "video-parent")
        self.source_bucket = source_bucket
        self.source_key = source_key
        self.markets = markets
        self.forks = forks

    async def process(self) -> Dict[str, str]:
        self.log("Video Parent Agent starting processing tree...")
        update_job_agent(self.job_id, self.agent_id, "running")
        
        # Spawn child tasks
        tasks = []
        for market in self.markets:
            fork_bucket = next(f["fork_bucket"] for f in self.forks if f["market"] == market)
            agent = VideoSubagent(self.job_id, market, self.source_bucket, self.source_key, fork_bucket)
            tasks.append(agent.process())
            
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        processed_maps = {}
        errors = []
        for market, result in zip(self.markets, results):
            if isinstance(result, Exception):
                self.log(f"Child video agent for market '{market}' failed: {result}")
                errors.append(result)
            else:
                processed_maps[market] = result
                
        if errors:
            update_job_agent(self.job_id, self.agent_id, "failed")
            raise RuntimeError("One or more child video subagents failed")
            
        update_job_agent(self.job_id, self.agent_id, "completed")
        return processed_maps


class AudioSubagent(BaseAgent):
    def __init__(self, job_id: str, market: str, source_bucket: str, source_key: str, fork_bucket: str):
        super().__init__(job_id, f"audio-agent-{market}", market)
        self.source_bucket = source_bucket
        self.source_key = source_key
        self.fork_bucket = fork_bucket

    async def process(self) -> str:
        self.log("Starting audio translation dubbing...")
        update_job_agent(self.job_id, self.agent_id, "running")
        
        try:
            # 0. Apify Dialect & Tone Extractor
            self.log("Launching Apify Actor to crawl local social feeds for dialect and colloquial tone guidelines...")
            await asyncio.sleep(0.8)  # Simulate crawl latency
            self.log("Apify Scraper completed: Colloquial tone parameters mapped successfully!")
            
            # 1. Generate Strategy Script and scan via Opsera
            market_profile = get_market_config(self.market)
            script = json.dumps({
                "market": self.market,
                "strategy": "voiceover-translation",
                "target_lang": market_profile["gemini_lang"]
            })
            
            security_pass = await self.scan_script_opsera(script, "audio-strategy")
            if not security_pass:
                raise PermissionError("Security validator rejected the audio strategy script")
            
            # 2. Download master audio from isolated fork
            self.log(f"Downloading master audio from fork bucket: '{self.fork_bucket}'")
            input_bytes = download_asset(self.fork_bucket, self.source_key)
            
            # 3. Translate + Synthesize audio via Google Gemini S2ST pipeline
            self.log("Executing Gemini 2-step S2ST pipeline (Transcribe+Translate → TTS synthesis)")
            await asyncio.sleep(1.0)
            
            # Fetch campaign ID dynamically from database to support campaign-specific audio narration
            from src import database
            job = database.get_job(self.job_id)
            campaign_id = job.get("campaign_id", "gtv_ad") if job else "gtv_ad"
            
            output_bytes = apply_audio_dubbing_mock(
                input_bytes, 
                market_profile["gemini_lang"], 
                campaign_id
            )
            
            # 4. Upload dubbed audio back to our fork under "output/"
            out_key = f"output/{self.market}_audio.wav"
            self.log(f"Uploading dubbed audio to fork: '{out_key}'")
            upload_asset(self.fork_bucket, out_key, output_bytes, "audio/wav")
            
            update_job_agent(self.job_id, self.agent_id, "completed")
            return out_key
            
        except Exception as e:
            self.log(f"Agent failed: {e}")
            update_job_agent(self.job_id, self.agent_id, "failed")
            raise e


class AudioParentAgent(BaseAgent):
    def __init__(self, job_id: str, source_bucket: str, source_key: str, markets: List[str], forks: List[Dict[str, str]]):
        super().__init__(job_id, "audio-parent")
        self.source_bucket = source_bucket
        self.source_key = source_key
        self.markets = markets
        self.forks = forks

    async def process(self) -> Dict[str, str]:
        self.log("Audio Parent Agent starting processing tree...")
        update_job_agent(self.job_id, self.agent_id, "running")
        
        # Spawn child tasks
        tasks = []
        for market in self.markets:
            fork_bucket = next(f["fork_bucket"] for f in self.forks if f["market"] == market)
            agent = AudioSubagent(self.job_id, market, self.source_bucket, self.source_key, fork_bucket)
            tasks.append(agent.process())
            
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        processed_maps = {}
        errors = []
        for market, result in zip(self.markets, results):
            if isinstance(result, Exception):
                self.log(f"Child audio agent for market '{market}' failed: {result}")
                errors.append(result)
            else:
                processed_maps[market] = result
                
        if errors:
            update_job_agent(self.job_id, self.agent_id, "failed")
            raise RuntimeError("One or more child audio subagents failed")
            
        update_job_agent(self.job_id, self.agent_id, "completed")
        return processed_maps
