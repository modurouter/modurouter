'use client';
import { useState } from 'react';
import { Popover } from '@base-ui/react/popover';
import { AlertDialog } from '@base-ui/react/alert-dialog';
import { History, Plus, Trash2, X } from 'lucide-react';
import { apiUrl } from '@/lib/api';
import type { useChatWorkspace } from '@/lib/use-chat-workspace';

function ConfirmDelete({label, description, action, disabled}: {label:string; description:string; action:()=>Promise<void>; disabled:boolean}) {
  const [open,setOpen]=useState(false), [busy,setBusy]=useState(false), [error,setError]=useState('');
  return <AlertDialog.Root open={open} onOpenChange={value=>{if(!busy)setOpen(value);}}>
    <AlertDialog.Trigger disabled={disabled} aria-label={label}><Trash2 size={16}/><span className="sr-only">{label}</span></AlertDialog.Trigger>
    <AlertDialog.Portal><AlertDialog.Backdrop className="confirm-backdrop"/><AlertDialog.Popup className="confirm-popup">
      <AlertDialog.Title>{label}</AlertDialog.Title><AlertDialog.Description>{description}</AlertDialog.Description>
      {error&&<p role="alert">{error}</p>}<div><AlertDialog.Close disabled={busy}>취소</AlertDialog.Close><button disabled={busy} onClick={async()=>{setBusy(true);try{await action();setOpen(false);}catch(e){setError(e instanceof Error?e.message:'삭제하지 못했습니다.');}finally{setBusy(false);}}}>{busy?'삭제 중':'삭제'}</button></div>
    </AlertDialog.Popup></AlertDialog.Portal>
  </AlertDialog.Root>;
}
export function WorkspaceMenu({workspace,disabled,onNavigate}: {workspace:ReturnType<typeof useChatWorkspace>; disabled:boolean; onNavigate:()=>void}) {
  const [open,setOpen]=useState(false), [error,setError]=useState('');
  return <nav className="workspace-nav" aria-label="대화 관리">
    <button disabled={disabled} onClick={()=>{onNavigate();workspace.newConversation();}} aria-label="새 대화"><Plus size={18}/><span>새 대화</span></button>
    <Popover.Root open={open} onOpenChange={setOpen}>
      <Popover.Trigger aria-label="대화 기록과 계정"><History size={18}/><span>대화 기록</span></Popover.Trigger>
      <Popover.Portal><Popover.Positioner side="bottom" align="end" sideOffset={12} collisionPadding={16} className="workspace-positioner"><Popover.Popup className="workspace-popup">
        <div className="workspace-popup-heading"><Popover.Title>대화 기록</Popover.Title><Popover.Close aria-label="대화 기록 닫기"><X size={18}/></Popover.Close></div>
        <div className="conversation-list">{workspace.conversations.map(c=><div key={c.id} data-active={workspace.conversationId===c.id}><button disabled={disabled} onClick={()=>{onNavigate();void workspace.openConversation(c.id);setOpen(false);}}>{c.title}</button><ConfirmDelete label={`${c.title} 대화 삭제`} description="이 대화와 첨부파일을 삭제합니다. 되돌릴 수 없습니다." action={()=>workspace.removeConversation(c.id)} disabled={disabled}/></div>)}{!workspace.conversations.length&&<p>저장된 대화가 없습니다.</p>}{workspace.cursor&&<button disabled={disabled} onClick={()=>void workspace.loadMore()}>이전 대화 더 보기</button>}</div>
        <div className="account-summary"><p>{workspace.user?.guest?'로그인 없이 이용 중':workspace.user?.display_name || '연결 중'}</p>
          {workspace.usage&&<p>오늘 남은 횟수: {workspace.usage.remaining_requests===null?'제한 없음':`${workspace.usage.remaining_requests}회`}<br/>남은 예산: ${Number(workspace.usage.remaining_usd).toFixed(4)}<br/>정산 대기: ${Number(workspace.usage.reserved_usd).toFixed(4)}</p>}
          {workspace.user?.guest&&workspace.config?.google_login_available&&<a href={apiUrl('/auth/google')}>Google 로그인</a>}
          {workspace.config?.admin_login_available&&<a href="/admin">{workspace.user?.admin?'관리자 설정':'관리자 로그인'}</a>}
          {workspace.user&&!workspace.user.guest&&<button disabled={disabled} onClick={()=>void workspace.logout().catch(e=>setError(e.message))}>로그아웃</button>}
          {workspace.user&&<div className="account-delete"><span>{workspace.user.guest?'전체 대화 기록 삭제':'계정 삭제'}</span><ConfirmDelete label={workspace.user.guest?'전체 대화 기록 삭제':'계정 삭제'} description="모든 대화와 첨부파일을 삭제합니다. 개인 정보는 지우고 비용 기록만 남깁니다. 되돌릴 수 없습니다." action={workspace.eraseAccount} disabled={disabled}/></div>}
          {error&&<p role="alert">{error}</p>}
        </div>
      </Popover.Popup></Popover.Positioner></Popover.Portal>
    </Popover.Root>
  </nav>;
}
