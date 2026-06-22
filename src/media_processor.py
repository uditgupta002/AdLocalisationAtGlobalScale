import os
import subprocess
import tempfile
from src.utils.logger import setup_logger

logger = setup_logger("swarm-media")

# Helper to find standard macOS fonts
def get_system_font_path() -> str:
    common_paths = [
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/System/Library/Fonts/Helvetica.ttc",
        "/System/Library/Fonts/Supplemental/Courier New.ttf",
        "/Library/Fonts/Arial.ttf"
    ]
    for path in common_paths:
        if os.path.exists(path):
            return path
    return ""

def is_ffmpeg_installed() -> bool:
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except FileNotFoundError:
        return False

def apply_video_transformation(
    video_data: bytes,
    text_overlay: str,
    font_color: str = "white",
    bg_color: str = "red",
    brightness: float = 0.0,
    saturation: float = 1.0
) -> bytes:
    """
    Applies text overlays and color correction filters locally using FFmpeg.
    If FFmpeg is not installed, gracefully returns the original video data.
    """
    if not is_ffmpeg_installed():
        logger.warning("FFmpeg is NOT installed on this system! Gracefully bypassing media transformation (returning raw input).")
        return video_data

    logger.info("Applying local FFmpeg visual transformation...")
    
    font_path = get_system_font_path()
    
    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = os.path.join(tmpdir, "input.mp4")
        output_path = os.path.join(tmpdir, "output.mp4")
        
        with open(input_path, "wb") as f:
            f.write(video_data)
            
        # Build FFmpeg command filters
        # 1. Color grade: eq = brightness, saturation
        # 2. Text overlay: drawtext
        vf_filters = []
        
        # Color correction
        if brightness != 0.0 or saturation != 1.0:
            vf_filters.append(f"eq=brightness={brightness}:saturation={saturation}")
            
        # Drawtext filter
        if text_overlay:
            text_overlay_escaped = text_overlay.replace("'", "'\\''").replace(":", "\\:")
            drawtext_str = f"drawtext=text='{text_overlay_escaped}':x=(w-text_w)/2:y=h-80:fontsize=28:fontcolor={font_color}:box=1:boxcolor={bg_color}@0.8:boxborderw=10"
            if font_path:
                drawtext_str += f":fontfile='{font_path}'"
            vf_filters.append(drawtext_str)
            
        vf_arg = ",".join(vf_filters) if vf_filters else "copy"
        
        cmd = [
            "ffmpeg", "-y", "-i", input_path,
            "-vf", vf_arg,
            "-c:a", "copy",
            output_path
        ]
        
        logger.debug(f"Executing: {' '.join(cmd)}")
        try:
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            with open(output_path, "rb") as f:
                return f.read()
        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg command failed: {e.stderr.decode('utf-8')}")
            logger.warning("Returning unmodified video input due to FFmpeg process error.")
            return video_data


def apply_audio_dubbing_mock(audio_data: bytes, target_language: str, campaign_id: str = "gtv_ad") -> bytes:
    """
    Mock audio dubbing. In production, this calls ElevenLabs.
    For the local MVP, we use the macOS native 'say' command to speak in the target language!
    This enables full offline localized audio demos at the hackathon.
    """
    logger.info(f"Simulating ElevenLabs dubbing voiceover for language: '{target_language}' (Campaign: '{campaign_id}')")
    
    # Translate the marketing script to Japanese, German, Hindi, and English
    # Supports both the default forest campaign (gtv_ad) and the viral Kokila Ben campaign (kokila_ad)!
    campaign_scripts = {
        "gtv_ad": {
            "ja": "フォレストキャンペーンへようこそ。今日、ふわふわのビッグ・バック・バニーを見つけてみてください。彼はとてもフレンドリーで、新鮮なニンジンが大好きで、エネルギーに満ちています。私はうさぎが大好きだ！",
            "de": "Willkommen zur Waldkampagne. Versuchen Sie heute, das flauschige Big Buck Bunny zu finden. Es ist extrem freundlich, liebt frische Karotten und ist voller Energie. Ich liebe Hasen!",
            "hi": "जंगल अभियान में आपका स्वागत है। आज प्यारे, बिग बक बनी को खोजने की कोशिश करें। वह बहुत अनुकूल है, उसे ताज़ी गाजर पसंद है, और वह ऊर्जा से भरपूर है। मुझे यह बहुत पसंद है!",
            "en": "Welcome to the forest campaign. Try to find the fluffy, big buck bunny today. He is extremely friendly, loves fresh carrots, and is loaded with energy. Absolutely loving it!"
        },
        "kokila_ad": {
            "ja": "ラソデには誰がいましたか？私でしたか？あなたでしたか？誰ですか？炊飯器から豆を抜いたのは誰ですか？答えなさい！",
            "de": "Wer war in der Küche? War ich es? Warst du es? Wer war es? Wer hat die Kichererbsen aus dem Schnellkochtopf genommen? Antworte mir!",
            "hi": "रसोड़े में कौन था? मैं थी? तुम थी? कौन था? प्रेशर कुकर में से चने किसने निकाल दिए और खाली कुकर गैस पर चढ़ा दिया? बताओ!",
            "en": "Who was in the kitchen? Was it me? Was it you? Who was it? Who removed the chickpeas from the pressure cooker and put the empty cooker on the stove? Tell me!"
        }
    }
    
    scripts = campaign_scripts.get(campaign_id.lower(), campaign_scripts["gtv_ad"])
    translated_text = scripts.get(target_language.lower(), scripts["en"])
    if not translated_text:
        # Fallback to standard pass-through if unknown language
        return audio_data
        
    # 2. Try to run macOS 'say' command
    with tempfile.TemporaryDirectory() as tmpdir:
        aiff_path = os.path.join(tmpdir, "dubbed.aiff")
        wav_path = os.path.join(tmpdir, "dubbed.wav")
        
        # Determine language voice parameters if possible
        # macOS has standard voices: ja -> Kyoko, de -> Anna, hi -> Lekha, en -> Samantha
        cmd_say = ["say", "-o", aiff_path, translated_text]
        
        if target_language.lower() == "ja":
            try:
                # Test if native Kyoko voice is preloaded
                subprocess.run(["say", "-v", "Kyoko", "テスト"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                cmd_say = ["say", "-v", "Kyoko", "-o", aiff_path, translated_text]
            except (subprocess.CalledProcessError, FileNotFoundError):
                logger.warning("Kyoko voice is not downloaded on this macOS host. Falling back to default system voice.")
        elif target_language.lower() == "de":
            try:
                # Test if native Anna voice is preloaded
                subprocess.run(["say", "-v", "Anna", "test"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                cmd_say = ["say", "-v", "Anna", "-o", aiff_path, translated_text]
            except (subprocess.CalledProcessError, FileNotFoundError):
                logger.warning("Anna voice is not downloaded on this macOS host. Falling back to default system voice.")
        elif target_language.lower() == "hi":
            try:
                # Test if native Lekha voice is preloaded
                subprocess.run(["say", "-v", "Lekha", "नमस्ते"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                cmd_say = ["say", "-v", "Lekha", "-o", aiff_path, translated_text]
            except (subprocess.CalledProcessError, FileNotFoundError):
                logger.warning("Lekha voice is not downloaded on this macOS host. Falling back to default system voice.")
        elif target_language.lower() == "en":
            try:
                # Test if native Samantha voice is preloaded
                subprocess.run(["say", "-v", "Samantha", "test"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                cmd_say = ["say", "-v", "Samantha", "-o", aiff_path, translated_text]
            except (subprocess.CalledProcessError, FileNotFoundError):
                logger.warning("Samantha voice is not downloaded on this macOS host. Falling back to default system voice.")
        
        try:
            logger.info(f"Executing local voice synthesizer for '{target_language}': {translated_text}")
            subprocess.run(cmd_say, check=True)
            
            # Convert AIFF output to standard WAV
            subprocess.run([
                "ffmpeg", "-y", "-i", aiff_path,
                "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
                wav_path
            ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            with open(wav_path, "rb") as f:
                return f.read()
                
        except Exception as e:
            logger.warning(f"Local speech synthesis failed or unsupported on this host OS: {e}. Falling back to original pass-through audio.")
            return audio_data


def merge_video_audio(video_data: bytes, audio_data: bytes) -> bytes:
    """
    Merges separate video and audio files into a single MP4 container using FFmpeg.
    """
    if not is_ffmpeg_installed():
        logger.warning("FFmpeg NOT installed! Returning video data as the final merged output.")
        return video_data
        
    logger.info("Merging video and audio streams using FFmpeg...")
    with tempfile.TemporaryDirectory() as tmpdir:
        video_path = os.path.join(tmpdir, "video.mp4")
        audio_path = os.path.join(tmpdir, "audio.wav")
        output_path = os.path.join(tmpdir, "merged.mp4")
        
        with open(video_path, "wb") as f:
            f.write(video_data)
        with open(audio_path, "wb") as f:
            f.write(audio_data)
            
        # Re-mux: copy video stream, encode audio as aac
        cmd = [
            "ffmpeg", "-y",
            "-i", video_path,
            "-i", audio_path,
            "-c:v", "copy",
            "-c:a", "aac",
            "-map", "0:v:0",
            "-map", "1:a:0",
            "-shortest",
            output_path
        ]
        
        logger.debug(f"Executing: {' '.join(cmd)}")
        try:
            subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            with open(output_path, "rb") as f:
                return f.read()
        except subprocess.CalledProcessError as e:
            logger.error(f"FFmpeg merge failed: {e.stderr.decode('utf-8')}")
            return video_data
