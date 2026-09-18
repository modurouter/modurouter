'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { api, attachmentExtensions, ensureSession, fetchApi, readSavedAttachments, restoreAttachments, runErrorMessage, type Attachment, type Conversation, type Message as StoredMessage, type Run, type Usage, type User } from './api';
import { useChatStore, type Message } from './chat-store';
import { useModelSettings } from './model-settings';

export const storage = {
  get(key: string) { try { return sessionStorage.getItem(key); } catch { return null; } },
  set(key: string, value: string) { try { sessionStorage.setItem(key, value); } catch {} },
  remove(key: string) { try { sessionStorage.removeItem(key); } catch {} },
};
const active = (run: Run) => ['accepted','preparing','model','tool','streaming'].includes(run.status);
type Config = { google_login_available: boolean; admin_login_available: boolean; voice_notice: string; max_attachment_bytes: number; max_attachments: number; attachment_extensions?: string[] };

export function useChatWorkspace() {
  const { conversationId, streaming } = useChatStore();
  const [user, setUser] = useState<User | null>(null);
  const [config, setConfig] = useState<Config | null>(null);
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [attachments, setAttachments] = useState<Attachment[]>([]);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState('');
  const lock = useRef(false);
  const version = useRef(0);
  const recovering = useRef<string | null>(null);
  const report = (error: unknown) => setError(error instanceof Error ? error.message : '요청을 완료하지 못했습니다.');
  const refresh = useCallback(async () => {
    const [list, usage] = await Promise.all([api<{items: Conversation[]; next_cursor: string | null}>('/v1/conversations'), api<Usage>('/v1/usage')]);
    setConversations(list.items); setCursor(list.next_cursor); setUsage(usage);
  }, []);
  async function openConversation(id: string, owner: User | null = user) {
    if (lock.current || useChatStore.getState().streaming) return;
    lock.current = true; setBusy(true); setError('');
    const operation = ++version.current;
    try {
      const detail = await api<{messages: StoredMessage[]}>(`/v1/conversations/${id}`);
      const ids = [...new Set(detail.messages.filter(m => m.role === 'assistant').map(m => m.run_id))];
      const runs = await Promise.all(ids.map(runId => api<Run>(`/v1/runs/${runId}`)));
      const files = await restoreAttachments(readSavedAttachments(storage.get(`modurouter-attachments:${owner?.id}:${id}`)));
      if (operation !== version.current) return;
      const store = useChatStore.getState();
      store.setConversationId(id);
      store.setMessages(detail.messages.map(m => {
        const run = runs.find(r => r.run_id === m.run_id);
        return {id:m.id, role:m.role as Message['role'], content:m.content, runId:m.run_id, run, sources:run?.sources,
          error:run && ['failed','interrupted'].includes(run.status) ? runErrorMessage(run.error_code) : undefined,
          activity:m.role === 'assistant' ? {startedAt:Date.now(), finishedAt:run && active(run) ? undefined : Date.now(), status:run?.status === 'completed' ? 'complete' : run?.status === 'cancelled' ? 'stopped' : run && active(run) ? 'writing' : 'error'} : undefined};
      }));
      setAttachments(files);
      if (owner) storage.set(`modurouter-conversation:${owner.id}`, id);
      const running = runs.find(active);
      if (running) {
        recovering.current = running.run_id;
        store.setStreaming(true);
        try {
          const deadline = Date.now() + 140000;
          while (operation === version.current) {
            const run = await api<Run>(`/v1/runs/${running.run_id}`);
            const message = store.messages.find(m => m.role === 'assistant' && m.runId === run.run_id) || useChatStore.getState().messages.find(m => m.role === 'assistant' && m.runId === run.run_id);
            if (message) store.patch(message.id, {content:run.response,run,sources:run.sources,error:['failed','interrupted'].includes(run.status)?runErrorMessage(run.error_code):undefined,activity:{startedAt:message.activity?.startedAt || Date.now(),finishedAt:active(run)?undefined:Date.now(),status:run.status==='completed'?'complete':run.status==='cancelled'?'stopped':active(run)?'writing':'error'}});
            if (!active(run)) break;
            if (Date.now() > deadline) throw new Error('답변 확인이 지연되고 있습니다. 대화를 다시 열어 주세요.');
            await new Promise(resolve => setTimeout(resolve, 1000));
          }
        } finally { recovering.current = null; store.setStreaming(false); }
      }
    } catch (error) { if (operation === version.current) report(error); }
    finally { lock.current = false; if (operation === version.current) setBusy(false); }
  }
  useEffect(() => {
    let live = true;
    void (async () => {
      try {
        const session = await ensureSession();
        if (!live) return;
        setUser(session);
        await refresh();
        const configuration = await api<Config>('/v1/config');
        if (!live) return;
        setConfig(configuration);
        void useModelSettings.getState().load();
        const saved = storage.get(`modurouter-conversation:${session.id}`);
        if (saved) await openConversation(saved, session);
        const authError = new URLSearchParams(location.search).get('auth_error');
        if (authError) setError('로그인하지 못했습니다. 다시 시도해 주세요.');
      } catch (error) { if (live) report(error); }
      finally { if (live) setBusy(false); }
    })();
    return () => { live = false; version.current++; };
    // Session bootstrap is tied to this mounted workspace.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => {
    if (user && conversationId) storage.set(`modurouter-conversation:${user.id}`, conversationId);
  }, [user, conversationId]);
  useEffect(() => {
    if (user && conversationId && !busy) storage.set(`modurouter-attachments:${user.id}:${conversationId}`, JSON.stringify(attachments.map(({id,filename}) => ({id,filename}))));
  }, [user, conversationId, attachments, busy]);
  useEffect(() => { if (user && !streaming) void refresh().catch(report); }, [streaming,user,refresh]);
  const pending = attachments.filter(a => ['queued','pending'].includes(a.status)).map(a => a.id).join(',');
  useEffect(() => {
    if (!pending) return;
    let live = true, polling = false;
    const timer = setInterval(async () => {
      if (polling) return;
      polling = true;
      try { const results = await Promise.all(pending.split(',').map(id => api<Attachment>(`/v1/attachments/${id}`))); if (live) setAttachments(files => files.map(file => results.find(r => r.id === file.id) || file)); }
      catch (error) { if (live) report(error); } finally { polling = false; }
    }, 1500);
    return () => { live = false; clearInterval(timer); };
  }, [pending]);
  function newConversation() {
    if (lock.current || useChatStore.getState().streaming) return;
    version.current++;
    const store = useChatStore.getState();
    store.setConversationId(null); store.setMessages([]); setAttachments([]); setError('');
    if (user) storage.remove(`modurouter-conversation:${user.id}`);
  }
  async function upload(files: FileList | File[] | null) {
    if (!files?.length || !user || lock.current || streaming) return;
    const selected = Array.from(files);
    const maxFiles = config?.max_attachments || 3;
    const maxBytes = config?.max_attachment_bytes || 10*1024*1024;
    const extensions = config?.attachment_extensions || attachmentExtensions;
    if (selected.length + attachments.length > maxFiles) { setError(`파일은 한 번에 ${maxFiles}개까지 첨부할 수 있습니다.`); return; }
    if (selected.some(file => !file.size || file.size > maxBytes)) { setError(`내용이 있는 ${maxBytes / (1024*1024)}MB 이하의 파일을 첨부해 주세요.`); return; }
    if (selected.some(file => !extensions.includes(file.name.slice(file.name.lastIndexOf('.')).toLowerCase()))) { setError('PDF나 한글 문서, Word와 Excel, PowerPoint 문서 또는 ODT/RTF를 첨부할 수 있습니다. Markdown과 HTML, CSV/TSV 등의 텍스트 파일 및 PNG/JPG 이미지도 지원합니다.'); return; }
    lock.current = true; setBusy(true); setError('');
    try {
      let id = useChatStore.getState().conversationId;
      if (!id) { const c = await api<Conversation>('/v1/conversations',{method:'POST',body:JSON.stringify({title:'새 대화'})},user.csrf_token); id = c.id; useChatStore.getState().setConversationId(id); }
      for (const file of selected) {
        const body = new FormData(); body.append('file',file); body.append('conversation_id',id);
        const item = await api<Attachment>('/v1/attachments',{method:'POST',body},user.csrf_token);
        setAttachments(files => [...files,item]);
      }
      await refresh();
    } catch (error) { report(error); } finally { lock.current = false; setBusy(false); }
  }
  async function removeAttachment(file: Attachment) {
    try { if (file.status !== 'expired') await api(`/v1/attachments/${file.id}`,{method:'DELETE'},user?.csrf_token); setAttachments(files => files.filter(item => item.id !== file.id)); }
    catch (error) { report(error); }
  }
  async function removeConversation(id: string) {
    await api(`/v1/conversations/${id}`,{method:'DELETE'},user?.csrf_token);
    if (conversationId === id) newConversation();
    await refresh();
  }
  async function loadMore() {
    if (!cursor || lock.current) return;
    lock.current = true; setBusy(true);
    try { const list = await api<{items: Conversation[]; next_cursor: string | null}>(`/v1/conversations?cursor=${encodeURIComponent(cursor)}`); setConversations(prior => [...prior,...list.items.filter(item => !prior.some(c => c.id === item.id))]); setCursor(list.next_cursor); }
    catch (error) { report(error); } finally { lock.current = false; setBusy(false); }
  }
  async function logout() {
    const result = await fetchApi('/auth/logout',{method:'POST',headers:{'X-CSRF-Token':user!.csrf_token}});
    if (!result.ok) throw new Error('로그아웃하지 못했습니다. 다시 시도해 주세요.');
    storage.remove('modurouter-draft'); location.reload();
  }
  async function eraseAccount() { await api('/v1/me',{method:'DELETE'},user?.csrf_token); storage.remove('modurouter-draft'); location.reload(); }
  async function cancelRecovery() { if (recovering.current) await api(`/v1/runs/${recovering.current}/cancel`,{method:'POST'},user?.csrf_token); }
  return {user,config,conversations,cursor,usage,attachments,busy,error,conversationId,refresh,openConversation,newConversation,upload,removeAttachment,removeConversation,loadMore,logout,eraseAccount,cancelRecovery,clearAttachments:()=>setAttachments([]), selectAttachment:(file:Attachment)=>setAttachments(files=>files.some(item=>item.id===file.id)?files:[...files,file]), excludeAttachment:(id:string)=>setAttachments(files=>files.filter(file=>file.id!==id))};
}
