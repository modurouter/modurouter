import { create } from 'zustand';
import type { Run, Source } from './api';
export const modes = [
  { id: 'senior', label: '노약자 모드', placeholder: '궁금한 것을 편하게 물어보세요' },
  { id: 'child', label: '어린이 모드', placeholder: '어떤 게 궁금해?' },
  { id: 'student', label: '학생모드', placeholder: '무엇이든 물어보세요' },
] as const;
export type Mode = typeof modes[number]['id'];
export type Activity = { startedAt: number; finishedAt?: number; status: 'writing' | 'complete' | 'stopped' | 'error'; stage?: string; events?: string[] };
export type Message = { id: string; role: 'user' | 'assistant'; content: string; activity?: Activity; selectedModel?: string; selectedProvider?: string; runId?: string; run?: Run; sources?: Source[]; error?: string };
type State = { conversationId: string | null; setConversationId: (id: string | null) => void; setMessages: (messages: Message[]) => void; mode: Mode; messages: Message[]; streaming: boolean; setMode: (mode: Mode) => void; add: (message: Message) => void; update: (id: string, content: string) => void; patch: (id: string, patch: Partial<Message>) => void; setStreaming: (value: boolean) => void };
export const useChatStore = create<State>((set) => ({
  conversationId: null, setConversationId: conversationId => set({conversationId}), setMessages: messages => set({messages}),
  mode: 'student', messages: [], streaming: false,
  setMode: (mode) => set({ mode }),
  add: (message) => set((s) => ({ messages: [...s.messages, message] })),
  update: (id, content) => set((s) => ({ messages: s.messages.map((m) => m.id === id ? { ...m, content } : m) })),
  patch: (id, patch) => set((s) => ({ messages: s.messages.map((m) => m.id === id ? { ...m, ...patch } : m) })),
  setStreaming: (streaming) => set({ streaming }),
}));
