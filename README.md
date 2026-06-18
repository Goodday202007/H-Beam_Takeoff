# 🤖 AI 기반 H-Beam 도면 적산 검증 시스템 (H-Beam Takeoff Verification System)

본 프로젝트는 CAD 도면(DXF 형식)을 파싱하여 철골 부재(기둥, 보)를 자동으로 감지 및 적산하고, Gemini AI 기반 분석 엔진을 통해 누락되거나 왜곡된 철골 정보를 정밀하게 보정하고 검증할 수 있는 통합 웹 GUI 시스템입니다.

---

## 🌟 주요 핵심 기능

### 1. DXF 도면 파싱 및 시트 분할 관리
- `ezdxf` 엔진을 통해 대용량 CAD 도면 파일에서 벡터 지오메트리(선, 원 등) 및 텍스트 데이터를 고속으로 추출합니다.
- 복잡하게 얽혀 있는 다중 시트 도면을 개별 작업 영역(기둥 도면, 보 도면 등)으로 수동 및 자동 분할하여 관리할 수 있습니다.

### 2. 기둥 및 보 자동 감지 (Rule-Based 적산)
- 규칙 기반 추출 알고리즘을 통해 기둥 위치(원형 마커) 및 보 라인(H-Beam 배선)을 감지합니다.
- 부재의 정확한 중심 좌표 및 길이를 자동으로 실측하여 테이블 리스트로 연동합니다.

### 3. Gemini AI Helper 연동 (AI-Based 보정)
- 도면 마다 제각기 다른 텍스트 규칙과 불규칙한 벡터 요소로 인해 규칙 기반 알고리즘이 찾아내지 못한 미매핑 기둥/보를 Gemini 2.5-flash AI 엔진이 정밀 검출합니다.
- AI가 제안한 부재 부호와 탐지 근거, 신뢰도를 UI 사이드바에서 직관적으로 검토하고 승인 혹은 거절할 수 있습니다.

### 4. 시각적 강조 및 자동 포커싱 (최근 업데이트)
- **동적 화면 이동 (Zoom & Pan)**: AI 제안 카드를 클릭하면 상세 캔버스 뷰가 해당 부재의 도면 좌표로 자동 정렬되며, 가시성을 극대화하기 위해 줌 레벨이 1.8배 수준으로 자동 확대됩니다.
- **네온 핫핑크 하이라이트**: 도면 내 해당 좌표에 핫핑크색 점선의 깜빡이는 듯한 **2중 포커스 링**을 드로잉하여 사용자가 도면 상의 정확한 매핑 지점을 1초 안에 인지할 수 있도록 시각 피드백을 제공합니다.
- **활성화 카드 매칭**: 클릭한 AI 카드의 테두리가 보라색 계열로 켜져 현재 어떤 아이템을 검토 중인지 직관적으로 보여줍니다.

### 5. AI 제안 통계 정보 시각화 (최근 업데이트)
- AI 추천 목록 상단에 **총 제안 수량** 및 **부호별(예: MC1, MT1 등) 집계 수량 요약 대시보드**를 은은한 보라색 카드로 상시 렌더링합니다.
- 승인/거절 시 실시간으로 대시보드 수치가 자동 갱신됩니다.

### 6. 참조 시트 분석기 및 엑셀 내보내기
- 기둥 화면에서 높이 기준 정보를 참조 시트 분석기로 일괄 추출하고 적용할 수 있습니다.
- 적산 완료된 도면 최종 결과는 미려하게 스타일링된 엑셀(`.xlsx`) 양식 파일로 자동 변환하여 다운로드할 수 있습니다.

---

## 🛠️ 기술 스택
- **Backend**: Python 3.8+, FastAPI, Uvicorn, ezdxf, openpyxl, httpx
- **Frontend**: Vanilla HTML5, CSS3, JavaScript (2D Canvas 그래픽스 엔진)
- **AI Engine**: OpenRouter API (Google Gemini 2.5-flash)

---

## 🚀 시작하기

### 1. 사전 요구사항
- Python 3.8 이상 설치
- OpenRouter API 키 발급 ([OpenRouter 공식 홈페이지](https://openrouter.ai/)에서 발급 가능)

### 2. 프로젝트 내려받기 및 라이브러리 설치
```bash
git clone https://github.com/YOUR_USERNAME/YOUR_REPOSITORY_NAME.git
cd YOUR_REPOSITORY_NAME
pip install -r requirements.txt
```

### 3. 환경 변수 설정
프로젝트 루트 디렉토리에 `.env` 파일을 생성하고 다음과 같이 API 키와 모델을 등록합니다.
```env
OPENROUTER_API_KEY=your_actual_openrouter_api_key_here
OPENROUTER_MODEL=google/gemini-2.5-flash
```

### 4. 서버 실행
```bash
python server.py
```
- 서버가 정상 작동하면 웹 브라우저에서 `http://localhost:8000`으로 접속할 수 있습니다.

---

## 📂 프로젝트 구조
```text
├── server.py              # FastAPI 백엔드 웹 서버 및 라우트 컨트롤러
├── takeoff_analysis.py    # DXF 분석, 기둥/보 추출, Excel 리포팅 코어 엔진
├── index.html             # Vanilla Web GUI (Canvas 뷰어 및 사이드바 인터랙션)
├── requirements.txt       # 프로젝트 실행을 위한 의존 파이썬 라이브러리 목록
├── .gitignore             # 깃허브 업로드 제외 파일 설정 (.env, venv 등)
├── data/                  # [로컬 전용] 업로드된 DXF 원본 도면 및 메타 JSON 저장소
└── output/                # [로컬 전용] 생성된 엑셀 다운로드 리포트 폴더
```

---

## ⚠️ 주의사항 및 보안 지침
- **API Key 노출 금지**: 절대 `.env` 파일을 GitHub Public 레포지토리에 푸시하지 마십시오. `.gitignore`에 이미 제외 설정되어 있습니다.
- **도면 데이터 유실 방지**: `data/` 및 `output/` 내부의 실제 도면 파일 및 산출 엑셀 파일은 기밀 유지 및 보안상 깃 업로드 목록에서 차단되어 있습니다.
