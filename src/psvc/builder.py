"""🚀 빌드 자동화 모듈 - PyInstaller 래퍼 with Style"""

import os
import sys
import shutil
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Optional, Any
from dataclasses import dataclass, asdict, field

from .utils.version import is_valid_version
from .utils.checksum import calculate_directory_checksums


@dataclass
class BuildMetadata:
    """빌드 메타데이터"""
    version: str
    status: str = 'draft'
    build_time: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    platform: str = field(default_factory=lambda: sys.platform)
    files: List[Dict[str, Any]] = field(default_factory=list)
    exclude_patterns: List[str] = field(default_factory=lambda: ['*.conf', '*.log'])
    rollback_target: Optional[str] = None
    release_notes: str = ''

    def to_dict(self) -> dict:
        """
        딕셔너리로 변환 (JSON 직렬화용)

        Returns:
            dict: 메타데이터 딕셔너리
        """
        return asdict(self)


class BuildError(Exception):
    """빌드 실패 시 발생하는 예외"""
    pass


class Builder:
    """
    PyInstaller 빌드 자동화 클래스

    빌드 파이프라인:
    1. 버전 검증
    2. PyInstaller 실행
    3. 아티팩트 복사 (제외 패턴 적용)
    4. 체크섬 계산
    5. 메타데이터 생성 및 저장
    """

    # 기본 제외 패턴 - 상수로 관리
    DEFAULT_EXCLUDE = ['*.conf', '*.log', '*.pyc', '__pycache__', '*.pyo']

    def __init__(
        self,
        service_name: str,
        root_path: str,
        release_path: Optional[str] = None
    ):
        """
        빌더 초기화

        Args:
            service_name: 서비스 이름
            root_path: 서비스 루트 경로 (__file__ 경로도 자동 해석)
            release_path: 릴리스 저장 경로 (기본: {root_path}/releases)
        """
        self.service_name = service_name
        self.root_path = self._resolve_path(root_path)
        self.release_path = (
            Path(release_path) if release_path
            else self.root_path / 'releases'
        )
        self.release_path.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _resolve_path(path: str) -> Path:
        """
        경로 해석 - 파일이면 부모 디렉토리, 디렉토리면 그대로

        Args:
            path: 해석할 경로

        Returns:
            Path: 디렉토리 경로
        """
        p = Path(path)
        return p.parent if p.is_file() else p

    def build(
        self,
        version: str,
        spec_file: str,
        exclude_patterns: Optional[List[str]] = None,
        **pyinstaller_options
    ) -> Path:
        """
        PyInstaller로 실행 파일 빌드

        Args:
            version: Semantic version (예: "1.0.0")
            spec_file: PyInstaller spec 파일 경로 (필수)
            exclude_patterns: 제외할 파일 패턴 (기본값 사용 가능)
            **pyinstaller_options: PyInstaller 추가 옵션

        Returns:
            빌드된 릴리스 디렉토리 경로

        Raises:
            BuildError: 빌드 실패 시

        Example:
            builder = Builder("MyApp", __file__)
            version_dir = builder.build(
                version="1.0.0",
                spec_file="app.spec",
                exclude_patterns=['*.conf']
            )
        """
        # 버전 검증
        if not is_valid_version(version):
            raise BuildError(f"잘못된 버전 형식: {version}")

        print(f"\n{'='*70}")
        print(f"🚀 {self.service_name} v{version} 빌드 중")
        print(f"{'='*70}")

        # 제외 패턴 설정
        exclude_patterns = exclude_patterns or self.DEFAULT_EXCLUDE

        # 버전 디렉토리 준비
        version_dir = self._prepare_version_dir(version)

        try:
            # 빌드 파이프라인
            dist_path = self._run_pyinstaller(spec_file, **pyinstaller_options)
            self._copy_artifacts(dist_path, version_dir, exclude_patterns)
            checksums = self._calculate_checksums(version_dir, exclude_patterns)
            metadata = self._create_metadata(version, version_dir, checksums)
            self._save_metadata(version_dir, metadata)

            self._print_summary(version_dir, metadata)
            return version_dir

        except Exception as e:
            # 실패 시 버전 디렉토리 정리
            if version_dir.exists():
                shutil.rmtree(version_dir, ignore_errors=True)
            raise BuildError(f"빌드 실패: {e}") from e

    def _prepare_version_dir(self, version: str) -> Path:
        """
        버전 디렉토리 준비 - 기존 버전 덮어쓰기

        Args:
            version: 버전 문자열

        Returns:
            Path: 버전 디렉토리 경로
        """
        version_dir = self.release_path / version

        if version_dir.exists():
            print(f"⚠️ 버전 {version}이(가) 이미 존재합니다. 덮어쓰는 중...")
            shutil.rmtree(version_dir)

        version_dir.mkdir(parents=True, exist_ok=True)
        return version_dir

    def _run_pyinstaller(self, spec_file: str, **options) -> Path:
        """
        PyInstaller 실행

        Spec 파일 기반 빌드만 지원 (일관성과 재현성 보장)

        Args:
            spec_file: Spec 파일 경로
            **options: PyInstaller 추가 옵션

        Returns:
            Path: 빌드 결과 경로 (dist 디렉토리 내)

        Raises:
            BuildError: Spec 파일 없음 또는 빌드 실패
        """
        print(f"\n[1/5] 🔧 PyInstaller 실행 중...")

        # Spec 파일 검증
        spec_path = self.root_path / spec_file
        if not spec_path.exists():
            raise BuildError(f"Spec 파일을 찾을 수 없음: {spec_path}")

        # 명령어 구성 (spec 파일 사용 시 경로 옵션 제외)
        cmd = [
            sys.executable, '-m', 'PyInstaller',
            str(spec_path),
            '--clean'
        ]

        # 추가 옵션 처리
        for key, value in options.items():
            if value is True:
                cmd.append(f'--{key}')
            elif value not in (False, None):
                cmd.extend([f'--{key}', str(value)])

        print(f"  Command: {' '.join(cmd)}")

        # PyInstaller 실행
        result = subprocess.run(
            cmd,
            cwd=str(self.root_path),
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            error_msg = result.stderr or result.stdout
            raise BuildError(
                f"PyInstaller 실패 (종료 코드 {result.returncode})\n{error_msg[:500]}"
            )

        # 빌드 결과 찾기
        dist_dir = self.root_path / 'dist'
        if not dist_dir.exists() or not list(dist_dir.iterdir()):
            raise BuildError("dist 디렉토리에 출력 파일이 없음")

        print(f"  ✓ PyInstaller 완료")
        return list(dist_dir.iterdir())[0]

    def _copy_artifacts(
        self,
        source: Path,
        destination: Path,
        exclude_patterns: List[str]
    ):
        """
        빌드 결과물 복사 (제외 패턴 적용)

        Args:
            source: 소스 경로 (파일 또는 디렉토리)
            destination: 목적지 디렉토리
            exclude_patterns: 제외할 파일 패턴 목록
        """
        import fnmatch

        print(f"\n[2/5] 빌드 결과물 복사 중...")

        if source.is_file():
            # 단일 파일 복사
            shutil.copy2(source, destination / source.name)
            print(f"  ✓ {source.name}")
            return

        # 디렉토리 재귀 복사
        copied = 0
        for item in source.rglob('*'):
            if not item.is_file():
                continue

            # 제외 패턴 체크
            if any(fnmatch.fnmatch(item.name, p) for p in exclude_patterns):
                continue

            # 복사 (디렉토리 구조 유지)
            rel_path = item.relative_to(source)
            dest_file = destination / rel_path
            dest_file.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, dest_file)
            copied += 1

        print(f"  ✓ {copied}개 파일 복사 완료")

    def _calculate_checksums(
        self,
        version_dir: Path,
        exclude_patterns: List[str]
    ) -> Dict[str, str]:
        """
        체크섬 계산 (SHA256)

        Args:
            version_dir: 버전 디렉토리 경로
            exclude_patterns: 제외할 파일 패턴 목록

        Returns:
            Dict[str, str]: 파일 경로별 체크섬 딕셔너리
        """
        print(f"\n[3/5] 체크섬 계산 중...")

        checksums = calculate_directory_checksums(
            str(version_dir),
            exclude_patterns
        )

        print(f"  ✓ {len(checksums)}개 파일 처리 완료")
        return checksums

    def _create_metadata(
        self,
        version: str,
        version_dir: Path,
        checksums: Dict[str, str]
    ) -> BuildMetadata:
        """
        메타데이터 생성 (dataclass 사용으로 타입 안전성 보장)

        Args:
            version: 버전 문자열
            version_dir: 버전 디렉토리 경로
            checksums: 파일 경로별 체크섬 딕셔너리

        Returns:
            BuildMetadata: 빌드 메타데이터
        """
        print(f"\n[4/5] 메타데이터 생성 중...")

        files = [
            {
                'path': rel_path.replace('\\', '/'),  # Windows 경로 정규화
                'size': (version_dir / rel_path).stat().st_size,
                'checksum': checksum
            }
            for rel_path, checksum in checksums.items()
        ]

        metadata = BuildMetadata(version=version, files=files)
        print(f"  ✓ {len(files)}개 파일에 대한 메타데이터 생성 완료")
        return metadata

    def _save_metadata(self, version_dir: Path, metadata: BuildMetadata):
        """
        메타데이터 저장

        Args:
            version_dir: 버전 디렉토리 경로
            metadata: 빌드 메타데이터
        """
        print(f"\n[5/5] status.json 저장 중...")

        status_file = version_dir / 'status.json'
        with open(status_file, 'w', encoding='utf-8') as f:
            json.dump(metadata.to_dict(), f, indent=2, ensure_ascii=False)

        print(f"  ✓ {status_file.name}")

    def _print_summary(self, version_dir: Path, metadata: BuildMetadata):
        """
        빌드 결과 요약 출력

        Args:
            version_dir: 버전 디렉토리 경로
            metadata: 빌드 메타데이터
        """
        total_size_mb = sum(f['size'] for f in metadata.files) / 1024 / 1024

        print(f"\n{'='*70}")
        print(f"✅ 빌드 완료: {version_dir}")
        print(f"{'='*70}")
        print(f"  버전:         {metadata.version}")
        print(f"  상태:         {metadata.status}")
        print(f"  플랫폼:       {metadata.platform}")
        print(f"  파일:         {len(metadata.files)}개")
        print(f"  전체 크기:    {total_size_mb:.2f} MB")
        print(f"  빌드 시간:    {metadata.build_time}")
        print(f"{'='*70}\n")
