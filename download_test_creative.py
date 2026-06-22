import os
import httpx
import subprocess

def setup_ad_assets():
    campaign_id = "gtv_ad"
    video_dir = "storage/master/campaigns/gtv_ad/video"
    audio_dir = "storage/master/campaigns/gtv_ad/audio"
    
    os.makedirs(video_dir, exist_ok=True)
    os.makedirs(audio_dir, exist_ok=True)
    
    video_path = os.path.join(video_dir, "master.mp4")
    aiff_temp_path = os.path.join(audio_dir, "temp_voiceover.aiff")
    audio_path = os.path.join(audio_dir, "voiceover.wav")
    
    # 1. Download Big Buck Bunny if it doesn't exist
    if not os.path.exists(video_path) or os.path.getsize(video_path) < 1000:
        url = "https://github.com/mediaelement/mediaelement-files/raw/master/big_buck_bunny.mp4"
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        print(f"Downloading test ad video from GitHub raw: {url}...")
        try:
            with httpx.Client(follow_redirects=True, timeout=90.0, headers=headers) as client:
                r = client.get(url)
                r.raise_for_status()
                with open(video_path, "wb") as f:
                    f.write(r.content)
            print(f"Successfully downloaded video to: {video_path} ({len(r.content)} bytes)")
        except Exception as e:
            print(f"Download failed: {e}")
            return
    else:
        print(f"Video file already exists at: {video_path}. Skipping download.")
        
    # 2. Generate a spoken English voiceover using macOS built-in 'say' engine!
    # This guarantees actual English dialogue about a food ad for your hackathon pitch!
    spoken_text = (
        "Welcome to the forest campaign. "
        "Try to find the fluffy, big buck bunny today. "
        "He is extremely friendly, loves fresh carrots, and is loaded with energy. "
        "I'm loving it!"
    )
    
    print(f"Generating spoken voiceover using macOS 'say' engine: '{spoken_text}'...")
    try:
        # Generate raw audio file using macOS say utility
        subprocess.run(["say", "-o", aiff_temp_path, spoken_text], check=True)
        
        # Convert to high-quality standard WAV format using local FFmpeg
        print("Converting spoken audio to WAV format using FFmpeg...")
        subprocess.run([
            "ffmpeg", "-y", "-i", aiff_temp_path,
            "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
            audio_path
        ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        
        # Clean up temp aiff file
        if os.path.exists(aiff_temp_path):
            os.remove(aiff_temp_path)
            
        print(f"🎉 Successfully generated and paired spoken voiceover WAV file at: {audio_path}")
        
        # Remux the master video to natively contain the English voiceover track!
        print("Remuxing the silent master video with the English voiceover track...")
        temp_silent_video = os.path.join(video_dir, "silent_temp.mp4")
        if os.path.exists(video_path):
            os.rename(video_path, temp_silent_video)
            
            subprocess.run([
                "ffmpeg", "-y",
                "-i", temp_silent_video,
                "-i", audio_path,
                "-c:v", "copy",
                "-c:a", "aac",
                "-map", "0:v:0",
                "-map", "1:a:0",
                "-shortest",
                video_path
            ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            if os.path.exists(temp_silent_video):
                os.remove(temp_silent_video)
            print("🎉 Original master video successfully remuxed with English voiceover track!")
        
    except Exception as e:
        print(f"Failed to generate spoken voiceover: {e}")

if __name__ == "__main__":
    setup_ad_assets()
