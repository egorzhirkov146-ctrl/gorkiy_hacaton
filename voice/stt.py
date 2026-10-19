import asyncio
import logging
import os
import subprocess
import tempfile
import wave
from typing import Optional
import numpy as np
from faster_whisper import WhisperModel

logger = logging.getLogger("voice.stt")

WHISPER_HALLUCINATIONS = {
    "субтитры сделал", "субтитры создавал", "редактор субтитров",
    "продолжение следует", "спасибо за просмотр", "подписывайтесь на канал",
    "dimatorzok", "amara.org"
}

_model: Optional[WhisperModel] = None


def init_stt_model(
    model_size: str = "small",
    device: str = "cpu",
    compute_type: str = "int8"
) -> WhisperModel:
    """Загружает модель в память один раз при старте приложения."""
    global _model
    if _model is None:
        logger.info(f"Инициализация faster-whisper ({model_size}) на {device}...")
        _model = WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type,
            cpu_threads=4
        )
        logger.info("faster-whisper успешно загружен в память.")
    return _model


def convert_to_wav16k(input_path: str, output_path: str) -> None:
    """Конвертирует webm/ogg/mp4/mp3 в 16kHz mono WAV с подавлением гула."""
    cmd = [
        "ffmpeg", "-y",
        "-i", input_path,
        "-vn",
        "-acodec", "pcm_s16le",
        "-ar", "16000",
        "-ac", "1",
        "-af", "highpass=f=80,lowpass=f=8000",
        output_path
    ]
    res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if res.returncode != 0:
        err = res.stderr.decode("utf-8", errors="ignore")
        logger.error(f"FFmpeg error: {err}")
        raise ValueError("Ошибка конвертации аудиофайла.")


def load_wav_as_float32(wav_path: str) -> np.ndarray:
    """Прямое чтение WAV в массив float32 (обходит ошибку PyAV metadata_errors)."""
    with wave.open(wav_path, "rb") as wf:
        frames = wf.readframes(wf.getnframes())
        audio_int16 = np.frombuffer(frames, dtype=np.int16)
        return audio_int16.astype(np.float32) / 32768.0


def _transcribe_sync(wav_path: str) -> dict:
    if _model is None:
        raise RuntimeError("STT модель не инициализирована. Вызовите init_stt_model().")

    audio_array = load_wav_as_float32(wav_path)
    prompt = (
        "Напомни мне, поставь задачу, создай встречу, что у меня сегодня, "
        "расписание на завтра, презентация, отправить отчет, позвонить Ивану."
    )

    segments, info = _model.transcribe(
        audio_array,
        language="ru",
        beam_size=3,
        vad_filter=True,
        vad_parameters=dict(min_silence_duration_ms=400, speech_pad_ms=200),
        condition_on_previous_text=False,
        initial_prompt=prompt
    )

    parts = [seg.text.strip() for seg in segments if seg.no_speech_prob < 0.7]
    text = " ".join(parts).strip()

    return {"text": text, "duration": round(info.duration, 2)}


async def transcribe_audio_bytes(
    audio_bytes: bytes,
    filename: str = "audio.webm",
    timeout_sec: float = 15.0
) -> dict:
    """Основная асинхронная функция обработки аудио."""
    if len(audio_bytes) < 500:
        raise ValueError("EMPTY_AUDIO")

    suffix = os.path.splitext(filename)[1] or ".webm"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_in:
        tmp_in.write(audio_bytes)
        in_path = tmp_in.name

    out_path = in_path + ".wav"
    try:
        await asyncio.to_thread(convert_to_wav16k, in_path, out_path)
        result = await asyncio.wait_for(
            asyncio.to_thread(_transcribe_sync, out_path),
            timeout=timeout_sec
        )

        text = result["text"]
        if not text or any(h in text.lower() for h in WHISPER_HALLUCINATIONS):
            raise ValueError("NO_SPEECH_DETECTED")

        return result
    finally:
        for p in (in_path, out_path):
            if os.path.exists(p):
                os.remove(p)
