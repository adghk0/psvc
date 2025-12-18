# 🧪 PyService 테스트 스위트

PyService의 빌드 및 릴리스 시스템에 대한 통합 테스트 모음입니다.

## 🎯 테스트 구성

### 빠른 검증 (5초 이내)
프로토콜과 로직 검증용 - 더미 파일 사용

| 테스트 | 시간 | 설명 |
|--------|------|------|
| [test_build_release_inte.py](test_build_release_inte.py) | ~3초 | 빌드 + 릴리스 승인 워크플로우 |
| [test_self_update_simple.py](test_self_update_simple.py) | ~3초 | 다중 파일 업데이트 + 체크섬 검증 |

### PyInstaller 검증 (30초~3분)
실제 빌드 및 실행 파일 검증

| 테스트 | 시간 | 설명 |
|--------|------|------|
| [test_pyinstaller_build.py](test_pyinstaller_build.py) | ~30초 | PyInstaller 빌드 + 실행 검증 |
| [test_full_update_workflow.py](test_full_update_workflow.py) | ~2-3분 | 전체 업데이트 워크플로우 |

## 🚀 빠른 시작

### 환경 설정
```bash
source .venv/bin/activate
pip install -e ".[dev]"  # pyinstaller 포함
```

### 모든 테스트 실행
```bash
# 빠른 검증 (개발 중)
python tests/test_build_release_inte.py
python tests/test_self_update_simple.py

# PyInstaller 검증 (통합 전)
python tests/test_pyinstaller_build.py

# 전체 워크플로우 (릴리스 전)
python tests/test_full_update_workflow.py
```

## 📋 테스트 상세

### 1. test_build_release_inte.py ✅
**빌드 및 릴리스 통합 테스트**

```python
# 시나리오
1. 릴리스 서버 시작
2. 개발 서비스가 v1.0.0 빌드
3. 릴리스 서버에 승인 요청
4. draft → approved 변경
5. 승인 결과 검증
```

**검증 항목**
- ✅ 빌드 디렉토리 생성
- ✅ status.json 생성
- ✅ 상태 변경 (draft → approved)
- ✅ 릴리스 노트 저장
- ✅ 서버-클라이언트 통신

---

### 2. test_self_update_simple.py ✅
**자가 업데이트 프로토콜 테스트**

```python
# 시나리오
1. v1.0.0 (approved) 생성
2. v0.9.0 (draft) 생성
3. 업데이트 서버 시작
4. v0.9.0 클라이언트 업데이트 감지
5. v1.0.0 다운로드 및 검증
```

**검증 항목**
- ✅ Semantic versioning 비교
- ✅ 다중 파일 전송
- ✅ SHA256 체크섬 검증
- ✅ 디렉토리 구조 보존
- ✅ approved 버전만 제공

---

### 3. test_pyinstaller_build.py ✅
**PyInstaller 빌드 테스트**

```python
# 시나리오
1. 최소 의존성 테스트 앱 생성
2. PyInstaller로 빌드
3. 실행 파일 실행
4. 출력 검증
5. 릴리스 승인
```

**검증 항목**
- ✅ PyInstaller 빌드 성공
- ✅ 실행 파일 생성 (7.1 MB)
- ✅ 실행 파일 실행 (exit code 0)
- ✅ 출력 검증 ("TestApp v1.0.0")
- ✅ 메타데이터 생성
- ✅ 체크섬 계산

**출력 예시**
```
🚀 Building TestService v1.0.0
======================================================================
[1/5] 🔧 Running PyInstaller...
  ✓ PyInstaller completed
[2/5] 📦 Copying build artifacts...
  ✓ Copied 1 file(s)
[3/5] 🔐 Calculating checksums...
  ✓ 1 file(s) processed
[4/5] 📝 Creating metadata...
  ✓ Metadata for 1 file(s)
[5/5] 💾 Saving status.json...
  ✓ status.json

======================================================================
✅ Build Completed: /tmp/.../releases/1.0.0
======================================================================
  Version:      1.0.0
  Status:       draft
  Platform:     linux
  Files:        1 file(s)
  Total size:   7.11 MB
  Build time:   2025-12-17T00:50:58+00:00
======================================================================
```

---

### 4. test_full_update_workflow.py
**전체 업데이트 워크플로우 테스트**

```python
# 시나리오
1. v1.0.0 및 v0.9.0 PyInstaller 빌드
2. v1.0.0 승인 (v0.9.0은 draft)
3. 업데이트 서버 시작
4. v0.9.0 실행 파일 실행
5. 자동 업데이트 감지 및 다운로드
6. 다운로드된 v1.0.0 실행 검증
```

**검증 항목**
- 🔄 두 버전 PyInstaller 빌드
- 🔄 업데이트 서버 시작
- 🔄 업데이트 감지 (0.9.0 → 1.0.0)
- 🔄 v1.0.0 다운로드
- 🔄 체크섬 검증
- 🔄 다운로드된 파일 실행

---

## 🛠️ 문제 해결

### PyInstaller 빌드 실패
```
ERROR: option(s) not allowed: --specpath
```
→ **해결됨**: spec 파일 사용 시 자동으로 해당 옵션 제거

### 실행 파일 찾을 수 없음
```
FileNotFoundError: Executable not found
```
→ spec 파일의 `name` 설정 확인
→ 버전 문자열의 점(.) → 언더스코어(_) 변환 확인

### 포트 충돌
```
OSError: Address already in use
```
→ 테스트가 사용하는 포트: 50003-50006
→ 다른 프로세스 종료 또는 포트 변경

---

## 📊 성능 벤치마크

**환경**: WSL2, Ubuntu 22.04, Python 3.12

| 테스트 | 소요 시간 | 파일 크기 | 메모리 |
|--------|----------|----------|--------|
| test_build_release_inte | ~3초 | - | ~50 MB |
| test_self_update_simple | ~3초 | - | ~60 MB |
| test_pyinstaller_build | ~30초 | 7.1 MB | ~200 MB |
| test_full_update_workflow | ~120초 | 16.8 MB | ~400 MB |

---

## 🎨 코드 스타일

Builder 클래스는 다음 원칙을 따릅니다:

1. **Dataclass 활용**: `BuildMetadata`로 타입 안전성 확보
2. **명확한 에러**: `BuildError` 예외로 빌드 실패 원인 명시
3. **파이프라인 구조**: 각 단계가 독립적이고 재사용 가능
4. **이모지 활용**: 로그 출력을 직관적으로 시각화
5. **불변성**: 메타데이터는 dataclass로 불변 보장

```python
# 깔끔한 사용 예시
builder = Builder("MyApp", __file__)
version_dir = builder.build(
    version="1.0.0",
    spec_file="app.spec",
    exclude_patterns=['*.conf']
)
```

---

## 📚 참고 문서

- [TEST_RESULTS.md](TEST_RESULTS.md) - 테스트 결과 요약
- [PYINSTALLER_TESTS.md](PYINSTALLER_TESTS.md) - PyInstaller 테스트 가이드
- [../src/psvc/builder.py](../src/psvc/builder.py) - Builder 클래스 소스

---

## 🚦 CI/CD 통합

```yaml
# .github/workflows/test.yml 예시
name: Test

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - uses: actions/setup-python@v4
        with:
          python-version: '3.12'
      - run: |
          pip install -e ".[dev]"
          python tests/test_build_release_inte.py
          python tests/test_self_update_simple.py
          python tests/test_pyinstaller_build.py
```

---

**Made with 🔥 and ☕ by PyService Team**
