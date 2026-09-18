'use client';

import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react';
import { animate, motion, useMotionValue, useReducedMotion } from 'motion/react';
import { Collapsible } from '@base-ui/react/collapsible';
import { ArrowUpRight, ArrowLeft, BookOpen, ChevronDown, ChevronRight, MessageCircle, Smartphone, Sprout, ShieldCheck, FileText, Coffee } from 'lucide-react';
import type { LearningView } from '@/lib/learning-voice';
import { getLearningTopics, learningPrompt } from '@/lib/learning-topics';
import type { Mode } from '@/lib/chat-store';
import { learningSpaces, practiceSteps, type Practice } from '@/lib/learning-journeys';
import { GlassSurface } from './glass-surface';

const brands = [
  { name: '서울특별시', file: 'seoul.png', kind: '행사 참여', className: 'brand-seoul' },
  { name: 'AI 디지털배움터', file: 'digital-learning.png', kind: '학습 서비스', className: 'brand-learning' },
  { name: '평생교육이용권', file: 'lifelong-voucher.svg', kind: '평생학습 서비스', className: 'brand-voucher' },
  { name: 'Upstage', file: 'upstage.avif', kind: 'AI 모델 개발사', className: 'brand-upstage' },
  { name: '에이닷', file: 'adot.svg', kind: 'AI 서비스', className: 'brand-adot', label: '에이닷' },
  { name: 'LG AI Research', file: 'lg-ai-research.png', kind: 'AI 연구기관', className: 'brand-lg' },
  { name: 'EXAONE', file: 'exaone.png', kind: 'AI 모델', className: 'brand-exaone', label: 'EXAONE' },
  { name: 'SpaceXAI', file: 'spacexai.svg', kind: '행사 크레딧 지원', className: 'brand-spacexai' },
  { name: 'Cursor', file: 'cursor.svg', kind: '행사 지원 도구', className: 'brand-cursor' },
];

function BrandRibbon() {
  const reduced = useReducedMotion();
  const [hovered, setHovered] = useState(false);
  const x = useMotionValue('0%');
  const playback = useRef<ReturnType<typeof animate> | null>(null);
  useEffect(() => {
    if (reduced) { x.set('0%'); return; }
    playback.current = animate(x, ['0%', '-50%'], { duration: 81, ease: 'linear', repeat: Infinity });
    return () => { playback.current?.stop(); };
  }, [reduced, x]);
  useEffect(() => {
    if (hovered) playback.current?.pause();
    else playback.current?.play();
  }, [hovered, reduced]);
  return <div className="brand-ribbon" onMouseEnter={() => setHovered(true)} onMouseLeave={() => setHovered(false)}>
    <div className="brand-window">
      <motion.div className="brand-track" style={{ x }}>
        {[0, 1].map(copy => <div key={copy} className="brand-group" aria-hidden={copy === 1 ? true : undefined}>
          {brands.map(brand => <div className={`brand-item ${brand.className}`} key={brand.name} title={`${brand.name} / ${brand.kind}`}>
            {/* Official brand assets are served locally without altering their geometry. */}
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={`/brands/${brand.file}`} alt={copy ? '' : `${brand.name} / ${brand.kind}`} />
            {brand.label && <span aria-hidden="true">{brand.label}</span>}
          </div>)}
        </div>)}
      </motion.div>
    </div>
  </div>;
}

const topicIcons = [MessageCircle, Smartphone, Coffee, ShieldCheck, FileText, Sprout];

export function LearningHeader({ onChoose, disabled = false, view, onViewChange, mode, progress, onPracticeChoice, onRestart, onClear, ready, navigation, studentContent }: {
  onChoose: (prompt: string, label: string) => void; disabled?: boolean; view: LearningView; onViewChange: (view: LearningView) => void;
  mode: Mode; progress: Practice; onPracticeChoice: (index: number) => void; onRestart: () => void; onClear: () => void; ready: boolean; navigation?: ReactNode; studentContent?: ReactNode;
}) {
  const { open, topicId } = view;
  const space = learningSpaces[mode];
  const topics = getLearningTopics(mode);
  const setOpen = (open: boolean) => onViewChange({ ...view, open });
  const setTopicId = (topicId: string | null) => onViewChange({ open: true, topicId, practice: false });
  const topic = topics.find(item => item.id === topicId);
  const step = practiceSteps[mode][progress.step];
  const heading = useRef<HTMLHeadingElement>(null);
  const header = useRef<HTMLDivElement>(null);
  useLayoutEffect(() => {
    const element = header.current;
    if (!element) return;
    const host = element.parentElement;
    const slot = element.querySelector<HTMLElement>('.header-ribbon-slot');
    const ribbon = host?.querySelector<HTMLElement>('.brand-ribbon');
    if (!host || !slot || !ribbon) return;
    const measure = () => {
      const bounds = slot.getBoundingClientRect();
      const values = {
        '--site-header-height': element.getBoundingClientRect().height,
        '--ribbon-top': bounds.top,
        '--ribbon-left': bounds.left,
        '--ribbon-width': bounds.width,
        '--ribbon-height': ribbon.getBoundingClientRect().height,
      };
      for (const [property, value] of Object.entries(values)) {
        const pixels = `${value}px`;
        if (host.style.getPropertyValue(property) !== pixels) host.style.setProperty(property, pixels);
      }
    };
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    observer.observe(slot);
    observer.observe(ribbon);
    measure();
    return () => observer.disconnect();
  }, []);
  useEffect(() => {
    if (!open) return;
    // The fixed learning trigger remains usable from anywhere in a long chat.
    const frame = requestAnimationFrame(() => window.scrollTo({ top: 0, behavior: 'instant' }));
    return () => cancelAnimationFrame(frame);
  }, [open]);
  useEffect(() => { if (open) heading.current?.focus({ preventScroll: true }); }, [topicId, open, view.practice, progress.step, mode]);
  const choose = (prompt: string, label: string) => { if (!disabled) { onChoose(learningPrompt(prompt), label); setOpen(false); } };
  return <Collapsible.Root open={open} onOpenChange={setOpen} className="learning-header">
    <header className="site-header">
      <div ref={header} className="header-controls">
      <span className="wordmark">modurouter</span>
      {navigation}
      <div className="header-ribbon-slot" aria-hidden="true" />
      <Collapsible.Trigger className="learning-trigger glass">
        <GlassSurface radius={24} />
        <BookOpen size={18} /><span>{space.title}</span><ChevronDown className={open ? 'is-open' : ''} size={15} />
      </Collapsible.Trigger>
      </div>
      <BrandRibbon />
    </header>
    <Collapsible.Panel className="learning-panel">
      {mode === 'student' ? studentContent : <>
      <div className="learning-heading">
        {(topic || view.practice) && <button type="button" className="learning-back" onClick={() => setTopicId(null)} aria-label="전체 활동으로 돌아가기"><ArrowLeft size={16} />전체 활동</button>}
        <h1 ref={heading} tabIndex={-1}>{view.practice ? space.activity : topic ? topic.title : space.title}</h1>
      </div>
      {view.practice ? <motion.div key={`${mode}-${progress.step}-${progress.complete}`} initial={{ opacity: 0, y: 5 }} animate={{ opacity: 1, y: 0 }} className="practice-card glass">
        <GlassSurface radius={26} />
        <div className="practice-content">
          {progress.complete ? <>
            <span className="practice-eyebrow">완료</span>
            <h2>{mode === 'senior' ? '주문 연습을 마쳤어요' : mode === 'child' ? '근거를 찾았어요!' : '다시 풀어냈어요'}</h2>
            <p>{mode === 'senior' ? progress.answers.slice(0, 3).join(' / ') : mode === 'child' ? 'AI의 말도 근거와 비교해요.' : '괄호 안의 모든 항에 곱해요.'}</p>
            <div className="practice-actions"><button type="button" onClick={onRestart}>다시 연습</button><button type="button" onClick={() => setTopicId(null)}>다른 활동</button></div>
          </> : <>
            <span className="practice-eyebrow">{progress.step + 1} / {practiceSteps[mode].length}</span>
            <h2>{step.title}</h2>
            {step.detail && <p>{step.detail}</p>}
            {mode === 'senior' && progress.step === 3 && <p className="practice-receipt">{progress.answers.join(' / ')}</p>}
            <div className="practice-choices">{step.choices.map((choice, index) => <button type="button" key={choice.label} onClick={() => onPracticeChoice(index)} disabled={disabled || !ready}>{choice.label}</button>)}</div>
            {progress.hint && <p className="practice-hint" role="status">{step.hint}</p>}
          </>}

        </div>
      </motion.div> : <>
        {!topic && <button type="button" className="practice-feature glass" disabled={!ready} onClick={() => onViewChange({ open: true, topicId: null, practice: true })}>
          <GlassSurface radius={24} tone="accent" />
          <span className="practice-feature-copy"><strong>{space.activity}</strong><span>{progress.complete ? '완료한 연습' : progress.step > 0 ? '이어 하기' : space.cue}</span></span><ArrowUpRight size={23} />
        </button>}
        <motion.div key={`${mode}-${topic?.id || 'topics'}`} initial={{ opacity: 0, y: 6 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: .18 }} className="learning-branches">
          {topic ? topic.activities.map(activity => <button type="button" key={activity.title} className="learning-branch glass" disabled={disabled} onClick={() => choose(activity.prompt, activity.title)}>
            <GlassSurface radius={22} /><strong>{activity.title}</strong><ArrowUpRight size={18} />
          </button>) : topics.map((item, index) => { const Icon = mode === 'senior' ? topicIcons[index] : [Sprout, FileText, MessageCircle][index]; return <button type="button" key={item.id} className="learning-branch learning-topic glass" onClick={() => setTopicId(item.id)}>
            <GlassSurface radius={22} /><Icon size={22} strokeWidth={1.5} /><strong>{item.title}</strong><ChevronRight size={17} />
          </button>; })}
        </motion.div>
      </>}
      {progress.completions > 0 && <div className="learning-record"><span>{space.activity} / {progress.completions}회 완료</span><button type="button" onClick={onClear}>기록 지우기</button></div>}
      {mode === 'senior' && <div className="learning-links"><a href="https://www.xn--2z1bw8k1pjz5ccumkb.kr/main.do" target="_blank" rel="noopener noreferrer">교육 찾기 <ArrowUpRight size={13} /></a><a href="https://www.lllcard.kr/" target="_blank" rel="noopener noreferrer">평생교육이용권 <ArrowUpRight size={13} /></a></div>}
      </>}
    </Collapsible.Panel>
  </Collapsible.Root>;
}
