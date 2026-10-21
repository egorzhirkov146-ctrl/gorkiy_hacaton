import { useCallback, useEffect, useRef, useState } from 'react';

const MAX_DURATION = 90;

function pickMime() {
  if (!window.MediaRecorder) return null;
  const options = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/webm', 'audio/ogg;codecs=opus'];
  return typeof MediaRecorder.isTypeSupported === 'function' ? options.find(m => MediaRecorder.isTypeSupported(m)) || '' : '';
}

export function useAudioRecorder({ onRecorded, onError, enableBrowserSTT = false }) {
  const [recording, setRecording] = useState(false);
  const [preparing, setPreparing] = useState(false);
  const startingRef = useRef(false);
  const [seconds, setSeconds] = useState(0);
  const recorderRef = useRef(null);
  const recognitionRef = useRef(null);
  const transcriptRef = useRef('');
  const enableBrowserSTTRef = useRef(enableBrowserSTT);
  enableBrowserSTTRef.current = enableBrowserSTT;
  const streamRef = useRef(null);
  const chunksRef = useRef([]);
  const canceledRef = useRef(false);
  const clockRef = useRef(null);
  const onRecordedRef = useRef(onRecorded);
  const onErrorRef = useRef(onError);
  const mountedRef = useRef(true);
  onRecordedRef.current = onRecorded;
  onErrorRef.current = onError;

  const release = useCallback(() => {
    if (clockRef.current) clearInterval(clockRef.current);
    clockRef.current = null;
    streamRef.current?.getTracks().forEach(track => track.stop());
    streamRef.current = null;
    if (mountedRef.current) { setRecording(false); setSeconds(0); }
  }, []);

  const stop = useCallback((cancel = false) => {
    const recorder = recorderRef.current;
    if (!recorder || recorder.state === 'inactive') return;
    canceledRef.current = cancel;
    try { recognitionRef.current?.stop(); } catch { /* already stopped */ }
    recorder.stop();
    release();
  }, [release]);

  const start = useCallback(async () => {
    if (startingRef.current || recorderRef.current) return;
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
      onErrorRef.current?.('Браузер не поддерживает запись. Попробуйте Chrome или Safari на HTTPS.');
      return;
    }
    startingRef.current = true;
    setPreparing(true);
    let stream;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
      if (!mountedRef.current) { stream.getTracks().forEach(t=>t.stop()); return; }
      streamRef.current = stream;
      chunksRef.current = [];
      canceledRef.current = false;
      transcriptRef.current = '';
      if (enableBrowserSTTRef.current) {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (SpeechRecognition) {
          try {
            const recognition = new SpeechRecognition();
            recognition.lang = 'ru-RU';
            recognition.continuous = true;
            recognition.interimResults = true;
            recognition.onresult = (event) => {
              let current = '';
              for (let i = 0; i < event.results.length; i++) current += `${event.results[i][0]?.transcript || ''} `;
              transcriptRef.current = current.trim();
            };
            recognition.onerror = () => { /* optional demo fallback may be unavailable */ };
            recognition.start();
            recognitionRef.current = recognition;
          } catch { recognitionRef.current = null; }
        }
      }
      const mimeType = pickMime();
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      recorderRef.current = recorder;
      recorder.ondataavailable = (event) => {
        if (event.data?.size > 0) chunksRef.current.push(event.data);
      };
      recorder.onerror = () => {
        canceledRef.current = true;
        try { recognitionRef.current?.abort(); } catch { /* best effort */ }
        onErrorRef.current?.('Ошибка во время записи. Повторите попытку.');
        release();
      };
      recorder.onstop = () => {
        const blob = new Blob(chunksRef.current, { type: recorder.mimeType || chunksRef.current[0]?.type || 'audio/webm' });
        const canceled = canceledRef.current;
        recorderRef.current = null;
        chunksRef.current = [];
        release();
        if (!canceled && mountedRef.current) {
          if (blob.size > 0) {
            // Give SpeechRecognition a moment to deliver its last final result.
            if (enableBrowserSTTRef.current && recognitionRef.current) {
              setTimeout(() => {
                if (mountedRef.current) onRecordedRef.current?.(blob, transcriptRef.current);
                recognitionRef.current = null;
              }, 400);
            } else onRecordedRef.current?.(blob, '');
          }
          else onErrorRef.current?.('Аудио не записалось. Попробуйте ещё раз.');
        }
      };
      recorder.start();
      setRecording(true);
      setSeconds(0);
      const startTime = Date.now();
      clockRef.current = setInterval(() => {
        const elapsed = Math.floor((Date.now() - startTime) / 1000);
        if (mountedRef.current) setSeconds(elapsed);
        if (elapsed >= MAX_DURATION && recorder.state === 'recording') stop(false);
      }, 250);
    } catch (err) {
      try { recognitionRef.current?.abort(); } catch { /* best effort */ }
      recognitionRef.current = null;
      stream?.getTracks().forEach(t=>t.stop());
      release();
      onErrorRef.current?.(err?.name === 'NotAllowedError' || err?.name === 'PermissionDeniedError'
        ? 'Нет доступа к микрофону. Разрешите его в настройках браузера.'
        : 'Не удалось запустить микрофон. Проверьте устройство и HTTPS.');
    } finally {
      startingRef.current = false;
      if (mountedRef.current) setPreparing(false);
    }
  }, [release, stop]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      canceledRef.current = true;
      try { recognitionRef.current?.abort(); } catch { /* not active */ }
      if (recorderRef.current?.state === 'recording') recorderRef.current.stop();
      release();
    };
  }, [release]);

  return { recording, preparing, seconds, start, stop, cancel: () => stop(true) };
}
