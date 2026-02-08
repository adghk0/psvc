# PyService 테스트 스위트

PyService 프레임워크의 pytest 기반 테스트 모음입니다.

## 빠른 시작

### 환경 설정

```bash
# 가상환경 활성화
source .venv/bin/activate

# 개발 의존성 설치
pip install -e ".[dev]"

# pytest 설치 확인
pytest --version
```

### 모든 테스트 실행

```bash
# 전체 테스트 실행
pytest

# 상세 출력
pytest -v

# 특정 파일만 실행
pytest tests/test_version.py

# 특정 테스트만 실행
pytest tests/test_version.py::TestParseVersion::test_full_version
```

## 테스트 구조

```
tests/
├── conftest.py              # pytest 설정 및 공통 픽스처
├── test_version.py          # 버전 유틸리티 테스트
├── test_checksum.py         # 체크섬 유틸리티 테스트
├── test_config.py           # 설정 관리 테스트
├── test_build_release.py    # 빌드/릴리스 통합 테스트
└── test_update.py           # 업데이트 기능 테스트
```

## 테스트 분류

### 단위 테스트 (빠름 - 1초 이내)

버전, 체크섬, 설정 등 개별 유틸리티 기능 테스트

```bash
pytest -m unit
pytest tests/test_version.py
pytest tests/test_checksum.py
pytest tests/test_config.py
```

### 통합 테스트 (중간 - 5초 이내)

여러 컴포넌트 간 상호작용 테스트

```bash
pytest -m integration
pytest tests/test_build_release.py
pytest tests/test_update.py
```

### 비동기 테스트

asyncio 기반 비동기 기능 테스트

```bash
pytest -m asyncio
```

## 주요 픽스처

테스트에서 사용 가능한 공통 픽스처 (conftest.py에 정의):

### 디렉토리 픽스처

- **temp_dir**: 임시 디렉토리 (자동 정리)
- **release_dir**: 릴리스 디렉토리
- **update_dir**: 업데이트 디렉토리

```python
def test_example(temp_dir, release_dir):
    assert temp_dir.exists()
    assert release_dir.exists()
```

### 파일 픽스처

- **dummy_app_file**: 테스트용 더미 앱 파일
- **spec_file**: PyInstaller spec 파일

```python
def test_example(dummy_app_file, spec_file):
    assert dummy_app_file.exists()
    assert spec_file.exists()
```

### 헬퍼 픽스처

- **create_build**: 더미 빌드 생성 함수

```python
def test_example(release_dir, create_build):
    version_dir = create_build(release_dir, '1.0.0', 'approved')
    assert version_dir.exists()
```

### 이벤트 루프 픽스처

- **event_loop**: 비동기 테스트용 이벤트 루프

```python
@pytest.mark.asyncio
async def test_example(event_loop):
    await asyncio.sleep(0.1)
```

## 테스트 작성 가이드

### 기본 구조

```python
"""모듈 설명"""

import pytest
from psvc import ...


class TestFeature:
    """기능 테스트 클래스"""

    def test_basic_case(self):
        """기본 케이스 테스트"""
        result = some_function()
        assert result == expected

    def test_edge_case(self):
        """엣지 케이스 테스트"""
        with pytest.raises(ValueError):
            some_function(invalid_input)

    def test_with_fixture(self, temp_dir):
        """픽스처 사용 테스트"""
        file_path = temp_dir / 'test.txt'
        file_path.write_text('test')
        assert file_path.exists()
```

### 비동기 테스트

```python
import pytest
import asyncio


class TestAsync:
    """비동기 테스트"""

    @pytest.mark.asyncio
    async def test_async_function(self):
        """비동기 함수 테스트"""
        result = await some_async_function()
        assert result == expected

    @pytest.mark.asyncio
    async def test_with_timeout(self):
        """타임아웃이 있는 비동기 테스트"""
        try:
            result = await asyncio.wait_for(
                some_async_function(),
                timeout=5.0
            )
            assert result == expected
        except asyncio.TimeoutError:
            pytest.fail("함수가 타임아웃됨")
```

### 예외 테스트

```python
def test_exception():
    """예외 발생 테스트"""
    with pytest.raises(ValueError, match="특정 메시지"):
        raise ValueError("특정 메시지")

def test_no_exception():
    """예외가 발생하지 않음을 테스트"""
    try:
        some_function()
    except Exception as e:
        pytest.fail(f"예외가 발생하지 않아야 함: {e}")
```

## 임시 파일 정리

모든 테스트는 자동으로 정리됩니다:

- **temp_dir 픽스처**: 테스트 종료 후 자동 삭제
- **release_dir, update_dir**: temp_dir 하위이므로 함께 삭제

수동 정리가 필요한 경우:

```python
import shutil

def test_with_cleanup(temp_dir):
    # 테스트 로직
    ...

    # 수동 정리 (선택사항 - 픽스처가 자동으로 정리함)
    shutil.rmtree(temp_dir, ignore_errors=True)
```

## 성능 벤치마크

평균 실행 시간 (WSL2, Ubuntu 22.04, Python 3.12):

| 테스트 파일 | 실행 시간 | 테스트 수 |
|------------|----------|----------|
| test_version.py | ~0.1초 | 12 |
| test_checksum.py | ~0.2초 | 15 |
| test_config.py | ~0.3초 | 6 |
| test_build_release.py | ~3초 | 4 |
| test_update.py | ~5초 | 4 |

**전체**: ~10초 (41개 테스트)

## 커버리지 확인

```bash
# 커버리지 실행
pytest --cov=src/psvc --cov-report=html

# 결과 확인
open htmlcov/index.html
```

## 디버깅

### 실패한 테스트만 재실행

```bash
pytest --lf  # last failed
```

### 특정 테스트 디버깅

```bash
# pdb로 디버깅
pytest --pdb

# 상세 출력
pytest -vv

# 출력 캡처 비활성화
pytest -s
```

### 로그 출력 보기

```bash
pytest --log-cli-level=DEBUG
```

## CI/CD 통합

GitHub Actions 예시:

```yaml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ['3.10', '3.11', '3.12']

    steps:
      - uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: ${{ matrix.python-version }}

      - name: Install dependencies
        run: |
          pip install -e ".[dev]"

      - name: Run tests
        run: |
          pytest --cov=src/psvc --cov-report=xml

      - name: Upload coverage
        uses: codecov/codecov-action@v3
```

## 문제 해결

### pytest를 찾을 수 없음

```bash
pip install pytest pytest-asyncio
```

### 모듈을 임포트할 수 없음

```bash
# editable 모드로 설치
pip install -e .
```

### 비동기 테스트 실패

```bash
# pytest-asyncio 설치
pip install pytest-asyncio

# pytest.ini에 asyncio_mode 설정 확인
```

### 포트 충돌

테스트에서 사용하는 포트:
- 50103: test_build_release.py
- 50104: test_update.py

다른 프로세스가 사용 중이면 테스트가 실패할 수 있습니다.

```bash
# 포트 사용 확인 (Linux)
sudo lsof -i :50103

# 프로세스 종료
kill <PID>
```

## 기여 가이드

새로운 테스트 추가 시:

1. **명확한 테스트 이름** 사용
   - ✅ `test_version_parsing_with_patch`
   - ❌ `test_1`

2. **docstring 작성**
   - 테스트 목적 명시

3. **적절한 픽스처 사용**
   - 중복 코드 최소화

4. **정리 로직 확인**
   - 임시 파일/디렉토리 정리

5. **마커 추가**
   - `@pytest.mark.unit`, `@pytest.mark.integration` 등

## 참고 문서

- [pytest 공식 문서](https://docs.pytest.org/)
- [pytest-asyncio](https://pytest-asyncio.readthedocs.io/)
- [PyService 문서](../README.md)

---

**Made with ☕ by PyService Team**
