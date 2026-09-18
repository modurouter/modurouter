'use client';

import { Select } from '@base-ui/react/select';
import { Check, ChevronDown, Globe } from 'lucide-react';
import { GlassSurface } from './glass-surface';

const options = [
  { value: 'auto', label: '웹 검색 자동' },
  { value: 'on', label: '웹 검색 항상' },
  { value: 'off', label: '웹 검색 끄기' },
];

export function SearchMode({ value, onChange, disabled }: { value: boolean | null; onChange: (value: boolean | null) => void; disabled: boolean }) {
  return <Select.Root items={options} value={value === null ? 'auto' : value ? 'on' : 'off'} disabled={disabled} onValueChange={next => {
    if (next !== null) onChange(next === 'auto' ? null : next === 'on');
  }}>
    <Select.Trigger className="composer-tool search-mode" aria-label="웹 검색 모드" title="자동 모드에서는 질문에 따라 웹 자료를 확인합니다.">
      <GlassSurface radius={18} /><Globe size={16} aria-hidden="true" />
      <Select.Value /><Select.Icon className="search-mode-chevron"><ChevronDown size={14} /></Select.Icon>
    </Select.Trigger>
    <Select.Portal>
      <Select.Positioner className="liquid-menu-positioner" side="top" align="start" sideOffset={8} collisionPadding={16} alignItemWithTrigger={false}>
        <Select.Popup className="liquid-popup search-mode-popup">
          <GlassSurface radius={22} />
          <Select.List className="liquid-popup-content liquid-menu-list">
            {options.map(option => <Select.Item key={option.value} value={option.value} className="liquid-menu-item">
              <Select.ItemText>{option.label}</Select.ItemText>
              <Select.ItemIndicator className="liquid-menu-check"><Check size={16} /></Select.ItemIndicator>
            </Select.Item>)}
          </Select.List>
        </Select.Popup>
      </Select.Positioner>
    </Select.Portal>
  </Select.Root>;
}
