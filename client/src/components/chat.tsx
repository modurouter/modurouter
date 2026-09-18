'use client';
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { AnimatePresence, motion, MotionConfig } from 'motion/react';
import { ArrowUp, Mic, Square, X, Copy, Check, RotateCcw } from 'lucide-react';
import { Streamdown } from 'streamdown';
import { Button } from '@base-ui/react/button';
import { modes, useChatStore } from '@/lib/chat-store';
import { useSpeechInput } from '@/lib/use-speech-input';
import { useChatApi } from '@/lib/use-chat-api';
import { GlassSurface } from './glass-surface';
import { AnswerActivity } from './answer-activity';
import { ModelSettings } from './model-settings';

export function Chat() {
  const { mode, setMode, messages, streaming } = useChatStore();
  const [input, setInput] = useState('');
  const [copied, setCopied] = useState<string | null>(null);
  const [copyError, setCopyError] = useState<string | null>(null);
  const speech = useSpeechInput(setInput);
  const recording = speech.recording;
  const chatApi = useChatApi();
  const [requestError, setRequestError] = useState('');
  const controls = useRef<HTMLDivElement>(null);
  const root = useRef<HTMLElement>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const followConversation = useRef(true);
  const modeTrack = useRef<HTMLDivElement>(null);
  const pointerStart = useRef<number | null>(null);
  const selected = modes.findIndex((m) => m.id === mode);
  const currentMode = modes[selected];
  useEffect(() => {
    const onScroll = () => {
      followConversation.current = document.documentElement.scrollHeight - window.scrollY - window.innerHeight < 100;
    };
    window.addEventListener('scroll', onScroll, { passive: true });
    return () => window.removeEventListener('scroll', onScroll);
  }, []);
  useEffect(() => {
    if (!messages.length || !followConversation.current) return;
    const frame = requestAnimationFrame(() => window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'instant' }));
    return () => cancelAnimationFrame(frame);
  }, [messages]);
  useLayoutEffect(() => {
    const el = controls.current;
    if (!el) return;
    const measure = () => {
      root.current?.style.setProperty('--controls-height', `${el.getBoundingClientRect().height}px`);
      if (followConversation.current && useChatStore.getState().messages.length) {
        window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'instant' });
      }
    };
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    measure();
    return () => observer.disconnect();
  }, []);
  useLayoutEffect(() => {
    const el = textarea.current;
    if (!el) return;
    const resize = () => {
      el.style.height = '0px';
      el.style.height = `${el.scrollHeight}px`;
    };
    resize();
    let width = el.getBoundingClientRect().width;
    const observer = new ResizeObserver(() => {
      const nextWidth = el.getBoundingClientRect().width;
      if (nextWidth !== width) { width = nextWidth; resize(); }
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [input, mode]);
  async function stop() {
    try { await chatApi.stop(); } catch (error) { setRequestError(error instanceof Error ? error.message : '중지 요청에 실패했어요.'); }
  }
  function send(retryText?: string) {
    const text = (retryText ?? input).trim();
    if (!text || streaming) return;
    if (!retryText) setInput('');
    setRequestError(''); speech.dismiss(); followConversation.current = true;
    void chatApi.send(text, mode);
    textarea.current?.focus();
  }
  function selectFromPointer(x: number) {
    const rect = modeTrack.current?.getBoundingClientRect();
    if (rect) setMode(modes[Math.max(0, Math.min(2, Math.floor((x - rect.left) / (rect.width / 3))))].id);
  }
  return <MotionConfig reducedMotion="user"><main ref={root} className={`app mode-${mode} ${messages.length ? 'has-messages' : ''}`}>
    <header><span className="wordmark">modurouter</span></header>
    <section className="workspace" aria-label="대화">
      {messages.length > 0 && <div className="conversation" role="log" aria-label="대화 내용" aria-live="off">
        {messages.map((message, messageIndex) => <motion.article initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} key={message.id} className={`message message-${message.role}`} aria-label={message.role === 'user' ? '내 질문' : '답변'}>
          {message.role === 'assistant' && <AnswerActivity message={message} />}
          {message.content ? <Streamdown className="message-content" isAnimating={streaming && message === messages.at(-1)}>{message.content}</Streamdown> : message.activity?.status === 'writing' ? <span className="thinking" aria-label="응답 준비 중"><i /><i /><i /></span> : null}
          {message.error && <p className="answer-error" role="alert">{message.error}</p>}
          {!!message.sources?.length && <div className="answer-sources" aria-label="참고한 자료">{message.sources.map((source, i) => <span key={`${source.source_id}-${i}`}>{source.url && /^https?:\/\//.test(source.url) ? <a href={source.url} target="_blank" rel="noopener noreferrer">[{source.source_id}] {source.title}</a> : <span>[{source.source_id}] {source.title}</span>}{source.truncated ? ' (일부)' : ''}</span>)}</div>}
          {message.role === 'assistant' && message.activity?.status !== 'writing' && <div className="answer-actions">
            <Button disabled={!message.content} aria-label="답변 복사" onClick={async () => { try { await navigator.clipboard.writeText(message.content); setCopied(message.id); setCopyError(null); } catch { setCopyError(message.id); } }}>{copied === message.id ? <Check size={15} /> : <Copy size={15} />}<span>{copied === message.id ? '복사됨' : '복사'}</span></Button>
            <Button disabled={streaming} onClick={() => { const question = messages.slice(0, messageIndex).findLast((item) => item.role === 'user'); if (question) send(question.content); }}><RotateCcw size={15} /><span>다시 생성</span></Button>
            {copyError === message.id && <span role="status">복사하지 못했어요. 다시 눌러 주세요.</span>}
          </div>}
        </motion.article>)}
      </div>}
      <div className="controls" ref={controls}>
        {requestError && <p className="request-error" role="alert">{requestError}</p>}
        <AnimatePresence>{speech.notice && <motion.div className="voice-panel glass" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 8 }} role="status">
          <div className="voice-wave" aria-hidden="true">{[12, 24, 17, 32, 20, 28, 14].map((height, i) => <span key={i} style={{ height, animationDelay: `${i * .1}s` }} />)}</div>
          <p>{speech.notice}</p>
          <Button aria-label="음성 입력 안내 닫기" onClick={speech.dismiss}><X size={18} /></Button>
        </motion.div>}</AnimatePresence>
        <div className="input-row">
          <form className="composer glass" onSubmit={(e) => { e.preventDefault(); send(); }}>
            <GlassSurface />
            <textarea ref={textarea} aria-label="메시지 입력" placeholder={currentMode.placeholder} value={input} rows={1} maxLength={12000} onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing && e.keyCode !== 229) { e.preventDefault(); send(); } }} />
            <motion.button whileTap={{ scale: .92 }} className={`send-button ${input.trim() || streaming ? 'is-ready' : ''}`} type={streaming ? 'button' : 'submit'} onClick={streaming ? () => stop() : undefined} disabled={!streaming && !input.trim()} aria-label={streaming ? '응답 중지' : '메시지 전송'}>{streaming ? <Square size={17} fill="currentColor" /> : <ArrowUp size={29} strokeWidth={1.7} />}</motion.button>
          </form>
          <motion.button className={`microphone glass ${recording ? 'is-recording' : ''}`} whileHover={{ scale: 1.045 }} whileTap={{ scale: .94 }} disabled={speech.processing} onClick={() => recording ? speech.stop() : void speech.start(input)} aria-label={recording ? '음성 입력 중지' : '음성 입력'} title="음성으로 입력하기 · 최대 10분" aria-pressed={recording}><GlassSurface radius={50} />{recording ? <Square size={21} strokeWidth={1.5} /> : <Mic size={27} strokeWidth={1.45} />}</motion.button>
        </div>
        <div className="settings-row">
        <div className="mode-track glass" role="radiogroup" aria-label="대화 모드" ref={modeTrack} onPointerDown={(e) => { pointerStart.current = e.clientX; }} onPointerMove={(e) => { if (pointerStart.current !== null && Math.abs(e.clientX - pointerStart.current) > 6) { e.currentTarget.setPointerCapture(e.pointerId); selectFromPointer(e.clientX); } }} onPointerUp={() => { pointerStart.current = null; }} onPointerCancel={() => { pointerStart.current = null; }}>
          <GlassSurface radius={21} />
          <motion.div initial={false} className="mode-indicator" animate={{ x: `${selected * 100}%` }} transition={{ type: 'spring', stiffness: 420, damping: 34 }} />
          {modes.map((item, index) => <button key={item.id} type="button" role="radio" aria-checked={mode === item.id} tabIndex={mode === item.id ? 0 : -1} onClick={() => setMode(item.id)} onKeyDown={(e) => { if (['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(e.key)) { e.preventDefault(); const next = e.key === 'Home' ? 0 : e.key === 'End' ? 2 : (index + (e.key === 'ArrowRight' ? 1 : 2)) % 3; setMode(modes[next].id); (e.currentTarget.parentElement?.querySelectorAll('button')[next] as HTMLButtonElement)?.focus(); } }}>{item.label}</button>)}
        </div>
        <ModelSettings />
        </div>
      </div>
    </section>
    <span className="sr-only" role="status">{streaming ? '응답을 작성하고 있습니다' : messages.at(-1)?.activity?.status === 'error' ? '응답 처리에 실패했습니다' : messages.at(-1)?.activity?.status === 'stopped' ? '응답이 중지되었습니다' : messages.length ? '응답이 완료되었습니다' : ''}</span>
  </main></MotionConfig>;
}
