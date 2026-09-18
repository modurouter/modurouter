export class ApiError extends Error {
  constructor(public code: string, message: string, public status: number) { super(message); }
}
export async function responseError(response: Response): Promise<ApiError> {
  const error = await response.json().catch(() => null);
  return new ApiError(typeof error?.code === 'string' ? error.code : 'NETWORK_ERROR',
    typeof error?.message === 'string' ? error.message : '서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.', response.status);
}
export function apiUrl(path: string): string {
  return `/api/backend${path}`;
}
export async function api<T>(url: string, init: RequestInit = {}, csrf?: string): Promise<T> {
  const headers = new Headers(init.headers);
  if (csrf) headers.set('X-CSRF-Token', csrf);
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  const response = await fetch(apiUrl(url), {...init, headers, credentials: 'include', cache: 'no-store'});
  if (!response.ok) {
    throw await responseError(response);
  }
  return response.json();
}
export async function ensureSession(): Promise<User> {
  try {
    return await api<User>('/v1/me');
  } catch (error) {
    if (!(error instanceof ApiError && error.status === 401)) throw error;
    await api('/auth/guest', {method: 'POST'});
    return api<User>('/v1/me');
  }
}
const runErrors: Record<string, string> = {
  SEARCH_UNAVAILABLE: '웹 검색을 사용할 수 없습니다. 검색을 끄거나 잠시 후 다시 시도해 주세요.',
  PAGE_UNAVAILABLE: '페이지를 읽을 수 없습니다. 주소를 확인하거나 내용을 파일로 첨부해 주세요.',
  PROVIDER_UNAVAILABLE: '모델 서비스에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.',
  PROVIDER_ACCOUNT_ERROR: '모델 서비스의 계정 설정을 확인해야 합니다. 관리자에게 알려 주세요.',
  PRICE_DATA_STALE: '모델 가격을 갱신 중입니다. 잠시 후 다시 시도해 주세요.',
  NO_ELIGIBLE_MODEL: '입력 길이와 가격 조건에 맞는 모델이 없습니다. 자료를 줄여 다시 시도해 주세요.',
  INPUT_TOO_LONG: '입력 한도를 초과했습니다. 질문이나 자료를 줄여 주세요.',
  BUDGET_EXCEEDED: '오늘의 사용 한도에 도달했습니다. 한국 시간 자정에 초기화됩니다.',
  BUDGET_REVIEW_REQUIRED: '이전 사용 비용을 확인해야 합니다. 관리자에게 알려 주세요.',
  RUN_TIMEOUT: '응답 시간 제한에 도달했습니다. 질문이나 자료를 줄여 다시 시도해 주세요.',
  CONTENT_REFUSED: '모델이 이 요청에 답변하지 않았습니다. 질문을 바꿔 주세요.',
  TOOL_PLAN_INVALID: '자료 처리 요청을 확인하지 못했습니다. 다시 시도해 주세요.',
  ATTACHMENT_NOT_READY: '첨부파일을 읽을 수 없습니다. 파일 상태를 확인하고 다시 첨부해 주세요.',
  SERVER_RESTARTED: '서버 재시작으로 답변이 중단되었습니다. 다시 시도해 주세요.',
  CANCELLED: '답변 생성을 중단했습니다.',
};
export function runErrorMessage(code?: string): string {
  return (code && runErrors[code]) || '답변 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.';
}
export type Source = {source_id:string; title:string; url?:string; scope:string; attachment_id?:string; truncated?:boolean};
export type Run = {run_id:string; status:string; response:string; selected_model?:string; cost_usd:string; pending_usd:string; cost_status:string; cost_source?:string; providers?:string[]; error_code?:string; sources:Source[]; attempts:number; input_tokens:number; output_tokens:number; tokens_complete:boolean; context_truncated:boolean};
export type Message = {id:string; run_id:string; role:string; content:string; status:string};
export type Conversation = {id:string; title:string; updated_at:string};
export type User = {id:string; display_name:string; email:string; csrf_token:string; guest?:boolean};
export type Usage = {remaining_requests:number; request_limit:number; spent_usd:string; reserved_usd:string; limit_usd:string; remaining_usd:string; resets_at:string};
export type Attachment = {id:string; filename:string; status:string; preview?:string; truncated:boolean; error_code?:string; expires_at:string};

export async function consumeEvents(response: Response, receive: (kind:string, data:Record<string, unknown>) => void) {
  if (!response.body) throw new Error('응답 스트림을 읽을 수 없습니다.');
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  try {
    while (true) {
      const {done,value} = await reader.read();
      // Normalize after concatenation because CRLF may straddle network chunks.
      buffer = (buffer + decoder.decode(value, {stream:!done})).replace(/\r\n/g,'\n');
      let boundary;
      while ((boundary = buffer.indexOf('\n\n')) >= 0) {
        const frame = buffer.slice(0,boundary); buffer = buffer.slice(boundary+2);
        const lines = frame.split('\n');
        const kind = lines.find(l => l.startsWith('event:'))?.slice(6).trim();
        const data = lines.filter(l => l.startsWith('data:')).map(l=>l.slice(5).trimStart()).join('\n');
        if (kind && data) receive(kind, JSON.parse(data));
      }
      if (done) return;
    }
  } finally { reader.releaseLock(); }
}
