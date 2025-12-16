# PyInstaller 빌드 및 업데이트 테스트

실제 PyInstaller를 사용한 빌드 및 자가 업데이트 테스트 가이드입니다.

## 테스트 개요

### 1. PyInstaller 빌드 테스트 ✅
**파일**: [test_pyinstaller_build.py](test_pyinstaller_build.py)

**소요 시간**: ~30초

**테스트 내용**:
- 최소 의존성 앱 PyInstaller 빌드
- 빌드된 실행 파일 실행 검증
- 릴리스 메타데이터 생성 확인
- 릴리스 승인 워크플로우

**실행 방법**:
```bash
source .venv/bin/activate
python tests/test_pyinstaller_build.py
```

**검증 항목**:
- ✅ PyInstaller 빌드 성공
- ✅ 실행 파일 생성 (test_app)
- ✅ 실행 파일 실행 (exit code 0)
- ✅ 출력 검증 ("TestApp v1.0.0", "Build: SUCCESS")
- ✅ status.json 생성
- ✅ 체크섬 및 메타데이터 생성
- ✅ 릴리스 승인 (draft → approved)

**실행 결과 예시**:
```
======================================================================
PyInstaller Build Test
======================================================================

[1/5] Creating test application...
  ✓ Created: test_app.py
  ✓ Created: test_app.spec

[2/5] Building with PyInstaller...
  ⏳ This may take 30-60 seconds...
  ✓ Build completed: /tmp/.../releases/1.0.0

[3/5] Verifying build artifacts...
  ✓ Executable found: test_app
  ✓ File size: 7.11 MB
  ✓ status.json created
  ✓ Metadata valid: 1 file(s)
    - test_app: 7454112 bytes
      Checksum: sha256:abc123...

[4/5] Testing executable...
  Running: /tmp/.../releases/1.0.0/test_app
  Exit code: 0
  Output:
    TestApp v1.0.0
    Python 3.12.3 (main, ...)
    Build: SUCCESS
  ✓ Executable runs successfully

[5/5] Testing release approval...
  ✓ Release approved successfully
  ✓ Status: approved
  ✓ Release notes: Test release with PyInstaller

✅ Test PASSED: PyInstaller build workflow successful!
```

---

### 2. 전체 업데이트 워크플로우 테스트
**파일**: [test_full_update_workflow.py](test_full_update_workflow.py)

**소요 시간**: ~2-3분 (두 버전 빌드)

**테스트 내용**:
- v0.9.0 및 v1.0.0 PyInstaller 빌드
- v1.0.0 승인 (v0.9.0은 draft 상태)
- 업데이트 서버 시작 (v1.0.0만 제공)
- v0.9.0 실행 파일 실행
- 자동 업데이트 감지 및 v1.0.0 다운로드
- 다운로드된 v1.0.0 실행 검증

**실행 방법**:
```bash
source .venv/bin/activate
python tests/test_full_update_workflow.py
```

**검증 항목**:
- ✅ v1.0.0 빌드 (approved)
- ✅ v0.9.0 빌드 (draft)
- ✅ 업데이트 서버 시작
- ✅ v0.9.0 실행 파일 실행
- ✅ 업데이트 감지 (0.9.0 → 1.0.0)
- ✅ v1.0.0 다운로드
- ✅ 다운로드된 파일 체크섬 검증
- ✅ 다운로드된 v1.0.0 실행 검증

**실행 결과 예시**:
```
======================================================================
Full Update Workflow Test (with PyInstaller)
======================================================================

[1/5] Building v1.0.0 (update version)...
  ⏳ This may take 1-2 minutes...
  Building v1.0.0...
    ✓ Built: /tmp/.../releases/1.0.0
    ✓ Executable: app_v1_0_0 (8.41 MB)
  ✓ Build completed in 6.4s

[2/5] Approving v1.0.0...
  ✓ v1.0.0 approved

[3/5] Building v0.9.0 (current version)...
  ⏳ This may take 1-2 minutes...
  Building v0.9.0...
    ✓ Built: /tmp/.../releases/0.9.0
    ✓ Executable: app_v0_9_0 (8.39 MB)
  ✓ Build completed in 6.2s

[4/5] Starting update server and running v0.9.0...
  ✓ Update server started
  Running: app_v0_9_0
  Exit code: 0
  Output:
    UpdatableApp v0.9.0 starting...
    Connected to update server, cid=1
    Checking for updates...
    Update available: 0.9.0 -> 1.0.0
    Downloading update...
    Update downloaded successfully!

[5/5] Verifying update results...
  ✓ Result file exists
  Old version: 0.9.0
  New version: 1.0.0
  Success: True
  ✓ Download path exists
  ✓ Downloaded executable: app_v1_0_0

  Testing downloaded v1.0.0...
  Exit code: 0
  ✓ v1.0.0 reports correct version

✅ Test PASSED: Full update workflow successful!

Summary:
  - Built v0.9.0 and v1.0.0 with PyInstaller
  - v0.9.0 detected update and downloaded v1.0.0
  - Downloaded v1.0.0 runs correctly
```

---

## 간단한 더미 테스트 (빠른 검증용)

빌드 시간을 절약하기 위해 더미 파일을 사용하는 간단한 테스트도 제공됩니다:

### test_build_release_inte.py ✅
- **소요 시간**: ~5초
- **내용**: 빌드 시뮬레이션 + 릴리스 승인 워크플로우
- **용도**: 릴리스 서버 통신 및 승인 로직 검증

### test_self_update_simple.py ✅
- **소요 시간**: ~5초
- **내용**: 더미 파일 업데이트 + 다중 파일 검증
- **용도**: 업데이트 프로토콜 및 체크섬 검증 로직 검증

---

## 테스트 전 준비사항

### 필수 패키지 설치
```bash
source .venv/bin/activate
pip install pyinstaller
```

### 권장 사항
- PyInstaller 첫 빌드는 시간이 오래 걸림 (~1분)
- WSL 또는 Linux 환경에서 테스트 권장
- Windows에서는 .exe 파일 생성, Linux에서는 ELF 바이너리 생성

---

## 테스트 순서 권장

1. **빠른 검증** (개발 중):
   ```bash
   python tests/test_build_release_inte.py
   python tests/test_self_update_simple.py
   ```

2. **PyInstaller 빌드 검증** (통합 전):
   ```bash
   python tests/test_pyinstaller_build.py
   ```

3. **전체 워크플로우 검증** (릴리스 전):
   ```bash
   python tests/test_full_update_workflow.py
   ```

---

## 문제 해결

### PyInstaller 빌드 실패
```
ERROR: option(s) not allowed: --specpath
```
→ builder.py 수정 완료: spec 파일 사용 시 해당 옵션 제거

### 실행 파일 찾을 수 없음
```
FileNotFoundError: Executable not found
```
→ spec 파일의 name 설정 확인, 버전 문자열의 점(.) 처리 확인

### 업데이트 서버 연결 실패
```
Failed to connect to update server
```
→ 서버 포트 충돌 확인 (50003-50006 사용 중)
→ 방화벽 설정 확인

---

## 성능 벤치마크

**테스트 환경**: WSL2, Ubuntu 22.04, Python 3.12

| 테스트 | 소요 시간 | 파일 크기 |
|--------|----------|----------|
| test_build_release_inte.py | ~3초 | - |
| test_self_update_simple.py | ~3초 | - |
| test_pyinstaller_build.py | ~30초 | 7.1 MB |
| test_full_update_workflow.py | ~120초 | 16.8 MB (2개 버전) |

---

## 다음 단계

1. ✅ PyInstaller 빌드 자동화
2. ✅ 다중 파일 업데이트 프로토콜
3. ✅ 체크섬 기반 무결성 검증
4. 🔄 자동 재시작 및 설치 로직
5. 🔄 차등 업데이트 (delta update)
6. 🔄 롤백 자동화

---

## 참고사항

- 모든 테스트는 임시 디렉토리를 사용하며 자동 정리됨
- 실제 프로덕션 환경에서는 `Service.on()` 메서드 사용
- 테스트 환경에서는 `_service()` 직접 호출로 이벤트 루프 제어
- PyInstaller 빌드 캐시는 자동으로 관리됨
