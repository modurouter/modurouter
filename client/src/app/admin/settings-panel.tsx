'use client';

import Link from 'next/link';
import {useCallback, useEffect, useRef, useState, type FormEvent} from 'react';
import {api, type ModelCatalog, type RoutingPreference, type User} from '@/lib/api';
import {providerName, routingName} from '../model-picker';

type Policy = {
  enabled_providers:string[]; model_allowlist:string[]; tool_model_allowlist:string[];
  manual_model_allowlist:string[]|null; allow_manual_selection:boolean; default_routing:RoutingPreference;
  input_price_cap_usd_per_m:string; output_price_cap_usd_per_m:string; user_daily_budget_usd:string;
  user_daily_request_limit:number; guest_daily_request_limit:number; max_input_tokens:number; max_output_tokens:number;
  max_model_calls_per_run:number; max_tool_calls_per_run:number; run_timeout_seconds:number;
  platform_concurrency:number; price_refresh_seconds:number; price_stale_seconds:number;
};
type SettingsResponse = {revision:number; policy:Policy; updated_at:string|null; providers:{code:string;configured:boolean}[]};
type NumericKey = Exclude<keyof Policy,'enabled_providers'|'model_allowlist'|'tool_model_allowlist'|'manual_model_allowlist'|'allow_manual_selection'|'default_routing'>;
const limits:{key:NumericKey;label:string;min:number;max:number;step?:string}[] = [
  {key:'input_price_cap_usd_per_m',label:'자동 선택 입력 단가 상한 / $ per 1M',min:0,max:10000,step:'any'},
  {key:'output_price_cap_usd_per_m',label:'자동 선택 출력 단가 상한 / $ per 1M',min:0,max:10000,step:'any'},
  {key:'user_daily_budget_usd',label:'사용자별 하루 예산 / USD',min:0,max:100000,step:'any'},
  {key:'user_daily_request_limit',label:'회원별 하루 질문 수',min:1,max:100000},
  {key:'guest_daily_request_limit',label:'비로그인 전체 하루 질문 수',min:1,max:100000},
  {key:'max_input_tokens',label:'요청당 입력 토큰 한도',min:512,max:32768},
  {key:'max_output_tokens',label:'호출당 최대 출력 토큰',min:1,max:8192},
  {key:'max_model_calls_per_run',label:'답변당 최대 모델 호출 수',min:1,max:3},
  {key:'max_tool_calls_per_run',label:'답변당 최대 도구 호출 수',min:1,max:2},
  {key:'run_timeout_seconds',label:'답변 제한 시간 / 초',min:10,max:120},
  {key:'platform_concurrency',label:'동시 답변 수',min:1,max:5},
  {key:'price_refresh_seconds',label:'가격 갱신 간격 / 초',min:30,max:86400},
  {key:'price_stale_seconds',label:'가격 정보 유효 시간 / 초',min:60,max:172800},
];
const allowed=(list:string[]|null,provider:string,model:string)=>list===null||list.includes(model)||list.includes(`${provider}::${model}`);

export default function SettingsPanel({user}:{user:User}) {
  const [saved,setSaved]=useState<SettingsResponse|null>(null);
  const [policy,setPolicy]=useState<Policy|null>(null);
  const [catalog,setCatalog]=useState<ModelCatalog|null>(null);
  const [busy,setBusy]=useState(false);
  const [error,setError]=useState('');
  const [notice,setNotice]=useState('');
  const [query,setQuery]=useState('');
  const [providerFilter,setProviderFilter]=useState('');
  const pending=useRef(false);
  const load=useCallback(async()=>{
    const [settings,models]=await Promise.all([api<SettingsResponse>('/v1/admin/settings'),api<ModelCatalog>('/v1/admin/models')]);
    setSaved(settings);setPolicy(settings.policy);setCatalog(models);
  },[]);
  useEffect(()=>{void load().catch(e=>setError(e.message))},[load]);
  const dirty=!!saved&&JSON.stringify(saved.policy)!==JSON.stringify(policy);
  useEffect(()=>{
    const warn=(event:BeforeUnloadEvent)=>{if(dirty){event.preventDefault();event.returnValue=''}};
    window.addEventListener('beforeunload',warn);return()=>window.removeEventListener('beforeunload',warn);
  },[dirty]);
  function update<K extends keyof Policy>(key:K,value:Policy[K]){setPolicy(p=>p?{...p,[key]:value}:p);setNotice('')}
  async function save(event:FormEvent) {
    event.preventDefault();if(!policy||!saved||pending.current)return;
    pending.current=true;setBusy(true);setError('');setNotice('');
    try {
      const result=await api<SettingsResponse>('/v1/admin/settings',{method:'POST',body:JSON.stringify({revision:saved.revision,policy})},user.csrf_token);
      setSaved(result);setPolicy(result.policy);setNotice('저장했습니다. 새 요청부터 적용됩니다.');
    }catch(e){setError(e instanceof Error?e.message:'설정을 저장하지 못했습니다.')}
    finally{pending.current=false;setBusy(false)}
  }
  async function refreshPrices(){
    if(pending.current)return;pending.current=true;setBusy(true);setError('');setNotice('');
    try{
      const result=await api<{results:{provider:string;count:number;error:string|null}[]}>('/v1/admin/models/refresh',{method:'POST'},user.csrf_token);
      setCatalog(await api<ModelCatalog>('/v1/admin/models'));
      const failed=result.results.filter(r=>r.error);
      if(failed.length)setError(`${failed.map(r=>providerName(r.provider)).join(', ')} 가격을 갱신하지 못했습니다.`);
      else setNotice('모델 목록과 가격을 갱신했습니다. 편집 중인 설정은 유지됩니다.');
    }catch(e){setError(e instanceof Error?e.message:'가격을 갱신하지 못했습니다.')}
    finally{pending.current=false;setBusy(false)}
  }
  function toggleModel(key:'model_allowlist'|'tool_model_allowlist'|'manual_model_allowlist',provider:string,model:string,enabled:boolean){
    if(!policy)return;
    const current=policy[key]||[];
    // Expand a provider-agnostic entry before changing just one provider.
    let next=current.filter(item=>item!==model&&item!==`${provider}::${model}`);
    if(current.includes(model))next=[...next,...(catalog?.models||[]).filter(m=>m.model_id===model&&m.provider!==provider).map(m=>`${m.provider}::${model}`)];
    if(enabled)next.push(`${provider}::${model}`);
    update(key,Array.from(new Set(next)).sort());
  }
  const models=(catalog?.models||[]).filter(m=>(!providerFilter||providerFilter===m.provider)&&`${m.model_id} ${m.name}`.toLowerCase().includes(query.toLowerCase()));
  return <main className="admin-workspace">
    <header className="admin-heading"><div><Link href="/" className="brand">모두라우터</Link><h1>라우팅 설정</h1><p className="muted">제공처와 모델 사용 기준을 관리합니다.</p></div><Link href="/" className="button">대화로 돌아가기</Link></header>
    {error&&<p className="error admin-feedback" role="alert">{error}</p>}
    {notice&&<p className="admin-feedback" role="status">{notice}</p>}
    {!policy||!saved?<><p role="status">설정을 불러오고 있습니다.</p>{error&&<button onClick={()=>void load().catch(e=>setError(e.message))}>다시 불러오기</button>}</>:<form onSubmit={save} aria-busy={busy}>
      <fieldset disabled={busy} className="admin-fields">
        <section className="admin-section" aria-labelledby="providers-title"><div><h2 id="providers-title">제공처</h2><p className="muted small">API 키는 서버의 .env에서 관리합니다.<br/>비활성화한 제공처는 새 요청에 사용하지 않습니다.</p></div><div className="admin-provider-list">{saved.providers.map(provider=><label key={provider.code} className="admin-provider"><span><input type="checkbox" checked={policy.enabled_providers.includes(provider.code)} disabled={!provider.configured} onChange={e=>update('enabled_providers',e.target.checked?[...policy.enabled_providers,provider.code]:policy.enabled_providers.filter(p=>p!==provider.code))}/>{providerName(provider.code)}</span><span className="small muted">{provider.configured?'키 설정됨':'키 없음'} / {catalog?.providers?.find(p=>p.provider===provider.code)?.stale?'가격 갱신 필요':'가격 '+(catalog?.providers?.some(p=>p.provider===provider.code)?'유효':'미확인')}</span></label>)}<button type="button" onClick={refreshPrices}>모델과 가격 새로고침</button></div></section>
        <section className="admin-section" aria-labelledby="default-title"><div><h2 id="default-title">기본 라우팅</h2><p className="small muted">사용자가 별도로 선택하지 않은 요청에 적용합니다.</p></div><div className="admin-form-stack"><label>기본 선택 방식<select value={policy.default_routing.mode} onChange={e=>update('default_routing',{mode:e.target.value as RoutingPreference['mode']})}>{(['auto','free','manual'] as const).map(mode=><option key={mode} value={mode} disabled={mode==='manual'&&!policy.allow_manual_selection}>{routingName(mode)}</option>)}</select></label>{policy.default_routing.mode==='manual'&&<label>기본 모델<select required value={policy.default_routing.model_id?`${policy.default_routing.provider}::${policy.default_routing.model_id}`:''} onChange={e=>{const m=catalog?.models.find(m=>`${m.provider}::${m.model_id}`===e.target.value);if(m)update('default_routing',{mode:'manual',provider:m.provider,model_id:m.model_id})}}><option value="">모델 선택</option>{(catalog?.models||[]).filter(m=>policy.enabled_providers.includes(m.provider)&&allowed(policy.manual_model_allowlist,m.provider,m.model_id)).map(m=><option key={`${m.provider}::${m.model_id}`} value={`${m.provider}::${m.model_id}`}>{providerName(m.provider)} / {m.name}</option>)}</select></label>}<label className="admin-checkbox"><input type="checkbox" checked={policy.allow_manual_selection} onChange={e=>update('allow_manual_selection',e.target.checked)}/>사용자가 모델과 제공처를 직접 선택할 수 있음</label></div></section>
        <section className="admin-section" aria-labelledby="models-title"><div><h2 id="models-title">허용 모델</h2><p className="small muted">자동 선택과 자료 처리에 사용할 모델을 구분합니다. 자료 처리는 검증한 모델만 허용하세요.</p></div><div className="admin-form-stack">
          <label className="admin-checkbox"><input type="checkbox" checked={policy.manual_model_allowlist===null} onChange={e=>update('manual_model_allowlist',e.target.checked?null:[])}/>무료와 직접 선택에 전체 가격 카탈로그 허용</label>
          <div className="admin-model-filters"><label><span className="sr-only">허용 모델 검색</span><input type="search" placeholder="모델 검색" value={query} onChange={e=>setQuery(e.target.value)}/></label><label><span className="sr-only">제공처 필터</span><select value={providerFilter} onChange={e=>setProviderFilter(e.target.value)}><option value="">전체 제공처</option>{saved.providers.map(p=><option key={p.code} value={p.code}>{providerName(p.code)}</option>)}</select></label></div>
          <div className="admin-model-table" tabIndex={0} role="region" aria-label="모델별 허용 설정"><table><thead><tr><th>모델 / 제공처</th><th>단가 / 1M</th><th>자동</th><th>자료 처리</th><th>무료 / 직접</th></tr></thead><tbody>{models.map(m=><tr key={`${m.provider}::${m.model_id}`}><td><strong>{m.name}</strong><span className="small muted">{providerName(m.provider)} / {m.model_id}</span></td><td className="small">{m.is_free?'무료':<>입력 ${Number(m.input_per_m)}<br/>출력 ${Number(m.output_per_m)}</>}</td>{(['model_allowlist','tool_model_allowlist','manual_model_allowlist'] as const).map((key,index)=><td key={key}><input type="checkbox" aria-label={`${providerName(m.provider)} ${m.model_id} ${['자동','자료 처리','무료와 직접'][index]} 허용`} checked={allowed(policy[key],m.provider,m.model_id)} disabled={key==='manual_model_allowlist'&&policy[key]===null} onChange={e=>toggleModel(key,m.provider,m.model_id,e.target.checked)}/></td>)}</tr>)}</tbody></table>{!models.length&&<p className="small muted">모델이 없습니다. 가격을 갱신하거나 검색 조건을 바꿔 주세요.</p>}</div>
          <details><summary>허용 목록 직접 편집</summary><p className="small muted">한 줄에 모델 ID 하나를 입력합니다. 제공처를 한정하려면 provider::model 형식을 사용하세요. 예: openrouter::qwen/qwen3-30b-a3b-instruct-2507</p>{(['model_allowlist','tool_model_allowlist','manual_model_allowlist'] as const).map((key,index)=><label key={key}>{['자동 선택 목록','자료 처리 목록','무료와 직접 선택 목록'][index]}<textarea rows={4} disabled={key==='manual_model_allowlist'&&policy[key]===null} value={(policy[key]||[]).join('\n')} onChange={e=>update(key,e.target.value.split('\n'))}/></label>)}</details>
        </div></section>
        <section className="admin-section" aria-labelledby="limits-title"><div><h2 id="limits-title">비용과 실행 제한</h2><p className="small muted">직접 선택에는 자동 단가 상한을 적용하지 않습니다. 하루 예산은 모든 유료 요청에 적용합니다. 관리자는 질문 횟수 제한을 받지 않습니다.</p></div><div className="admin-limit-grid">{limits.map(field=><label key={field.key}>{field.label}<input type="number" required min={field.min} max={field.max} step={field.step||1} value={policy[field.key]} onChange={e=>update(field.key,field.step==='any'?e.target.value:Number(e.target.value))}/></label>)}</div></section>
      </fieldset>
      <footer className="admin-save-bar"><div><strong>{dirty?'저장하지 않은 변경사항':'저장된 설정'}</strong><p className="small muted">{saved.updated_at?new Date(saved.updated_at).toLocaleString('ko-KR'):'서버 기본값 사용 중'} / 버전 {saved.revision}</p></div><div className="admin-save-actions"><button type="button" disabled={busy} onClick={()=>void load().then(()=>{setError('');setNotice('최신 설정을 불러왔습니다.')}).catch(e=>setError(e.message))}>다시 불러오기</button><button type="submit" className="primary" disabled={busy||!dirty}>{busy?'처리 중':'변경사항 저장'}</button></div></footer>
    </form>}
  </main>;
}
