import os
import sys
import subprocess

# Add project root to python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

def main():
    campaign_id = "kokila_ad"
    video_dir = "storage/master/campaigns/kokila_ad/video"
    audio_dir = "storage/master/campaigns/kokila_ad/audio"
    
    os.makedirs(video_dir, exist_ok=True)
    os.makedirs(audio_dir, exist_ok=True)
    
    video_path = os.path.join(video_dir, "master.mp4")
    audio_path = os.path.join(audio_dir, "voiceover.wav")
    
    url = "https://www.youtube.com/watch?v=SjhBeIz1tDI"
    
    print("==================================================")
    print("      KOKILA BEN TEST ASSETS GENERATOR            ")
    print("==================================================")
    print(f"Downloading short segment of Kokila Ben rap from: {url}...")
    
    # We download the first 8 seconds using yt-dlp's download-sections option
    cmd = [
        "venv/bin/yt-dlp",
        "-f", "mp4[height<=480]",  # Download 480p for fast download
        "--download-sections", "*00:00-00:08",
        "--force-keyframes-at-cuts",
        "-o", video_path,
        url
    ]
    
    try:
        subprocess.run(cmd, check=True)
        print(f"✓ Video successfully downloaded to: {video_path}")
        
        # Extract audio using FFmpeg
        print("Extracting audio track from video using FFmpeg...")
        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-vn",
            "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
            audio_path
        ]
        subprocess.run(ffmpeg_cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print(f"✓ Audio successfully extracted to: {audio_path}")
        
        print("--------------------------------------------------")
        print(" 🎉 KOKILA BEN TEST CAMPAIGN ASSETS GENERATED SUCCESSFUL!")
        print(" Campaign ID: kokila_ad")
        print("==================================================")
        
    except Exception as e:
        print(f"❌ Failed to download/process Kokila Ben clip: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
