'use client';
import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import { AnimatePresence, motion, MotionConfig } from 'motion/react';
import { ArrowUp, Mic, Square, X, Copy, Check, RotateCcw, Volume2, Globe } from 'lucide-react';
import { Streamdown } from 'streamdown';
import { Button } from '@base-ui/react/button';
import { modes, useChatStore } from '@/lib/chat-store';
import { useSpeechInput } from '@/lib/use-speech-input';
import { useChatApi } from '@/lib/use-chat-api';
import { GlassSurface } from './glass-surface';
import { AnswerActivity } from './answer-activity';
import { useFileDrop } from '@/lib/use-file-drop';
import { useAttachments } from '@/lib/use-attachments';
import type { Attachment } from '@/lib/api';
import { AttachmentCard, AttachmentMenu, FileSource } from './attachment-ui';
import { ModelSettings } from './model-settings';
import { resolveLearningVoice, type LearningView } from '@/lib/learning-voice';
import { learningPrompt } from '@/lib/learning-topics';
import { useLearningProgress } from '@/lib/use-learning-progress';
import { learningSpaces, practiceVoiceIndex } from '@/lib/learning-journeys';
import { LearningHeader } from './learning-header';
import { useSpeechOutput } from '@/lib/use-speech-output';
import { storage, useChatWorkspace } from '@/lib/use-chat-workspace';
import { WorkspaceMenu } from './workspace-menu';
import { useStudyStudio } from '@/lib/use-study-studio';
import { StudyStudio } from './study-studio';

export function Chat() {
  const { mode, setMode, messages, streaming } = useChatStore();
  const [input, setInput] = useState('');
  const [learningView, setLearningView] = useState<LearningView>({ open: false, topicId: null });
  const learning = useLearningProgress();
  const [learningContext, setLearningContext] = useState<{ mode: typeof mode; prompt: string; label: string } | null>(null);
  useEffect(() => { setLearningView(v => ({ open: v.open, topicId: null, practice: false })); setLearningContext(null); }, [mode]);
  const [pendingVoice, setPendingVoice] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [copyError, setCopyError] = useState<string | null>(null);
  const chatApi = useChatApi();
  const workspace = useChatWorkspace();
  const studio = useStudyStudio(workspace.user);
  const output = useSpeechOutput();
  const attachments = useAttachments(workspace);
  const [search, setSearch] = useState<boolean | null>(null);
  const [draftReady, setDraftReady] = useState(false);
  useEffect(() => {
    setInput(storage.get('modurouter-draft') || '');
    const saved = storage.get('modurouter-search');
    setSearch(saved === 'true' ? true : saved === 'false' ? false : null);
    setDraftReady(true);
  }, []);
  useEffect(() => { if (draftReady) storage.set('modurouter-draft', input); }, [input, draftReady]);
  useEffect(() => { if (draftReady) storage.set('modurouter-search', String(search)); }, [search, draftReady]);
  const composer = useRef<HTMLFormElement>(null);
  const draggingFile = useFileDrop(composer, files => { if (!disabled) void attachments.add(files); });
  const [requestError, setRequestError] = useState('');
  const controls = useRef<HTMLDivElement>(null);
  const root = useRef<HTMLElement>(null);
  const textarea = useRef<HTMLTextAreaElement>(null);
  const followConversation = useRef(true);
  const modeTrack = useRef<HTMLDivElement>(null);
  const pointerStart = useRef<number | null>(null);
  const selected = modes.findIndex((m) => m.id === mode);
  const currentMode = modes[selected];
  const speech = useSpeechInput((text, transcript) => {
    if (mode === 'student' && learningView.open) { studio.voice(transcript); return; }
    if (learningView.open && learningView.practice) {
      if (/뒤로|전체.*활동/.test(transcript)) { setLearningView({ open: true, topicId: null }); return; }
      if (/다시.*연습|처음부터/.test(transcript)) { learning.restart(mode); return; }
      const index = practiceVoiceIndex(mode, learning.progress[mode], transcript);
      if (index !== null) { learning.choose(mode, index); return; }
      setRequestError('선택지 이름을 말해 주세요.'); return;
    }
    const choice = resolveLearningVoice(transcript, learningView, mode);
    if (choice?.type === 'practice') { setLearningContext(null); setLearningView({ open: true, topicId: null, practice: true }); return; }
    if (choice?.type === 'open' || choice?.type === 'back') {
      setLearningView({ open: true, topicId: null }); return;
    }
    if (choice?.type === 'topic') {
      setLearningView({ open: true, topicId: choice.topicId }); return;
    }
    if (choice?.type === 'activity') {
      setLearningContext({ mode, prompt: choice.prompt, label: choice.title });
      setLearningView(view => ({ ...view, open: false }));
    } else if (learningView.open) {
      setLearningContext({ mode, label: learningSpaces[mode].title, prompt: learningPrompt('원하는 활동을 명확히 알 수 없으면 무엇을 배우고 싶은지 한 가지 물어봐 주세요.') });
    }
    setInput(text);
    if (text.length > 12000) {
      setRequestError('말씀하신 내용이 길어요. 내용을 나누어 전송해 주세요.');
      return;
    }
    setPendingVoice(text);
  });
  const recording = speech.recording;
  const disabled = streaming || workspace.busy || recording || speech.processing || (mode === 'student' && learningView.open && studio.busy);
  useEffect(() => {
    if (!pendingVoice) return;
    if (disabled) return;
    setPendingVoice(null);
    send(pendingVoice, attachments.ready, true);
  // Voice submits immediately with the files that are ready at transcription completion.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingVoice, disabled]);
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
    try { await workspace.cancelRecovery(); await chatApi.stop(); } catch (error) { setRequestError(error instanceof Error ? error.message : '중지 요청에 실패했어요.'); }
  }
  function send(retryText?: string, retryFiles?: Attachment[], clearDraft = retryText === undefined, context = learningContext?.mode === mode ? learningContext.prompt : '') {
    const text = (retryText ?? input).trim();
    if (!text || disabled || useChatStore.getState().streaming || (clearDraft && retryFiles === undefined && attachments.blocked)) return;
    if (retryText === undefined && mode === 'student' && learningView.open) { studio.voice(text); setInput(''); return; }
    if (retryText === undefined && learningView.open && learningView.practice) {
      const index = practiceVoiceIndex(mode, learning.progress[mode], text);
      if (index !== null) { learning.choose(mode, index); setInput(''); return; }
      setRequestError('선택지 이름을 입력해 주세요.'); return;
    }
    output.stop();
    setPendingVoice(null);
    if (clearDraft) setInput('');
    setRequestError(''); speech.dismiss(); followConversation.current = true;
    const files = retryFiles ?? attachments.ready;
    void chatApi.send(text, mode, { attachment_ids: files.map(file => file.id), attachments: files, search_enabled: search, learning_context: context }).then(() => {
      const last = useChatStore.getState().messages.at(-1);
      if (last?.activity?.status === 'complete') workspace.clearAttachments();
      else if (last?.activity?.status === 'error' && clearDraft) setInput(prior => prior || text);
    });
    textarea.current?.focus();
  }
  function selectFromPointer(x: number) {
    const rect = modeTrack.current?.getBoundingClientRect();
    if (rect) setMode(modes[Math.max(0, Math.min(2, Math.floor((x - rect.left) / (rect.width / 3))))].id);
  }
  return <MotionConfig reducedMotion="user"><main ref={root} className={`app mode-${mode} ${messages.length ? 'has-messages' : ''}`}>
    <LearningHeader studentContent={<StudyStudio studio={studio} disabled={disabled} guest={workspace.user?.guest ?? true} onCoach={async () => {
      const id = await studio.conversation();
      if (!id) return;
      output.stop(); setPendingVoice(null);
      await workspace.openConversation(id);
      if (useChatStore.getState().conversationId !== id) return;
      setLearningContext({mode:'student',label:studio.task?.title || '학습 스튜디오',prompt:''});
      setLearningView(view => ({...view,open:false}));
      setInput('지금 학습 단계에서 제가 생각해 볼 점을 하나씩 알려 주세요.');
      textarea.current?.focus();
    }}/>} navigation={<WorkspaceMenu workspace={workspace} disabled={disabled} onNavigate={() => { output.stop(); speech.dismiss(); setInput(''); setPendingVoice(null); setLearningContext(null); }} />} mode={mode} progress={learning.progress[mode]} ready={learning.ready} onPracticeChoice={index => { setRequestError(''); learning.choose(mode, index); }} onRestart={() => learning.restart(mode)} onClear={() => learning.clear(mode)} view={learningView} onViewChange={view => { if (view.practice) setLearningContext(null); setLearningView(view); }} disabled={disabled} onChoose={(prompt, label) => { setLearningContext({ mode, prompt, label }); send(label, attachments.ready, false, prompt); }} />
    <section className="workspace" aria-label="대화">
      {learningContext?.mode === mode && <div className="learning-context"><span>{learningContext.label}</span><button type="button" aria-label="학습 마치기" disabled={disabled} onClick={() => { if (learningContext.mode === 'student') { workspace.newConversation(); setInput(''); } setLearningContext(null); }}><X size={14} /></button></div>}
      {messages.length > 0 && <div className="conversation" role="log" aria-label="대화 내용" aria-live="off">
        {messages.map((message, messageIndex) => <motion.article initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} key={message.id} className={`message message-${message.role}`} aria-label={message.role === 'user' ? '내 질문' : '답변'}>
          {!!message.attachments?.length && <div className="message-attachments">{message.attachments.map(file => <AttachmentCard key={file.id} file={file} />)}</div>}
          {message.role === 'assistant' && <AnswerActivity message={message} />}
          {message.content ? <Streamdown className="message-content" isAnimating={streaming && message === messages.at(-1)}>{message.content}</Streamdown> : message.activity?.status === 'writing' ? <span className="thinking" aria-label="응답 준비 중"><i /><i /><i /></span> : null}
          {message.error && <p className="answer-error" role="alert">{message.error}</p>}
          {!!message.sources?.length && <div className="answer-sources" aria-label="참고한 자료">{message.sources.map((source, i) => <span key={`${source.source_id}-${i}`}>{source.attachment_id ? <FileSource source={source} /> : source.url && /^https?:\/\//.test(source.url) ? <a href={source.url} target="_blank" rel="noopener noreferrer">[{source.source_id}] {source.title}</a> : <span>[{source.source_id}] {source.title}</span>}{source.truncated && !source.attachment_id ? ' (일부)' : ''}</span>)}</div>}
          {message.role === 'assistant' && message.activity?.status !== 'writing' && <div className="answer-actions">
            <Button disabled={!message.content} aria-label="답변 복사" onClick={async () => { try { await navigator.clipboard.writeText(message.content); setCopied(message.id); setCopyError(null); } catch { setCopyError(message.id); } }}>{copied === message.id ? <Check size={15} /> : <Copy size={15} />}<span>{copied === message.id ? '복사됨' : '복사'}</span></Button>
            <Button disabled={!message.content} aria-pressed={output.speaking === message.id} onClick={() => void output.speak(message.id, message.content)}><Volume2 size={15} /><span>{output.speaking === message.id ? '읽기 중지' : '읽어주기'}</span></Button>
            <Button disabled={disabled} onClick={() => { const question = messages.slice(0, messageIndex).findLast((item) => item.role === 'user'); if (question) send(question.content, question.attachments); }}><RotateCcw size={15} /><span>다시 생성</span></Button>
            {copyError === message.id && <span role="status">복사하지 못했어요. 다시 눌러 주세요.</span>}
          </div>}
        </motion.article>)}
      </div>}
      <div className="controls" ref={controls}>
        {(workspace.error || output.error) && <p className="request-error" role="alert">{workspace.error || output.error}</p>}
        {workspace.busy && <p className="workspace-status" role="status">대화와 자료를 확인하고 있어요.</p>}
        {pendingVoice && streaming && <p className="request-error" role="status">답변이 끝나면 이어서 전송할게요.<button type="button" onClick={() => setPendingVoice(null)}>전송 취소</button></p>}
        {requestError && <p className="request-error" role="alert">{requestError}</p>}
        <AnimatePresence>{speech.notice && <motion.div className="voice-panel glass" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} exit={{ opacity: 0, y: 8 }} role="status">
          <div className="voice-wave" aria-hidden="true">{[12, 24, 17, 32, 20, 28, 14].map((height, i) => <span key={i} style={{ height, animationDelay: `${i * .1}s` }} />)}</div>
          <p>{speech.notice}</p>
          <Button aria-label="음성 입력 안내 닫기" onClick={speech.dismiss}><X size={18} /></Button>
        </motion.div>}</AnimatePresence>
        <div className="composer-tools"><AttachmentMenu attachments={attachments} disabled={disabled} labeled /><label className="search-mode" title="자동 모드에서는 질문에 따라 웹 자료를 확인합니다."><Globe size={16} aria-hidden="true"/><select aria-label="웹 검색 모드" disabled={disabled} value={search === null ? 'auto' : search ? 'on' : 'off'} onChange={event => setSearch(event.target.value === 'auto' ? null : event.target.value === 'on')}><option value="auto">웹 검색 자동</option><option value="on">웹 검색 항상</option><option value="off">웹 검색 끄기</option></select></label></div>
        <div className="input-row">
          <form ref={composer} className={`composer glass ${draggingFile ? 'is-file-over' : ''}`} onPaste={e => { if (!disabled && e.clipboardData.files.length) { e.preventDefault(); void attachments.add(Array.from(e.clipboardData.files)); } }} onSubmit={(e) => { e.preventDefault(); send(); }}>
            <GlassSurface />
            {!!attachments.selected.length && <div className="composer-attachments">{attachments.selected.map(file => <div key={file.localId}><AttachmentCard file={file} onRemove={disabled ? undefined : () => attachments.toggle(file.localId)} /></div>)}</div>}
            {attachments.error && <p className="attachment-error" role="alert">{attachments.error}<button type="button" onClick={attachments.clearError} aria-label="첨부 안내 닫기"><X size={14} /></button></p>}
            <div className="composer-entry">
            <textarea ref={textarea} aria-label="메시지 입력" placeholder={currentMode.placeholder} value={input} readOnly={recording || speech.processing || workspace.busy || (mode === 'student' && learningView.open && studio.busy)} rows={1} maxLength={12000} onChange={(e) => { setPendingVoice(null); setInput(e.target.value); }} />
            <motion.button whileTap={{ scale: .92 }} className={`send-button ${input.trim() || streaming ? 'is-ready' : ''}`} type={streaming ? 'button' : 'submit'} onClick={streaming ? () => stop() : undefined} disabled={!streaming && (!input.trim() || disabled || attachments.blocked)} aria-label={streaming ? '응답 중지' : '메시지 전송'}>{streaming ? <Square size={17} fill="currentColor" /> : <ArrowUp size={29} strokeWidth={1.7} />}</motion.button>
            </div>
          </form>
          <motion.button className={`microphone glass ${recording ? 'is-recording' : ''}`} whileHover={{ scale: 1.045 }} whileTap={{ scale: .94 }} disabled={!recording && (streaming || workspace.busy || speech.processing)} onClick={() => { output.stop(); if (recording) speech.stop(); else { setPendingVoice(null); setRequestError(''); void speech.start(input); } }} aria-label={recording ? '녹음 종료 후 전송' : '음성 입력'} title="음성으로 입력하기 / 최대 10분" aria-pressed={recording}><GlassSurface radius={50} tone="accent" />{recording ? <Square size={21} strokeWidth={1.5} /> : <Mic size={27} strokeWidth={1.45} />}</motion.button>
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
