"""버전 유틸리티 테스트"""

import pytest
from psvc.utils.version import parse_version, is_valid_version, compare_versions


class TestParseVersion:
    """parse_version 함수 테스트"""

    def test_full_version(self):
        """MAJOR.MINOR.PATCH 형식 파싱"""
        assert parse_version("1.2.3") == (1, 2, 3)
        assert parse_version("0.0.1") == (0, 0, 1)
        assert parse_version("10.20.30") == (10, 20, 30)

    def test_short_version(self):
        """MAJOR.MINOR 형식 파싱 (patch는 0)"""
        assert parse_version("1.0") == (1, 0, 0)
        assert parse_version("2.5") == (2, 5, 0)

    def test_invalid_version(self):
        """잘못된 형식 예외 발생"""
        with pytest.raises(ValueError, match="잘못된 버전 형식"):
            parse_version("1")

        with pytest.raises(ValueError, match="잘못된 버전 형식"):
            parse_version("1.2.3.4")

        with pytest.raises(ValueError, match="잘못된 버전 형식"):
            parse_version("invalid")


class TestIsValidVersion:
    """is_valid_version 함수 테스트"""

    def test_valid_versions(self):
        """유효한 버전 문자열"""
        assert is_valid_version("1.0.0") is True
        assert is_valid_version("2.5") is True
        assert is_valid_version("0.0.1") is True

    def test_invalid_versions(self):
        """유효하지 않은 버전 문자열"""
        assert is_valid_version("1") is False
        assert is_valid_version("1.2.3.4") is False
        assert is_valid_version("invalid") is False


class TestCompareVersions:
    """compare_versions 함수 테스트"""

    def test_greater_than(self):
        """v1 > v2"""
        assert compare_versions("2.0.0", "1.0.0") == 1
        assert compare_versions("1.1.0", "1.0.0") == 1
        assert compare_versions("1.0.1", "1.0.0") == 1

    def test_less_than(self):
        """v1 < v2"""
        assert compare_versions("1.0.0", "2.0.0") == -1
        assert compare_versions("1.0.0", "1.1.0") == -1
        assert compare_versions("1.0.0", "1.0.1") == -1

    def test_equal(self):
        """v1 == v2"""
        assert compare_versions("1.0.0", "1.0.0") == 0
        assert compare_versions("1.0", "1.0.0") == 0
        assert compare_versions("2.5", "2.5") == 0

    def test_short_vs_full(self):
        """짧은 형식과 전체 형식 비교"""
        assert compare_versions("1.0", "1.0.0") == 0
        assert compare_versions("1.1", "1.0.5") == 1
        assert compare_versions("1.0", "1.1.0") == -1
