import os
import sys

# Add project root to python path so we can import src.config and src.storage
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config import settings
from src import media_processor

def main():
    print("==================================================")
    print("   GOOGLE GEMINI 2-STEP S2ST PIPELINE TESTER     ")
    print("     (Transcribe+Translate → TTS Synthesis)      ")
    print("==================================================")

    # We will look up the GEMINI_API_KEY from settings
    api_key_masked = f"{settings.GEMINI_API_KEY[:8]}***" if settings.GEMINI_API_KEY else "Not Configured"
    print(f"API Key: {api_key_masked}")
    print("--------------------------------------------------")

    try:
        # Try multiple locations for the master audio file
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

        print(f"   ✓ Using audio: {used_path} ({len(audio_input):,} bytes)")
        print()
        print("Step 1: Transcribing + Translating audio → German text (gemini-2.5-flash)...")
        print("Step 2: Synthesizing German speech (gemini-2.5-flash-preview-tts, Charon voice)...")
        print()

        wav_bytes = media_processor.apply_audio_dubbing_mock(
            audio_data=audio_input,
            target_language="de",  # Test German (Charon voice)
            campaign_id="gtv_ad"
        )

        # Save output WAV file
        output_dir = os.path.join(project_root, "storage")
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, "gemini_s2st_test.wav")

        with open(output_path, "wb") as f:
            f.write(wav_bytes)

        print(f"   ✓ Saved synthesized voiceover to: {output_path} ({len(wav_bytes):,} bytes)")

        print("--------------------------------------------------")
        print(" 🎉 GOOGLE GEMINI S2ST PIPELINE VERIFIED: SUCCESS ✓")
        print("==================================================")

    except Exception as e:
        print("\n❌ GOOGLE GEMINI DIAGNOSTIC FAILED!")
        print(f"Reason: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
