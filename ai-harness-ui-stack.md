# AI Harness UI / Tech Stack

## Tech Stack

### Frontend

- **Next.js + React 19 + TypeScript**
- **Tailwind CSS v4**
- **shadcn/ui / Base UI** — 기본 primitive만 활용
- **Vercel AI Elements** — 채팅, 스트리밍, 첨부 등 기본 AI UI 로직
- **Motion** — 토글 드래그, spring, hover/press 애니메이션
- **liquid-dom (`@liquid-dom/react`)** — 핵심 glass UI
- **Lucide React** — 최소한의 아이콘
- **Streamdown** — 스트리밍 Markdown 렌더링
- **Zustand** — UI 상태 관리

### Backend / Harness

- **FastAPI + Pydantic + httpx**
- **SSE Streaming**
- Provider별 API를 하나의 OpenAI-compatible 인터페이스로 통합
- PDF / Web / OCR / STT / TTS 도구를 하네스 레이어에서 연결
- 가격과 조건에 따라 저가 모델/API provider로 라우팅

---

## 화면 방향

전체적으로 **큰 여백 + 최소한의 텍스트 + 둥글고 부드러운 Liquid Glass** 스타일.

초기 화면에 남기는 요소는 아래 정도로 제한한다.

1. **좌측 상단 로고**
   - 심볼 없이 서비스 이름만 표시

2. **화면 중앙 하단 Glass 채팅창**
   - 부드러운 rounded rectangle
   - 내부 왼쪽은 입력창
   - 내부 오른쪽에 rounded-square 형태의 위 화살표 전송 버튼
   - 첨부, 모델 선택, 상태 표시 등 불필요한 UI는 기본 화면에서 제외

3. **채팅창 오른쪽 외부의 큰 Glass 마이크 버튼**
   - 원형
   - 채팅창과 비슷한 높이
   - hover / press / recording 상태를 부드러운 scale animation으로 표현

4. **채팅창 바로 아래 Glass 모드 토글**
   - 채팅창과 동일한 폭
   - `노약자 모드 / 어린이 모드 / 학생모드`
   - 클릭과 좌우 드래그 모두 지원
   - 선택 indicator가 spring animation으로 부드럽게 이동

---

## UI 원칙

- 무료 사용량, 추천 문구, 배지, 상태 dot, sidebar 등 불필요한 요소 제거
- 첫 화면은 사실상 **이름 / 입력창 / 전송 / 마이크 / 모드 토글**만 존재
- 하네스의 세부 기능은 필요할 때만 문서 분석, 웹 검색 등의 진행 상태로 노출

서비스 이름은 modurouter

일단 backend는 아예 제외하고
frontend 만 작동하도록 데모버젼으로 만들어볼거야.
그렇다고 화면이나 코드에 "데모"를 넣지는 마.
