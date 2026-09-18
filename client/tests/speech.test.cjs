const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { runInNewContext } = require('node:vm');
const ts = require('typescript');
function setup(response) {
  let recorder, finish, resolveResponse;
  const delivered = [], notices = [], requests = [];
  const track = { stopped: false, stop() { this.stopped = true; } };
  class Recorder {
    static isTypeSupported() { return true; }
    constructor(stream) { this.stream = stream; this.mimeType = 'audio/webm'; recorder = this; }
    start() { this.state = 'recording'; }
    stop() { this.state = 'inactive'; this.ondataavailable({data:new Blob(['audio'])}); finish = this.onstop(); }
  }
  const exports = {};
  runInNewContext(ts.transpileModule(readFileSync('src/lib/use-speech-input.ts','utf8'), {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText, {
    exports, Blob, AbortController, DOMException, Error, MediaRecorder:Recorder,
    navigator:{mediaDevices:{getUserMedia:async()=>({getTracks:()=>[track]})}},
    setTimeout:()=>1, clearTimeout:()=>{},
    fetch: async (url,init) => { requests.push({url,init}); return response ?? new Promise(resolve=>{resolveResponse=resolve}); },
    require(name) {
      if(name==='react') return {useRef:v=>({current:v}),useState:v=>[v,next=>{if(typeof next==='string')notices.push(next)}],useEffect:fn=>{fn()}};
      if(name==='./encode-speech') return {encodeSpeech:async()=>new Blob(['wav'])};
      if(name==='./api') return {api:async()=>({stt_available:true}),apiUrl:p=>p,ensureSession:async()=>({csrf_token:'test'}),responseError:async()=>new Error('전사 오류')};
      throw Error(name);
    },
  });
  const hook=exports.useSpeechInput(text=>{delivered.push(text);hook.dismiss()});
  return {hook,delivered,notices,requests,track,complete:()=>finish,respond:value=>resolveResponse(value)};
}
test('stopping speech delivers the transcript once for immediate chat submission and leaves no success panel',async()=>{
 const s=setup(Response.json({text:'음성 질문'}));await s.hook.start('기존 질문');s.hook.stop();s.hook.stop();await s.complete();
 assert.deepEqual(s.delivered,['기존 질문 음성 질문']);assert.equal(s.requests.length,1);assert.equal(s.notices.at(-1),'');assert.equal(s.track.stopped,true);
});
test('empty or failed transcription never submits a chat message',async()=>{
 for(const response of [Response.json({text:'  '}),Response.json({}, {status:503})]){
  const s=setup(response);await s.hook.start('');s.hook.stop();await s.complete();assert.equal(s.delivered.length,0);assert.ok(s.notices.at(-1));
 }
});
test('closing the voice panel while transcription is pending prevents automatic submission',async()=>{
 const s=setup();await s.hook.start('');s.hook.stop();
 await new Promise(resolve=>setImmediate(resolve));s.hook.dismiss();s.respond(Response.json({text:'취소한 음성'}));await s.complete();
 assert.equal(s.delivered.length,0);assert.equal(s.requests[0].init.signal.aborted,true);assert.equal(s.notices.at(-1),'');
});
