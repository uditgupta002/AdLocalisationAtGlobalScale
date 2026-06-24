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

def is_drawtext_supported() -> bool:
    if not is_ffmpeg_installed():
        return False
    try:
        res = subprocess.run(["ffmpeg", "-filters"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        return "drawtext" in res.stdout
    except Exception:
        return False

import struct

def pcm_to_wav(pcm_data: bytes, sample_rate: int = 24000, num_channels: int = 1, bits_per_sample: int = 16) -> bytes:
    """
    Constructs a valid 44-byte RIFF/WAV header for raw PCM audio data in pure Python.
    """
    subchunk2_size = len(pcm_data)
    chunk_size = 36 + subchunk2_size
    byte_rate = sample_rate * num_channels * bits_per_sample // 8
    block_align = num_channels * bits_per_sample // 8
    
    header = struct.pack(
        '<4sI4s4sIHHIIHH4sI',
        b'RIFF',
        chunk_size,
        b'WAVE',
        b'fmt ',
        16,                # Subchunk1Size (16 for PCM)
        1,                 # AudioFormat (1 = PCM)
        num_channels,
        sample_rate,
        byte_rate,
        block_align,
        bits_per_sample,
        b'data',
        subchunk2_size
    )
    return header + pcm_data

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
            if is_drawtext_supported():
                text_overlay_escaped = text_overlay.replace("'", "'\\''").replace(":", "\\:")
                drawtext_str = f"drawtext=text='{text_overlay_escaped}':x=(w-text_w)/2:y=h-80:fontsize=28:fontcolor={font_color}:box=1:boxcolor={bg_color}@0.8:boxborderw=10"
                if font_path:
                    drawtext_str += f":fontfile='{font_path}'"
                vf_filters.append(drawtext_str)
            else:
                logger.warning("FFmpeg installed but does NOT support the 'drawtext' filter (requires libfreetype). Skipping text overlay.")
            
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
    Audio dubbing using Google Gemini 4-step S2ST pipeline with music preservation:
    """
    if not settings.GEMINI_LIVE_MODE:
        logger.info(f"[S2ST] Mock Mode Enabled (GEMINI_LIVE_MODE=False). Returning mock audio track for language '{target_language}'.")
        return audio_data

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
    import sys
    import os

    # Check if Gemini key is set
    if not settings.GEMINI_API_KEY or settings.GEMINI_API_KEY == "your_gemini_api_key":
        raise ValueError(
            "GEMINI_API_KEY is not configured in your .env file! "
            "Please create a key in Google AI Studio and save it as GEMINI_API_KEY to run live S2ST translation."
        )

    client = genai.Client(api_key=settings.GEMINI_API_KEY)

    with tempfile.TemporaryDirectory() as tmpdir:
        # Write original audio to disk for processing
        original_wav = os.path.join(tmpdir, "original.wav")
        with open(original_wav, "wb") as f:
            f.write(audio_data)

        # ── STEP 0: Stem Separation — split vocals from background music ────
        logger.info("[S2ST Step 0] Running Facebook Demucs stem separation (vocals + background music)...")

        vocals_path = None
        music_path = None
        demucs_out = os.path.join(tmpdir, "demucs_stems")

        try:
            # Use demucs with --two-stems=vocals to get vocals + no_vocals
            # --flac avoids the torchcodec/torchaudio WAV-writer dependency on Python 3.14+
            result = subprocess.run(
                [
                    sys.executable, "-m", "demucs",
                    "--two-stems", "vocals",
                    "--flac",                   # output as FLAC (FFmpeg-compatible, no torchcodec needed)
                    "--out", demucs_out,
                    original_wav,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=300,  # 5 min timeout for model download + inference
            )

            if result.returncode != 0:
                stderr_msg = result.stderr.decode("utf-8", errors="replace")[-500:]
                logger.warning(f"[S2ST Step 0] Demucs exited with code {result.returncode}: {stderr_msg}")
            else:
                # Use glob to find stems anywhere under demucs_out
                # (works regardless of model name: htdemucs, mdx_extra, mdx, etc.)
                import glob
                # Match both .flac (preferred) and .wav (fallback)
                vocals_matches = (
                    glob.glob(os.path.join(demucs_out, "**", "vocals.flac"), recursive=True) or
                    glob.glob(os.path.join(demucs_out, "**", "vocals.wav"),  recursive=True)
                )
                music_matches = (
                    glob.glob(os.path.join(demucs_out, "**", "no_vocals.flac"), recursive=True) or
                    glob.glob(os.path.join(demucs_out, "**", "no_vocals.wav"),  recursive=True)
                )

                if vocals_matches and music_matches:
                    vocals_path = vocals_matches[0]
                    music_path  = music_matches[0]
                    logger.info(
                        f"[S2ST Step 0] ✓ Stems separated — "
                        f"vocals={os.path.getsize(vocals_path):,}B  "
                        f"music={os.path.getsize(music_path):,}B"
                    )
                else:
                    all_found = glob.glob(os.path.join(demucs_out, "**", "*"), recursive=True)
                    logger.warning(
                        f"[S2ST Step 0] Demucs ran OK but stems not found. "
                        f"Files under output dir: {all_found[:10]}"
                    )

        except Exception as e:
            logger.warning(f"[S2ST Step 0] Demucs stem separation failed: {e}. Proceeding with full audio (no music separation).")

        # If demucs failed, fall back to the original audio for translation
        vocals_for_translation = vocals_path if vocals_path else original_wav

        # ── STEP 1: Transcribe + Translate vocals → translated text ─────────
        logger.info(f"[S2ST Step 1] Transcribing and translating to {target_lang_name} using gemini-2.5-flash...")

        with open(vocals_for_translation, "rb") as f:
            vocals_bytes = f.read()

        audio_part = types.Part.from_bytes(data=vocals_bytes, mime_type="audio/wav")

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

        # ── STEP 2: TTS — Synthesize translated text into speech ─────────────
        logger.info(f"[S2ST Step 2] Synthesizing {target_lang_name} speech via gemini-2.5-flash-preview-tts (Voice: {voice_name})...")

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

        # Decode PCM → WAV (Gemini TTS returns raw PCM: s16le, 24kHz, mono)
        raw_path = os.path.join(tmpdir, "gemini_tts.pcm")
        speech_wav = os.path.join(tmpdir, "speech.wav")

        with open(raw_path, "wb") as f:
            f.write(generated_audio_bytes)

        transcoded = False
        if is_ffmpeg_installed():
            logger.info("Transcoding Gemini TTS PCM → 44.1kHz stereo WAV via FFmpeg...")
            try:
                subprocess.run([
                    "ffmpeg", "-y",
                    "-f", "s16le",    # signed 16-bit little-endian PCM
                    "-ar", "24000",   # Gemini TTS native sample rate
                    "-ac", "1",       # mono
                    "-i", raw_path,
                    "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2",
                    speech_wav,
                ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                transcoded = True
            except Exception as e:
                logger.warning(f"FFmpeg transcoding failed: {e}. Falling back to pure Python PCM-to-WAV.")
                transcoded = False

        if not transcoded:
            logger.info("Writing WAV header via pure Python fallback (no FFmpeg)...")
            try:
                wav_data = pcm_to_wav(generated_audio_bytes, sample_rate=24000, num_channels=1, bits_per_sample=16)
                with open(speech_wav, "wb") as f:
                    f.write(wav_data)
            except Exception as e:
                logger.error(f"Failed to write pure Python PCM-to-WAV fallback: {e}")
                # As a last-ditch effort, just write PCM bytes directly to speech_wav
                with open(speech_wav, "wb") as f:
                    f.write(generated_audio_bytes)

        # ── STEP 3: Re-mix — translated speech + original background music ───
        final_wav = os.path.join(tmpdir, "final_dubbed.wav")

        mixed = False
        if music_path and os.path.exists(music_path) and is_ffmpeg_installed():
            logger.info("[S2ST Step 3] Re-mixing translated speech with original background music...")
            try:
                # Mix strategy:
                #   - Speech (translated): 0 dB (full volume, foreground)
                #   - Background music: -4 dB (slightly ducked so speech is intelligible)
                # amix normalizes by default; use weights to duck music slightly
                subprocess.run([
                    "ffmpeg", "-y",
                    "-i", speech_wav,       # input 0: translated speech
                    "-i", music_path,       # input 1: original background music
                    "-filter_complex",
                    # Normalize both to 44100 stereo, then mix with music ducked -4dB
                    "[0:a]aresample=44100,aformat=sample_fmts=s16:channel_layouts=stereo[speech];"
                    "[1:a]aresample=44100,aformat=sample_fmts=s16:channel_layouts=stereo,volume=0.63[music];"
                    "[speech][music]amix=inputs=2:duration=longest:dropout_transition=0[out]",
                    "-map", "[out]",
                    "-acodec", "pcm_s16le",
                    final_wav,
                ], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                mixed = True
                logger.info(f"✓ Google Gemini S2ST + Music Mix completed for {target_lang_name}!")
            except Exception as e:
                logger.warning(f"[S2ST Step 3] FFmpeg remixing failed: {e}. Falling back to speech-only output.")
                mixed = False

        if not mixed:
            # No music stem available or remix failed or FFmpeg missing — use speech-only output
            logger.info("[S2ST Step 3] No background music stem or FFmpeg remix failed — using speech-only output.")
            final_wav = speech_wav

        with open(final_wav, "rb") as f:
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
