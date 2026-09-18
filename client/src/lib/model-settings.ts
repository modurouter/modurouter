import { create } from 'zustand';
import { api, ensureSession, type ModelCatalog, type ModelOption, type RoutingPreference } from './api';

export const effortOptions = [{ id: 'minimal', label: '최소' }, { id: 'low', label: '낮음' }] as const;
export const modelKey = (model: ModelOption) => `${model.provider}::${model.model_id}`;
export function routingFor(model: string, models: ModelOption[]): RoutingPreference {
  if (model === 'auto' || model === 'free') return { mode: model };
  const option = models.find(item => modelKey(item) === model);
  if (!option) throw new Error('모델 목록을 새로 불러온 뒤 다시 선택해 주세요.');
  return { mode: 'manual', provider: option.provider, model_id: option.model_id };
}
export const useModelSettings = create<{
  model: string; chosen: boolean; effort: number; models: ModelOption[]; allowManual: boolean;
  loaded: boolean; loading: boolean; error: string;
  setModel: (model: string) => void; setEffort: (effort: number) => void; load: () => Promise<void>;
}>((set, get) => ({
  model: 'auto', chosen: false, effort: 0, models: [], allowManual: true, loaded: false, loading: false, error: '',
  setModel: model => {
    const option = get().models.find(m => modelKey(m) === model);
    if (!['auto', 'free'].includes(model) && (!option || !get().allowManual)) return;
    set({ model, chosen: true, effort: option?.efforts?.[0] === 'low' ? 1 : 0 });
  },
  setEffort: effort => set({ effort: Math.max(0, Math.min(1, Math.round(effort))) }),
  load: async () => {
    if (get().loading) return;
    set({loading:true,error:''});
    try {
      await ensureSession();
      const result = await api<ModelCatalog>('/v1/models');
      const current = get();
      const routing = result.default_routing || {mode:'auto'};
      const model = current.chosen ? current.model : routing.mode === 'manual' ? `${routing.provider}::${routing.model_id}` : routing.mode;
      // Preserve an unavailable explicit choice so it never silently becomes a paid automatic route.
      set({models:result.models,loaded:true,model,allowManual:result.allow_manual_selection !== false});
    } catch {
      set({loaded:false,error:'모델 목록을 불러오지 못했어요. 다시 시도해 주세요.'});
    } finally { set({loading:false}); }
  },
}));
