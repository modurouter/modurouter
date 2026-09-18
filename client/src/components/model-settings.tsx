'use client';

import { Popover } from '@base-ui/react/popover';
import { Radio } from '@base-ui/react/radio';
import { RadioGroup } from '@base-ui/react/radio-group';
import { Slider } from '@base-ui/react/slider';
import { SlidersHorizontal, X } from 'lucide-react';
import { motion } from 'motion/react';
import { GlassSurface } from './glass-surface';
import { effortOptions, useModelSettings } from '@/lib/model-settings';

export function ModelSettings() {
  const { model, models, effort, setModel, setEffort, load, loading, error, loaded } = useModelSettings();
  const selected = models.find(option => option.id === model);
  const modelOptions = [{ id: 'auto', name: '자동 선택', providers: ['가격 우선'] }, ...models];
  const supported = model === 'auto' ? [...new Set(models.flatMap(option => option.efforts))] : selected?.efforts || [];
  const adjustable = loaded && supported.length > 1;
  const spring = { type: 'spring' as const, stiffness: 420, damping: 34 };

  return <Popover.Root onOpenChange={open => { if (open) void load(); }}>
    <Popover.Trigger className="settings-trigger" aria-label="모델 및 thinking effort 설정" title={selected?.name || "자동 선택"}>
      <GlassSurface radius={21} />
      <SlidersHorizontal size={21} strokeWidth={1.6} />
    </Popover.Trigger>
    <Popover.Portal>
      <Popover.Positioner className="settings-positioner" side="top" align="end" sideOffset={16} collisionPadding={18}>
        <Popover.Popup className="settings-popup">
          <GlassSurface radius={28} />
          <div className="settings-content">
            <div className="settings-heading">
              <Popover.Title>대화 설정</Popover.Title>
              <Popover.Close className="settings-close" aria-label="설정 닫기"><X size={18} strokeWidth={1.7} /></Popover.Close>
            </div>
            <section className="model-section" aria-labelledby="model-list-label">
              <h3 id="model-list-label" className="sr-only">모델</h3>
              <RadioGroup value={model} onValueChange={setModel} className="model-options" aria-labelledby="model-list-label">
                {modelOptions.map((option) => <Radio.Root key={option.id} value={option.id}  className="model-option">
                  <span className="model-option-copy"><span>{option.name}</span><small>{option.providers.join(' · ')}</small></span>
                </Radio.Root>)}
              </RadioGroup>
            </section>
            {loading && <p className="settings-api-note" role="status">모델 목록을 불러오는 중…</p>}
            {error && <p className="settings-api-note" role="status">{error} <button onClick={() => void load()}>다시 시도</button></p>}
            <Slider.Root disabled={!adjustable} min={0} max={1} step={1} largeStep={1} value={effort} onValueChange={setEffort} className="effort-slider" thumbAlignment="edge">
              <div className="effort-heading"><Slider.Label>Thinking effort</Slider.Label><span className="effort-current" aria-hidden="true">{supported.length ? effortOptions[effort].label : '미지원'}</span></div>
              <Slider.Control className="effort-control">
                <Slider.Track className="effort-track">
                  <GlassSurface radius={12} />
                  <Slider.Indicator className="effort-indicator" render={<motion.div layout transition={spring} />} />
                  <Slider.Thumb render={<motion.div layout="position" transition={spring} />} className="effort-thumb" aria-valuetext={effortOptions[effort].label}>
                    <GlassSurface radius={18} />
                    <span className="thumb-grip" aria-hidden="true"><i /><i /></span>
                  </Slider.Thumb>
                </Slider.Track>
              </Slider.Control>
              <div className="effort-labels" aria-hidden="true">{effortOptions.map((option) => <span key={option.id}>{option.label}</span>)}</div>
            </Slider.Root>
          </div>
        </Popover.Popup>
      </Popover.Positioner>
    </Popover.Portal>
  </Popover.Root>;
}
