'use client';
import { useEffect, useRef, useState } from 'react';
import { api, apiUrl, ensureSession, responseError } from './api';
import { encodeSpeech } from './encode-speech';

export function useSpeechInput(onText: (text: string) => void) {
  const [recording, setRecording] = useState(false);
  const [processing, setProcessing] = useState(false);
  const [notice, setNotice] = useState('');
  const capture = useRef<MediaRecorder | null>(null);
  const busy = useRef(false);
  const cancelled = useRef(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const request = useRef<AbortController | null>(null);
  const write = useRef(onText);
  useEffect(() => { write.current = onText; }, [onText]);
  function release() {
    if (timer.current) clearTimeout(timer.current);
    capture.current?.stream.getTracks().forEach(track => track.stop());
    capture.current = null;
  }
  function dismiss() {
    cancelled.current = true;
    if (capture.current?.state === 'recording') capture.current.stop();
    release(); request.current?.abort(); setRecording(false); setNotice('');
  }
  useEffect(() => () => {
    cancelled.current = true;
    if (capture.current?.state === 'recording') capture.current.stop();
    release(); request.current?.abort();
  }, []);
  function stop() { if (capture.current?.state === 'recording') capture.current.stop(); }
  async function start(existing: string) {
    if (busy.current) return;
    if (!navigator.mediaDevices?.getUserMedia || typeof MediaRecorder === 'undefined') {
      setNotice('이 브라우저는 녹음을 지원하지 않아요. Chrome 또는 Safari에서 이용해 주세요.'); return;
    }
    busy.current = true; cancelled.current = false;
    setNotice('마이크 사용을 준비하고 있어요.');
    try {
      const config = await api<{stt_available?: boolean}>('/v1/config');
      if (!config.stt_available) throw new Error('지금은 음성 입력을 사용할 수 없어요. 잠시 후 다시 시도해 주세요.');
      if (cancelled.current) { busy.current = false; return; }
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      if (cancelled.current) { stream.getTracks().forEach(track => track.stop()); busy.current = false; return; }
      const mimeType = ['audio/webm;codecs=opus', 'audio/mp4', 'audio/webm'].find(type => MediaRecorder.isTypeSupported(type));
      const recorder = new MediaRecorder(stream, mimeType ? { mimeType } : undefined);
      capture.current = recorder;
      const chunks: Blob[] = [];
      recorder.ondataavailable = event => { if (event.data.size) chunks.push(event.data); };
      recorder.onerror = () => { cancelled.current = true; release(); busy.current = false; setRecording(false); setNotice('녹음을 완료하지 못했어요. 다시 눌러 주세요.'); };
      recorder.onstop = async () => {
        release(); setRecording(false);
        if (cancelled.current) { busy.current = false; return; }
        setProcessing(true); setNotice('말씀하신 내용을 글로 옮기고 있어요.');
        const abort = new AbortController(); request.current = abort;
        try {
          const wav = await encodeSpeech(new Blob(chunks, { type: recorder.mimeType }));
          const session = await ensureSession();
          if (cancelled.current) return;
          const response = await fetch(apiUrl('/v1/audio/transcriptions'), {
            method: 'POST', credentials: 'include', body: wav, signal: AbortSignal.any([abort.signal, AbortSignal.timeout(330_000)]),
            headers: { 'Content-Type': 'audio/wav', 'X-CSRF-Token': session.csrf_token },
          });
          if (!response.ok) throw await responseError(response);
          const data = await response.json();
          if (cancelled.current) return;
          if (typeof data.text !== 'string' || !data.text.trim()) throw new Error('목소리를 인식하지 못했어요. 다시 녹음해 주세요.');
          const combined = existing + (existing.trim() ? ' ' : '') + data.text.trim();
          if (combined.length > 12000) throw new Error('변환한 문장이 입력 한도를 넘었어요. 짧게 나누어 녹음해 주세요.');
          write.current(combined);
          setNotice('말씀하신 내용을 입력했어요. 내용을 확인한 뒤 전송해 주세요.');
        } catch (error) {
          if (!cancelled.current) setNotice(error instanceof Error ? error.message : '음성 인식에 실패했어요.');
        } finally { busy.current = false; request.current = null; setProcessing(false); }
      };
      recorder.start(); setRecording(true);
      setNotice('편하게 말씀해 주세요. 다 하셨으면 정지 버튼을 눌러 주세요.');
      timer.current = setTimeout(stop, 600_000);
    } catch (error) {
      release(); busy.current = false;
      setNotice(error instanceof DOMException && error.name === 'NotAllowedError' ? '마이크 사용 권한을 허용해 주세요.' : error instanceof Error ? error.message : '마이크를 시작하지 못했어요.');
    }
  }
  return { recording, processing, notice, start, stop, dismiss, finish: dismiss };
}
