import os
import sys

# Add project root to python path so we can import src.config and src.storage
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import settings
from src import media_processor

def main():
    print("==================================================")
    print("  GEMINI 4-STEP S2ST + MUSIC PRESERVATION TEST   ")
    print("  Step 0: Demucs Stem Split                      ")
    print("  Step 1: Gemini Transcribe + Translate           ")
    print("  Step 2: Gemini TTS Synthesis                    ")
    print("  Step 3: FFmpeg Music Re-mix                     ")
    print("==================================================")

    api_key_masked = f"{settings.GEMINI_API_KEY[:8]}***" if settings.GEMINI_API_KEY else "Not Configured"
    print(f"API Key: {api_key_masked}")
    print("--------------------------------------------------")

    try:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        audio_candidates = [
            os.path.join(project_root, "storage", "canva-swarm-input-live", "campaigns", "gtv_ad", "audio", "voiceover.wav"),
            os.path.join(project_root, "storage", "master", "campaigns", "gtv_ad", "audio", "voiceover.wav"),
            os.path.join(project_root, "storage", "elevenlabs_test.wav"),
        ]

        audio_input = None
        used_path = None
        for candidate in audio_candidates:
            if os.path.exists(candidate):
                with open(candidate, "rb") as f:
                    audio_input = f.read()
                used_path = candidate
                break

        if audio_input is None:
            raise FileNotFoundError(
                "No test audio file found. Tried:\n" + "\n".join(f"  - {p}" for p in audio_candidates)
            )

        print(f"   ✓ Audio source: {used_path} ({len(audio_input):,} bytes)")
        print()
        print("Running full 4-step pipeline (Step 0 may take ~60s for Demucs model download on first run)...")
        print()

        wav_bytes = media_processor.apply_audio_dubbing_mock(
            audio_data=audio_input,
            target_language="de",  # German: Charon voice
            campaign_id="gtv_ad"
        )

        output_dir = os.path.join(project_root, "storage")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, "gemini_s2st_music_test.wav")

        with open(output_path, "wb") as f:
            f.write(wav_bytes)

        print(f"   ✓ Output saved: {output_path} ({len(wav_bytes):,} bytes)")
        print()
        print("--------------------------------------------------")
        print(" 🎉 FULL PIPELINE WITH MUSIC MIX: SUCCESS ✓")
        print("==================================================")

    except Exception as e:
        print("\n❌ PIPELINE TEST FAILED!")
        print(f"Reason: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
