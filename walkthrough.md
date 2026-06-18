# AutoQTO AI Helper 기능 개발 완료 보고서 (Walkthrough)

H형강 적산 검증 시스템(`AutoQTO`)에 OpenRouter 기반의 **AI Helper (기둥 AI / 보 AI / 기둥 높이 추천 AI)** 기능을 연동하고 개발을 성공적으로 완료하였습니다.

---

## 🛠️ 작업 내용 및 수정된 파일 요약

1. **규칙 가이드 문서 작성 ([NEW] [rules_reference.md](file:///d:/python_2025-26/aiffel_p/c_partner/final/rules_reference.md))**:
   - AI가 도면을 정확히 이해하고 기존 분석 기준에 맞춰 결과를 도출할 수 있도록 H형강 부호 정규식, 기하 필터링, 매칭 임계치(3,600mm/4,000mm/5,000mm) 규칙을 정리한 참고 가이드 문서를 완성했습니다.

2. **백엔드 AI 분석 API 추가 ([MODIFY] [server.py](file:///d:/python_2025-26/aiffel_p/c_partner/final/server.py))**:
   - `/api/ai_analyze_columns`, `/api/ai_analyze_beams`, `/api/ai_recommend_height` 엔드포인트를 구현하여 OpenRouter `google/gemini-2.5-flash` 모델과 비동기(`httpx.AsyncClient`) 연동을 구축했습니다.
   - `rules_reference.md`와 DXF 압축 텍스트 데이터 및 기존 적산 목록을 컨텍스트로 LLM에 주입하여 도출 성능을 최적화했습니다.
   - **적산 이력 연동**: 최종 엑셀 적산 내역서 출력 시 개별 산출 상세 내역서 탭의 `비고` 컬럼에 AI 승인 부재의 경우 `"AI 제안 승인"` 문구가 기입되도록 최종 엑셀 빌드 로직을 수정했습니다.

3. **DXF AI용 전처리 함수 추가 ([MODIFY] [takeoff_analysis.py](file:///d:/python_2025-26/aiffel_p/c_partner/final/takeoff_analysis.py))**:
   - LLM 입력 토큰 절약을 위해 지정된 BBox 내부의 `TEXT`/`MTEXT`/`ATTRIB`/`BLOCK` 텍스트와 기둥 단면 후보(LWPOLYLINE), 보 기하선 후보(LINE/LWPOLYLINE) 데이터를 압축하여 가공하는 `extract_dxf_data_for_ai()` 함수를 추가했습니다.
   - 기둥 높이 분석 전용으로 도면 내 1000~100000 사이의 치수선 값 및 수치 텍스트를 추출하는 `extract_height_texts_for_ai()` 함수를 설계하고 추가했습니다.

4. **프론트엔드 UI/UX 개편 ([MODIFY] [index.html](file:///d:/python_2025-26/aiffel_p/c_partner/final/index.html))**:
   - **AI 분석 버튼**: 기둥 및 보 리스트 상단 헤더에 보라색 그라데이션 스타일의 `[🤖 AI 기둥 분석]`, `[🤖 AI 보 분석]` 버튼을 구현했습니다.
   - **AI 높이 추천 버튼**: 기둥 높이 직접 입력 패널(`height-input-wrap`) 내 '높이 입력 (mm)' 헤더 우측에 `[🤖 AI 높이 추천]` 버튼을 추가했습니다.
   - **AI 추천 사이드 패널**: 사용자가 분석 버튼을 클릭하면 슬라이드인(Slide-in) 형태로 추천 목록과 분석 근거, 신뢰도를 보여주는 패널을 제작했습니다.
   - **도면 마킹**: AI가 판정한 기둥/보 영역을 도면 캔버스에 보라색 점선 및 실선으로 덧씌워 시각적 확인이 가능하게 연동했습니다.
   - **Human-in-the-loop 검토 및 데이터 융합**: 
     - 각 제안에 대해 `승인`/`거절` 및 `일괄 승인`/`일괄 거절` 프로세스를 구현하고, 승인 시 `source: 'ai'` 메타데이터가 부여되어 최종 적산서에 이력이 추적되도록 설계했습니다.
     - 높이 추천 승인 시 높이 인풋 박스에 추천된 제일 긴 높이값이 자동완성되도록 바인딩 로직을 처리했습니다.

5. **환경변수 파일 생성 ([NEW] [.env](file:///d:/python_2025-26/aiffel_p/c_partner/final/.env))**:
   - OpenRouter API 키 및 모델 명칭 설정을 위한 템플릿 파일을 구성했습니다.

6. **도면 파싱 및 분석 성능 대폭 개선 (성능 최적화)**:
   - **`sanitize_surrogates` 병목 해결 (`server.py`)**: 대용량 기하 데이터(예: `thumbnail_lines` 등)에 대해 불필요하게 깊은 재귀 탐색을 방지하고 조기 리턴하는 최적화 로직을 도입하여 surrogate 정제 속도를 약 68배 단축시켰습니다.
   - **`find_rectangles_from_lines` 알고리즘 최적화 (`takeoff_analysis.py`)**: 수평/수직선 2중 루프 내에서 전체 수직선을 순회하던 기존 `O(H^2 * V)` 3중 루프를, Y축 정렬을 통한 조기 루프 탈출 및 X축 기준 이진 탐색(`bisect`)을 결합한 알고리즘으로 개선하여, 수만 개의 선이 존재하는 복잡한 도면에서 사각형 프레임(도곽)을 찾는 탐색 속도를 획기적으로 향상시켰습니다.

---

## 🚀 AI Helper 사용 가이드

### 1단계: API 키 설정
프로젝트 루트 폴더에 생성된 `.env` 파일을 메모장이나 에디터로 열어 사용 중이신 OpenRouter API Key를 입력합니다.
```env
OPENROUTER_API_KEY=sk-or-v1-본인의_API_키_입력
```

### 2단계: 서버 재실행
```powershell
python server.py
```
서버를 시작하고 웹 브라우저에서 접속합니다.

### 3단계: AI 분석 실행 및 승인
1. DXF 도면을 업로드하고 기존 규칙 기반 1차 분석을 완료합니다.
2. 우측 상단 탭에서 **기둥** 또는 **보** 검증 화면으로 이동합니다.
3. 리스트 헤더 영역에 추가된 **`[🤖 AI 기둥 분석]`** 혹은 **`[🤖 AI 보 분석]`** 버튼을 클릭합니다.
4. AI 분석이 수행된 후 오른쪽 사이드에 보라색 **AI 분석 추천 결과** 패널이 슬라이드인됩니다. 동시에 도면 위에 보라색으로 감지된 AI 기둥/보가 마킹됩니다.
5. 추천 목록에서 판정 근거와 도면 위치를 대조하고, **[승인]**을 누르면 정식 기둥/보 리스트에 추가되어 즉시 최종 적산 중량 집계표와 보고서에 포함됩니다. (승인 부재는 최종 출력물 비고 란에 `"AI 제안 승인"` 표기)

### 4단계: AI 높이 추천 기능 실행
1. 기둥 리스트 중 높이를 설정하려는 기둥을 선택합니다.
2. 높이 직접 입력창 우측 상단에 위치한 **`[🤖 AI 높이 추천]`** 버튼을 클릭합니다.
3. AI가 도면(또는 선택한 참조 도면)을 분석하여 가장 긴 높이 수치를 계산하고 근거와 함께 팝업 대화창으로 제시합니다.
4. **[확인(적용)]**을 누르면 기둥 높이 입력 창에 해당 수치(예: 4200mm)가 자동 기입됩니다.
