"""Semantic versioning 유틸리티"""

import re
from typing import Tuple


def parse_version(version_str: str) -> Tuple[int, int, int]:
    """
    Semantic version 문자열을 파싱

    Args:
        version_str: 버전 문자열 (예: "1.0.0", "0.9.5")

    Returns:
        (major, minor, patch) 튜플

    Raises:
        ValueError: 잘못된 버전 형식
    """
    pattern = r'^(\d+)\.(\d+)\.(\d+)$'
    match = re.match(pattern, version_str)

    if not match:
        raise ValueError(
            f"Invalid version format: '{version_str}'. "
            f"Expected format: MAJOR.MINOR.PATCH (e.g., 1.0.0)"
        )

    major, minor, patch = match.groups()
    return (int(major), int(minor), int(patch))


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
