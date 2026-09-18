'use client';
import { useRef, useState } from 'react';
import { Popover } from '@base-ui/react/popover';
import { FileText, ImageIcon, Plus, X, ChevronDown, Check } from 'lucide-react';
import type { Attachment, Source } from '@/lib/api';
import { api } from '@/lib/api';
import { attachmentAccept, type useAttachments } from '@/lib/use-attachments';
import { GlassSurface } from './glass-surface';

export function AttachmentCard({ file, onRemove }: { file: Attachment & { notice?: string }; onRemove?: () => void }) {
  const [expanded, setExpanded] = useState(false);
  const [data, setData] = useState<Attachment | null>(null);
  const [notice, setNotice] = useState('');
  const [loading, setLoading] = useState(false);
  const current = data && (data.status === 'expired' || data.status === 'failed' || file.status !== 'ready') ? data : file;
  const status = current.status === 'ready' ? current.truncated ? '일부만 읽었어요' : '준비됐어요' : current.status === 'expired' ? '다시 첨부해 주세요' : current.status === 'failed' ? '읽지 못했어요' : current.status === 'uploading' ? '올리는 중…' : '읽는 중…';
  async function open() {
    if (expanded) { setExpanded(false); return; }
    setExpanded(true);
    if (!file.id) return;
    setLoading(true); setNotice('');
    try { setData(await api<Attachment>(`/v1/attachments/${file.id}`)); }
    catch { setData(null); setNotice('내용을 불러오지 못했어요. 다시 눌러 주세요.'); }
    finally { setLoading(false); }
  }
  return <div className={`attachment-card ${expanded ? 'is-expanded' : ''}`}>
    <div className="attachment-card-row">
      <button type="button" className="attachment-open" onClick={() => void open()} aria-expanded={expanded}>
        {/\.(png|jpe?g)$/i.test(file.filename) ? <ImageIcon size={20} /> : <FileText size={20} />}
        <span><strong title={file.filename}>{file.filename}</strong><small>{status}</small></span><ChevronDown size={14} />
      </button>
      {onRemove && <button type="button" className="attachment-remove" onClick={onRemove} aria-label={`${file.filename} 다음 질문에서 제외`}><X size={15} /></button>}
    </div>
    {file.notice && <p className="attachment-notice">{file.notice}</p>}
    {expanded && <div className="attachment-preview">{loading ? '불러오는 중…' : notice || (current.status === 'ready' ? <><small>읽은 내용{current.truncated ? ' · 일부' : ''}</small><p>{current.preview || '표시할 내용이 없어요.'}</p></> : current.status === 'failed' ? '파일을 확인한 뒤 다시 첨부해 주세요.' : current.status === 'expired' ? '보관 기간이 지났어요. 다시 첨부해 주세요.' : '내용을 읽고 있어요.')}</div>}
  </div>;
}
export function AttachmentMenu({ attachments, disabled }: { attachments: ReturnType<typeof useAttachments>; disabled: boolean }) {
  const fileInput = useRef<HTMLInputElement>(null);
  const photoInput = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  return <>
    <input hidden ref={fileInput} type="file" multiple accept={attachmentAccept} onChange={e => { void attachments.add(Array.from(e.target.files || [])); e.target.value = ''; }} />
    <input hidden ref={photoInput} type="file" multiple accept="image/png,image/jpeg" onChange={e => { void attachments.add(Array.from(e.target.files || [])); e.target.value = ''; }} />
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger type="button" className="attachment-add" aria-label="파일 또는 사진 첨부" disabled={disabled}><GlassSurface radius={50} tone="gray" /><Plus size={18} /></Popover.Trigger>
      <Popover.Portal><Popover.Positioner side="top" align="start" sideOffset={14} collisionPadding={16} className="settings-positioner"><Popover.Popup className="attachment-menu glass">
        <Popover.Title className="sr-only">첨부하기</Popover.Title>
        <button type="button" onClick={() => { setOpen(false); fileInput.current?.click(); }}><FileText size={18} />파일 첨부</button>
        <button type="button" onClick={() => { setOpen(false); photoInput.current?.click(); }}><ImageIcon size={18} />사진 첨부</button>
        {!!attachments.files.length && <div className="attachment-library"><small>이 대화의 파일</small>{attachments.files.filter(f => f.id).map(f => <button type="button" key={f.localId} aria-pressed={f.selected} disabled={f.status !== 'ready'} onClick={() => attachments.toggle(f.localId)}><span>{f.filename}</span>{f.selected && <Check size={15} />}</button>)}</div>}
      </Popover.Popup></Popover.Positioner></Popover.Portal>
    </Popover.Root>
  </>;
}
export function FileSource({ source }: { source: Source }) {
  const [file, setFile] = useState<Attachment | null>(null);
  const [notice, setNotice] = useState('');
  return <span className="file-source"><button type="button" onClick={async () => { if (file) { setFile(null); return; } setNotice('불러오는 중…'); try { setFile(await api<Attachment>(`/v1/attachments/${source.attachment_id}`)); setNotice(''); } catch { setNotice('파일을 다시 첨부해 주세요.'); } }}>[{source.source_id}] {source.title}{source.truncated ? ' · 일부' : ''}</button>{notice && <small>{notice}</small>}{file && <AttachmentCard file={file} />}</span>;
}
