const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { runInNewContext } = require('node:vm');
const ts = require('typescript');
function load(path, extras) {
  const target = {};
  runInNewContext(ts.transpileModule(readFileSync(path,'utf8'), {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,
    {exports:target, process:{env:{}}, Error, Date, JSON, TextDecoder, Headers, FormData, Response, AbortSignal, URL, crypto, setTimeout, ...extras});
  return target;
}
function setup(fetcher, settings={loaded:false}) {
  const calls=[];
  const fetch = async (url, init={}) => { calls.push({url,init}); return fetcher(url,init); };
  const api=load('src/lib/api.ts',{fetch});
  const state={conversationId:null,setConversationId(id){this.conversationId=id},messages:[],streaming:false,add(m){this.messages.push(m)},patch(id,p){Object.assign(this.messages.find(m=>m.id===id),p)},setStreaming(v){this.streaming=v}};
  const modelSettings=load('src/lib/model-settings.ts',{require(name){if(name==='zustand')return {create:()=>{}};if(name==='./api')return api;throw Error(name);}});
  const hook=load('src/lib/use-chat-api.ts',{fetch,require(name){if(name==='react')return {useRef:v=>({current:v}),useEffect:()=>{}};if(name==='./api')return api;if(name==='./model-settings')return {...modelSettings,useModelSettings:{getState:()=>settings}};if(name==='./learning-journeys')return load('src/lib/learning-journeys.ts',{});if(name==='./chat-store')return {useChatStore:{getState:()=>state}};throw Error(name);}}).useChatApi();
  return {calls,state,hook};
}
const result=(status='completed')=>({run_id:'run-1',status,response:'5입니다.',sources:[],selected_model:'test/model',providers:['test']});
function common(url) {
  if(url.endsWith('/v1/me'))return Response.json({id:'guest',csrf_token:'csrf-test'});
  if(url.endsWith('/v1/conversations'))return Response.json({id:'conversation-1'});
}
function stream(events) {return new Response(events.map(([kind,data])=>`event: ${kind}\ndata: ${JSON.stringify({run_id:'run-1',...data})}\n\n`).join(''),{headers:{'Content-Type':'text/event-stream'}})}
test('real-contract stream updates content, verifies saved result, and uses supported mode only',async()=>{
 const {hook,state,calls}=setup((url)=>common(url)|| (url.endsWith('/runs')?stream([['meta',{}],['status',{status:'model'}],['delta',{text:'5입니다.'}],['done',{status:'completed'}]]):Response.json(result())));
 await hook.send('2+3','child');
 assert.equal(state.streaming,false); assert.equal(state.messages[1].content,'5입니다.');assert.equal(state.messages[1].activity.status,'complete');
 const req=calls.find(c=>c.url.endsWith('/runs'));const body=JSON.parse(req.init.body); assert.equal(body.explanation_mode,'simple');assert.equal('model' in body,false);assert.equal('effort' in body,false);assert.equal(req.init.headers['X-CSRF-Token'],'csrf-test');assert.ok(req.init.headers['Idempotency-Key']);
});
test('admission failures remain errors, not fake completions',async()=>{
 const {hook,state}=setup(url=>common(url)||Response.json({code:'BUDGET_EXCEEDED',message:'오늘 한도 초과'},{status:429}));
 await hook.send('질문','student');assert.equal(state.messages[1].activity.status,'error');assert.equal(state.messages[1].error,'오늘 한도 초과');assert.equal(state.streaming,false);
});
test('ambiguous request retries reuse idempotency key and existing conversation',async()=>{
 let attempts=0;const {hook,calls}=setup(url=>{const r=common(url);if(r)return r;if(url.endsWith('/runs')){if(++attempts===1)throw Error('network');return Response.json(result());}return Response.json(result())});
 await hook.send('질문','student');await hook.send('질문','student');const requests=calls.filter(c=>c.url.endsWith('/runs'));assert.equal(requests[0].init.headers['Idempotency-Key'],requests[1].init.headers['Idempotency-Key']);assert.equal(calls.filter(c=>c.url.endsWith('/v1/conversations')).length,1);
});
test('truncated stream recovers stored run without another generation',async()=>{
 const {hook,state,calls}=setup(url=>common(url)||(url.endsWith('/runs')?stream([['meta',{}],['delta',{text:'5'}]]):Response.json(result())));
 await hook.send('질문','student');assert.equal(state.messages[1].content,'5입니다.');assert.equal(calls.filter(c=>c.url.endsWith('/runs')).length,1);
});
test('Stop calls cancellation endpoint and confirms cancelled state',async()=>{
 let controller;const response=new Response(new ReadableStream({start(c){controller=c;c.enqueue(new TextEncoder().encode('event: meta\ndata: {"run_id":"run-1"}\n\n'));}}),{headers:{'Content-Type':'text/event-stream'}});
 const {hook,state,calls}=setup(url=>{const r=common(url);if(r)return r;if(url.endsWith('/cancel')){controller.close();return Response.json(null)}if(url.endsWith('/runs'))return response;return Response.json(result('cancelled'));});
 const pending=hook.send('질문','student');await new Promise(r=>setTimeout(r,10));await hook.stop();await pending;
 assert.ok(calls.some(c=>c.url.endsWith('/cancel')));assert.equal(state.messages[1].activity.status,'stopped');assert.equal(state.streaming,false);
});
test('selected server model and low effort reach the run payload',async()=>{
 const {hook,calls}=setup(url=>common(url)||(url.endsWith('/runs')?Response.json(result()):Response.json(result())),{loaded:true,chosen:true,model:'openai::test/model',effort:1,models:[{provider:'openai',model_id:'test/model',efforts:['minimal','low']}]});
 await hook.send('질문','student');const body=JSON.parse(calls.find(c=>c.url.endsWith('/runs')).init.body);assert.equal(body.routing.mode,'manual');assert.equal(body.routing.provider,'openai');assert.equal(body.routing.model_id,'test/model');assert.equal('model' in body,false);assert.equal(body.reasoning_effort,'low');
});

test('free routing and attachments keep the existing backend contract and cross-origin credentials',async()=>{
 const {hook,calls,state}=setup(url=>common(url)||Response.json(result()),{loaded:true,chosen:true,model:'free',effort:0,models:[]});
 state.setConversationId('existing');
 await hook.send('첨부 질문','student',{attachment_ids:['attachment-1'],search_enabled:true});
 const request=calls.find(c=>c.url.endsWith('/runs'));const body=JSON.parse(request.init.body);
 assert.equal(body.routing.mode,'free');assert.equal(body.attachment_ids[0],'attachment-1');assert.equal(body.search_enabled,true);assert.equal(request.init.credentials,'include');assert.equal(request.url,'/v1/conversations/existing/runs');
 assert.equal(calls.filter(c=>c.url.endsWith('/v1/conversations')).length,0);
});
test('unavailable explicit selection never silently switches to auto',async()=>{
 const {hook,calls,state}=setup(url=>common(url)||Response.json(result()),{loaded:false,chosen:true,model:'openai::missing',effort:0,models:[]});
 await hook.send('질문','student');assert.equal(calls.filter(c=>c.url.endsWith('/runs')).length,0);assert.equal(state.messages[1].activity.status,'error');
});
test('Korean TTS chooses Korean voice instead of a default foreign language',async()=>{
 const {koreanVoice}=load('src/lib/use-speech-output.ts',{clearTimeout,require:()=>({})});
 const ko={lang:'ko-KR',name:'Korean'};
 assert.equal(await koreanVoice({getVoices:()=>[{lang:'en-US'},ko]}),ko);
});
test('Korean TTS waits for voiceschanged before choosing the Korean voice',async()=>{
 const {koreanVoice}=load('src/lib/use-speech-output.ts',{clearTimeout,require:()=>({})});
 let voices=[],listener,removed=false;const ko={lang:'ko-KR'};
 const waiting=koreanVoice({getVoices:()=>voices,addEventListener:(_,fn)=>listener=fn,removeEventListener:()=>removed=true});
 voices=[ko];listener();assert.equal(await waiting,ko);assert.ok(removed);
});

for (const [label, options, expected] of [
  ['default automatic', {}, null],
  ['explicit automatic', {search_enabled:null}, null],
  ['always', {search_enabled:true}, true],
  ['off', {search_enabled:false}, false],
]) {
  test(`web lookup mode ${label} reaches the server without losing false or null`, async()=>{
    const {hook,calls}=setup(url=>common(url)||Response.json(result()));
    await hook.send('현재 소식','student',options);
    assert.equal(JSON.parse(calls.find(c=>c.url.endsWith('/runs')).init.body).search_enabled,expected);
  });
}

test('a text model without native tools can send document attachments and web lookup together',async()=>{
  const {hook,calls,state}=setup(url=>common(url)||Response.json(result()),{
    loaded:true,chosen:true,model:'upstage::text-model',effort:0,
    models:[{provider:'upstage',model_id:'text-model',supports_tools:false,efforts:[]}],
  });
  await hook.send('첨부한 보고서와 최신 발표를 비교해 주세요','student',{
    attachment_ids:['report-docx','scan-pdf'],search_enabled:true,
  });
  const body=JSON.parse(calls.find(c=>c.url.endsWith('/runs')).init.body);
  assert.deepEqual(body.routing,{mode:'manual',provider:'upstage',model_id:'text-model'});
  assert.deepEqual(body.attachment_ids,['report-docx','scan-pdf']);
  assert.equal(body.search_enabled,true);
  assert.equal(state.messages[1].activity.status,'complete');
});

test('learning context and attachments preserve routing and the visible question', async () => {
 const {hook,state,calls}=setup(url=>common(url)||Response.json(result()));
 const files=[{id:'file-1',filename:'lesson.pdf',status:'ready'}];
 await hook.send('내 문제로 복습','student',{attachments:files,attachment_ids:['file-1'],learning_context:'풀이를 확인하고 힌트를 주세요.',search_enabled:true});
 const body=JSON.parse(calls.find(c=>c.url.endsWith('/runs')).init.body);
 assert.equal(state.messages[0].content,'내 문제로 복습');assert.equal(state.messages[0].attachments[0].id,'file-1');
 assert.match(body.message,/자기주도 학습 코치/);assert.match(body.message,/풀이를 확인하고 힌트/);
 assert.deepEqual(body.attachment_ids,['file-1']);assert.equal(body.search_enabled,true);
});
