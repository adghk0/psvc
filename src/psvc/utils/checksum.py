"""파일 체크섬 계산 유틸리티"""

import hashlib
import os
from typing import Dict


def calculate_checksum(file_path: str, algorithm: str = 'sha256') -> str:
    """
    파일의 체크섬 계산

    Args:
        file_path: 파일 경로
        algorithm: 해시 알고리즘 (sha256, md5 등)

    Returns:
        "{algorithm}:{checksum}" 형식의 문자열
    """
    if not os.path.isfile(file_path):
        raise FileNotFoundError(f"파일을 찾을 수 없음: {file_path}")

    hasher = hashlib.new(algorithm)

    # 큰 파일도 처리 가능하도록 청크 단위로 읽기
    with open(file_path, 'rb') as f:
        while chunk := f.read(65536):  # 64KB 단위
            hasher.update(chunk)

    return f"{algorithm}:{hasher.hexdigest()}"


def verify_checksum(file_path: str, expected_checksum: str) -> bool:
    """
    파일의 체크섬 검증

    Args:
        file_path: 파일 경로
        expected_checksum: "{algorithm}:{checksum}" 형식의 기대값

    Returns:
        체크섬이 일치하면 True
    """
    try:
        algorithm, expected_hash = expected_checksum.split(':', 1)
    except ValueError:
        raise ValueError(
            f"잘못된 체크섬 형식: '{expected_checksum}'. "
            f"예상 형식: 'algorithm:hash'"
        )

    actual_checksum = calculate_checksum(file_path, algorithm)
    return actual_checksum == expected_checksum


def calculate_directory_checksums(
    directory: str,
    exclude_patterns: list = None
) -> Dict[str, str]:
    """
    디렉토리 내 모든 파일의 체크섬 계산

    Args:
        directory: 디렉토리 경로
        exclude_patterns: 제외할 파일 패턴 리스트 (예: ['*.conf', '*.log'])

    Returns:
        {상대경로: 체크섬} 딕셔너리
    """
    import fnmatch

    exclude_patterns = exclude_patterns or []
    checksums = {}

    for root, dirs, files in os.walk(directory):
        for filename in files:
            # 제외 패턴 확인
            if any(fnmatch.fnmatch(filename, pattern) for pattern in exclude_patterns):
                continue

            file_path = os.path.join(root, filename)
            # 상대 경로 계산
            rel_path = os.path.relpath(file_path, directory)

            try:
                checksums[rel_path] = calculate_checksum(file_path)
            except Exception as e:
                print(f"경고: {rel_path}의 체크섬 계산 실패: {e}")

    return checksums
