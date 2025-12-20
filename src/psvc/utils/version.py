"""Semantic versioning 유틸리티"""

import re
from typing import Tuple


def parse_version(version_str: str) -> Tuple[int, int, int]:
    """
    Semantic version 문자열을 파싱

    Args:
        version_str: 버전 문자열 (예: "1.0.0", "0.9.5", "1.0")

    Returns:
        (major, minor, patch) 튜플 (patch가 없으면 0으로 설정)

    Raises:
        ValueError: 잘못된 버전 형식
    """
    # MAJOR.MINOR.PATCH 형식
    pattern_full = r'^(\d+)\.(\d+)\.(\d+)$'
    match = re.match(pattern_full, version_str)

    if match:
        major, minor, patch = match.groups()
        return (int(major), int(minor), int(patch))

    # MAJOR.MINOR 형식 (patch는 0으로 처리)
    pattern_short = r'^(\d+)\.(\d+)$'
    match = re.match(pattern_short, version_str)

    if match:
        major, minor = match.groups()
        return (int(major), int(minor), 0)

    # 둘 다 아니면 에러
    raise ValueError(
        f"Invalid version format: '{version_str}'. "
        f"Expected format: MAJOR.MINOR.PATCH (e.g., 1.0.0) or MAJOR.MINOR (e.g., 1.0)"
    )


def is_valid_version(version_str: str) -> bool:
    """버전 문자열이 유효한지 확인"""
    try:
        parse_version(version_str)
        return True
    except ValueError:
        return False


def compare_versions(v1: str, v2: str) -> int:
    """
    두 버전을 비교

    Args:
        v1: 첫 번째 버전
        v2: 두 번째 버전

    Returns:
        v1 > v2: 양수
        v1 == v2: 0
        v1 < v2: 음수
    """
    parsed_v1 = parse_version(v1)
    parsed_v2 = parse_version(v2)

    if parsed_v1 > parsed_v2:
        return 1
    elif parsed_v1 < parsed_v2:
        return -1
    else:
        return 0
