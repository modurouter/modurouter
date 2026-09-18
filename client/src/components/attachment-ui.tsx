'use client';
import { useRef, useState } from 'react';
import { Menu } from '@base-ui/react/menu';
import { FileText, ImageIcon, Plus, X, ChevronDown, Check } from 'lucide-react';
import type { Attachment, Source } from '@/lib/api';
import { api } from '@/lib/api';
import { type useAttachments } from '@/lib/use-attachments';
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
    {expanded && <div className="attachment-preview">{loading ? '불러오는 중…' : notice || (current.status === 'ready' ? <><small>읽은 내용{current.truncated ? ' (일부)' : ''}</small><p>{current.preview || '표시할 내용이 없어요.'}</p></> : current.status === 'failed' ? '파일을 확인한 뒤 다시 첨부해 주세요.' : current.status === 'expired' ? '보관 기간이 지났어요. 다시 첨부해 주세요.' : '내용을 읽고 있어요.')}</div>}
  </div>;
}
export function AttachmentMenu({ attachments, disabled, labeled = false }: { attachments: ReturnType<typeof useAttachments>; disabled: boolean; labeled?: boolean }) {
  const fileInput = useRef<HTMLInputElement>(null);
  const photoInput = useRef<HTMLInputElement>(null);
  const [open, setOpen] = useState(false);
  return <>
    <input hidden ref={fileInput} type="file" multiple accept={attachments.accept} onChange={e => { void attachments.add(Array.from(e.target.files || [])); e.target.value = ''; }} />
    <input hidden ref={photoInput} type="file" multiple accept="image/png,image/jpeg" onChange={e => { void attachments.add(Array.from(e.target.files || [])); e.target.value = ''; }} />
    <Menu.Root open={open} onOpenChange={setOpen}>
      <Menu.Trigger type="button" className={labeled ? "attachment-add attachment-add-labeled composer-tool" : "attachment-add"} aria-label="파일 또는 사진 첨부" disabled={disabled}><GlassSurface radius={labeled ? 18 : 50} tone={labeled ? 'neutral' : 'gray'} /><Plus size={18} />{labeled && <span>파일 첨부</span>}</Menu.Trigger>
      <Menu.Portal><Menu.Positioner side="top" align="start" sideOffset={8} collisionPadding={16} className="liquid-menu-positioner"><Menu.Popup className="attachment-menu liquid-popup" aria-label="첨부하기">
        <GlassSurface radius={22} />
        <div className="liquid-popup-content liquid-menu-list">
          <Menu.Item className="liquid-menu-item" onClick={() => { setOpen(false); fileInput.current?.click(); }}><FileText size={18} /><span>파일 첨부</span></Menu.Item>
          <Menu.Item className="liquid-menu-item" onClick={() => { setOpen(false); photoInput.current?.click(); }}><ImageIcon size={18} /><span>사진 첨부</span></Menu.Item>
          {!!attachments.files.length && <Menu.Group className="attachment-library"><Menu.GroupLabel>이 대화의 파일</Menu.GroupLabel>{attachments.files.filter(f => f.id).map(f => <Menu.CheckboxItem className="liquid-menu-item" key={f.localId} checked={f.selected} disabled={f.status !== 'ready'} onCheckedChange={() => attachments.toggle(f.localId)}>
            <span className="attachment-menu-filename" title={f.filename}>{f.filename}</span><Menu.CheckboxItemIndicator className="liquid-menu-check"><Check size={16} /></Menu.CheckboxItemIndicator>
          </Menu.CheckboxItem>)}</Menu.Group>}
        </div>
      </Menu.Popup></Menu.Positioner></Menu.Portal>
    </Menu.Root>
  </>;
}
export function FileSource({ source }: { source: Source }) {
  const [file, setFile] = useState<Attachment | null>(null);
  const [notice, setNotice] = useState('');
  return <span className="file-source"><button type="button" onClick={async () => { if (file) { setFile(null); return; } setNotice('불러오는 중…'); try { setFile(await api<Attachment>(`/v1/attachments/${source.attachment_id}`)); setNotice(''); } catch { setNotice('파일을 다시 첨부해 주세요.'); } }}>[{source.source_id}] {source.title}{source.truncated ? ' (일부)' : ''}</button>{notice && <small>{notice}</small>}{file && <AttachmentCard file={file} />}</span>;
}
