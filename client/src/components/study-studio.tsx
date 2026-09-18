'use client';
import { useEffect, useRef, useState } from 'react';
import { ArrowLeft, ArrowUpRight, Check, Download, RotateCcw } from 'lucide-react';
import { motion } from 'motion/react';
import type { useStudyStudio } from '@/lib/use-study-studio';

type Studio = ReturnType<typeof useStudyStudio>;
export function StudyStudio({studio, disabled, guest, onCoach}: {studio:Studio;disabled:boolean;guest:boolean;onCoach:()=>Promise<void>}) {
  const {catalog,selected,task,step} = studio;
  const [confirm, setConfirm] = useState(false);
  const heading = useRef<HTMLHeadingElement>(null);
  const blocked = disabled || studio.busy;
  useEffect(() => { heading.current?.focus({preventScroll:true}); setConfirm(false); }, [selected?.id,selected?.step,selected?.complete,studio.topic]);
  function download(content = selected?.result) {
    if (!content) return;
    const url = URL.createObjectURL(new Blob([content], {type:'text/markdown;charset=utf-8'}));
    const link = document.createElement('a'); link.href = url; link.download = `${task?.id || 'study'}-note.md`; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  return <section className="study-studio" aria-label="학습 스튜디오 활동">
    <div className="study-heading">
      {(selected || studio.topic) && <button type="button" className="study-back" disabled={blocked} onClick={() => selected ? void studio.back() : studio.setTopic(null)}><ArrowLeft size={16}/>{selected ? '활동 목록' : '전체 활동'}</button>}
      <h1 ref={heading} tabIndex={-1}>{task?.title || catalog?.topics.find(item => item.id === studio.topic)?.title || '학습 스튜디오'}</h1>
      {!selected && <p>예제로 익히고 내 생각을 기록해 보세요. 저장한 활동은 이어서 할 수 있어요.</p>}
    </div>
    {studio.error && <div className="study-error" role="alert">{studio.error}{!catalog && <button type="button" disabled={blocked} onClick={() => void studio.load()}>다시 불러오기</button>}</div>}
    <p className="study-status" role="status">{studio.busy ? '학습 기록을 확인하고 있어요.' : studio.notice}</p>
    {!catalog && !studio.error && <p>학습 자료를 불러오고 있어요.</p>}
    {catalog && !selected && <>
      {!studio.topic && <>
        {studio.sessions.find(item => !item.complete) && (() => { const recent = studio.sessions.find(item => !item.complete)!; const activity = catalog.tasks.find(item => item.id === recent.task_id); return activity ? <button type="button" className="study-resume" disabled={blocked} onClick={() => void studio.start(activity.id)}><span><small>최근 학습 이어 하기</small><strong>{activity.title}</strong><span>{recent.step} / {activity.steps.length}단계 완료</span></span><ArrowUpRight size={20}/></button> : null; })()}
        <nav className="study-topics" aria-label="학습 분야">{catalog.topics.map(item => <button type="button" key={item.id} disabled={blocked} onClick={() => studio.setTopic(item.id)}>{item.title}<ArrowUpRight size={16}/></button>)}</nav>
      </>}
      <div className="study-task-list">{catalog.tasks.filter(item => !studio.topic || item.topic_id === studio.topic).map(item => {
        const record = studio.sessions.find(session => session.task_id === item.id);
        return <button type="button" className="study-task" key={item.id} disabled={blocked} onClick={() => void studio.start(item.id)}>
          <span><strong>{item.title}</strong><span>{item.summary}</span></span>
          <span className="study-task-state">{record?.complete ? <><Check size={15}/>완료</> : record ? `이어 하기 ${record.step}/${item.steps.length}` : `${item.minutes}분`}<ArrowUpRight size={16}/></span>
        </button>;
      })}</div>
      <p className="study-footnote">{guest ? '게스트 기록은 현재 브라우저의 세션으로 저장됩니다. 쿠키를 지우면 다시 불러올 수 없어요.' : '학습 기록은 현재 계정에 저장됩니다.'}</p>
    </>}
    {selected && task && <motion.div key={`${selected.id}-${selected.step}`} initial={{opacity:0,y:4}} animate={{opacity:1,y:0}} className="study-lesson">
      <div className="study-progress"><progress value={selected.step} max={task.steps.length} aria-label="활동 진행률"/><span>{selected.step} / {task.steps.length}단계 완료</span></div>
      {selected.feedback && <p className={`study-feedback is-${selected.feedback.kind}`} role="status">{selected.feedback.message}</p>}
      {step ? <>
        <h2>{step.title}</h2><p className="study-body">{step.body}</p>
        <form onSubmit={event => {event.preventDefault();void studio.change('answer');}}>
          <h3 id="study-question">{step.prompt}</h3>
          {step.kind === 'choice' ? <div className="study-choices" role="group" aria-labelledby="study-question">{step.options?.map((option,index) => <button type="button" key={option} disabled={blocked} onClick={() => void studio.change('answer',option)}><span>{index+1}</span>{option}</button>)}</div> : <>
            <details className="study-example"><summary>작성 예시 보기</summary><p>{step.example}</p></details>
            <textarea aria-labelledby="study-question" value={studio.draft} onChange={event=>studio.setDraft(event.target.value)} disabled={blocked} maxLength={3000} rows={5} placeholder="내 생각을 10자 이상 적어 주세요."/>
            <div className="study-writing-note"><span>다음 단계로 넘어가면 답안이 저장됩니다.</span><span>{studio.draft.length} / 3,000</span></div>
          </>}
          <div className="study-actions">
            <button type="button" disabled={blocked} onClick={()=>void studio.change('hint')}>힌트 보기</button>
            {step.kind === 'text' && <><button type="button" disabled={blocked || studio.draft === selected.draft} onClick={()=>void studio.change('draft')}>답안 저장</button><button className="study-primary" type="submit" disabled={blocked || studio.draft.trim().length < 10}>{selected.step === task.steps.length-1 ? '저장하고 마치기' : '저장하고 다음'}</button></>}
          </div>
        </form>
      </> : <>
        <div className="study-complete"><Check size={24}/><h2>활동을 마쳤어요</h2><p>{task.outcome}를 저장했습니다. 작성형 답안은 내 기록이며, AI 코치에게 검토를 부탁할 수 있어요.</p></div>
        <div className="study-result">{selected.answers.map((item,index)=><section key={index}><h3>{item.title}</h3><p>{item.answer}</p></section>)}</div>
        <div className="study-actions"><button type="button" onClick={() => download()}><Download size={16}/>노트 내려받기</button><button type="button" disabled={blocked} onClick={()=>void studio.change('restart','')}><RotateCcw size={16}/>다시 연습</button></div>
      </>}
      {!selected.complete && selected.previous_result && <button type="button" className="study-back" onClick={()=>download(selected.previous_result)}><Download size={16}/>이전 완료 노트 내려받기</button>}
      <div className="study-coach"><div><strong>AI 코치와 이어서</strong><p>이 활동과 저장한 답안을 바탕으로 질문해요. 내 문제나 자료도 대화에 첨부할 수 있어요.</p></div><button type="button" disabled={blocked} onClick={()=>void onCoach()}>코치 대화 열기<ArrowUpRight size={16}/></button></div>
      <div className="study-record"><span>{selected.completions > 0 ? `${selected.completions}회 완료` : '진행 중'} / 기록은 서버에 저장됩니다.</span><button type="button" disabled={blocked} onClick={()=>setConfirm(true)}>기록 지우기</button></div>
      {confirm && <div className="study-delete" role="group" aria-label="학습 기록 삭제 확인"><p>이 활동의 답안과 완료 기록을 지울까요? 코치 대화는 남습니다.</p><button type="button" disabled={blocked} onClick={()=>setConfirm(false)}>취소</button><button type="button" disabled={blocked} onClick={()=>void studio.remove()}>기록 삭제</button></div>}
    </motion.div>}
  </section>;
}
