import os
import subprocess
import tempfile
from src.config import settings
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
    Audio dubbing using Google Gemini 2-step S2ST pipeline:

    Step 1 — Transcribe + Translate (gemini-2.5-flash):
        Input audio → transcribed + translated text in target language.

    Step 2 — Text-to-Speech (gemini-2.5-flash-preview-tts):
        Translated text → synthesized audio in target language voice.

    This preserves tone and style through the translation prompt instructions,
    and produces high-quality native-language speech output.
    """
    from src.config import MARKET_CONFIGS
    voice_name = "Aoede"  # Default
    target_lang_name = "Japanese"  # Default

    # Map target language to Gemini prebuilt voice and language profile
    for market_id, profile in MARKET_CONFIGS.items():
        if profile.get("language_code") == target_language.lower() or profile.get("gemini_lang") == target_language.lower():
            voice_name = profile.get("gemini_voice_name", voice_name)
            target_lang_name = profile.get("name", target_lang_name)
            break

    from google import genai
    from google.genai import types
    import tempfile
    import subprocess
    import os

    # Check if Gemini key is set
    if not settings.GEMINI_API_KEY or settings.GEMINI_API_KEY == "your_gemini_api_key":
        raise ValueError(
            "GEMINI_API_KEY is not configured in your .env file! "
            "Please create a key in Google AI Studio and save it as GEMINI_API_KEY to run live S2ST translation."
        )

    client = genai.Client(api_key=settings.GEMINI_API_KEY)

    # ── STEP 1: Transcribe + Translate audio → text ─────────────────────────
    logger.info(f"[S2ST Step 1] Transcribing and translating audio to {target_lang_name} using gemini-2.5-flash...")

    audio_part = types.Part.from_bytes(
        data=audio_data,
        mime_type="audio/wav"
    )

    transcribe_prompt = (
        f"Listen carefully to the spoken audio and translate the speech into natural, fluent {target_lang_name}.\n"
        f"Instructions:\n"
        f"- Output ONLY the translated {target_lang_name} text. No explanations, no English text, no markdown.\n"
        f"- Preserve the speaker's tone: energetic, promotional, enthusiastic.\n"
        f"- Keep the same pacing and rhythm as the original when spoken aloud.\n"
        f"- Use natural, colloquial {target_lang_name} that sounds like native advertising voiceover."
    )

    transcribe_response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[transcribe_prompt, audio_part],
    )

    translated_text = transcribe_response.text.strip()
    if not translated_text:
        raise ValueError(
            f"Gemini transcription/translation returned empty text for {target_lang_name}. "
            "Check that the audio file contains clear speech."
        )
    logger.info(f"[S2ST Step 1] ✓ Translated text ({target_lang_name}): {translated_text[:120]}...")

    # ── STEP 2: TTS — Synthesize translated text into speech ────────────────
    logger.info(f"[S2ST Step 2] Synthesizing {target_lang_name} speech using gemini-2.5-flash-preview-tts (Voice: {voice_name})...")

    tts_prompt = (
        f"Read the following {target_lang_name} text aloud as a professional advertising voiceover.\n"
        f"Use an energetic, enthusiastic, warm tone. Sound like a native {target_lang_name} speaker.\n\n"
        f"{translated_text}"
    )

    tts_config = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(
                    voice_name=voice_name
                )
            )
        ),
    )

    tts_response = client.models.generate_content(
        model="gemini-2.5-flash-preview-tts",
        contents=tts_prompt,
        config=tts_config,
    )

    # Extract the generated audio bytes from the TTS response
    generated_audio_bytes = None
    if tts_response.candidates:
        for candidate in tts_response.candidates:
            if candidate.content and candidate.content.parts:
                for part in candidate.content.parts:
                    if part.inline_data and part.inline_data.data:
                        generated_audio_bytes = part.inline_data.data
                        break
                if generated_audio_bytes:
                    break

    if not generated_audio_bytes:
        raise ValueError(
            f"Gemini TTS returned no audio data for {target_lang_name}. "
            "Verify your API Key supports gemini-2.5-flash-preview-tts and check billing."
        )

    # Convert returned audio (PCM/L16 24kHz mono) → standard 44.1kHz stereo WAV via FFmpeg
    with tempfile.TemporaryDirectory() as tmpdir:
        # TTS returns raw PCM audio (little-endian 16-bit, 24kHz, mono)
        raw_path = os.path.join(tmpdir, "gemini_tts.pcm")
        wav_path = os.path.join(tmpdir, "gemini_tts.wav")

        with open(raw_path, "wb") as f:
            f.write(generated_audio_bytes)

        logger.info("Transcoding Gemini TTS PCM stream → standard 44.1kHz stereo WAV via FFmpeg...")
        subprocess.run([
            "ffmpeg", "-y",
            "-f", "s16le",       # signed 16-bit little-endian PCM
            "-ar", "24000",      # Gemini TTS outputs at 24kHz
            "-ac", "1",          # mono
            "-i", raw_path,
            "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
            wav_path
        ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        with open(wav_path, "rb") as f:
            logger.info(f"✓ Google Gemini S2ST pipeline completed for {target_lang_name}!")
            return f.read()


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
