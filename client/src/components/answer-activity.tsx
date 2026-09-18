'use client';

import { useEffect, useState } from 'react';
import { Collapsible } from '@base-ui/react/collapsible';
import { ChevronRight } from 'lucide-react';
import type { Message } from '@/lib/chat-store';

export function AnswerActivity({ message }: { message: Message }) {
  const activity = message.activity;
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (activity?.status !== 'writing') return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [activity?.status]);
  if (!activity) return null;
  const seconds = Math.max(0, Math.round(((activity.finishedAt ?? now) - activity.startedAt) / 1000));
  const label = activity.status === 'writing' ? `${activity.stage || '답변 준비 중'} · ${seconds}초` : activity.status === 'stopped' ? `응답 중지 · ${seconds}초` : activity.status === 'error' ? `응답 오류 · ${seconds}초` : `${seconds < 1 ? '1초 미만' : `${seconds}초`} 동안 처리`;
  return <Collapsible.Root className="answer-activity">
    <Collapsible.Trigger className="activity-trigger">
      <span>{label}</span><ChevronRight size={14} className="activity-chevron" />
    </Collapsible.Trigger>
    <Collapsible.Panel className="activity-panel">
      {activity.events?.map((event, i) => <p key={i}>{event}</p>)}
      {message.run?.selected_model && <p>사용 모델: {message.run.selected_model}</p>}
      {!!message.run?.providers?.length && <p>제공자: {message.run.providers.join(', ')}</p>}
      {message.run?.context_truncated && <p>입력 한도에 맞춰 이전 대화나 자료 일부를 제외했어요.</p>}
      {activity.status === 'stopped' && <p>답변 생성을 중지했어요.</p>}
    </Collapsible.Panel>
  </Collapsible.Root>;
}
