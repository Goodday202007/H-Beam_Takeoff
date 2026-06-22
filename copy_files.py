import shutil
from datetime import datetime

# 복사할 파일 목록
files_to_copy = [
    "index.html",
    "server.py",
    "takeoff_analysis.py"
]

# 현재 날짜와 시간 가져오기
now = datetime.now()
date_str = now.strftime("%Y%m%d")
minute_str = now.strftime("%H%M")

# 각 파일의 복사본 생성
for original_file in files_to_copy:
    # 파일명과 확장자 분리
    parts = original_file.rsplit('.', 1)
    if len(parts) == 2:
        filename, extension = parts
    else:
        filename = parts[0]
        extension = ""
    
    # 복사본 파일명 생성: 파일명_b현재일자_현재분.파일확장자
    if extension:
        backup_name = f"{filename}_b{date_str}_{minute_str}.{extension}"
    else:
        backup_name = f"{filename}_b{date_str}_{minute_str}"
    
    # 파일 복사
    try:
        shutil.copy2(original_file, backup_name)
        print(f"복사 완료: {original_file} -> {backup_name}")
    except FileNotFoundError:
        print(f"파일을 찾을 수 없음: {original_file}")
    except Exception as e:
        print(f"오류 발생 ({original_file}): {e}")

print("\n모든 파일 처리가 완료되었습니다.")
