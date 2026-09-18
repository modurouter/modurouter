export class ApiError extends Error {
  constructor(public code: string, message: string, public status: number) { super(message); }
}
export async function responseError(response: Response): Promise<ApiError> {
  const error = await response.json().catch(() => null);
  return new ApiError(typeof error?.code === 'string' ? error.code : 'NETWORK_ERROR',
    typeof error?.message === 'string' ? error.message : '서버에 연결하지 못했습니다. 잠시 후 다시 시도해 주세요.', response.status);
}
export function apiUrl(path: string): string {
  const origin = process.env.NEXT_PUBLIC_API_ORIGIN?.replace(/\/$/, '') || '';
  return `${origin}${path}`;
}
export async function fetchApi(url: string, init: RequestInit = {}): Promise<Response> {
  try {
    return await fetch(apiUrl(url), {...init, credentials: 'include'});
  } catch (error) {
    if (init.signal?.aborted || (error instanceof Error && error.name === 'AbortError')) throw error;
    throw new ApiError('NETWORK_ERROR', '서버에 연결하지 못했습니다. 인터넷 연결을 확인한 뒤 다시 전송해 주세요.', 0);
  }
}
export async function api<T>(url: string, init: RequestInit = {}, csrf?: string): Promise<T> {
  const headers = new Headers(init.headers);
  if (csrf) headers.set('X-CSRF-Token', csrf);
  if (init.body && !(init.body instanceof FormData)) headers.set('Content-Type', 'application/json');
  const response = await fetchApi(url, {...init, headers, cache: 'no-store'});
  if (!response.ok) {
    throw await responseError(response);
  }
  return response.json();
}
let sessionRequest: Promise<User> | null = null;
export function ensureSession(): Promise<User> {
  if (!sessionRequest) sessionRequest = loadSession().finally(() => { sessionRequest = null; });
  return sessionRequest;
}
async function loadSession(): Promise<User> {
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
  MANUAL_SELECTION_DISABLED: '관리자가 직접 모델 선택을 비활성화했습니다. 다른 선택 방식을 사용해 주세요.',
  SELECTED_MODEL_UNAVAILABLE: '선택한 모델을 현재 사용할 수 없습니다. 모델을 다시 선택하거나 입력 길이와 자료 처리 지원 여부를 확인해 주세요.',
  NO_FREE_MODEL: '현재 요청을 처리할 무료 모델이 없습니다. 유료 모델로 자동 전환하지 않았습니다.',
  NO_ELIGIBLE_MODEL: '입력 길이와 가격 조건에 맞는 모델이 없습니다. 자료를 줄여 다시 시도해 주세요.',
  INPUT_TOO_LONG: '입력 한도를 초과했습니다. 질문이나 자료를 줄여 주세요.',
  BUDGET_EXCEEDED: '오늘의 사용 한도에 도달했습니다. 한국 시간 자정에 초기화됩니다.',
  BUDGET_REVIEW_REQUIRED: '이전 사용 비용을 확인해야 합니다. 관리자에게 알려 주세요.',
  RUN_TIMEOUT: '응답 시간 제한에 도달했습니다. 질문이나 자료를 줄여 다시 시도해 주세요.',
  CONTENT_REFUSED: '모델이 이 요청에 답변하지 않았습니다. 질문을 바꿔 주세요.',
  TOOL_PLAN_INVALID: '자료 처리 요청을 확인하지 못했습니다. 다시 시도해 주세요.',
  ATTACHMENT_EXPIRED: '이전 첨부파일이 만료되거나 삭제되어 원문을 확인할 수 없습니다. 파일을 다시 첨부해 주세요.',
  ATTACHMENT_NOT_READY: '첨부파일을 읽을 수 없습니다. 파일 상태를 확인하고 다시 첨부해 주세요.',
  SERVER_RESTARTED: '서버 재시작으로 답변이 중단되었습니다. 다시 시도해 주세요.',
  CANCELLED: '답변 생성을 중단했습니다.',
};
export function runErrorMessage(code?: string): string {
  return (code && runErrors[code]) || '답변 처리 중 오류가 발생했습니다. 잠시 후 다시 시도해 주세요.';
}
export type Source = {source_id:string; title:string; url?:string; scope:string; attachment_id?:string; truncated?:boolean};
export type RoutingPreference = {mode:"auto"|"free"|"manual"; provider?:string; model_id?:string};
export type ModelOption = {efforts?:string[]; provider:string; model_id:string; name:string; input_per_m:string; output_per_m:string; is_free:boolean; context_length:number; supports_tools:boolean; auto_eligible:boolean; price_kind:string};
export type ModelCatalog = {default_routing?:RoutingPreference; allow_manual_selection?:boolean; providers?:{provider:string;stale:boolean;last_success_at:string|null}[]; models:ModelOption[]; last_success_at:string|null; refresh_error:string|null; stale:boolean};
export type Run = {run_id:string; status:string; response:string; selected_model?:string; selected_provider?:string; routing?:RoutingPreference; cost_usd:string; pending_usd:string; cost_status:string; cost_source?:string; providers?:string[]; error_code?:string; sources:Source[]; attempts:number; input_tokens:number; output_tokens:number; tokens_complete:boolean; context_truncated:boolean};
export type Message = {id:string; run_id:string; role:string; content:string; status:string};
export type Conversation = {id:string; title:string; updated_at:string};
export type User = {id:string; display_name:string; email:string; csrf_token:string; guest?:boolean; admin?:boolean};
export type Usage = {remaining_requests:number|null; request_limit:number|null; spent_usd:string; reserved_usd:string; limit_usd:string; remaining_usd:string; resets_at:string};
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

const attachmentErrors: Record<string, string> = {
  HWP_ENCRYPTED: '암호화된 한글 문서입니다. 암호를 해제한 파일을 다시 첨부해 주세요.',
  HWP_PROTECTED: '보안이 설정된 한글 문서입니다. 보안을 해제한 파일을 다시 첨부해 주세요.',
  HWP_INVALID: '한글 문서가 손상되었거나 내부 구조를 읽을 수 없습니다. 한글에서 다시 저장한 파일을 첨부해 주세요.',
  HWP_VERSION_UNSUPPORTED: '이 버전의 한글 문서는 읽을 수 없습니다. 최신 한글에서 HWPX로 저장해 다시 첨부해 주세요.',
  HWP_SIZE_LIMIT: '한글 문서의 내부 데이터가 너무 큽니다. 파일을 나누어 다시 첨부해 주세요.',
  PDF_ENCRYPTED: '암호화된 PDF는 읽을 수 없습니다. 암호를 해제한 파일을 다시 첨부해 주세요.',
  PDF_PAGE_LIMIT: 'PDF는 20쪽까지 읽을 수 있습니다. 파일을 나누어 다시 첨부해 주세요.',
  NO_EXTRACTABLE_TEXT: '읽을 수 있는 텍스트가 없습니다. 이미지로만 된 문서는 페이지를 PNG/JPG로 저장하거나 내용을 TXT로 첨부해 주세요.',
  FILE_ENCODING_INVALID: '텍스트 인코딩을 읽을 수 없습니다. UTF-8 형식의 TXT로 저장해 다시 첨부해 주세요.',
  IMAGE_PIXEL_LIMIT: '이미지가 너무 큽니다. 2천만 픽셀 이하로 줄여 다시 첨부해 주세요.',
  OCR_LOW_CONFIDENCE: '이미지의 글자를 정확히 읽지 못했습니다. 원본을 확인하고 선명한 이미지나 TXT로 다시 첨부해 주세요.',
  OCR_FAILED: '이미지의 글자를 읽지 못했습니다. 선명한 이미지나 TXT로 다시 첨부해 주세요.',
  OCR_TIMEOUT: '이미지를 읽는 시간이 초과되었습니다. 크기를 줄이거나 잠시 후 다시 첨부해 주세요.',
  EXTRACTION_TIMEOUT: '파일을 읽는 시간이 초과되었습니다. 파일을 나누거나 잠시 후 다시 첨부해 주세요.',
  WORKER_INTERRUPTED: '파일 처리 중 연결이 중단되었습니다. 파일을 삭제한 뒤 다시 첨부해 주세요.',
  FILE_UNSUPPORTED: '지원하지 않는 파일입니다. HWP/HWPX 문서나 TXT/PDF 파일, PNG/JPG 이미지를 다시 첨부해 주세요.',
  UPLOAD_FAILED: '파일 업로드에 실패했습니다. 인터넷 연결을 확인한 뒤 다시 첨부해 주세요.',
  ATTACHMENT_RESTORE_FAILED: '첨부 상태를 확인하지 못했습니다. 연결을 확인하고 대화를 다시 열거나 파일을 다시 첨부해 주세요.',
};
export function attachmentErrorMessage(attachment: Attachment): string | null {
  if (attachment.status === 'expired') return '첨부파일이 만료되거나 삭제되었습니다. 파일을 제거한 뒤 다시 첨부해 주세요.';
  if (!['failed', 'unavailable'].includes(attachment.status)) return null;
  return attachmentErrors[attachment.error_code || ''] || '파일을 읽지 못했습니다. 파일을 확인하고 삭제한 뒤 다시 첨부해 주세요.';
}

export type SavedAttachment = Pick<Attachment, 'id' | 'filename'>;
export function readSavedAttachments(value: string | null): SavedAttachment[] {
  if (!value) return [];
  const parsed: unknown = JSON.parse(value);
  if (!Array.isArray(parsed) || parsed.length > 3 || parsed.some(a =>
    !a || typeof a.id !== 'string' || typeof a.filename !== 'string')) throw new Error('저장한 첨부 정보를 읽지 못했습니다. 파일을 다시 첨부해 주세요.');
  return parsed;
}
export async function restoreAttachments(saved: SavedAttachment[]): Promise<Attachment[]> {
  return Promise.all(saved.map(async item => {
    try { return await api<Attachment>(`/v1/attachments/${encodeURIComponent(item.id)}`); }
    catch (error) {
      if (error instanceof ApiError && error.status === 401) throw error;
      return {...item, status: error instanceof ApiError && error.status === 404 ? 'expired' : 'unavailable',
        error_code: 'ATTACHMENT_RESTORE_FAILED', truncated: false, expires_at: ''};
    }
  }));
}
