'use client';
import { useEffect, useState } from 'react';
import type { Mode } from './chat-store';
import { advancePractice, emptyPractice, readPractice, type Practice } from './learning-journeys';
const key = 'modurouter.learning.v1';
type Progress = Record<Mode, Practice>;
export function useLearningProgress() {
  const [progress, setProgress] = useState<Progress>({ senior: emptyPractice(), child: emptyPractice(), student: emptyPractice() });
  const [ready, setReady] = useState(false);
  useEffect(() => {
    try {
      const saved = JSON.parse(localStorage.getItem(key) || '{}');
      setProgress({ senior: readPractice(saved?.senior, 'senior'), child: readPractice(saved?.child, 'child'), student: readPractice(saved?.student, 'student') });
    } catch { /* Storage may be disabled; the session still works. */ }
    setReady(true);
  }, []);
  useEffect(() => { if (ready) { try { localStorage.setItem(key, JSON.stringify(progress)); } catch { /* Keep in-memory progress. */ } } }, [progress, ready]);
  return {
    progress, ready,
    choose: (mode: Mode, index: number) => setProgress(p => ({ ...p, [mode]: advancePractice(mode, p[mode], index) })),
    restart: (mode: Mode) => setProgress(p => ({ ...p, [mode]: { ...emptyPractice(), completions: p[mode].completions } })),
    clear: (mode: Mode) => setProgress(p => ({ ...p, [mode]: emptyPractice() })),
  };
}
