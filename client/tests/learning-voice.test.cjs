const {test}=require('node:test');
const assert=require('node:assert/strict');
const {readFileSync}=require('node:fs');
const {runInNewContext}=require('node:vm');
const ts=require('typescript');
function load(file,deps={}){const exports={};runInNewContext(ts.transpileModule(readFileSync(file,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText,{exports,require:name=>deps[name]});return exports;}
const topics=load('src/lib/learning-topics.ts');
const {resolveLearningVoice:resolve}=load('src/lib/learning-voice.ts',{'./learning-topics':topics});
const open={open:true,topicId:null};
test('voice topic and exercise selections use the same prompts as buttons',()=>{
 assert.equal(resolve('스마트폰 배우고 싶어',open).topicId,'phone');
 assert.equal(resolve('사진 보내는 법 알려줘',{open:true,topicId:'phone'}).prompt,topics.learningPrompt(topics.learningTopics[1].activities[1].prompt));
 assert.equal(resolve('카페에서 커피 주문하고 싶어요',open).type,'activity');
 assert.equal(resolve('키오스크 연습하고 싶어',open).topicId,'daily');
});
test('spoken order follows the currently visible list and checks bounds',()=>{
 assert.equal(resolve('두 번째 거',open).topicId,'phone');
 assert.equal(resolve('두 번째 거',{open:true,topicId:'phone'}).prompt,topics.learningPrompt(topics.learningTopics[1].activities[1].prompt));
 assert.equal(resolve('여섯 번째 거',{open:true,topicId:'phone'}),null);
});
test('closed panel and negative requests do not select exercises; open and back commands work',()=>{
 assert.equal(resolve('사진 보내고 싶어',{open:false,topicId:null}),null);
 assert.equal(resolve('사진 보내기 말고',open),null);
 assert.equal(resolve('오늘 날씨 알려줘',open),null);
 assert.equal(resolve('AI 디지털 배움터 열어줘',{open:false,topicId:null}).type,'open');
 assert.equal(resolve('전체 주제로 돌아가줘',open).type,'back');
});
