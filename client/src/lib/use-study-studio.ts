'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { api, ApiError, type User } from './api';

export type StudyStep = { title: string; body: string; prompt: string; kind: 'text' | 'choice'; example?: string; options?: string[]; hint: string };
export type StudyTask = { id: string; topic_id: string; title: string; summary: string; outcome: string; version: number; minutes: number; steps: StudyStep[] };
export type StudySession = { id: string; task_id: string; revision: number; updated_at: string; step: number; answers: {title:string;answer:string}[]; draft: string; complete: boolean; completions: number; hints: number; result: string; previous_result?: string; feedback: {kind:string;message:string} | null };
type Catalog = {topics: {id:string;title:string}[];tasks: StudyTask[]};
type Action = 'answer' | 'draft' | 'hint' | 'restart';

export function useStudyStudio(user: User | null) {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [sessions, setSessions] = useState<StudySession[]>([]);
  const [selected, setSelected] = useState<StudySession | null>(null);
  const [topic, setTopic] = useState<string | null>(null);
  const [draft, setDraft] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const lock = useRef(false);
  const version = useRef(0);
  const pending = useRef<{signature:string;request_id:string} | null>(null);
  const save = (value: StudySession) => { setSelected(value); setDraft(value.draft); setSessions(items => [value, ...items.filter(item => item.id !== value.id)]); };
  const report = (e: unknown) => setError(e instanceof Error ? e.message : '학습 기록을 불러오지 못했어요.');
  const load = useCallback(async () => {
    if (!user) return;
    const operation = ++version.current;
    setBusy(true); setError('');
    try {
      const [content, records] = await Promise.all([api<Catalog>('/v1/learning/catalog'), api<{items:StudySession[]}>('/v1/learning/sessions')]);
      if (operation !== version.current) return;
      setCatalog(content); setSessions(records.items);
    } catch (e) { if (operation === version.current) report(e); }
    finally { if (operation === version.current) setBusy(false); }
  }, [user?.id]); // Identity, not the rotating CSRF value, owns these records.
  useEffect(() => { setSelected(null); setSessions([]); setDraft(''); pending.current = null; void load(); return () => { version.current++; }; }, [load]);
  async function start(id: string) {
    if (!user || lock.current || busy) return;
    lock.current = true; setBusy(true); setError(''); setNotice('');
    try { save(await api<StudySession>(`/v1/learning/tasks/${encodeURIComponent(id)}/session`, {method:'POST'}, user.csrf_token)); pending.current = null; }
    catch (e) { report(e); } finally { lock.current = false; setBusy(false); }
  }
  async function change(action: Action, answer = draft) {
    if (!user || !selected || lock.current || busy) return false;
    lock.current = true; setBusy(true); setError(''); setNotice('');
    const signature = JSON.stringify([selected.id, selected.revision, action, answer]);
    if (pending.current?.signature !== signature) pending.current = {signature, request_id:crypto.randomUUID()};
    try {
      save(await api<StudySession>(`/v1/learning/sessions/${selected.id}`, {method:'POST', body:JSON.stringify({action, answer, revision:selected.revision, request_id:pending.current.request_id})}, user.csrf_token));
      pending.current = null;
      if (action === 'draft') setNotice('답안을 저장했어요. 나중에 이어서 쓸 수 있어요.');
      return true;
    } catch (e) {
      report(e);
      if (e instanceof ApiError && e.code === 'LEARNING_CONFLICT') {
        try { const latest = await api<StudySession>(`/v1/learning/sessions/${selected.id}`); save(latest); if (latest.step === selected.step && (action === 'answer' || action === 'draft')) setDraft(answer); pending.current = null; }
        catch { /* Keep the previous state until the user retries. */ }
      }
      return false;
    } finally { lock.current = false; setBusy(false); }
  }
  async function back() {
    if (busy || lock.current) return;
    if (selected && !selected.complete && draft !== selected.draft && !await change('draft')) return;
    setSelected(null); setError(''); setNotice('');
  }
  async function remove() {
    if (!user || !selected || lock.current || busy) return;
    lock.current = true; setBusy(true); setError('');
    try { await api(`/v1/learning/sessions/${selected.id}`, {method:'DELETE'}, user.csrf_token); setSessions(items => items.filter(item => item.id !== selected.id)); setSelected(null); setDraft(''); setNotice('학습 기록을 지웠어요. 코치와 나눈 대화는 대화 기록에서 따로 관리할 수 있어요.'); }
    catch (e) { report(e); } finally { lock.current = false; setBusy(false); }
  }
  async function conversation(): Promise<string | null> {
    if (!user || !selected || busy || lock.current) return null;
    if (!selected.complete && draft !== selected.draft && !await change('draft')) return null;
    lock.current = true; setBusy(true); setError('');
    try { return (await api<{conversation_id:string}>(`/v1/learning/sessions/${selected.id}/conversation`, {method:'POST'}, user.csrf_token)).conversation_id; }
    catch (e) { report(e); return null; } finally { lock.current = false; setBusy(false); }
  }
  const task = catalog?.tasks.find(item => item.id === selected?.task_id) || null;
  const step = task && selected && !selected.complete ? task.steps[selected.step] : null;
  function voice(text: string) {
    if (busy || lock.current) return;
    setError('');
    if (/^(뒤로|전체 활동|활동 목록)/.test(text)) { void back(); return; }
    if (step?.kind === 'text') { setDraft(prior => prior ? `${prior}\n${text}` : text); setNotice('말한 내용을 답안에 넣었어요. 확인한 뒤 저장해 주세요.'); return; }
    const normalized = text.replace(/[\s.!?]/g, '').toLowerCase();
    const ordinal = normalized.match(/^([1-9]|첫|두|세|네)(?:번째|번)(?:거|것|으로|할래|선택|요|주세요)*$/);
    const n = ordinal ? (/^\d$/.test(ordinal[1]) ? Number(ordinal[1]) - 1 : ['첫','두','세','네'].indexOf(ordinal[1])) : -1;
    if (step?.kind === 'choice') {
      const matches = (step.options || []).filter(option => normalized.includes(option.replace(/\s/g, '').toLowerCase()));
      const answer = n >= 0 ? step.options?.[n] : matches.length === 1 ? matches[0] : undefined;
      if (answer && !/말고|아니|않/.test(text)) { void change('answer', answer); return; }
    } else if (!selected) {
      const items = topic ? catalog?.tasks.filter(item => item.topic_id === topic) : catalog?.tasks;
      const found = n >= 0 && topic ? items?.[n] : items?.find(item => normalized.includes(item.title.replace(/\s/g,'')));
      if (found) { void start(found.id); return; }
      const group = catalog?.topics.find(item => normalized.includes(item.title.replace(/\s/g,'')));
      if (group) { setTopic(group.id); return; }
    }
    setNotice('화면에 있는 활동 이름이나 선택지 번호를 말해 주세요.');
  }
  return {catalog,sessions,selected,task,step,topic,setTopic,draft,setDraft,busy,error,notice,load,start,change,back,remove,conversation,voice};
}
