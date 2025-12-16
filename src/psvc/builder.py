"""빌드 자동화 모듈"""

import os
import sys
import shutil
import json
import subprocess
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

from .utils.version import is_valid_version
from .utils.checksum import calculate_directory_checksums


class Builder:
    """PyInstaller 빌드 자동화 클래스"""

    def __init__(
        self,
        service_name: str,
        root_path: str,
        release_path: str = None
    ):
        """
        Args:
            service_name: 서비스 이름
            root_path: 서비스 루트 경로 (__file__ 경로)
            release_path: 릴리스 저장 경로 (기본: {root_path}/releases)
        """
        self.service_name = service_name
        self.root_path = Path(root_path).parent if os.path.isfile(root_path) else Path(root_path)

        if release_path:
            self.release_path = Path(release_path)
        else:
            self.release_path = self.root_path / 'releases'

        self.release_path.mkdir(parents=True, exist_ok=True)

    def build(
        self,
        version: str,
        spec_file: str = None,
        exclude_patterns: List[str] = None,
        **pyinstaller_options
    ) -> Path:
        """
        PyInstaller로 실행 파일 빌드

        Args:
            version: Semantic version (예: "1.0.0")
            spec_file: PyInstaller spec 파일 경로
            exclude_patterns: 제외할 파일 패턴 (기본: ['*.conf', '*.log'])
            **pyinstaller_options: PyInstaller 추가 옵션

        Returns:
            빌드된 릴리스 디렉토리 경로

        Raises:
            ValueError: 잘못된 버전 형식
            RuntimeError: 빌드 실패
        """
        # 버전 검증
        if not is_valid_version(version):
            raise ValueError(f"Invalid version format: {version}")

        print(f"=== Building {self.service_name} v{version} ===")

        # 기본 제외 패턴
        if exclude_patterns is None:
            exclude_patterns = ['*.conf', '*.log', '*.pyc', '__pycache__']

        # 버전 디렉토리 생성
        version_dir = self.release_path / version
        if version_dir.exists():
            print(f"Warning: Version {version} already exists. Overwriting...")
            shutil.rmtree(version_dir)

        version_dir.mkdir(parents=True, exist_ok=True)

        # 1. PyInstaller 실행
        print("\n[1/5] Running PyInstaller...")
        dist_path = self._run_pyinstaller(spec_file, **pyinstaller_options)

        # 2. 빌드 결과물 복사
        print("\n[2/5] Copying build artifacts...")
        self._copy_artifacts(dist_path, version_dir, exclude_patterns)

        # 3. 체크섬 계산
        print("\n[3/5] Calculating checksums...")
        checksums = calculate_directory_checksums(str(version_dir), exclude_patterns)

        # 4. 메타데이터 생성
        print("\n[4/5] Creating metadata...")
        metadata = self._create_metadata(version, checksums)

        # 5. status.json 저장
        print("\n[5/5] Saving status.json...")
        status_file = version_dir / 'status.json'
        with open(status_file, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        print(f"\n✓ Build completed: {version_dir}")
        print(f"  Status: {metadata['status']}")
        print(f"  Files: {len(metadata['files'])} files")
        print(f"  Total size: {sum(f['size'] for f in metadata['files']) / 1024 / 1024:.2f} MB")

        return version_dir

    def _run_pyinstaller(
        self,
        spec_file: str = None,
        **options
    ) -> Path:
        """PyInstaller 실행"""
        # 빌드 임시 디렉토리
        build_dir = self.root_path / 'build'
        dist_dir = self.root_path / 'dist'

        cmd = [sys.executable, '-m', 'PyInstaller']

        if spec_file:
            # spec 파일 사용
            spec_path = self.root_path / spec_file
            if not spec_path.exists():
                raise FileNotFoundError(f"Spec file not found: {spec_path}")
            cmd.append(str(spec_path))
        else:
            # 기본 옵션으로 빌드
            raise ValueError("spec_file is required for build")

        # 공통 옵션
        cmd.extend([
            '--distpath', str(dist_dir),
            '--workpath', str(build_dir / 'work'),
            '--specpath', str(build_dir),
            '--clean',
        ])

        # 추가 옵션
        for key, value in options.items():
            if value is True:
                cmd.append(f'--{key}')
            elif value is not False:
                cmd.extend([f'--{key}', str(value)])

        print(f"  Command: {' '.join(cmd)}")

        # 실행
        result = subprocess.run(cmd, cwd=str(self.root_path))

        if result.returncode != 0:
            raise RuntimeError(f"PyInstaller failed with code {result.returncode}")

        # dist 디렉토리에서 결과 찾기
        dist_contents = list(dist_dir.iterdir())
        if not dist_contents:
            raise RuntimeError("No output found in dist directory")

        # 첫 번째 디렉토리 또는 파일 반환
        return dist_contents[0]

    def _copy_artifacts(
        self,
        source: Path,
        destination: Path,
        exclude_patterns: List[str]
    ):
        """빌드 결과물 복사 (제외 패턴 적용)"""
        import fnmatch

        if source.is_file():
            # 단일 파일
            shutil.copy2(source, destination / source.name)
            print(f"  Copied: {source.name}")
        else:
            # 디렉토리
            for item in source.rglob('*'):
                if item.is_file():
                    # 제외 패턴 확인
                    if any(fnmatch.fnmatch(item.name, pattern) for pattern in exclude_patterns):
                        print(f"  Skipped: {item.relative_to(source)} (excluded)")
                        continue

                    # 상대 경로 유지
                    rel_path = item.relative_to(source)
                    dest_file = destination / rel_path

                    # 디렉토리 생성
                    dest_file.parent.mkdir(parents=True, exist_ok=True)

                    # 파일 복사
                    shutil.copy2(item, dest_file)
                    print(f"  Copied: {rel_path}")

    def _create_metadata(
        self,
        version: str,
        checksums: Dict[str, str]
    ) -> dict:
        """메타데이터 생성"""
        version_dir = self.release_path / version

        files = []
        for rel_path, checksum in checksums.items():
            file_path = version_dir / rel_path
            files.append({
                'path': rel_path.replace('\\', '/'),  # Windows 경로 변환
                'size': os.path.getsize(file_path),
                'checksum': checksum
            })

        return {
            'version': version,
            'status': 'draft',  # draft | approved | deprecated
            'build_time': datetime.utcnow().isoformat() + 'Z',
            'platform': sys.platform,
            'files': files,
            'exclude_patterns': ['*.conf', '*.log'],
            'rollback_target': None,
            'release_notes': ''
        }
