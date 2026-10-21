import { useCallback, useEffect, useRef, useState } from 'react';
import { DEMO_MODE, textToSpeech } from '../services/api.js';

export function useSpeechPlayback() {
  const [speakingId, setSpeakingId] = useState(null);
  const audioRef = useRef(null);
  const objectUrlRef = useRef(null);
  const activeIdRef = useRef(null);
  const generationRef = useRef(0);

  const stop = useCallback(() => {
    generationRef.current += 1;
    activeIdRef.current = null;
    window.speechSynthesis?.cancel();
    if (audioRef.current) { audioRef.current.pause(); audioRef.current.src = ''; audioRef.current = null; }
    if (objectUrlRef.current) { URL.revokeObjectURL(objectUrlRef.current); objectUrlRef.current = null; }
    setSpeakingId(null);
  }, []);

  const play = useCallback(async (id, text) => {
    if (activeIdRef.current === id) { stop(); return; }
    stop();
    const gen = generationRef.current;
    activeIdRef.current = id;
    setSpeakingId(id);
    try {
      if (DEMO_MODE) {
        if (!window.speechSynthesis) throw new Error('Ваш браузер не поддерживает синтез речи.');
        const utterance = new SpeechSynthesisUtterance(text);
        utterance.lang = 'ru-RU';
        utterance.rate = 1;
        utterance.onend = () => { if (generationRef.current === gen) stop(); };
        utterance.onerror = () => { if (generationRef.current === gen) stop(); };
        window.speechSynthesis.speak(utterance);
      } else {
        const blob = await textToSpeech(text);
        if (generationRef.current !== gen) return;
        const url = URL.createObjectURL(blob);
        objectUrlRef.current = url;
        const audio = new Audio(url);
        audioRef.current = audio;
        audio.onended = () => { if (generationRef.current === gen) stop(); };
        await audio.play();
      }
    } catch (err) {
      if (generationRef.current === gen) stop();
      throw err;
    }
  }, [stop]);

  useEffect(() => () => {
    generationRef.current += 1;
    window.speechSynthesis?.cancel();
    audioRef.current?.pause();
    if (objectUrlRef.current) URL.revokeObjectURL(objectUrlRef.current);
  }, []);
  return { play, stop, speakingId };
}
