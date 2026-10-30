"""Converts uploaded voice notes (WhatsApp OGG/Opus, Android AAC/AMR) to 16 kHz mono WAV for speech-to-text."""
import shutil
import subprocess


class AudioConversionError(Exception):
    pass


def is_wav(audio: bytes) -> bool:
    return audio[:4] == b"RIFF" and audio[8:12] == b"WAVE"


def to_wav_16k(audio: bytes, filename: str = "") -> bytes:
    if is_wav(audio):
        return audio
    if shutil.which("ffmpeg") is None:
        raise AudioConversionError("ffmpeg is not installed, so this audio format cannot be converted")
    proc = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", "pipe:0", "-f", "wav", "-ar", "16000", "-ac", "1", "pipe:1"],
                          input=audio, capture_output=True, timeout=30)
    if proc.returncode != 0 or not proc.stdout:
        raise AudioConversionError(f"ffmpeg failed: {proc.stderr.decode(errors='replace')[:200]}")
    return proc.stdout


def to_ogg_opus(audio: bytes) -> bytes:
    """WhatsApp voice notes must be OGG/Opus; our TTS returns WAV."""
    if shutil.which("ffmpeg") is None:
        raise AudioConversionError("ffmpeg is not installed, so voice replies cannot be sent as audio")
    proc = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", "pipe:0", "-c:a", "libopus", "-f", "ogg", "pipe:1"],
                          input=audio, capture_output=True, timeout=30)
    if proc.returncode != 0 or not proc.stdout:
        raise AudioConversionError(f"ffmpeg failed: {proc.stderr.decode(errors='replace')[:200]}")
    return proc.stdout
