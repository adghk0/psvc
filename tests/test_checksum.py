"""체크섬 유틸리티 테스트"""

import pytest
from pathlib import Path
from psvc.utils.checksum import (
    calculate_checksum,
    verify_checksum,
    calculate_directory_checksums
)


class TestCalculateChecksum:
    """calculate_checksum 함수 테스트"""

    def test_calculate_sha256(self, temp_dir):
        """SHA256 체크섬 계산"""
        test_file = temp_dir / 'test.txt'
        test_file.write_text('Hello, World!')

        checksum = calculate_checksum(str(test_file), 'sha256')
        assert checksum.startswith('sha256:')
        assert len(checksum.split(':')[1]) == 64  # SHA256은 64자

    def test_calculate_md5(self, temp_dir):
        """MD5 체크섬 계산"""
        test_file = temp_dir / 'test.txt'
        test_file.write_text('Hello, World!')

        checksum = calculate_checksum(str(test_file), 'md5')
        assert checksum.startswith('md5:')
        assert len(checksum.split(':')[1]) == 32  # MD5는 32자

    def test_file_not_found(self):
        """파일이 없을 때 예외 발생"""
        with pytest.raises(FileNotFoundError, match="파일을 찾을 수 없음"):
            calculate_checksum('/nonexistent/file.txt')

    def test_same_content_same_checksum(self, temp_dir):
        """같은 내용이면 같은 체크섬"""
        file1 = temp_dir / 'file1.txt'
        file2 = temp_dir / 'file2.txt'

        content = 'Test content'
        file1.write_text(content)
        file2.write_text(content)

        checksum1 = calculate_checksum(str(file1))
        checksum2 = calculate_checksum(str(file2))
        assert checksum1 == checksum2


class TestVerifyChecksum:
    """verify_checksum 함수 테스트"""

    def test_verify_success(self, temp_dir):
        """체크섬 검증 성공"""
        test_file = temp_dir / 'test.txt'
        test_file.write_text('Hello, World!')

        expected = calculate_checksum(str(test_file))
        assert verify_checksum(str(test_file), expected) is True

    def test_verify_failure(self, temp_dir):
        """체크섬 검증 실패"""
        test_file = temp_dir / 'test.txt'
        test_file.write_text('Hello, World!')

        wrong_checksum = 'sha256:' + '0' * 64
        assert verify_checksum(str(test_file), wrong_checksum) is False

    def test_invalid_format(self, temp_dir):
        """잘못된 체크섬 형식"""
        test_file = temp_dir / 'test.txt'
        test_file.write_text('Hello, World!')

        with pytest.raises(ValueError, match="잘못된 체크섬 형식"):
            verify_checksum(str(test_file), 'invalid_checksum')


class TestCalculateDirectoryChecksums:
    """calculate_directory_checksums 함수 테스트"""

    def test_single_file(self, temp_dir):
        """단일 파일 디렉토리"""
        test_file = temp_dir / 'test.txt'
        test_file.write_text('Hello')

        checksums = calculate_directory_checksums(str(temp_dir))
        assert 'test.txt' in checksums
        assert checksums['test.txt'].startswith('sha256:')

    def test_multiple_files(self, temp_dir):
        """여러 파일이 있는 디렉토리"""
        (temp_dir / 'file1.txt').write_text('Content 1')
        (temp_dir / 'file2.txt').write_text('Content 2')
        (temp_dir / 'file3.txt').write_text('Content 3')

        checksums = calculate_directory_checksums(str(temp_dir))
        assert len(checksums) == 3
        assert 'file1.txt' in checksums
        assert 'file2.txt' in checksums
        assert 'file3.txt' in checksums

    def test_nested_directories(self, temp_dir):
        """중첩 디렉토리"""
        subdir = temp_dir / 'subdir'
        subdir.mkdir()

        (temp_dir / 'root.txt').write_text('Root')
        (subdir / 'nested.txt').write_text('Nested')

        checksums = calculate_directory_checksums(str(temp_dir))
        assert len(checksums) == 2
        assert 'root.txt' in checksums
        assert str(Path('subdir') / 'nested.txt') in checksums

    def test_exclude_patterns(self, temp_dir):
        """파일 제외 패턴"""
        (temp_dir / 'file.txt').write_text('Include')
        (temp_dir / 'file.log').write_text('Exclude')
        (temp_dir / 'file.conf').write_text('Exclude')

        checksums = calculate_directory_checksums(
            str(temp_dir),
            exclude_patterns=['*.log', '*.conf']
        )

        assert len(checksums) == 1
        assert 'file.txt' in checksums
        assert 'file.log' not in checksums
        assert 'file.conf' not in checksums
