const { test } = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { runInNewContext } = require('node:vm');
const ts = require('typescript');
function setup() {
  const listeners = new Map(); const received = []; const states = []; const cleanups = [];
  const local = new Map(); const child = {};
  const element = {contains: node => node === child, addEventListener:(name,fn)=>local.set(name,fn),removeEventListener:name=>local.delete(name)};
  const target = {};
  runInNewContext(ts.transpileModule(readFileSync('src/lib/use-file-drop.ts', 'utf8'), {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText, {
    exports: target,
    window: {addEventListener:(name,fn)=>listeners.set(name,fn),removeEventListener:name=>listeners.delete(name)},
    require:()=>({useRef:value=>({current:value}),useState:()=>[false,value=>states.push(value)],useEffect:fn=>{const cleanup=fn();if(cleanup)cleanups.push(cleanup)}}),
  });
  target.useFileDrop({current:element}, files=>received.push(files));
  function emit(name, props={}, outside=false) {
    const event={type:name,target:outside?{}:child,stopPropagation(){this.stopped=true},dataTransfer:{types:['Files'],files:[{name:'sample.pdf'}]},relatedTarget:child,preventDefault(){this.prevented=true},...props};
    (outside ? listeners : local).get(name)?.(event); return event;
  }
  return {emit,received,states,listeners,cleanup:()=>cleanups.forEach(fn=>fn())};
}
test('composer drop attaches once and clears its highlight',()=>{
  const s=setup();s.emit('dragenter');s.emit('dragenter');s.emit('dragleave');
  assert.equal(s.states.at(-1),true);
  assert.equal(s.emit('dragover').dataTransfer.dropEffect,'copy');
  assert.equal(s.emit('drop').prevented,true);
  assert.equal(s.received.length,1);assert.equal(s.received[0][0].name,'sample.pdf');assert.equal(s.states.at(-1),false);
  s.cleanup();assert.equal(s.listeners.size,0);
});
test('text drags are untouched; leaving the window and Escape clear file hints',()=>{
  const s=setup();assert.equal(s.emit('drop',{dataTransfer:{types:['text/plain'],files:[]}}).prevented,undefined);assert.equal(s.received.length,0);
  s.emit('dragenter');s.emit('dragleave',{relatedTarget:null});assert.equal(s.states.at(-1),false);
  s.emit('dragenter');s.emit('keydown',{key:'Escape'},true);assert.equal(s.states.at(-1),false);
});
test('outside file drops prevent navigation without uploading',()=>{
  const s=setup();assert.equal(s.emit('dragover',{},true).dataTransfer.dropEffect,'none');assert.equal(s.emit('drop',{},true).prevented,true);assert.equal(s.received.length,0);
});
test('file items work when a drag source omits the Files type',()=>{
 const s=setup();s.emit('drop',{dataTransfer:{types:[],files:[],items:[{kind:'file',getAsFile:()=>({name:'photo.png'})}]}});assert.equal(s.received.length,1);assert.equal(s.received[0][0].name,'photo.png');
});
