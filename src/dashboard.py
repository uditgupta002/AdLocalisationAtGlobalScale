import os
import time
import httpx
import sqlite3
import subprocess
import streamlit as st
from datetime import datetime
from src.config import settings, get_market_config
from src import database
from src.media_processor import is_ffmpeg_installed

# Set page configurations
st.set_page_config(
    page_title="OmniSwarm Dashboard",
    page_icon="🐝",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom premium styling
st.markdown("""
<style>
    .main {
        background-color: #0e1117;
        color: #ffffff;
    }
    .reportview-container .main .block-container{
        padding-top: 2rem;
    }
    .status-badge {
        padding: 6px 12px;
        border-radius: 20px;
        font-weight: bold;
        font-size: 0.9rem;
        display: inline-block;
    }
    .status-completed { background-color: #1e7e34; color: white; }
    .status-failed { background-color: #bd2130; color: white; }
    .status-processing { background-color: #007bff; color: white; }
    .status-forking { background-color: #17a2b8; color: white; }
    .status-scanning { background-color: #ffc107; color: black; }
    .status-initializing { background-color: #6c757d; color: white; }
    
    .log-box {
        font-family: 'Courier New', Courier, monospace;
        background-color: #1e2530;
        border-left: 5px solid #ffcc00;
        color: #a4b3c6;
        padding: 15px;
        border-radius: 8px;
        max-height: 400px;
        overflow-y: auto;
        white-space: pre-wrap;
    }
    .card {
        background-color: #1e2530;
        border: 1px solid #2d3748;
        padding: 20px;
        border-radius: 12px;
        margin-bottom: 20px;
    }
    h1, h2, h3 {
        color: #ffcc00 !important;
    }
</style>
""", unsafe_allow_html=True)


def generate_offline_test_assets(campaign_id: str):
    """
    Zero-dependency local media generator. Creates short 3s video + audio files
    offline using local FFmpeg, ensuring hackathon demos work 100% without internet.
    If assets already exist, skips generation to prevent overwriting custom uploads.
    """
    storage_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "storage", settings.TIGRIS_MASTER_BUCKET)
    campaign_dir = os.path.join(storage_dir, f"campaigns/{campaign_id}")
    os.makedirs(os.path.join(campaign_dir, "video"), exist_ok=True)
    os.makedirs(os.path.join(campaign_dir, "audio"), exist_ok=True)
    
    video_path = os.path.join(campaign_dir, "video/master.mp4")
    audio_path = os.path.join(campaign_dir, "audio/voiceover.wav")
    
    # Safe check: if assets are already pre-loaded/downloaded, do not overwrite them!
    if os.path.exists(video_path) and os.path.exists(audio_path) and os.path.getsize(video_path) > 1000:
        return video_path, audio_path
        
    if not is_ffmpeg_installed():
        # Edge fallback if FFmpeg is completely missing: create empty files
        with open(video_path, "wb") as f:
            f.write(b"mock video")
        with open(audio_path, "wb") as f:
            f.write(b"mock audio")
        return video_path, audio_path
        
    # Generate 3 seconds of a visual test grid (video)
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", "testsrc=duration=3:size=1280x720:rate=30",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        video_path
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    # Generate 3 seconds of a standard tone beep (audio)
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi",
        "-i", "sine=frequency=440:duration=3",
        "-c:a", "pcm_s16le",
        audio_path
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    return video_path, audio_path


def trigger_swarm_pipeline(campaign_id: str):
    """
    Submits object created events to our local FastAPI webhook.
    """
    # 1. Generate local files
    video_path, audio_path = generate_offline_test_assets(campaign_id)
    
    # In live storage mode, upload these generated master assets to your actual Tigris master bucket
    # so the orchestrator agent and downstream subagents can fetch them from the cloud!
    video_key = f"campaigns/{campaign_id}/video/master.mp4"
    audio_key = f"campaigns/{campaign_id}/audio/voiceover.wav"
    
    if settings.TIGRIS_LIVE_MODE:
        from src import storage
        st.toast(f"📤 Uploading master creative to Tigris: {settings.TIGRIS_MASTER_BUCKET}...", icon="☁️")
        try:
            with open(video_path, "rb") as f:
                storage.upload_asset(settings.TIGRIS_MASTER_BUCKET, video_key, f.read(), "video/mp4")
            with open(audio_path, "rb") as f:
                storage.upload_asset(settings.TIGRIS_MASTER_BUCKET, audio_key, f.read(), "audio/wav")
            st.toast("✅ Master creative successfully synced to Tigris cloud!", icon="☁️")
        except Exception as e:
            return {"error": f"Failed to upload master creative to Tigris: {e}"}

    # 2. POST object creation notification to the webhook server
    webhook_url = f"http://localhost:{settings.WEBHOOK_PORT}/webhook/tigris"
    
    headers = {
        "Authorization": f"Bearer {settings.WEBHOOK_AUTH_TOKEN}",
        "Content-Type": "application/json"
    }
    
    payload = {
        "events": [
            {
                "eventName": "OBJECT_CREATED_PUT",
                "eventTime": datetime.utcnow().isoformat(),
                "bucket": settings.TIGRIS_MASTER_BUCKET,
                "object": {
                    "key": video_key,
                    "size": os.path.getsize(video_path) if os.path.exists(video_path) else 1024,
                    "eTag": f"vid-{campaign_id}"
                }
            },
            {
                "eventName": "OBJECT_CREATED_PUT",
                "eventTime": datetime.utcnow().isoformat(),
                "bucket": settings.TIGRIS_MASTER_BUCKET,
                "object": {
                    "key": audio_key,
                    "size": os.path.getsize(audio_path) if os.path.exists(audio_path) else 512,
                    "eTag": f"aud-{campaign_id}"
                }
            }
        ]
    }
    
    try:
        r = httpx.post(webhook_url, json=payload, headers=headers)
        return r.json()
    except Exception as e:
        return {"error": f"Could not connect to webhook server: {e}"}


# --- UI LAYOUT ---

st.sidebar.markdown("# 🐝 OmniSwarm")
st.sidebar.markdown("---")
st.sidebar.markdown(f"**Mock Mode**: `{settings.MOCK_SERVICES}`")
st.sidebar.markdown(f"**Target Markets**: `{', '.join(settings.TARGET_MARKETS)}`")
st.sidebar.markdown(f"**FastAPI Webhook Port**: `{settings.WEBHOOK_PORT}`")

st.sidebar.markdown("---")
st.sidebar.markdown("### 🚀 Campaign Trigger")
if "campaign_id" not in st.session_state:
    st.session_state.campaign_id = "gtv_ad"
campaign_input = st.sidebar.text_input("New Campaign ID", value=st.session_state.campaign_id)
st.session_state.campaign_id = campaign_input

if st.sidebar.button("Trigger Agent Swarm", use_container_width=True):
    with st.spinner("Generating test assets and launching swarm..."):
        res = trigger_swarm_pipeline(campaign_input)
        if "error" in res:
            st.sidebar.error(res["error"])
        else:
            st.sidebar.success("🎉 Swarm triggered successfully!")
            time.sleep(0.5)
            st.rerun()

st.sidebar.markdown("---")
auto_refresh = st.sidebar.checkbox("Auto Refresh Logs (2s)", value=True)

# Main Title Area
st.markdown("# 🐝 Global Ad Localization Pipeline")
st.markdown("##### AI Agent Swarm transforming Master Creative Assets in parallel.")
st.markdown("---")

# Query current jobs from database
jobs = database.list_jobs()

if not jobs:
    st.info("No localization jobs active. Trigger a new campaign using the sidebar to begin!")
else:
    # Select Job to view
    job_options = {f"{j['campaign_id']} ({j['id'][:8]}) - {j['status'].upper()}": j["id"] for j in jobs}
    selected_job_key = st.selectbox("Select Active or Completed Campaign", list(job_options.keys()))
    selected_job_id = job_options[selected_job_key]
    
    # Fetch detailed job data
    job = database.get_job(selected_job_id)
    
    if job:
        col_status, col_campaign, col_time = st.columns(3)
        with col_status:
            status_class = f"status-{job['status'].split('-')[0]}"
            st.markdown(f"### Status: <span class='status-badge {status_class}'>{job['status'].upper()}</span>", unsafe_allow_html=True)
        with col_campaign:
            st.markdown(f"### Campaign ID: `{job['campaign_id']}`")
        with col_time:
            st.markdown(f"### Launched: `{job['created_at'].split('T')[1][:8]}`")
            
        st.markdown("---")
        
        # Grid layout
        left_col, right_col = st.columns([1, 1])
        
        with left_col:
            st.subheader("📋 Swarm Audit & Compliance Logs")
            
            # Print logs in terminal-like viewport
            log_text = "\n".join(job["logs"])
            st.markdown(f"<div class='log-box'>{log_text}</div>", unsafe_allow_html=True)
            
            # Display active bucket forks
            st.subheader("📂 Active Isolation Forks")
            if job["forks"]:
                st.json(job["forks"])
            else:
                st.info("No isolation forks currently mapped.")
                
        with right_col:
            st.subheader("🎬 Campaign Creative Assets")
            
            if job["status"] == "completed" and job["results"]:
                results = job["results"]
                
                # Add ORIGINAL tab at index 0 to compare side-by-side
                markets_list = [m.upper() for m in job["markets"]]
                tabs = st.tabs(["ORIGINAL"] + markets_list)
                
                # Tab 0: ORIGINAL Master Creative
                with tabs[0]:
                    st.info("Original Master Creative (English Voiceover, No Subtitles)")
                    
                    master_vid_path = os.path.join(
                        os.path.dirname(os.path.dirname(__file__)),
                        "storage",
                        job["source_bucket"],
                        job["video_key"]
                    )
                    if os.path.exists(master_vid_path):
                        st.video(master_vid_path)
                        st.code(f"Original S3 Location: s3://{job['source_bucket']}/{job['video_key']}", language="bash")
                    else:
                        st.warning(f"Original master file not found at: {master_vid_path}")
                
                # Localized Regional Tabs
                for i, market in enumerate(job["markets"]):
                    with tabs[i + 1]:
                        market_res = results.get(market)
                        if market_res:
                            st.success(f"Localization Bundle Ready for {market.upper()}")
                            
                            # Get localized files
                            output_dir = os.path.join(
                                os.path.dirname(os.path.dirname(__file__)), "storage"
                            )
                            # Video path: storage/output/campaigns/{campaign_id}/{market}/final_ad.mp4
                            relative_vid_path = f"storage/{market_res['output_bucket']}/{market_res['merged_ad_key']}"
                            absolute_vid_path = os.path.join(os.path.dirname(output_dir), relative_vid_path)
                            
                            if os.path.exists(absolute_vid_path):
                                # Load and display video directly
                                st.video(absolute_vid_path)
                                st.code(f"CDN URL: https://cdn.tigris.dev/{market_res['output_bucket']}/{market_res['merged_ad_key']}", language="bash")
                            else:
                                st.warning(f"Video file compiled but not found locally at: {absolute_vid_path}")
                                
                            # Display Cultural Rules applied
                            m_config = get_market_config(market)
                            st.markdown("**🧠 Applied Cultural Strategy Rules:**")
                            for rule in m_config["cultural_notes"]:
                                st.markdown(f"- {rule}")
                        else:
                            st.warning(f"No result returned for market: {market}")
            elif job["status"] == "failed":
                st.error(f" Swarm Pipeline Aborted: {job['error']}")
            else:
                st.info("Swarm Agents are still transforming assets. Localized media players will display here upon assembly completion!")
                st.markdown("### Active Swarm Agent Statuses:")
                for agent_id, data in job["agents"].items():
                    st.markdown(f"- **{agent_id}**: `{data['status'].upper()}`")

# Auto-refresh loop to see live logs print
if auto_refresh:
    time.sleep(2.0)
    st.rerun()
