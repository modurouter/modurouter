'use client';
import { useEffect, useRef } from 'react';
import { api, apiUrl, ApiError, fetchApi, consumeEvents, ensureSession, responseError, runErrorMessage, type Run, type Source, type User } from './api';
import { useModelSettings, effortOptions, modelKey, routingFor } from './model-settings';
import { useChatStore, type Mode } from './chat-store';

const stages: Record<string, string> = { accepted: '질문 접수', preparing: '대화 준비 중', model: '답변 준비 중', tool: '자료 확인 중', streaming: '답변 작성 중', context_truncated: '입력 한도에 맞춰 일부 맥락 제외', tool_warning: '일부 자료 확인 실패' };
const active = (run: Run) => ['accepted', 'preparing', 'model', 'tool', 'streaming'].includes(run.status);

export function useChatApi() {
  const session = useRef<User | null>(null);
  const conversation = useRef<string | null>(null);
  const current = useRef<{ runId?: string; cancel: boolean; cancelling: boolean } | null>(null);
  const uncertain = useRef<{ body: string; key: string; conversation: string } | null>(null);
  useEffect(() => {
    const leave = () => {
      if (current.current?.runId && session.current) void fetch(apiUrl(`/v1/runs/${current.current.runId}/cancel`), { method: 'POST', credentials: 'include', keepalive: true, headers: { 'X-CSRF-Token': session.current.csrf_token } }).catch(() => {});
    };
    window.addEventListener('pagehide', leave);
    return () => { window.removeEventListener('pagehide', leave); leave(); };
  }, []);

  async function stop() {
    const operation = current.current;
    if (!operation || operation.cancelling) return;
    operation.cancel = true;
    if (!operation.runId || !session.current) return;
    operation.cancelling = true;
    try { await api(`/v1/runs/${operation.runId}/cancel`, { method: 'POST' }, session.current.csrf_token); }
    catch { operation.cancelling = false; operation.cancel = false; throw new Error('중지 요청을 보내지 못했어요. 다시 눌러 주세요.'); }
  }

  async function send(text: string, mode: Mode, options: {attachment_ids?: string[]; search_enabled?: boolean | null} = {}) {
    if (current.current) return;
    const store = useChatStore.getState();
    conversation.current = store.conversationId ?? null;
    const operation: { runId?: string; cancel: boolean; cancelling: boolean } = { cancel: false, cancelling: false };
    current.current = operation;
    store.setStreaming(true);
    const id = crypto.randomUUID();
    const startedAt = Date.now();
    let events = ['서버 연결 중'];
    let content = '';
    let sources: Source[] = [];
    let terminal = false;
    store.add({ id: crypto.randomUUID(), role: 'user', content: text });
    store.add({ id, role: 'assistant', content: '', activity: { startedAt, status: 'writing', stage: events[0], events } });
    const stage = (value: string) => {
      if (events.at(-1) !== value) events = [...events, value];
      store.patch(id, { activity: { startedAt, status: 'writing', stage: value, events } });
    };
    const applyRun = (run: Run) => {
      operation.runId = run.run_id;
      content = run.response;
      terminal = !active(run);
      store.patch(id, { content, runId: run.run_id, run, sources: run.sources, error: ['failed', 'interrupted'].includes(run.status) ? runErrorMessage(run.error_code) : undefined,
        activity: { startedAt, finishedAt: terminal ? Date.now() : undefined, status: run.status === 'completed' ? 'complete' : run.status === 'cancelled' ? 'stopped' : terminal ? 'error' : 'writing', stage: stages[run.status], events } });
    };
    const follow = async () => {
      const deadline = Date.now() + 140_000;
      while (operation.runId) {
        const run = await api<Run>(`/v1/runs/${operation.runId}`);
        applyRun(run);
        if (!active(run)) { uncertain.current = null; return; }
        if (Date.now() > deadline) throw new Error('답변 상태 확인이 지연되고 있어요. 서버에서 처리가 계속될 수 있습니다.');
        await new Promise(resolve => setTimeout(resolve, 1000));
      }
    };
    try {
      session.current = await ensureSession();
      if (operation.cancel) { store.patch(id, { activity: { startedAt, finishedAt: Date.now(), status: 'stopped', events } }); return; }
      if (!conversation.current) {
        const created = await api<{ id: string }>('/v1/conversations', { method: 'POST', body: JSON.stringify({ title: '새 대화' }) }, session.current.csrf_token);
        conversation.current = created.id;
        store.setConversationId(created.id);
      }
      if (operation.cancel) { store.patch(id, { activity: { startedAt, finishedAt: Date.now(), status: 'stopped', events } }); return; }
      const settings = useModelSettings.getState();
      const selected = settings.models?.find(m => modelKey(m) === settings.model);
      const supported = ['auto','free'].includes(settings.model) ? settings.models?.filter(m => settings.model === 'free' ? m.is_free : m.auto_eligible).flatMap(m => m.efforts || []) : selected?.efforts;
      const effort = supported?.includes(effortOptions[settings.effort]?.id) ? effortOptions[settings.effort].id : supported?.[0];
      const body = JSON.stringify({ ...(settings.chosen ? { routing: routingFor(settings.model, settings.models) } : {}), reasoning_effort: effort || null, message: text, attachment_ids: options.attachment_ids || [], search_enabled: options.search_enabled ?? null, explanation_mode: mode === 'student' ? 'standard' : 'simple' });
      const key = uncertain.current?.body === body && uncertain.current.conversation === conversation.current ? uncertain.current.key : crypto.randomUUID();
      uncertain.current = { body, key, conversation: conversation.current };
      stage('질문 전송 중');
      const response = await fetchApi(`/v1/conversations/${conversation.current}/runs`, { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': session.current.csrf_token, 'Idempotency-Key': key }, body });
      if (!response.ok) throw await responseError(response);
      if (response.headers.get('content-type')?.includes('application/json')) applyRun(await response.json() as Run);
      else await consumeEvents(response, (kind, data) => {
        if (typeof data.run_id === 'string') { operation.runId = data.run_id; store.patch(id, { runId: data.run_id }); }
        if (operation.cancel && !operation.cancelling) void stop().catch(error => store.patch(id, { error: error.message }));
        if (kind === 'status') stage(typeof data.message === 'string' ? data.message : stages[String(data.status)] || '처리 중');
        if (kind === 'model' && typeof data.selected_model === 'string') store.patch(id, { selectedModel: data.selected_model, selectedProvider: typeof data.selected_provider === 'string' ? data.selected_provider : undefined });
        if (kind === 'delta' && typeof data.text === 'string') { content += data.text; store.patch(id, { content }); }
        if (kind === 'source' && data.source) { sources = [...sources, data.source as Source]; store.patch(id, { sources }); }
        if (kind === 'error') store.patch(id, { error: runErrorMessage(String(data.code)) });
      });
      if (!operation.runId) throw new Error('응답 연결이 끊겼어요. 같은 질문을 다시 보내면 저장된 요청부터 확인합니다.');
      if (operation.cancel && !operation.cancelling) await stop();
      await follow();
    } catch (error) {
      if (operation.runId && !terminal) {
        try { stage('저장된 답변 확인 중'); await follow(); return; } catch { /* Preserve partial content and expose uncertainty below. */ }
      }
      if (error instanceof ApiError && error.status === 401) { session.current = null; conversation.current = null; uncertain.current = null; store.setConversationId(null); }
      store.patch(id, { error: error instanceof Error ? error.message : '서버에 연결하지 못했어요.', activity: { startedAt, finishedAt: Date.now(), status: 'error', events } });
    } finally { current.current = null; store.setStreaming(false); }
  }
  return { send, stop };
}
