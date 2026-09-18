import { create } from 'zustand';
import { api, ApiError } from './api';

export type ModelOption = { id: string; name: string; providers: string[]; efforts: string[]; input_per_m: string; output_per_m: string };
export const effortOptions = [{ id: 'minimal', label: '최소' }, { id: 'low', label: '낮음' }] as const;
export const useModelSettings = create<{
  model: string; effort: number; models: ModelOption[]; loaded: boolean; loading: boolean; error: string;
  setModel: (model: string) => void; setEffort: (effort: number) => void; load: () => Promise<void>;
}>((set, get) => ({
  model: 'auto', effort: 0, models: [], loaded: false, loading: false, error: '',
  setModel: model => {
    const option = get().models.find(m => m.id === model);
    if (model !== 'auto' && !option) return;
    set({ model, effort: option?.efforts.length === 1 && option.efforts[0] === 'low' ? 1 : 0 });
  },
  setEffort: effort => set({ effort: Math.max(0, Math.min(1, Math.round(effort))) }),
  load: async () => {
    if (get().loading) return;
    set({loading:true,error:''});
    try {
      const result = await api<{models:ModelOption[]}>('/v1/models');
      set({models:result.models,loaded:true,model: result.models.some(m=>m.id===get().model)?get().model:'auto'});
    } catch (error) {
      set({loaded:false,models:[],model:'auto',error:error instanceof ApiError && error.status===404 ? '서버 업데이트 후 모델 목록을 선택할 수 있어요.' : '모델 목록을 불러오지 못했어요. 다시 시도해 주세요.'});
    } finally { set({loading:false}); }
  },
}));
