# server.py 디버깅 가이드

## 1. 서버 실행 방법

### 1.1 기본 실행
```bash
python server.py
```
- 서버 주소: `http://127.0.0.1:8000`
- API 문서: `http://127.0.0.1:8000/docs` (Swagger UI)

### 1.2 개발 모드 (자동 리로드)
```bash
# server.py의 마지막 줄을 다음과 같이 수정
uvicorn.run("server:app", host="127.0.0.1", port=8000, reload=True)
```
또는 직접 실행:
```bash
uvicorn server:app --reload --host 127.0.0.1 --port 8000
```

---

## 2. 디버깅 환경 설정

### 2.1 VSCode 디버거 설정

`.vscode/launch.json` 파일을 생성하고 다음 내용을 추가:

```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "FastAPI Server",
            "type": "python",
            "request": "launch",
            "module": "uvicorn",
            "args": [
                "server:app",
                "--reload",
                "--host", "127.0.0.1",
                "--port", "8000"
            ],
            "console": "integratedTerminal",
            "justMyCode": false
        },
        {
            "name": "Python: Current File",
            "type": "python",
            "request": "launch",
            "program": "${file}",
            "console": "integratedTerminal"
        }
    ]
}
```

### 2.2 디버깅 브레이크포인트 설정

1. VSCode에서 `server.py` 파일 열기
2. 코드 왼쪽 여백 클릭하여 브레이크포인트 설정 (빨간 점 표시)
3. F5 키를 눌러 디버거 시작
4. 브라우저에서 API 호출 시 브레이크포인트에서 실행 중지

---

## 3. API 엔드포인트 테스트

### 3.1 Swagger UI 사용
1. 서버 실행 후 `http://127.0.0.1:8000/docs` 접속
2. 각 엔드포인트 클릭 → "Try it out" 버튼
3. 요청 파라미터 입력 → "Execute" 클릭

### 3.2 curl 명령어 사용

**DXF 파일 업로드 및 분석:**
```bash
curl -X POST "http://127.0.0.1:8000/api/analyze" \
  -H "Content-Type: multipart/form-data" \
  -F "file=@data/test.dxf"
```

**메타데이터 저장:**
```bash
curl -X POST "http://127.0.0.1:8000/api/save_meta" \
  -H "Content-Type: application/json" \
  -d '{
    "filename": "test.dxf",
    "metadata": {"sheets": [], "columns": [], "beams": []}
  }'
```

**AI 기둥 분석:**
```bash
curl -X POST "http://127.0.0.1:8000/api/ai_analyze_columns" \
  -H "Content-Type: application/json" \
  -d '{
    "filename": "test.dxf",
    "sheet_id": "sheet_1",
    "bbox": [0, 0, 10000, 10000],
    "existing_data": []
  }'
```

**엑셀/PDF 내보내기:**
```bash
curl -X POST "http://127.0.0.1:8000/api/export" \
  -H "Content-Type: application/json" \
  -d '{
    "filename": "test.dxf",
    "sheets": [],
    "columns": [],
    "beams": []
  }'
```

### 3.3 Postman 사용
1. Postman 설치 및 실행
2. 새 요청 생성
3. HTTP 메서드, URL, Body 설정
4. Send 클릭

---

## 4. 일반적인 디버깅 시나리오

### 4.1 서버 시작 오류

**증상**: 서버가 시작되지 않음
```bash
# 오류 메시지 확인
python server.py
```

**확인 사항**:
1. Python 버전 확인: `python --version` (3.8+ 필요)
2. 의존성 설치: `pip install -r requirements.txt`
3. 포트 사용 중 확인: `netstat -ano | findstr :8000`

### 4.2 DXF 분석 오류

**증상**: `/api/analyze` 호출 시 오류 발생

**디버깅 단계**:
1. `server.py`의 [`analyze_file()`](server.py:50) 함수에 브레이크포인트 설정
2. 요청 전송
3. 변수 확인:
   - `file.filename`: 업로드된 파일명
   - `file_path`: 저장된 파일 경로
   - `result`: 분석 결과

**추가 로깅**:
```python
# analyze_file() 함수 내부에 로그 추가
print(f"[DEBUG] 파일 저장 경로: {file_path}")
print(f"[DEBUG] 분석 결과 키: {result.keys() if isinstance(result, dict) else 'Not a dict'}")
```

### 4.3 AI 분석 오류

**증상**: `/api/ai_analyze_columns` 또는 `/api/ai_analyze_beams` 호출 시 오류

**확인 사항**:
1. 환경 변수 설정 확인:
   ```bash
   # .env 파일 확인
   OPENROUTER_API_KEY=your_api_key_here
   OPENROUTER_MODEL=google/gemini-2.5-flash
   ```

2. API 키 유효성 확인:
   ```python
   # server.py에서 확인
   print(f"[DEBUG] API Key 설정됨: {bool(OPENROUTER_API_KEY)}")
   ```

3. OpenRouter API 응답 확인:
   ```python
   # ai_analyze_columns() 함수 내부
   print(f"[DEBUG] API 응답 상태 코드: {response.status_code}")
   print(f"[DEBUG] API 응답 내용: {response.text[:500]}")
   ```

### 4.4 엑셀/PDF 생성 오류

**증상**: `/api/export` 호출 시 파일 생성 실패

**디버깅 단계**:
1. `export_takeoff()` 함수에 브레이크포인트 설정
2. 요청 데이터 확인:
   ```python
   print(f"[DEBUG] 시트 수: {len(request.sheets)}")
   print(f"[DEBUG] 기둥 수: {len(request.columns)}")
   print(f"[DEBUG] 보 수: {len(request.beams)}")
   ```

3. 파일 권한 확인:
   - `output/` 디렉토리 쓰기 권한
   - 동일 파일명이 열려 있는지 확인

---

## 5. 로깅 활용

### 5.1 기본 로깅 추가

```python
import logging

# 로거 설정
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 사용 예시
logger.debug("디버그 메시지")
logger.info("정보 메시지")
logger.warning("경고 메시지")
logger.error("오류 메시지")
```

### 5.2 API 요청/응답 로깅

```python
from fastapi import Request
import time

@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    
    response = await call_next(request)
    
    process_time = time.time() - start_time
    print(f"[LOG] {request.method} {request.url.path} - {response.status_code} - {process_time:.3f}s")
    
    return response
```

### 5.3 takeoff_analysis.py 디버깅

```python
# takeoff_analysis.py 함수에 디버그 출력 추가
def analyze_dxf_json(file_path):
    print(f"[DEBUG] 분석 시작: {file_path}")
    
    # ... 기존 코드 ...
    
    print(f"[DEBUG] 감지된 시트 수: {len(detected_sheets)}")
    print(f"[DEBUG] 매칭된 기둥 수: {len(columns)}")
    print(f"[DEBUG] 매칭된 보 수: {len(beams)}")
    
    return {...}
```

---

## 6. 테스트 데이터 준비

### 6.1 테스트 DXF 파일
- `data/` 디렉토리에 테스트용 DXF 파일 배치
- 파일명: `test.dxf` 또는 실제 도면 파일

### 6.2 테스트 시나리오

| 시나리오 | 설명 |
|----------|------|
| 빈 파일 | 엔티티가 없는 DXF |
| 단일 시트 | 시트가 1개인 DXF |
| 다중 시트 | 여러 시트가 있는 DXF |
| 기둥만 있음 | 보가 없고 기둥만 있는 DXF |
| 보만 있음 | 기둥이 없고 보만 있는 DXF |
| 한글 텍스트 | 한글이 포함된 DXF |

---

## 7. 디버깅 체크리스트

### 서버 시작 전
- [ ] Python 3.8+ 설치 확인
- [ ] `pip install -r requirements.txt` 실행
- [ ] `.env` 파일에 `OPENROUTER_API_KEY` 설정
- [ ] `data/` 디렉토리에 테스트 DXF 파일 준비
- [ ] 포트 8000이 사용 중이지 않은지 확인

### API 테스트 시
- [ ] 서버가 정상 실행 중인지 확인
- [ ] Swagger UI (`/docs`) 접근 가능
- [ ] 요청 파라미터가 올바른지 확인
- [ ] 응답 상태 코드 확인 (200, 400, 500 등)

### 오류 발생 시
- [ ] 콘솔 출력 확인
- [ ] 로그 파일 확인 (있는 경우)
- [ ] 브레이크포인트에서 변수 값 확인
- [ ] 예외 메시지 확인

---

## 8. 유용한 디버깅 도구

### 8.1 Python 디버거 (pdb)
```python
# 코드 안에 디버거 삽입
import pdb; pdb.set_trace()

# 또는 Python 3.7+
breakpoint()
```

**주요 명령어**:
| 명령어 | 설명 |
|--------|------|
| `n` (next) | 다음 줄 실행 |
| `s` (step) | 함수 안으로 들어감 |
| `c` (continue) | 다음 브레이크포인트까지 계속 실행 |
| `p 변수명` | 변수 값 출력 |
| `l` (list) | 현재 위치 주변 코드 표시 |
| `q` (quit) | 디버거 종료 |

### 8.2 print 디버깅
```python
# 빠른 디버깅을 위한 print
print(f"[DEBUG] 변수값: {variable}")
print(f"[DEBUG] 타입: {type(variable)}")
print(f"[DEBUG] 길이: {len(variable) if hasattr(variable, '__len__') else 'N/A'}")
```

### 8.3 rich 라이브러리
```python
from rich import print
from rich.pretty import pprint

# 예쁜 출력
pprint(large_dict)
```

---

## 9. 일반적인 오류 및 해결

| 오류 메시지 | 원인 | 해결 방법 |
|-------------|------|-----------|
| `ModuleNotFoundError` | 의존성 미설치 | `pip install -r requirements.txt` |
| `Address already in use` | 포트 8000 사용 중 | 다른 프로세스 종료 또는 포트 변경 |
| `OPENROUTER_API_KEY not found` | 환경 변수 미설정 | `.env` 파일 확인 |
| `File not found` | DXF 파일 경로 오류 | `data/` 디렉토리 확인 |
| `JSON decode error` | AI 응답 파싱 실패 | API 응답 내용 확인 |
| `PermissionError` | 파일이 열려 있음 | 엑셀 파일 닫기 |

---

## 10. 디버깅 순서 추천

1. **서버 시작**: `python server.py`로 서버 시작
2. **Swagger UI 접속**: `http://127.0.0.1:8000/docs`에서 API 테스트
3. **단순 요청부터**: `/api/analyze`로 간단한 DXF 파일 업로드
4. **응답 확인**: 반환된 JSON 데이터 확인
5. **문제 발생 시**: 브레이크포인트 설정 후 단계별 실행
6. **로그 추가**: 필요한 위치에 print/log 추가
7. **수정 후 재테스트**: 수정 사항 적용 후 다시 테스트
