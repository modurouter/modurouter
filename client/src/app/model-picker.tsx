'use client';

import {useState} from 'react';
import type {ModelCatalog, RoutingPreference} from '@/lib/api';

export const providerName = (code?:string) => ({openrouter:'OpenRouter',zenmux:'ZenMux',openai:'OpenAI',upstage:'Upstage'}[code||'']||code||'확인 중');
export const routingName = (mode?:string) => mode==='manual'?'직접 선택':mode==='free'?'무료만':'자동 절약';

export function ModelPicker({catalog,value,onChange,disabled,needsTools}:{catalog:ModelCatalog|null;value:RoutingPreference;onChange:(value:RoutingPreference)=>void;disabled:boolean;needsTools:boolean}) {
  const [query,setQuery]=useState('');
  const selected=catalog?.models.find(m=>m.provider===value.provider&&m.model_id===value.model_id);
  const matches=(catalog?.models||[]).filter(m=>`${m.name} ${m.model_id} ${providerName(m.provider)}`.toLowerCase().includes(query.toLowerCase()));
  const visible=selected&&!matches.includes(selected)?[selected,...matches]:matches;
  return <div className="model-picker">
    <div className="routing-modes" role="group" aria-label="모델 선택 방식">
      {(['auto','free','manual'] as const).map(mode=><button key={mode} type="button" disabled={disabled||(mode==='manual'&&catalog?.allow_manual_selection===false)} aria-pressed={value.mode===mode} onClick={()=>onChange({mode})}>{routingName(mode)}</button>)}
    </div>
    {value.mode==='auto'&&<p className="small muted">검증된 모델 중 예상 비용이 가장 낮은 모델을 선택합니다. 무료 모델이 조건에 맞으면 먼저 사용합니다.</p>}
    {value.mode==='free'&&<p className="small muted">입력과 출력 단가가 모두 $0인 모델만 사용합니다. 사용할 수 없으면 유료 모델로 전환하지 않습니다.</p>}
    {value.mode==='manual'&&<>
      <div className="model-select-fields">
        <label><span className="sr-only">모델 검색</span><input type="search" value={query} onChange={e=>setQuery(e.target.value)} disabled={disabled} placeholder="모델 이름 또는 제공처 검색"/></label>
        <label><span className="sr-only">사용할 모델과 제공처</span><select value={selected?`${selected.provider}::${selected.model_id}`:''} disabled={disabled||!catalog} onChange={e=>{const model=catalog?.models.find(m=>`${m.provider}::${m.model_id}`===e.target.value);if(model)onChange({mode:'manual',provider:model.provider,model_id:model.model_id})}}>
          <option value="" disabled>모델을 선택하세요</option>
          {['zenmux','openrouter','openai','upstage'].map(provider=><optgroup key={provider} label={providerName(provider)}>{visible.filter(m=>m.provider===provider).map(m=><option key={m.model_id} value={`${provider}::${m.model_id}`} disabled={needsTools&&!m.supports_tools}>{m.name}{m.is_free?' / 무료':` / 입력 $${Number(m.input_per_m)} / 출력 $${Number(m.output_per_m)}`}{needsTools&&!m.supports_tools?' / 자료 처리 미검증':''}</option>)}</optgroup>)}
        </select></label>
      </div>
      {!visible.length&&<p className="small muted">{catalog?.stale?'가격 정보를 갱신한 뒤 모델을 선택할 수 있습니다.':'검색 조건에 맞는 모델이 없습니다.'}</p>}
      {selected?<p className="small muted">{providerName(selected.provider)} / {selected.is_free?'무료':`100만 토큰당 입력 $${Number(selected.input_per_m)}, 출력 $${Number(selected.output_per_m)}`}<br/>선택한 모델을 사용하며 다른 모델로 자동 변경하지 않습니다. 실제 비용은 사용 토큰에 따라 달라지고 하루 비용 한도가 적용됩니다.</p>:<p className="small muted">고성능 모델도 직접 선택할 수 있습니다. 표시 가격은 USD 기준 100만 토큰당 단가입니다.</p>}
      {selected&&needsTools&&!selected.supports_tools&&<p className="small error" role="alert">이 모델은 자료 처리 검증 전입니다. 웹 검색과 첨부를 끄거나 지원 모델을 선택해 주세요.</p>}
    </>}
  </div>;
}
