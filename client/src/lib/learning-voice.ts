import { learningTopics, getLearningTopics, learningPrompt } from './learning-topics';
export type LearningView = { open: boolean; topicId: string | null; practice?: boolean };
type VoiceChoice = { type: 'open' | 'back' | 'practice' } | { type: 'topic'; topicId: string } | { type: 'activity'; prompt: string; title: string };
const aliases: Record<string, RegExp[]> = {
 ai: [/질문|프롬프트/, /글.*(다듬|고치)|문장.*(수정|고치)/, /이미지|그림/, /ai.*(확인|검증)|답변.*(확인|검증)/],
 phone: [/설정|글자.*크기|소리.*조절/, /사진.*(보내|전송|공유)/, /지도|길.*찾/, /앱.*(설치|정리|삭제)/],
 daily: [/카페|커피|음료/, /식당|음식.*주문/, /교통|기차|버스|예매/, /온라인.*신청|신청서/],
 safety: [/수상한.*문자|스미싱|피싱/, /계정|비밀번호/, /개인정보/, /가짜.*정보|가짜.*뉴스/],
 documents: [/안내문/, /표.*읽|표.*보는/, /발표/, /파일.*정리|폴더/],
 learning: [/어디서부터|뭐부터/, /학습.*계획|공부.*계획/, /복습/, /평생교육|이용권/],
};
export function resolveLearningVoice(utterance: string, view: LearningView, mode?: 'senior' | 'child' | 'student'): VoiceChoice | null {
 const topics = mode ? getLearningTopics(mode) : learningTopics;
 const text=utterance.replace(/\s+/g,'').toLowerCase();
 if (/(?:배움터|호기심교실|학습스튜디오).*(열|켜|시작|들어)/.test(text)) return {type:'open'};
 if (!view.open || /싫|말고|않|아니/.test(text)) return null;
 if (mode && (/이어|실습시작/.test(text) || text.includes({ senior: '주문연습', child: 'ai탐정', student: '오답복습' }[mode]))) return { type: 'practice' };
 if (/전체주제|처음으로|뒤로/.test(text)) return {type:'back'};
 const topic=topics.find(t=>t.id===view.topicId);
 const ordinal=text.match(/^(?:제)?([1-7]|첫|두|세|네|다섯|여섯|일곱)(?:번째|번)(?:거|것|으로|할래|해줘|선택|하고싶어|요|주세요|할게|\.|!)*$/);
 if (ordinal) {
  const n=/^[1-7]$/.test(ordinal[1])?Number(ordinal[1])-1:['첫','두','세','네','다섯','여섯','일곱'].indexOf(ordinal[1]);
  if(topic) return topic.activities[n] ? {type:'activity',prompt:learningPrompt(topic.activities[n].prompt),title:topic.activities[n].title} : null;
  if (mode && n === 0) return { type: 'practice' };
  const item = topics[mode ? n - 1 : n];
  return item ? {type:'topic',topicId:item.id} : null;
 }
 const candidates=topic?[topic,...topics.filter(t=>t.id!==topic.id)]:topics;
 for(const item of candidates) {
  const matches=item.activities.filter((activity,index)=>text.includes(activity.title.replace(/\s+/g,'').toLowerCase()) || aliases[item.id]?.[index]?.test(text));
  if(matches.length===1) return {type:'activity',prompt:learningPrompt(matches[0].prompt),title:matches[0].title};
  if(matches.length>1) return {type:'topic',topicId:item.id};
 }
 const intent: Record<string, RegExp> = { explore: /궁금|탐험|관찰/, story: /이야기|동화|결말/, detect: /확인|설명/, study: /공부|문제|복습|개념/, project: /탐구|발표|자료/, literacy: /질문|출처|프롬프트/ };
 if (mode && mode !== 'senior') { const found = topics.find(t => intent[t.id]?.test(text)); if (found) return { type: 'topic', topicId: found.id }; }
 const broad=[/AI|인공지능/i,/스마트폰|휴대폰/,/키오스크|생활/,/안전|보안/,/문서|자료/,/배움|학습|공부/];
 const match=topics.find((t,i)=>text.includes(t.title.replace(/\s+/g,'').toLowerCase())||(!mode || mode === 'senior') && broad[i]?.test(text));
 return match?{type:'topic',topicId:match.id}:null;
}
