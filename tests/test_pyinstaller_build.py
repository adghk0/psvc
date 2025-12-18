"""PyInstaller 빌드 및 실행 파일 테스트

실제 PyInstaller를 사용하여:
1. 최소 의존성 앱 빌드
2. 빌드된 실행 파일 실행 검증
3. 릴리스 메타데이터 생성 확인
"""

import asyncio
import sys
import os
import tempfile
import shutil
import subprocess
import json
from pathlib import Path

# 프로젝트 루트 찾기
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT / "src"))

from psvc import Service
from psvc.builder import Builder


def create_minimal_test_app(temp_dir: Path) -> Path:
    """최소한의 테스트 애플리케이션 생성"""
    app_content = '''#!/usr/bin/env python3
"""Minimal test application for PyInstaller"""
import sys

def main():
    # 버전 정보 출력
    print("TestApp v1.0.0")
    print(f"Python {sys.version}")
    print("Build: SUCCESS")
    return 0

if __name__ == '__main__':
    sys.exit(main())
'''
    app_file = temp_dir / 'test_app.py'
    app_file.write_text(app_content)
    return app_file


def create_test_spec(temp_dir: Path, app_file: Path) -> Path:
    """PyInstaller spec 파일 생성 (onefile 모드)"""
    spec_content = f'''# -*- mode: python ; coding: utf-8 -*-

a = Analysis(
    [{repr(str(app_file))}],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={{}},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='test_app',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
'''
    spec_file = temp_dir / 'test_app.spec'
    spec_file.write_text(spec_content)
    return spec_file


def test_pyinstaller_build():
    """PyInstaller 빌드 테스트"""
    print("\n" + "="*70)
    print("PyInstaller Build Test")
    print("="*70)

    # 임시 디렉토리 생성
    temp_root = Path(tempfile.mkdtemp(prefix='psvc_pyinstaller_test_'))
    release_path = temp_root / 'releases'
    release_path.mkdir()

    print(f"\n📁 Test directory: {temp_root}")
    print(f"📁 Release path: {release_path}")

    try:
        # 1. 테스트 앱 생성
        print("\n[1/5] Creating test application...")
        app_file = create_minimal_test_app(temp_root)
        spec_file = create_test_spec(temp_root, app_file)
        print(f"  ✓ Created: {app_file.name}")
        print(f"  ✓ Created: {spec_file.name}")

        # 2. Service 생성 및 빌드
        print("\n[2/5] Building with PyInstaller...")
        print("  ⏳ This may take 30-60 seconds...")

        class TestService(Service):
            def __init__(self):
                super().__init__('TestService', str(temp_root))
                self.set_config('PSVC', 'version', '1.0.0')
                self.version = '1.0.0'

            async def run(self):
                pass

        service = TestService()

        # 빌드 실행
        version_dir = service.build(
            version='1.0.0',
            spec_file=str(spec_file),
            release_path=str(release_path),
            exclude_patterns=['*.conf', '*.log', '*.pyc']
        )

        print(f"  ✓ Build completed: {version_dir}")

        # 3. 빌드 결과물 검증
        print("\n[3/5] Verifying build artifacts...")

        # 실행 파일 찾기
        exe_name = 'test_app.exe' if sys.platform == 'win32' else 'test_app'
        exe_path = version_dir / exe_name

        assert exe_path.exists(), f"Executable not found: {exe_path}"
        print(f"  ✓ Executable found: {exe_name}")

        exe_size = exe_path.stat().st_size
        print(f"  ✓ File size: {exe_size / 1024 / 1024:.2f} MB")

        # status.json 확인
        status_file = version_dir / 'status.json'
        assert status_file.exists(), "status.json not found"
        print(f"  ✓ status.json created")

        with open(status_file, 'r', encoding='utf-8') as f:
            metadata = json.load(f)

        assert metadata['version'] == '1.0.0', "Version mismatch"
        assert metadata['status'] == 'draft', "Status should be draft"
        assert len(metadata['files']) > 0, "No files in metadata"
        print(f"  ✓ Metadata valid: {len(metadata['files'])} file(s)")

        # 파일 정보 확인
        for file_info in metadata['files']:
            print(f"    - {file_info['path']}: {file_info['size']} bytes")
            print(f"      Checksum: {file_info['checksum'][:20]}...")

        # 4. 실행 파일 실행 테스트
        print("\n[4/5] Testing executable...")
        print(f"  Running: {exe_path}")

        result = subprocess.run(
            [str(exe_path)],
            capture_output=True,
            text=True,
            timeout=10,
            cwd=str(version_dir)
        )

        print(f"  Exit code: {result.returncode}")
        print(f"  Output:")
        for line in result.stdout.strip().split('\n'):
            print(f"    {line}")

        assert result.returncode == 0, f"Executable failed with code {result.returncode}"
        assert "TestApp v1.0.0" in result.stdout, "Version string not found in output"
        assert "Build: SUCCESS" in result.stdout, "Success message not found"
        print(f"  ✓ Executable runs successfully")

        # 5. 릴리스 승인 테스트
        print("\n[5/5] Testing release approval...")

        service.release(
            version='1.0.0',
            approve=True,
            release_notes='Test release with PyInstaller',
            release_path=str(release_path)
        )

        # 상태 확인
        with open(status_file, 'r', encoding='utf-8') as f:
            metadata = json.load(f)

        assert metadata['status'] == 'approved', "Status should be approved"
        assert metadata['release_notes'] == 'Test release with PyInstaller'
        print(f"  ✓ Release approved successfully")
        print(f"  ✓ Status: {metadata['status']}")
        print(f"  ✓ Release notes: {metadata['release_notes']}")

        print("\n" + "="*70)
        print("✅ Test PASSED: PyInstaller build workflow successful!")
        print("="*70)

        return True

    except subprocess.TimeoutExpired:
        print("\n❌ Executable timeout")
        return False
    except Exception as e:
        print(f"\n❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        # 임시 디렉토리 정리
        print(f"\n🧹 Cleaning up: {temp_root}")
        shutil.rmtree(temp_root, ignore_errors=True)


if __name__ == '__main__':
    success = test_pyinstaller_build()
    sys.exit(0 if success else 1)
