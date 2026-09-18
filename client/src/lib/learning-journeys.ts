import type { Mode } from './chat-store';

export const learningSpaces: Record<Mode, { title: string; activity: string; cue: string }> = {
  senior: { title: '생활 배움터', activity: '주문 연습', cue: '음성으로도 골라보세요' },
  child: { title: '호기심 교실', activity: 'AI 탐정', cue: 'AI의 말을 확인해 볼까요?' },
  student: { title: '학습 스튜디오', activity: '오답 복습', cue: '틀린 풀이부터 살펴보기' },
};
export const modeGuidance: Record<Mode, string> = {
  senior: '생활 속 디지털 자립을 돕는 안내자로 답하세요. 존댓말과 쉬운 말을 쓰고, 조작 안내는 한 단계씩 진행하며 답을 기다리세요. 나이만으로 능력을 단정하지 마세요.',
  child: '초등학생의 탐구를 돕는 선생님으로 답하세요. 짧고 쉬운 말로 설명하고, 학습 질문에서는 아이의 예상이나 생각을 하나 물은 뒤 관찰과 자기 설명으로 이어가세요. 개인정보를 요구하지 마세요.',
  student: '중고등학생의 자기주도 학습 코치로 답하세요. 문제 풀이에서는 시도한 풀이를 확인하고 필요한 힌트부터 주되, 풀이를 요청하면 설명하세요. 조사에서는 근거와 출처를 구별하고 확인하지 않은 출처를 만들지 마세요.',
};
export type PracticeChoice = { label: string; matches: RegExp; correct?: boolean };
export type PracticeStep = { title: string; detail?: string; choices: PracticeChoice[]; hint?: string };
export const practiceSteps: Record<Mode, PracticeStep[]> = {
  senior: [
    { title: '어디에서 드실까요?', choices: [{ label: '매장에서', matches: /매장|먹고|여기/ }, { label: '포장', matches: /포장|가져|테이크/ }] },
    { title: '무엇을 드실까요?', choices: [{ label: '아메리카노', matches: /아메리카노|커피/ }, { label: '유자차', matches: /유자|차로/ }] },
    { title: '온도를 골라주세요', choices: [{ label: '따뜻하게', matches: /따뜻|뜨거|핫/ }, { label: '차갑게', matches: /차갑|시원|아이스/ }] },
    { title: '주문을 확인해 주세요', choices: [{ label: '주문 확인', matches: /확인|맞아|맞네|완료|주문해/ }] },
  ],
  child: [
    { title: '이 말을 믿어도 될까?', detail: 'AI 답변 예시: “펭귄은 모두 북극에 살아.”', choices: [{ label: '그대로 믿을래', matches: /그대로|믿을|맞는|맞아/, correct: false }, { label: '한번 확인할래', matches: /확인|찾아|의심|틀린|아니/, correct: true }], hint: 'AI도 틀릴 수 있어요. 동물 도감과 비교해 볼까요?' },
    { title: '무엇을 근거로 삼을까?', detail: '동물 도감에는 펭귄이 남반구에 살며, 갈라파고스펭귄은 적도 부근에 산다고 나와요.', choices: [{ label: '동물 도감의 설명', matches: /도감|남반구|적도/, correct: true }, { label: 'AI가 자신 있게 말한 것', matches: /자신|확신/, correct: false }], hint: '말투보다 확인할 수 있는 근거를 살펴봐요.' },
    { title: '어떻게 고치면 좋을까?', choices: [{ label: '펭귄은 남반구에 주로 살아', matches: /남반구|남쪽/, correct: true }, { label: '펭귄은 북극에만 살아', matches: /북극/, correct: false }], hint: '도감에서 읽은 내용을 떠올려 봐요.' },
  ],
  student: [
    { title: '어디서 틀렸을까?', detail: '3(x + 2) = 15 → 3x + 2 = 15 → x = 13/3', choices: [{ label: '괄호를 풀 때', matches: /괄호|분배|첫|전개/, correct: true }, { label: '마지막에 3으로 나눌 때', matches: /나눌|나누|마지막/, correct: false }], hint: '괄호 밖의 3은 x와 2에 각각 곱해져요.' },
    { title: '다시 풀면 x는?', detail: '3x + 6 = 15', choices: [{ label: 'x = 3', matches: /^(?:x는|답은|엑스는)?3(?:이야|입니다|이에요)?$|^삼(?:이야|입니다|이에요)?$/, correct: true }, { label: 'x = 7', matches: /^7|^칠/, correct: false }], hint: '양쪽에서 6을 뺀 다음, 3으로 나눠보세요.' },
    { title: '비슷한 문제도 풀어볼까?', detail: '2(x + 4) = 18', choices: [{ label: 'x = 5', matches: /^(?:x는|답은|엑스는)?5(?:이야|입니다|이에요)?$|^오(?:야|입니다|예요)?$/, correct: true }, { label: 'x = 7', matches: /^7|^칠/, correct: false }], hint: '먼저 양쪽을 2로 나누면 x + 4 = 9가 돼요.' },
  ],
};
export type Practice = { step: number; answers: string[]; complete: boolean; hint: boolean; completions: number };
export const emptyPractice = (): Practice => ({ step: 0, answers: [], complete: false, hint: false, completions: 0 });
export function advancePractice(mode: Mode, state: Practice, index: number): Practice {
  const step = practiceSteps[mode][state.step];
  const choice = step?.choices[index];
  if (!choice || state.complete) return state;
  if (choice.correct === false) return { ...state, hint: true };
  const complete = state.step === practiceSteps[mode].length - 1;
  return { ...state, step: complete ? state.step : state.step + 1, answers: [...state.answers, choice.label], complete, hint: false, completions: state.completions + Number(complete) };
}
export function practiceVoiceIndex(mode: Mode, state: Practice, utterance: string): number | null {
  if (state.complete) return null;
  const text = utterance.replace(/[\s.!?]/g, '').toLowerCase();
  if (/말고|싫|않/.test(text)) return null;
  const choices = practiceSteps[mode][state.step].choices;
  const ordinal = text.match(/^([1-2]|첫|두)(?:번째|번)(?:거|것|으로|할래|해줘|선택|요|주세요)*$/);
  if (ordinal) { const i = ['1', '첫'].includes(ordinal[1]) ? 0 : 1; return choices[i] ? i : null; }
  const matches = choices.map((choice, i) => text.includes(choice.label.replace(/\s+/g, '').toLowerCase()) || choice.matches.test(text) ? i : -1).filter(i => i !== -1);
  return matches.length === 1 ? matches[0] : null;
}
// Versioned, bounded local progress; no recording or attachment data is stored.
export function readPractice(value: unknown, mode: Mode): Practice {
  if (!value || typeof value !== 'object') return emptyPractice();
  const p = value as Practice;
  if (!Number.isInteger(p.step) || p.step < 0 || p.step >= practiceSteps[mode].length || !Array.isArray(p.answers) || p.answers.length > practiceSteps[mode].length || p.answers.some(a => typeof a !== 'string' || a.length > 100) || typeof p.complete !== 'boolean') return emptyPractice();
  return { step: p.step, answers: p.answers, complete: p.complete, hint: Boolean(p.hint), completions: Number.isInteger(p.completions) ? Math.max(0, Math.min(9999, p.completions)) : 0 };
}

export function composeLearningMessage(text: string, mode: Mode, context = '') {
  const guidance = `\n\n[응답 방식]\n${modeGuidance[mode]}`;
  const learning = context ? `\n[진행 중인 학습]\n${context}\n이전 대화를 이어서 진행하세요.` : '';
  // Preserve the user's entire input at the existing server limit.
  if ((text + guidance + learning).length <= 12000) return text + guidance + learning;
  return (text + guidance).length <= 12000 ? text + guidance : text;
}
