'use client';
import { useState } from 'react';
import { attachmentErrorMessage, attachmentExtensions, type Attachment } from './api';
import { useChatStore } from './chat-store';
import type { useChatWorkspace } from './use-chat-workspace';
export const attachmentAccept = attachmentExtensions.join(',');
export type DraftAttachment = Attachment & { localId: string; notice?: string; selected: boolean };

// Share the existing workspace lifecycle so navigation and draft restoration retain files.
export function useAttachments(workspace: ReturnType<typeof useChatWorkspace>) {
  const [error, setError] = useState('');
  const messages = useChatStore(state => state.messages);
  const known = new Map(messages.flatMap(message => message.attachments || []).map(file => [file.id, file]));
  for (const file of workspace.attachments) known.set(file.id, file);
  const selectedIds = new Set(workspace.attachments.map(file => file.id));
  const files: DraftAttachment[] = [...known.values()].map(file => ({ ...file, localId: file.id, notice: attachmentErrorMessage(file) || undefined, selected: selectedIds.has(file.id) }));
  const selected = files.filter(file => file.selected);
  function toggle(id: string) {
    if (selectedIds.has(id)) { workspace.excludeAttachment(id); return; }
    const file = known.get(id);
    if (!file || file.status !== 'ready') return;
    const max = workspace.config?.max_attachments || 3;
    if (selected.length >= max) { setError(`파일은 ${max}개까지 골라 주세요.`); return; }
    workspace.selectAttachment(file);
  }
  return { files, selected, error, add: (incoming: File[]) => workspace.upload(incoming), toggle,
    accept: (workspace.config?.attachment_extensions || attachmentExtensions).join(','),
    clearError: () => setError(''), blocked: selected.some(file => file.status !== 'ready'),
    failed: selected.filter(file => !['ready', 'uploading', 'queued', 'pending'].includes(file.status)),
    ready: selected.filter(file => file.status === 'ready') };
}
