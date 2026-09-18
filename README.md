# modurouter

Next.js 기반 프론트엔드입니다. modurouter/modurouter의 FastAPI 서버에 게스트 세션과 SSE로 연결합니다.

## 실행

```sh
cd client
npm install
npm run dev
```

http://localhost:3107 에서 확인할 수 있습니다.

```sh
npm run typecheck
npm run build
npm start -- --port 3107
```

현재 개발 환경의 Turbopack 내부 포트 오류를 피하기 위해 개발 및 빌드에 Webpack을 사용합니다.

## 서버 연결

서버 계약: https://github.com/modurouter/modurouter/tree/main/server

`client/.env.local`에 다음 두 주소를 설정합니다. 서버 전용 환경변수이며 API 키는 필요하지 않습니다.

```dotenv
API_UPSTREAM_URL=https://api.modurouter.today
BACKEND_WEB_ORIGIN=https://modurouter.today
```

로컬 백엔드를 쓰려면 `API_UPSTREAM_URL=http://127.0.0.1:8000`과 백엔드에 설정한 web origin을 지정합니다. `/api/backend/*`는 허용한 채팅 경로만 전달하며 브라우저의 같은 출처를 확인한 후 upstream의 Origin으로 변환합니다. HttpOnly 세션 쿠키와 CSRF 토큰을 유지하고, 공급자 키를 브라우저에 전달하지 않습니다. 위 운영 주소를 쓰면 전송한 질문은 실제 서버에 저장되고 서버 사용 한도를 소비합니다.

## 현재 동작

- 첫 전송 시 기존 세션 확인 또는 게스트 세션 생성, 새 대화 생성
- SSE 실제 응답 스트리밍, 진행 상태 및 출처 표시, 실제 사용 모델 확인
- 중지 API 호출, 부분 응답 유지, 오류·사용 한도 안내
- 끊긴 스트림은 실행 조회 API로 확인하며 새 생성을 자동 재시도하지 않음
- 실행 ID를 받기 전 연결이 끊기면 같은 대화·같은 질문의 재전송에 동일한 idempotency key 사용
- 학생 모드는 standard, 노약자·어린이 모드는 simple 설명 옵션 적용
- GET /v1/models의 실제 가격·허용 목록 기반 모델 선택. 모델 목록 API 미배포 시 자동 선택을 유지하고 업데이트 안내 표시
- 페이지 스크롤과 독립된 하단 고정 입력 UI, 내부 스크롤 없는 입력창 확장
- 복사 및 다시 생성, 모드에 따른 글자·컨트롤 크기 변화

현재 화면의 대화는 메모리에서 유지됩니다. 서버에 저장된 대화를 새로고침 후 다시 불러오는 목록 UI, 로그인 통합 UI, 검색 토글은 이번 연결에 포함하지 않았습니다. 파일·사진은 첨부 메뉴, 붙여넣기 또는 입력창 드래그 앤 드롭으로 첨부하고 준비된 파일을 질문에 함께 보냅니다. 음성 입력은 MediaRecorder로 최대 10분 녹음 후 서버의 OpenAI 전사 API로 전달합니다. 음성 버튼을 다시 눌러 녹음을 종료하면 전사 결과가 채팅으로 자동 전송됩니다. 음성 서버 기능의 0006 마이그레이션과 운영 배포는 완료했으며 실제 마이크 인식 품질은 별도 확인이 필요합니다. URL을 질문에 넣으면 서버가 해당 자료를 읽고 출처를 반환할 수 있습니다. 서버는 사고 요약 스트림을 제공하지 않으므로 진행 상태만 표시합니다.

모드별 학습 공간은 생활 배움터·호기심 교실·학습 스튜디오로 나뉩니다. 주문 연습·AI 탐정·오답 복습은 단계별 예제로 동작하며 이어 하기와 완료 기록을 현재 브라우저에 저장합니다. 자유 학습 활동은 모드별 지도 방식과 함께 기존 AI 채팅으로 이어집니다. 자세한 범위는 [모드별 학습 공간](docs/mode-learning.md)을 참고하세요.

## 검증

```sh
npm test
npm run typecheck
npm run build
```

테스트는 합성 응답으로 인증 흐름, 한글 SSE 분할, 서버 오류, 중복 방지, 저장 결과 복구, 취소 및 프록시 출처 검사를 검증합니다. 외부 모델을 호출하지 않습니다.

## 화면과 서체

홈 배경은 그라데이션 없는 단색입니다. 입력창과 버튼의 외곽 포커스 링은 표시하지 않습니다. Apple 시스템 서체를 우선하며, 다른 환경의 한국어 표시는 패키지에 포함된 Pretendard Variable 웹폰트를 같은 서버에서 제공합니다.

- Pretendard: https://github.com/orioncactus/pretendard
- 라이선스: node_modules/pretendard/dist/LICENSE.txt (SIL Open Font License)

유리 표면은 `@liquid-dom/core`의 `WebGpuGlassCore`로 실제 WebGPU 렌더링합니다. 입력창·음성 버튼·모드 토글이 같은 GPU device를 공유하고, 크기 및 포인터 변경 시 다시 그립니다. 페이지의 단색 배경을 GPU 텍스처로 제공하므로 HTML-in-Canvas 실험 기능은 필요하지 않습니다. 단색 배경에는 휘어 보일 무늬가 없어 반사광 위주로 표현됩니다. HTML 입력 요소는 네이티브 DOM으로 유지합니다. WebGPU 미지원·초기화 실패·GPU 텍스처 크기 제한 초과 시에는 CSS 표면이 남습니다. 상태는 Zustand, 애니메이션은 Motion, Markdown은 Streamdown을 사용합니다. Base UI는 기본 버튼 primitive에 적용했습니다.

Vercel AI Elements의 전체 채팅 입력·첨부 구조는 아직 도입하지 않았습니다. 입력은 기존 UI를 유지하며 응답은 서버 SSE 계약에 연결합니다.

## 모델과 사고 강도

서버 변경: 공개 `/v1/models`는 기존 허용 목록, 유효 가격 및 가격 상한을 통과한 모델만 반환합니다. 요청은 `model`과 `reasoning_effort`를 받으며 effort는 `minimal` 또는 `low`만 허용합니다. 선택 모델과 맞지 않는 다른 모델로 바꾸지 않습니다. 지원하지 않는 공급자에는 reasoning 파라미터를 보내지 않습니다. 기존 토큰 상한, 예약 비용 및 일일 사용 한도는 그대로 적용합니다. 2026-09-18 운영 API에 배포했습니다. 현재 허용된 세 모델의 공급자 경로에는 조절 가능한 effort가 없어 슬라이더가 비활성화됩니다.

슬라이더 이동은 Motion의 layout spring 애니메이션을 사용합니다. 기본값은 최소이며 사고 강도 조절이 가능한 모델에만 활성화합니다. 모델 선택은 체크마크 없이 짙은 노란 배경으로 표시합니다.

Git 원격은 `https://github.com/modurouter/modurouter.git`, 로컬 main은 origin/main을 추적합니다. 프론트는 client/, 서버는 server/에 있습니다. 로컬 변경은 커밋하지 않았습니다. 기존 원격 client 사본은 `/tmp/modurouter-client-before-integration`에 보관했습니다.
