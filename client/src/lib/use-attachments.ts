'use client';
import { useEffect, useRef, useState } from 'react';
import { api, type Attachment } from './api';
export const attachmentAccept = '.txt,.pdf,.png,.jpg,.jpeg';
export type DraftAttachment = Attachment & { localId: string; notice?: string; selected: boolean };
const terminal = (status: string) => ['ready', 'failed', 'expired'].includes(status);
export function useAttachments(prepare: () => Promise<{ id: string; csrf: string }>) {
  const [files, setFiles] = useState<DraftAttachment[]>([]);
  const [error, setError] = useState('');
  const filesRef = useRef(files); filesRef.current = files;
  const alive = useRef(true);
  const busy = useRef(false);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const patch = (localId: string, data: Partial<DraftAttachment>) => { if (alive.current) setFiles(items => items.map(item => item.localId === localId ? { ...item, ...data } : item)); };
  async function add(incoming: File[]) {
    if (!incoming.length) return;
    if (busy.current) { setError('파일을 읽고 있어요. 잠시 후 다시 놓아 주세요.'); return; }
    busy.current = true; setError('');
    try {
      const config = await api<{ max_attachment_bytes: number; max_attachments: number }>('/v1/config');
      const selected = filesRef.current.filter(f => f.selected).length;
      if (selected + incoming.length > config.max_attachments) throw new Error(`파일은 ${config.max_attachments}개까지 골라 주세요.`);
      if (incoming.some(f => !/\.(txt|pdf|png|jpe?g)$/i.test(f.name))) throw new Error('TXT, PDF, PNG, JPG 파일을 골라 주세요.');
      if (incoming.some(f => f.size > config.max_attachment_bytes)) throw new Error(`파일 하나당 ${Math.floor(config.max_attachment_bytes / 1048576)}MB까지 올릴 수 있어요.`);
      if (incoming.some(f => !f.size)) throw new Error('내용이 있는 파일을 골라 주세요.');
      const drafts = incoming.map(f => ({ localId: crypto.randomUUID(), filename: f.name, id: '', status: 'uploading', truncated: false, expires_at: '', selected: true }));
      setFiles(items => [...items, ...drafts]);
      let context: { id: string; csrf: string };
      try { context = await prepare(); } catch (e) { drafts.forEach(f => patch(f.localId, { status: 'failed', notice: '연결하지 못했어요. 다시 첨부해 주세요.' })); throw e; }
      await Promise.all(drafts.map(async (draft, index) => {
        try {
          const form = new FormData(); form.append('file', incoming[index]); form.append('conversation_id', context.id);
          let file = await api<Attachment>('/v1/attachments', { method: 'POST', body: form }, context.csrf);
          patch(draft.localId, file);
          const deadline = Date.now() + 120_000;
          while (alive.current && !terminal(file.status)) {
            if (Date.now() > deadline) { patch(draft.localId, { status: 'delayed', notice: '조금 늦어지고 있어요. 상태를 다시 확인해 주세요.' }); return; }
            await new Promise(resolve => setTimeout(resolve, 1200));
            if (!alive.current) return;
            file = await api<Attachment>(`/v1/attachments/${file.id}`); patch(draft.localId, file);
          }
        } catch (e) { patch(draft.localId, { status: 'failed', notice: e instanceof Error ? e.message : '다시 첨부해 주세요.' }); }
      }));
    } catch (e) { if (alive.current) setError(e instanceof Error ? e.message : '파일을 올리지 못했어요.'); }
    finally { busy.current = false; }
  }
  async function refresh(file: DraftAttachment) {
    try { patch(file.localId, { ...await api<Attachment>(`/v1/attachments/${file.id}`), notice: undefined }); }
    catch { patch(file.localId, { notice: '상태를 확인하지 못했어요.' }); }
  }
  function toggle(localId: string) {
    const file = filesRef.current.find(f => f.localId === localId);
    if (file && !file.selected && filesRef.current.filter(f => f.selected).length >= 3) { setError('파일은 3개까지 골라 주세요.'); return; }
    setFiles(items => items.map(f => f.localId === localId ? { ...f, selected: !f.selected } : f));
  }
  const selected = files.filter(f => f.selected);
  return { files, selected, error, add, toggle, refresh, clearError: () => setError(''), blocked: selected.some(f => f.status !== 'ready'), ready: selected.filter(f => f.status === 'ready') };
}
