'use client';

import {useCallback, useEffect, useRef, useState} from 'react';
import {AlertDialog} from '@base-ui/react/alert-dialog';
import {Dialog} from '@base-ui/react/dialog';
import {ArrowUp, ArrowUpRight, BookOpen, Check, FileText, Globe, Menu, Mic, Paperclip, Plus, Settings, Square, Trash2, Volume2, X} from 'lucide-react';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import {api, apiUrl, ApiError, attachmentErrorMessage, fetchApi, readSavedAttachments, restoreAttachments, consumeEvents, ensureSession, responseError, runErrorMessage, type Attachment, type Conversation, type Message, type Run, type Source, type Usage, type User} from '@/lib/api';

type SpeechResultEvent = {results: {length:number; [index:number]:{[index:number]:{transcript:string}}}};
type Recognition = {lang:string; interimResults:boolean; continuous:boolean; onresult:((e:SpeechResultEvent)=>void)|null; onerror:((e:{error:string})=>void)|null; onend:(()=>void)|null; start:()=>void; stop:()=>void; abort:()=>void};
type SpeechWindow = Window & {SpeechRecognition?:new()=>Recognition; webkitSpeechRecognition?:new()=>Recognition};
type Config = {google_login_available:boolean; admin_login_available:boolean; voice_notice:string; max_attachment_bytes:number; max_attachments:number};
type ModelStatus = {last_success_at:string|null; refresh_error:string|null; stale:boolean};
const statusText:Record<string,string> = {accepted:'질문을 받았습니다.',preparing:'대화와 자료를 준비하고 있습니다.',model:'답변을 생각하고 있습니다.',tool:'자료를 읽고 있습니다.',streaming:'답변을 작성하고 있습니다.',completed:'답변을 마쳤습니다.',cancelled:'답변 생성을 중단했습니다.',failed:'답변을 완료하지 못했습니다.',interrupted:'서버 재시작으로 답변이 중단되었습니다.'};
const isActive = (run:Run) => ['accepted','preparing','model','tool','streaming'].includes(run.status);
const storage = {
  get(key:string) {try{return sessionStorage.getItem(key)}catch{return null}},
  set(key:string,value:string) {try{sessionStorage.setItem(key,value)}catch{}},
  remove(key:string) {try{sessionStorage.removeItem(key)}catch{}},
};

function koreanVoice(synthesis:SpeechSynthesis):Promise<SpeechSynthesisVoice|null> {
  const find=()=>synthesis.getVoices().find(voice=>voice.lang.toLowerCase().startsWith('ko'))||null;
  const available=find();
  if(available)return Promise.resolve(available);
  return new Promise(resolve=>{
    let timer:number;
    const finish=(voice:SpeechSynthesisVoice|null)=>{window.clearTimeout(timer);synthesis.removeEventListener('voiceschanged',check);resolve(voice)};
    const check=()=>{const voice=find();if(voice)finish(voice)};
    synthesis.addEventListener('voiceschanged',check);
    timer=window.setTimeout(()=>finish(find()),3000);
    check();
  });
}

function Brand() {return <span className="brand"><span className="brand-mark" aria-hidden="true"><i/><i/><i/><i/></span>모두라우터</span>}

function DeleteConversation({conversation,disabled,onDelete}:{conversation:Conversation;disabled:boolean;onDelete:()=>Promise<void>}) {
  const [open,setOpen]=useState(false);
  const [pending,setPending]=useState(false);
  const [error,setError]=useState('');
  return <AlertDialog.Root open={open} onOpenChange={value=>{if(!pending){setOpen(value);setError('')}}}>
    <AlertDialog.Trigger className="delete" disabled={disabled} aria-label={`${conversation.title} 대화 삭제`}><Trash2/></AlertDialog.Trigger>
    <AlertDialog.Portal><AlertDialog.Backdrop className="backdrop"/><AlertDialog.Popup className="popup">
      <AlertDialog.Title className="popup-title">대화를 삭제할까요?</AlertDialog.Title>
      <AlertDialog.Description className="popup-description">대화 내용과 첨부파일이 삭제됩니다. 삭제한 대화는 복구할 수 없습니다.</AlertDialog.Description>
      {error&&<p role="alert" className="error">{error}</p>}
      <div className="popup-actions"><AlertDialog.Close disabled={pending}>취소</AlertDialog.Close><button className="danger" disabled={pending} onClick={async()=>{setPending(true);setError('');try{await onDelete();setOpen(false)}catch(e){setError(e instanceof Error?e.message:'대화를 삭제하지 못했습니다. 다시 시도해 주세요.')}finally{setPending(false)}}}>{pending?'삭제 중':'삭제'}</button></div>
    </AlertDialog.Popup></AlertDialog.Portal>
  </AlertDialog.Root>
}

function DeleteAccount({disabled,guest,onDelete}:{disabled:boolean;guest?:boolean;onDelete:()=>Promise<void>}) {
  const [pending,setPending]=useState(false);
  const [error,setError]=useState('');
  return <AlertDialog.Root><AlertDialog.Trigger disabled={disabled} className="danger">{guest?'대화 기록 삭제':'계정 삭제'}</AlertDialog.Trigger><AlertDialog.Portal><AlertDialog.Backdrop className="backdrop"/><AlertDialog.Popup className="popup"><AlertDialog.Title className="popup-title">{guest?'모든 대화 기록을 삭제할까요?':'계정을 삭제할까요?'}</AlertDialog.Title><AlertDialog.Description className="popup-description">모든 대화와 첨부파일을 삭제합니다. 개인 정보는 지우고 비용 기록만 남깁니다. 되돌릴 수 없습니다.</AlertDialog.Description>{error&&<p role="alert" className="error">{error}</p>}<div className="popup-actions"><AlertDialog.Close disabled={pending}>취소</AlertDialog.Close><button className="danger" disabled={pending} onClick={async()=>{setPending(true);try{await onDelete()}catch{setError('계정을 삭제하지 못했습니다. 진행 중인 답변을 중단한 뒤 다시 시도해 주세요.')}finally{setPending(false)}}}>{pending?'삭제 중':guest?'대화 기록 삭제':'계정과 대화 삭제'}</button></div></AlertDialog.Popup></AlertDialog.Portal></AlertDialog.Root>
}

export default function Home() {
  const [user,setUser]=useState<User|null>(null);
  const [loading,setLoading]=useState(true);
  const [config,setConfig]=useState<Config|null>(null);
  const [conversations,setConversations]=useState<Conversation[]>([]);
  const [cursor,setCursor]=useState<string|null>(null);
  const [current,setCurrent]=useState<string|null>(null);
  const [messages,setMessages]=useState<Message[]>([]);
  const [draft,setDraft]=useState('');
  const [search,setSearch]=useState(false);
  const [simple,setSimple]=useState(false);
  const [busy,setBusy]=useState(false);
  const [uploading,setUploading]=useState(false);
  const [opening,setOpening]=useState(false);
  const [loadingMore,setLoadingMore]=useState(false);
  const [error,setError]=useState('');
  const [status,setStatus]=useState('');
  const [usage,setUsage]=useState<Usage|null>(null);
  const [modelStatus,setModelStatus]=useState<ModelStatus|null>(null);
  const [attachments,setAttachments]=useState<Attachment[]>([]);
  const [preview,setPreview]=useState<Attachment|null>(null);
  const [runs,setRuns]=useState<Record<string,Run>>({});
  const [drawer,setDrawer]=useState(false);
  const [listening,setListening]=useState(false);
  const [speaking,setSpeaking]=useState<string|null>(null);
  const [voiceConsent,setVoiceConsent]=useState(false);
  const input=useRef<HTMLTextAreaElement>(null);
  const uploadInput=useRef<HTMLInputElement>(null);
  const settingsClose=useRef<HTMLButtonElement>(null);
  const scroller=useRef<HTMLDivElement>(null);
  const activeRun=useRef<string|null>(null);
  const csrf=useRef<string|undefined>(undefined);
  const controller=useRef<AbortController|null>(null);
  const recognition=useRef<Recognition|null>(null);
  const speechRequest=useRef(0);
  const retry=useRef<{key:string; body:string; conversationId:string}|null>(null);
  const initialLoad=useRef(false);
  const navigation=useRef(0);
  const operation=useRef(false);
  const morePending=useRef(false);
  useEffect(()=>{csrf.current=user?.csrf_token},[user]);

  const handleError=useCallback((e:unknown)=>{
    if(e instanceof ApiError && e.status===401) {navigation.current++;controller.current?.abort();setOpening(false);setUser(null);setMessages([]);setConversations([]);setCurrent(null);setAttachments([]);setUsage(null);setRuns({});setDraft('');storage.remove('modurouter-draft');retry.current=null;}
    setError(e instanceof Error?e.message:'처리하지 못했습니다. 잠시 후 다시 시도해 주세요.');
  },[]);

  const refresh=useCallback(async()=>{
    const [list,u,m]=await Promise.all([api<{items:Conversation[];next_cursor:string|null}>('/v1/conversations'),api<Usage>('/v1/usage'),api<ModelStatus>('/v1/models/status')]);
    setConversations(list.items);setCursor(list.next_cursor);setUsage(u);setModelStatus(m);
  },[]);

  useEffect(()=>{
    const leave=()=>{
      if(activeRun.current&&csrf.current)void fetch(apiUrl(`/v1/runs/${activeRun.current}/cancel`),{method:'POST',credentials:'include',keepalive:true,headers:{'X-CSRF-Token':csrf.current}}).catch(()=>{});
      controller.current?.abort();
    };
    window.addEventListener('pagehide',leave);
    setDraft(storage.get('modurouter-draft')||'');
    window.speechSynthesis?.getVoices();
    if(!initialLoad.current){
      initialLoad.current=true;
      void (async()=>{
        try{
          const [configuration,session]=await Promise.allSettled([api<Config>('/v1/config'),ensureSession()]);
          if(configuration.status==='fulfilled')setConfig(configuration.value);else handleError(configuration.reason);
          const active:User|null=session.status==='fulfilled'?session.value:null;
          if(session.status==='rejected'&&!(session.reason instanceof ApiError&&session.reason.status===401))handleError(session.reason);
          if(active){setUser(active);await refresh();const saved=storage.get(`modurouter-conversation:${active.id}`);if(saved)await openConversation(saved,active.id)}
        }catch(e){handleError(e)}finally{setLoading(false)}
      })();
    }
    const authError=new URLSearchParams(location.search).get('auth_error');
    if(authError)setError(authError==='account_deleted'?'삭제한 계정으로 로그인할 수 없습니다.':'로그인을 완료하지 못했습니다. 다시 시도해 주세요.');
    return ()=>{window.removeEventListener('pagehide',leave);leave();recognition.current?.abort();speechRequest.current++;window.speechSynthesis?.cancel()};
  },[refresh,handleError]);

  useEffect(()=>{if(!loading)storage.set('modurouter-draft',draft)},[draft,loading]);
  useEffect(()=>{
    if(!loading&&!opening&&user&&current)storage.set(`modurouter-attachments:${user.id}:${current}`,JSON.stringify(attachments.map(({id,filename})=>({id,filename}))));
  },[attachments,current,user,loading,opening]);
  useEffect(()=>{const element=scroller.current;if(element && element.scrollHeight-element.scrollTop-element.clientHeight<220)element.scrollTo({top:element.scrollHeight})},[messages,status]);

  const pendingFiles=attachments.filter(a=>a.status==='queued'||a.status==='pending').map(a=>a.id).join(',');
  useEffect(()=>{
    if(!pendingFiles)return;
    let live=true, polling=false;
    const timer=setInterval(async()=>{
      if(polling)return;
      polling=true;
      try{const results=await Promise.all(pendingFiles.split(',').map(id=>api<Attachment>(`/v1/attachments/${id}`)));if(live)setAttachments(current=>current.map(a=>results.find(r=>r.id===a.id)||a))}catch(e){if(live)handleError(e)}finally{polling=false}
    },1500);
    return ()=>{live=false;clearInterval(timer)};
  },[pendingFiles,handleError]);

  async function ensureConversation() {
    if(current)return current;
    const c=await api<Conversation>('/v1/conversations',{method:'POST',body:JSON.stringify({title:'새 대화'})},user?.csrf_token);
    setCurrent(c.id);storage.set(`modurouter-conversation:${user!.id}`,c.id);setConversations(cs=>[c,...cs]);return c.id;
  }

  async function openConversation(id:string, ownerId=user?.id) {
    if(operation.current)return;
    const version=++navigation.current;
    setOpening(true);stopSpeech();
    setError('');setStatus('');setDrawer(false);retry.current=null;
    try {
      const c=await api<Conversation&{messages:Message[]}>(`/v1/conversations/${id}`);
      const ids=Array.from(new Set(c.messages.filter(m=>m.role==='assistant').map(m=>m.run_id)));
      const details=await Promise.all(ids.map(id=>api<Run>(`/v1/runs/${id}`)));
      const savedAttachments=ownerId?readSavedAttachments(storage.get(`modurouter-attachments:${ownerId}:${id}`)):[];
      const restored=await restoreAttachments(savedAttachments);
      if(version!==navigation.current)return;
      setCurrent(id);setAttachments(restored);if(ownerId)storage.set(`modurouter-conversation:${ownerId}`,id);setMessages(c.messages);
      setRuns(Object.fromEntries(details.map(r=>[r.run_id,r])));
      setOpening(false);
      const running=details.find(isActive);
      if(running){
        operation.current=true;setBusy(true);
        controller.current=new AbortController();
        try{await followRun(running.run_id,controller.current.signal);await refresh()}
        finally{operation.current=false;setBusy(false);activeRun.current=null;controller.current=null}
      }
    } catch(e){if(version===navigation.current)handleError(e)}
    finally{if(version===navigation.current)setOpening(false)}
  }

  function stopSpeech(){recognition.current?.abort();setListening(false);speechRequest.current++;window.speechSynthesis?.cancel();setSpeaking(null)}

  function newConversation(){if(operation.current)return;if(user)storage.remove(`modurouter-conversation:${user.id}`);navigation.current++;setOpening(false);stopSpeech();setCurrent(null);setMessages([]);setAttachments([]);setRuns({});setStatus('');setError('');setDrawer(false);retry.current=null;input.current?.focus()}

  async function removeConversation(c:Conversation) {
    try{await api(`/v1/conversations/${c.id}`,{method:'DELETE'},user?.csrf_token);if(c.id===current)newConversation();await refresh()}catch(e){handleError(e);throw e}
  }

  async function loadMore(){
    if(morePending.current||!cursor)return;
    morePending.current=true;setLoadingMore(true);
    try{const list=await api<{items:Conversation[];next_cursor:string|null}>(`/v1/conversations?cursor=${encodeURIComponent(cursor)}`);setConversations(cs=>[...cs,...list.items.filter(item=>!cs.some(c=>c.id===item.id))]);setCursor(list.next_cursor)}catch(e){handleError(e)}finally{morePending.current=false;setLoadingMore(false)}
  }

  function applyRun(run:Run) {
    setRuns(rs=>({...rs,[run.run_id]:run}));
    setMessages(ms=>ms.map(m=>m.role==='assistant'&&(m.run_id===run.run_id||m.id==='pending')?{...m,run_id:run.run_id,content:run.response,status:run.status}:m));
    setStatus(['failed','cancelled','interrupted'].includes(run.status)?'':statusText[run.status]||run.status);
  }

  async function followRun(id:string,signal:AbortSignal) {
    activeRun.current=id;
    const deadline=Date.now()+135000;
    while(true){
      signal.throwIfAborted();
      const result=await api<Run>(`/v1/runs/${id}`,{signal});
      applyRun(result);
      if(!isActive(result))return result;
      if(Date.now()>deadline)throw new Error('답변 상태 확인이 지연되고 있습니다. 대화를 다시 열어 확인해 주세요.');
      await new Promise(resolve=>setTimeout(resolve,1000));
    }
  }

  async function send() {
    if(!user||operation.current||opening||!draft.trim())return;
    if(attachments.some(a=>a.status!=='ready')){setError('첨부파일 처리가 끝나지 않았습니다. 실패한 파일은 삭제하고 다시 첨부해 주세요.');return}
    operation.current=true;stopSpeech();setError('');setBusy(true);setStatus('질문을 보내고 있습니다.');
    const question=draft.trim();
    let runId:string|null=null;let optimisticKey:string|null=null;
    const abort=new AbortController();controller.current=abort;
    try {
      const conversationId=await ensureConversation();
      abort.signal.throwIfAborted();
      const body=JSON.stringify({message:question,search_enabled:search,attachment_ids:attachments.map(a=>a.id),explanation_mode:simple?'simple':'standard'});
      const key=retry.current?.body===body&&retry.current.conversationId===conversationId?retry.current.key:crypto.randomUUID();
      retry.current={key,body,conversationId};
      const response=await fetchApi(`/v1/conversations/${conversationId}/runs`,{method:'POST',credentials:'include',signal:abort.signal,headers:{'Content-Type':'application/json','X-CSRF-Token':user.csrf_token,'Idempotency-Key':key},body});
      if(!response.ok)throw await responseError(response);
      setDraft('');
      if(response.headers.get('Content-Type')?.includes('application/json')){
        const run=await response.json() as Run;runId=run.run_id;activeRun.current=runId;applyRun(run);
        const conversation=await api<{messages:Message[]}>(`/v1/conversations/${conversationId}`);setMessages(conversation.messages);
      } else {
        optimisticKey=key;
        setMessages(ms=>[...ms,{id:key,run_id:'',role:'user',content:question,status:'completed'},{id:'pending',run_id:'',role:'assistant',content:'',status:'accepted'}]);
        await consumeEvents(response,(kind,data)=>{
          if(typeof data.run_id==='string'){runId=data.run_id;activeRun.current=runId;setMessages(ms=>ms.map(m=>m.id===key||m.id==='pending'?{...m,run_id:String(data.run_id)}:m))}
          if(kind==='status'){setStatus(typeof data.message==='string'?data.message:statusText[String(data.status)]||'처리 중입니다.');if(data.status==='context_truncated')setRuns(rs=>({...rs,[String(data.run_id)]:{...rs[String(data.run_id)],run_id:String(data.run_id),context_truncated:true}}))}
          if(kind==='model'&&typeof data.selected_model==='string')setRuns(rs=>({...rs,[String(data.run_id)]:{...rs[String(data.run_id)],run_id:String(data.run_id),selected_model:data.selected_model as string}}));
          if(kind==='delta')setMessages(ms=>ms.map(m=>m.id==='pending'?{...m,run_id:String(data.run_id),content:m.content+String(data.text),status:'streaming'}:m));
          if(kind==='source'){const source=data.source as Source;setRuns(rs=>{const prior=rs[String(data.run_id)];return {...rs,[String(data.run_id)]:{...prior,run_id:String(data.run_id),sources:[...(prior?.sources||[]),source]}}})}
          if(kind==='error')setStatus('답변 상태를 확인하고 있습니다.');
          if(kind==='done')setStatus(statusText[String(data.status)]||'완료했습니다.');
        });
      }
      if(runId){
        const completed=await followRun(runId,abort.signal);
        if(completed.status==='failed'||completed.status==='interrupted'){setDraft(question);setError('')}
        else setAttachments([]);
        setMessages(ms=>ms.map(m=>m.id==='pending'?{...m,id:runId!}:m));
      }else throw new Error('응답 연결이 끊겼습니다. 같은 질문을 다시 보내 저장 여부를 확인해 주세요.');
      retry.current=null;await refresh();
    } catch(e) {
      if(e instanceof Error && e.name==='AbortError')setStatus('답변 연결을 중단했습니다.');else{setStatus('');handleError(e)}
      if(!runId&&!(e instanceof ApiError&&e.status===401)){setDraft(question);setMessages(ms=>ms.filter(m=>m.id!=='pending'&&m.id!==optimisticKey))}
      if(runId&&!(e instanceof ApiError&&e.status===401)){try{const completed=await followRun(runId,abort.signal);retry.current=null;setError('');if(completed.status==='failed'||completed.status==='interrupted')setDraft(question);else setAttachments([]);setMessages(ms=>ms.map(m=>m.id==='pending'?{...m,id:runId!}:m));await refresh()}catch{setError('연결이 끊겼습니다. 대화를 다시 열어 저장된 답변을 확인해 주세요.')}}
    } finally {operation.current=false;setBusy(false);controller.current=null;activeRun.current=null;input.current?.focus()}
  }

  async function cancel(){if(activeRun.current){try{await api(`/v1/runs/${activeRun.current}/cancel`,{method:'POST'},user?.csrf_token)}catch(e){handleError(e)}}else controller.current?.abort()}

  async function uploadFiles(files:FileList|null) {
    if(!files||!files.length||!user||operation.current||opening)return;
    const selected=Array.from(files);
    if(uploadInput.current)uploadInput.current.value='';
    if(selected.length+attachments.length>(config?.max_attachments||3)){setError(`한 번에 파일 ${config?.max_attachments||3}개까지 첨부할 수 있습니다.`);return}
    const maxBytes=config?.max_attachment_bytes||10*1024*1024;
    if(selected.some(file=>file.size>maxBytes)){setError(`파일은 ${Math.floor(maxBytes/1024/1024)}MB까지 첨부할 수 있습니다.`);return}
    if(selected.some(file=>!file.size||! /\.(txt|pdf|png|jpe?g)$/i.test(file.name))){setError('내용이 있는 TXT, PDF, PNG, JPG 파일을 첨부해 주세요.');return}
    operation.current=true;setUploading(true);setError('');
    try {
      const id=await ensureConversation();
      for(const file of selected){
        const body=new FormData();body.append('file',file);body.append('conversation_id',id);
        const uploaded=await api<Attachment>('/v1/attachments',{method:'POST',body},user.csrf_token);setAttachments(as=>[...as,uploaded]);
      }
    }catch(e){handleError(e)}finally{operation.current=false;setUploading(false)}
  }

  async function removeAttachment(a:Attachment){try{if(a.status!=='expired')await api(`/v1/attachments/${a.id}`,{method:'DELETE'},user?.csrf_token);setAttachments(as=>as.filter(x=>x.id!==a.id))}catch(e){handleError(e)}}

  function startVoice() {
    const Constructor=(window as SpeechWindow).SpeechRecognition||(window as SpeechWindow).webkitSpeechRecognition;
    if(!Constructor){setError('이 브라우저는 음성 입력을 지원하지 않습니다. 입력창에 질문을 적어 주세요.');return}
    const instance=new Constructor();recognition.current=instance;instance.lang='ko-KR';instance.interimResults=false;instance.continuous=false;
    instance.onresult=e=>{let text='';for(let i=0;i<e.results.length;i++)text+=e.results[i][0].transcript;setDraft(d=>d+(d?' ':'')+text);input.current?.focus()};
    instance.onerror=e=>{setError(e.error==='not-allowed'?'마이크 권한이 거부되었습니다. 글로 질문을 입력할 수 있습니다.':'음성을 인식하지 못했습니다. 다시 말하거나 글로 입력해 주세요.');setListening(false)};
    instance.onend=()=>setListening(false);
    setListening(true);try{instance.start()}catch{setListening(false);setError('마이크를 시작하지 못했습니다. 글로 질문을 입력해 주세요.')}
  }

  function voice(){if(listening){recognition.current?.stop();return}if(storage.get('voice-consent')==='yes')startVoice();else setVoiceConsent(true)}
  async function speak(message:Message) {
    if(!window.speechSynthesis){setError('이 브라우저는 답변 읽어주기를 지원하지 않습니다.');return}
    const request=++speechRequest.current;
    window.speechSynthesis.cancel();
    if(speaking===message.id){setSpeaking(null);return}
    setSpeaking(message.id);
    const voice=await koreanVoice(window.speechSynthesis);
    if(request!==speechRequest.current)return;
    if(!voice){setSpeaking(null);setError('사용 가능한 한국어 음성이 없습니다. 기기의 음성 설정을 확인해 주세요.');return}
    const utterance=new SpeechSynthesisUtterance(message.content.replace(/[#*`]/g,''));
    utterance.lang='ko-KR';utterance.voice=voice;
    utterance.onend=()=>{if(request===speechRequest.current)setSpeaking(null)};
    utterance.onerror=()=>{if(request===speechRequest.current){setSpeaking(null);setError('답변 읽어주기를 완료하지 못했습니다.')}};
    window.speechSynthesis.speak(utterance);
  }

  async function logout(){try{const response=await fetchApi('/auth/logout',{method:'POST',headers:{'X-CSRF-Token':user!.csrf_token},credentials:'include'});if(!response.ok)throw new Error('로그아웃하지 못했습니다. 다시 시도해 주세요.');storage.remove('modurouter-draft');location.reload()}catch(e){handleError(e)}}

  async function deleteAccount(){try{await api('/v1/me',{method:'DELETE'},user?.csrf_token);storage.remove('modurouter-draft');location.reload()}catch(e){handleError(e);throw e}}

  const loginLinks=(!user||user.guest)&&<div className="login-actions">{config?.google_login_available&&<a className="button" href={apiUrl('/auth/google/start')}>Google로 로그인<ArrowUpRight/></a>}{config?.admin_login_available&&<a className="button" href="/admin">관리자 로그인<ArrowUpRight/></a>}</div>;

  const sidebar=<div className="sidebar"><Brand/><button onClick={newConversation} disabled={busy||uploading||!user}><Plus/>새 대화</button><nav className="history" aria-label="대화 기록"><p className="history-title">내 대화</p>{conversations.length===0&&<p className="muted small" style={{padding:'0 8px'}}>대화가 여기에 저장됩니다.</p>}{conversations.map(c=><div key={c.id} className="history-row" data-active={c.id===current}><button disabled={busy||uploading} onClick={()=>openConversation(c.id)} aria-current={c.id===current?'page':undefined}><span>{c.title}</span></button><DeleteConversation conversation={c} disabled={busy||uploading} onDelete={()=>removeConversation(c)}/></div>)}{cursor&&<button className="quiet" disabled={loadingMore||busy||uploading} onClick={loadMore}>{loadingMore?'불러오는 중':'이전 대화 더 보기'}</button>}</nav><div className="account"><p className="small muted">{user?user.display_name:'한국어 AI 도우미'}</p><p className="small muted">{user?.guest?'로그인 없이 이용 중':'질문부터 자료 이해까지'}</p>{loginLinks}</div></div>;

  return <div className="app-shell">
    {sidebar}
    <main className="workspace">
      <header className="workspace-header">
        <Dialog.Root open={drawer} onOpenChange={setDrawer}><Dialog.Trigger className="quiet mobile-menu" aria-label="대화 목록 열기"><Menu/></Dialog.Trigger><Dialog.Portal><Dialog.Backdrop className="backdrop"/><Dialog.Popup className="popup drawer"><div className="drawer-top"><Dialog.Title className="popup-title">대화 목록</Dialog.Title><Dialog.Close className="quiet" aria-label="대화 목록 닫기"><X/></Dialog.Close></div><Dialog.Description className="sr-only">저장한 대화를 열거나 새 대화를 시작합니다.</Dialog.Description>{sidebar}</Dialog.Popup></Dialog.Portal></Dialog.Root>
        <p className="title">{conversations.find(c=>c.id===current)?.title||'새로운 대화'}</p>
        <div className="header-actions"><span className="small muted usage-text">{usage?(usage.request_limit===null?'질문 횟수 무제한':`오늘 ${usage.remaining_requests}회 남음`):'필요한 만큼, 차근차근'}</span>
          <Dialog.Root><Dialog.Trigger className="quiet" aria-label="사용량과 계정 설정"><Settings/></Dialog.Trigger><Dialog.Portal><Dialog.Backdrop className="backdrop"/><Dialog.Popup className="popup" initialFocus={settingsClose}><Dialog.Title className="popup-title">사용량과 계정</Dialog.Title><Dialog.Description className="popup-description">오늘 사용할 수 있는 질문 횟수와 비용을 확인하세요.</Dialog.Description>{usage?<><dl className="usage-rows"><dt>남은 질문</dt><dd>{usage.request_limit===null?'무제한':`${usage.remaining_requests} / ${usage.request_limit}회`}</dd><dt>확정 사용 비용</dt><dd>${Number(usage.spent_usd).toFixed(5)}</dd><dt>확인 중인 예약액</dt><dd>${Number(usage.reserved_usd).toFixed(5)}</dd><dt>하루 비용 한도</dt><dd>${Number(usage.limit_usd).toFixed(2)}</dd><dt>사용량 초기화</dt><dd>한국 시간 자정</dd></dl><p className="small muted">{modelStatus?.last_success_at?`가격 갱신: ${new Date(modelStatus.last_success_at).toLocaleString('ko-KR')}`:'가격 정보 준비 중'}</p>{modelStatus?.refresh_error&&<p className="small error">가격 갱신에 실패했습니다.{modelStatus.stale?' 새 질문이 일시 중단됩니다.':' 유효한 이전 가격을 사용합니다.'}</p>}</>:<p className="muted">서비스에 연결하면 사용량을 확인할 수 있습니다.</p>}{user?.guest&&<p className="small muted">비로그인 사용자는 하루 질문 횟수와 비용 한도를 함께 사용합니다.</p>}{loginLinks}<p className="small muted">첨부파일 원본과 추출문은 24시간 후 삭제됩니다. 답변에 인용된 내용은 대화를 삭제할 때까지 남습니다.</p><div className="popup-actions">{user&&<><DeleteAccount disabled={busy||uploading} guest={user.guest} onDelete={deleteAccount}/>{!user.guest&&<button disabled={busy||uploading} onClick={logout}>로그아웃</button>}</>}<Dialog.Close ref={settingsClose}>닫기</Dialog.Close></div></Dialog.Popup></Dialog.Portal></Dialog.Root>
        </div>
      </header>
      <div className="conversation-scroll" ref={scroller}>
        {loading||opening?<p className="loading" role="status">{opening?'대화를 불러오고 있습니다.':'서비스에 연결하고 있습니다.'}</p>:messages.length===0?<section className="empty"><Brand/><h1>{user?'무엇이 궁금한가요?':'궁금한 것부터 물어보세요.'}</h1><p className="muted">어려운 개념을 풀어보고, 찾은 자료를 정리해 보세요. 모두라우터가 한국어로 함께합니다.</p>{user?.guest&&<p className="small muted">로그인 없이 바로 질문할 수 있습니다. 대화 기록은 현재 브라우저 세션에서만 이어갈 수 있으며, 로그인한 계정으로 옮겨지지 않습니다.</p>}{!user?<button onClick={()=>location.reload()}>다시 연결하기</button>:<div className="examples"><button onClick={()=>{setDraft('광합성을 쉬운 예시로 설명해 줘');setSimple(true);input.current?.focus()}}><BookOpen/>광합성을 쉬운 예시로 설명해 줘<ArrowUpRight/></button><button onClick={()=>{setDraft('한국의 최신 우주 탐사 소식을 찾아 줘');setSearch(true);input.current?.focus()}}><Globe/>출처를 확인하며 최신 소식 알아보기<ArrowUpRight/></button><button disabled={busy||uploading||opening} onClick={()=>uploadInput.current?.click()}><FileText/>파일을 읽고 핵심 내용 정리하기<ArrowUpRight/></button></div>}</section>:<div className="reading" aria-label="대화 내용">{messages.map(m=>{const run=runs[m.run_id];const allowed=new Set(run?.sources?.map(s=>s.url).filter(Boolean));return <article key={m.id} className="message"><div className="message-author">{m.role==='user'?'나':'모두라우터'}{m.role==='assistant'&&m.status==='completed'&&<Check aria-label="완료"/>}{m.role==='assistant'&&<span className="message-model" aria-live="polite">{run?.selected_model?`모델: ${run.selected_model}`:['accepted','preparing','model','tool','streaming'].includes(m.status)?'모델 자동 선택 중':'모델 정보 없음'}</span>}</div>{m.role==='user'?<p className="message-content">{m.content}</p>:<div className="markdown"><Markdown remarkPlugins={[remarkGfm]} components={{a:({href,children})=>href&&allowed.has(href)?<a href={href} target="_blank" rel="noopener noreferrer">{children}</a>:<span>{children}</span>,img:()=>null}}>{m.content||(['failed','cancelled','interrupted'].includes(m.status)?'':'답변을 준비하고 있습니다.')}</Markdown></div>}{m.role==='assistant'&&<>{run?.context_truncated&&<p className="small context-notice" role="note">입력 한도로 이전 대화나 자료 일부가 제외되었습니다. 문서 전체를 반영한 답변이 아닐 수 있습니다.</p>}{['failed','cancelled','interrupted'].includes(m.status)&&<p className="small error">{m.status==='failed'?runErrorMessage(run?.error_code):statusText[m.status]}</p>}<div className="message-actions">{m.content&&<button className="quiet" onClick={()=>speak(m)}><Volume2/>{speaking===m.id?'읽기 중단':'읽어주기'}</button>}{run&&<details><summary>답변 상세</summary><p className="small">모델: {run.selected_model||'미확인'}<br/>공급자: {run.providers?.join(', ')||'OpenRouter'}<br/>{run.cost_source==='calculated'?'토큰 기준 계산 비용':run.cost_source==='mixed'?'청구 및 계산 비용':'확정 비용'}: ${Number(run.cost_usd||0).toFixed(6)}<br/>확인 중인 예약액: ${Number(run.pending_usd||0).toFixed(6)}<br/>입력 토큰: {run.input_tokens??0}<br/>출력 토큰: {run.output_tokens??0}{!run.tokens_complete&&' (일부 사용량 확인 중)'}<br/>모델 호출: {run.attempts||0}회</p></details>}{['failed','interrupted'].includes(m.status)&&<button className="quiet" disabled={busy||opening} onClick={()=>{const question=messages.find(item=>item.run_id===m.run_id&&item.role==='user');if(question){setDraft(question.content);input.current?.focus()}}}>질문 다시 입력</button>}</div>{run?.sources?.length>0&&<div className="sources" aria-label="확인한 출처"><strong>참고한 자료</strong>{run.sources.map((s,i)=><span key={`${s.source_id}-${i}`}>{s.url?<a href={s.url} target="_blank" rel="noopener noreferrer">[{s.source_id}] {s.title}<ArrowUpRight/></a>:<span>[{s.source_id}] {s.title}</span>}<span className="muted"> {s.scope==='search_snippet'?'검색 발췌':s.scope==='attachment'?'첨부파일':'페이지 본문'}{s.truncated?' (일부)':''}</span></span>)}</div>}</>}</article>})}</div>}
      </div>
      <div className="composer-zone"><div className="reading">
        {error&&<p id="composer-error" className="error" role="alert">{error}</p>}
        <p className="status-line" role="status" aria-live="polite">{listening?'듣고 있습니다. 인식한 문장은 전송 전에 수정할 수 있습니다.':uploading?'파일을 올리고 있습니다.':status}</p>
        <p className="model-routing-note">모델 자동 선택 <span>질문에 맞춰 선택하며, 사용한 모델은 각 답변에 표시됩니다.</span></p>
        <form className="composer" onSubmit={e=>{e.preventDefault();send()}}>
          {attachments.length>0&&<div className="attachments">{attachments.map(a=><div className="attachment-item" key={a.id}><div className="attachment"><FileText/><span className="name">{a.filename}</span><span>{a.status==='ready'?'읽기 완료':a.status==='failed'?'읽기 실패':a.status==='expired'?'만료됨':a.status==='unavailable'?'확인 필요':'읽는 중'}</span>{a.status==='ready'&&<button type="button" className="quiet" onClick={()=>setPreview(a)}>내용 확인</button>}<button type="button" className="quiet" disabled={busy||uploading||opening} aria-label={`${a.filename} 첨부 삭제`} onClick={()=>removeAttachment(a)}><X/></button></div>{attachmentErrorMessage(a)&&<p className="small error" role="alert">{attachmentErrorMessage(a)}</p>}{a.status==='ready'&&/\.(png|jpe?g)$/i.test(a.filename)&&<p className="small muted">이미지에서 읽은 내용은 누락되거나 틀릴 수 있습니다. 내용 확인에서 원본과 비교해 주세요.</p>}</div>)}</div>}
          <label htmlFor="question" className="sr-only">질문 입력</label><textarea aria-describedby={error?'composer-error':undefined} id="question" ref={input} value={draft} onChange={e=>setDraft(e.target.value)} placeholder={loading?'서비스에 연결하고 있습니다.':'질문을 입력하거나 자료를 첨부하세요.'} disabled={!user||busy||opening} maxLength={12000} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing&&window.matchMedia('(hover: hover) and (pointer: fine)').matches){e.preventDefault();send()}}}/>
          <div className="composer-controls"><div className="tools"><input ref={uploadInput} type="file" hidden tabIndex={-1} accept=".txt,.pdf,.png,.jpg,.jpeg" multiple aria-hidden="true" onChange={e=>uploadFiles(e.target.files)}/><button type="button" aria-label="파일 첨부" disabled={!user||busy||uploading||opening} onClick={()=>uploadInput.current?.click()}><Paperclip/><span className="tool-text">첨부</span></button><button type="button" aria-pressed={search} disabled={!user||busy||opening} onClick={()=>setSearch(s=>!s)}><Globe/>웹 검색</button><button type="button" aria-pressed={simple} disabled={!user||busy||opening} onClick={()=>setSimple(s=>!s)}><BookOpen/><span className="tool-text" aria-hidden="true">쉬운 설명</span><span className="sr-only">쉬운 설명</span></button><button type="button" aria-label={listening?'음성 입력 중단':'음성 입력'} aria-pressed={listening} disabled={!user||busy||opening} onClick={voice}><Mic/></button></div>{busy?<button type="button" onClick={cancel} aria-label="답변 생성 중단"><Square/>중단</button>:<button className="primary" type="submit" disabled={!user||busy||opening||!draft.trim()||uploading||attachments.some(a=>a.status!=='ready')} aria-label="질문 전송"><ArrowUp/></button>}</div>
        </form><p className="composer-note">AI의 답변은 틀릴 수 있습니다. 중요한 내용은 출처를 확인해 주세요.</p>
      </div></div>
    </main>
    <Dialog.Root open={!!preview} onOpenChange={open=>{if(!open)setPreview(null)}}><Dialog.Portal><Dialog.Backdrop className="backdrop"/><Dialog.Popup className="popup"><Dialog.Title className="popup-title">읽어낸 내용</Dialog.Title><Dialog.Description className="popup-description">{preview?.filename}{preview?.truncated?' (20,000자 이후 내용은 제외됨)':''}</Dialog.Description><pre>{preview?.preview}</pre><Dialog.Close>닫기</Dialog.Close></Dialog.Popup></Dialog.Portal></Dialog.Root>
    <AlertDialog.Root open={voiceConsent} onOpenChange={setVoiceConsent}><AlertDialog.Portal><AlertDialog.Backdrop className="backdrop"/><AlertDialog.Popup className="popup"><AlertDialog.Title className="popup-title">음성으로 입력할까요?</AlertDialog.Title><AlertDialog.Description className="popup-description">음성을 인식하기 위해 브라우저 제공자의 서버로 음성이 전송될 수 있습니다. 인식한 문장을 확인하고 수정한 뒤 직접 전송할 수 있습니다.</AlertDialog.Description><div className="popup-actions"><AlertDialog.Close>취소</AlertDialog.Close><button onClick={()=>{storage.set('voice-consent','yes');setVoiceConsent(false);startVoice()}}>동의하고 시작</button></div></AlertDialog.Popup></AlertDialog.Portal></AlertDialog.Root>
  </div>;
}
