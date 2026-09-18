'use client';
import { useState } from 'react';
import { Popover } from '@base-ui/react/popover';
import { AlertDialog } from '@base-ui/react/alert-dialog';
import { Check, ChevronDown, History, LogIn, LogOut, MessageSquare, Plus, Settings2, Trash2, UserRound, X } from 'lucide-react';
import { apiUrl } from '@/lib/api';
import type { useChatWorkspace } from '@/lib/use-chat-workspace';

function ConfirmDelete({label, description, action, disabled, showLabel = false}: {label:string; description:string; action:()=>Promise<void>; disabled:boolean; showLabel?:boolean}) {
  const [open,setOpen]=useState(false), [busy,setBusy]=useState(false), [error,setError]=useState('');
  return <AlertDialog.Root open={open} onOpenChange={value=>{if(!busy)setOpen(value);}}>
    <AlertDialog.Trigger className={`delete-trigger${showLabel ? ' delete-trigger-labeled' : ''}`} disabled={disabled} aria-label={label} title={label}><Trash2 size={16} aria-hidden="true"/><span className={showLabel ? undefined : 'sr-only'}>{label}</span></AlertDialog.Trigger>
    <AlertDialog.Portal><AlertDialog.Backdrop className="confirm-backdrop"/><AlertDialog.Popup className="confirm-popup">
      <AlertDialog.Title>{label}</AlertDialog.Title><AlertDialog.Description>{description}</AlertDialog.Description>
      {error&&<p role="alert">{error}</p>}<div><AlertDialog.Close disabled={busy}>취소</AlertDialog.Close><button disabled={busy} onClick={async()=>{setBusy(true);try{await action();setOpen(false);}catch(e){setError(e instanceof Error?e.message:'삭제하지 못했습니다.');}finally{setBusy(false);}}}>{busy?'삭제 중':'삭제'}</button></div>
    </AlertDialog.Popup></AlertDialog.Portal>
  </AlertDialog.Root>;
}
export function WorkspaceMenu({workspace,disabled,onNavigate}: {workspace:ReturnType<typeof useChatWorkspace>; disabled:boolean; onNavigate:()=>void}) {
  const [open,setOpen]=useState(false), [error,setError]=useState('');
  const accountName = workspace.user?.guest ? '게스트' : workspace.user?.display_name || '연결 중';
  return <nav className="workspace-nav" aria-label="대화 관리">
    <button disabled={disabled} onClick={()=>{onNavigate();workspace.newConversation();}} aria-label="새 대화"><Plus size={18}/><span>새 대화</span></button>
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger aria-label="대화 기록과 계정"><History size={18}/><span>대화 기록</span></Popover.Trigger>
      <Popover.Portal><Popover.Positioner side="bottom" align="end" sideOffset={12} collisionPadding={16} className="workspace-positioner"><Popover.Popup className="workspace-popup">
        <div className="workspace-popup-heading"><Popover.Title>대화 기록</Popover.Title><Popover.Close aria-label="대화 기록 닫기"><X size={18} aria-hidden="true"/></Popover.Close></div>
        <Popover.Description className="sr-only">지난 대화를 이어가거나 계정과 사용량을 확인하세요.</Popover.Description>
        <div className="conversation-list">
          {workspace.conversations.map(c=><div className="conversation-row" key={c.id} data-active={workspace.conversationId===c.id}>
            <button className="conversation-open" disabled={disabled} aria-current={workspace.conversationId===c.id ? 'true' : undefined} title={c.title} onClick={()=>{onNavigate();void workspace.openConversation(c.id);setOpen(false);}}>
              <MessageSquare size={16} aria-hidden="true"/><span>{c.title}</span>{workspace.conversationId===c.id&&<Check className="conversation-current" size={15} aria-hidden="true"/>}
            </button>
            <ConfirmDelete label={`${c.title} 대화 삭제`} description="이 대화와 첨부파일을 삭제합니다. 되돌릴 수 없습니다." action={()=>workspace.removeConversation(c.id)} disabled={disabled}/>
          </div>)}
          {!workspace.conversations.length&&<div className="conversation-empty"><MessageSquare size={24} strokeWidth={1.5} aria-hidden="true"/><p>{workspace.busy ? '대화를 불러오고 있어요' : '아직 저장된 대화가 없어요'}</p>{!workspace.busy&&<span>새 대화를 시작하면 여기에 표시됩니다.</span>}</div>}
          {workspace.cursor&&<button className="conversation-more" disabled={disabled} onClick={()=>void workspace.loadMore()}>이전 대화 더 보기<ChevronDown size={14} aria-hidden="true"/></button>}
        </div>
        <div className="account-summary">
          <div className="account-identity"><span className="account-avatar" aria-hidden="true"><UserRound size={18}/></span><div><p className="account-name">{accountName}</p><p className="account-kind">{workspace.user?.guest ? '로그인 없이 이용 중' : workspace.user?.admin ? '관리자 계정' : workspace.user ? '로그인됨' : '계정 확인 중'}</p></div></div>
          {workspace.usage&&<dl className="account-usage">
            <div><dt>오늘 남은 횟수</dt><dd>{workspace.usage.remaining_requests===null?'제한 없음':`${workspace.usage.remaining_requests}회`}</dd></div>
            <div><dt>남은 예산</dt><dd>${Number(workspace.usage.remaining_usd).toFixed(4)}</dd></div>
            <div><dt>정산 대기</dt><dd>${Number(workspace.usage.reserved_usd).toFixed(4)}</dd></div>
          </dl>}
          <div className="account-actions">
            {workspace.user?.guest&&workspace.config?.google_login_available&&<a href={apiUrl('/auth/google/start')}><LogIn size={16} aria-hidden="true"/>Google 로그인</a>}
            {workspace.config?.admin_login_available&&<a href="/admin"><Settings2 size={16} aria-hidden="true"/>{workspace.user?.admin?'관리자 설정':'관리자 로그인'}</a>}
            {workspace.user&&!workspace.user.guest&&<button disabled={disabled} onClick={()=>void workspace.logout().catch(e=>setError(e.message))}><LogOut size={16} aria-hidden="true"/>로그아웃</button>}
          </div>
          {workspace.user&&<div className="account-delete"><ConfirmDelete showLabel label={workspace.user.guest?'전체 대화 기록 삭제':'계정 삭제'} description="모든 대화와 첨부파일을 삭제합니다. 개인 정보는 지우고 비용 기록만 남깁니다. 되돌릴 수 없습니다." action={workspace.eraseAccount} disabled={disabled}/></div>}
          {error&&<p role="alert">{error}</p>}
        </div>
      </Popover.Popup></Popover.Positioner></Popover.Portal>
    </Popover.Root>
    {workspace.config?.google_login_available && (!workspace.user || workspace.user.guest) && <a
      className="workspace-login" href={apiUrl('/auth/google/start')}
      aria-disabled={disabled || undefined} tabIndex={disabled ? -1 : undefined}
      onClick={event=>{if(disabled)event.preventDefault();}}
    ><LogIn size={16} aria-hidden="true"/><span>Google 로그인</span></a>}
  </nav>;
}
