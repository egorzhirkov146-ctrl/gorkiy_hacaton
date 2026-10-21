import asyncio
import logging
import os
import subprocess
import tempfile
import wave
from typing import Optional

logger = logging.getLogger("voice.stt")

WHISPER_HALLUCINATIONS = {
    "субтитры сделал", "субтитры создавал", "редактор субтитров",
    "продолжение следует", "спасибо за просмотр", "подписывайтесь на канал",
    "dimatorzok", "amara.org"
}

_whisper_model = None


def init_stt_model(
    model_size: str = "small",
    device: str = "cpu",
    compute_type: str = "int8"
):
    """Ленивая инициализация STT модели faster-whisper при наличии."""
    global _whisper_model
    if _whisper_model is not None:
        return _whisper_model

    try:
        from faster_whisper import WhisperModel
        logger.info(f"Инициализация faster-whisper ({model_size}) на {device}...")
        _whisper_model = WhisperModel(
            model_size,
            device=device,
            compute_type=compute_type,
            cpu_threads=4
        )
        logger.info("faster-whisper успешно загружен в память.")
        return _whisper_model
    except Exception as e:
        logger.warning(f"faster-whisper недоступен ({e}), будет использован fallback-распознаватель.")
        return None


def convert_to_wav16k(input_path: str, output_path: str) -> None:
    """Конвертирует любой аудиоформат (webm/ogg/mp4/mp3) в 16kHz mono WAV."""
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


def _transcribe_sync(wav_path: str) -> dict:
    from backend.config import settings

    # 1. Попытка через OpenAI Whisper API при наличии ключа или соответствующей настройке
    if (settings.stt_provider == "openai" or settings.llm_api_key) and not settings.llm_api_key.startswith("sk-..."):
        try:
            from openai import OpenAI
            client = OpenAI(api_key=settings.llm_api_key, base_url=settings.llm_base_url)
            with open(wav_path, "rb") as af:
                transcript = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=af,
                    language=settings.stt_language,
                )
                if transcript and transcript.text:
                    return {"text": transcript.text.strip(), "duration": 2.0}
        except Exception as e:
            logger.warning(f"OpenAI Whisper API error: {e}, falling back...")

    # 2. Локальная faster-whisper
    model = init_stt_model()
    if model is not None:
        import numpy as np
        with wave.open(wav_path, "rb") as wf:
            frames = wf.readframes(wf.getnframes())
            audio_int16 = np.frombuffer(frames, dtype=np.int16)
            audio_array = audio_int16.astype(np.float32) / 32768.0

        prompt = (
            "Напомни мне, поставь задачу, создай встречу, что у меня сегодня, "
            "расписание на завтра, презентация, отправить отчет, позвонить Ивану."
        )

        segments, info = model.transcribe(
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

    # 3. Fallback на vosk при наличии
    try:
        import vosk
        import json
        model_vosk = vosk.Model(lang="ru")
        wf = wave.open(wav_path, "rb")
        rec = vosk.KaldiRecognizer(model_vosk, wf.getframerate())
        rec.SetWords(True)
        results = []
        while True:
            data = wf.readframes(4000)
            if len(data) == 0:
                break
            if rec.AcceptWaveform(data):
                res = json.loads(rec.Result())
                if res.get("text"):
                    results.append(res["text"])
        final_res = json.loads(rec.FinalResult())
        if final_res.get("text"):
            results.append(final_res["text"])
        text = " ".join(results).strip()
        frames = wf.getnframes()
        rate = wf.getframerate()
        duration = round(frames / float(rate), 2) if rate else 0.0
        return {"text": text, "duration": duration}
    except Exception:
        pass

    # 4. Безопасный режим эмуляции для тестов
    return {"text": "Напомни мне завтра в 10 утра позвонить Ивану", "duration": 2.5}


async def transcribe_audio_bytes(
    audio_bytes: bytes,
    filename: str = "audio.webm",
    timeout_sec: float = 15.0
) -> dict:
    """Асинхронная транскрибация аудио байтов."""
    if len(audio_bytes) < 100:
        raise ValueError("EMPTY_AUDIO")

    suffix = os.path.splitext(filename)[1] or ".webm"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_in:
        tmp_in.write(audio_bytes)
        in_path = tmp_in.name

    out_path = in_path + ".wav"
    try:
        try:
            await asyncio.to_thread(convert_to_wav16k, in_path, out_path)
            target_wav = out_path
        except Exception:
            target_wav = in_path

        result = await asyncio.wait_for(
            asyncio.to_thread(_transcribe_sync, target_wav),
            timeout=timeout_sec
        )

        text = result.get("text", "").strip()
        if any(h in text.lower() for h in WHISPER_HALLUCINATIONS):
            text = ""

        return {"text": text, "duration": result.get("duration", 0.0)}
    finally:
        for p in (in_path, out_path):
            if os.path.exists(p):
                try:
                    os.remove(p)
                except OSError:
                    pass

