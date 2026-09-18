'use client';
import { useEffect, useRef, useState } from 'react';

export function koreanVoice(synthesis: SpeechSynthesis): Promise<SpeechSynthesisVoice | null> {
  const find = () => synthesis.getVoices().find(voice => voice.lang.toLowerCase().startsWith('ko')) || null;
  const available = find();
  if (available) return Promise.resolve(available);
  return new Promise(resolve => {
    let timer: ReturnType<typeof setTimeout>;
    const finish = (voice: SpeechSynthesisVoice | null) => { clearTimeout(timer); synthesis.removeEventListener('voiceschanged', check); resolve(voice); };
    const check = () => { const voice = find(); if (voice) finish(voice); };
    synthesis.addEventListener('voiceschanged', check);
    timer = setTimeout(() => finish(find()), 3000);
    check();
  });
}
export function useSpeechOutput() {
  const [speaking, setSpeaking] = useState<string | null>(null);
  const [error, setError] = useState('');
  const request = useRef(0);
  function stop() { request.current++; window.speechSynthesis?.cancel(); setSpeaking(null); }
  useEffect(() => {
    window.speechSynthesis?.getVoices();
    const leave = () => { request.current++; window.speechSynthesis?.cancel(); };
    window.addEventListener('pagehide', leave);
    return () => { window.removeEventListener('pagehide', leave); leave(); };
  }, []);
  async function speak(id: string, text: string) {
    if (!window.speechSynthesis) { setError('이 브라우저는 답변 읽어주기를 지원하지 않습니다.'); return; }
    const prior = speaking;
    stop(); setError('');
    if (prior === id) return;
    const operation = request.current;
    setSpeaking(id);
    const voice = await koreanVoice(window.speechSynthesis);
    if (operation !== request.current) return;
    if (!voice) { setSpeaking(null); setError('사용 가능한 한국어 음성이 없습니다. 기기의 음성 설정을 확인해 주세요.'); return; }
    const utterance = new SpeechSynthesisUtterance(text.replace(/[#*`]/g, ''));
    utterance.lang = 'ko-KR'; utterance.voice = voice;
    utterance.onend = () => { if (operation === request.current) setSpeaking(null); };
    utterance.onerror = () => { if (operation === request.current) { setSpeaking(null); setError('답변 읽어주기를 완료하지 못했습니다.'); } };
    window.speechSynthesis.speak(utterance);
  }
  return { speaking, error, speak, stop };
}
