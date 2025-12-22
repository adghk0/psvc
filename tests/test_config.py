"""Config 클래스 테스트"""

import pytest
import json
from pathlib import Path
from psvc.main import Service, Config


class DummyService(Service):
    """테스트용 더미 서비스"""

    async def run(self):
        pass


class TestConfig:
    """Config 클래스 테스트"""

    def test_json_config_load(self, temp_dir):
        """JSON 설정 파일 로드"""
        config_file = temp_dir / 'test.json'
        config_data = {
            'PSVC': {
                'version': '1.0.0',
                'log_level': 'INFO'
            }
        }

        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(config_data, f)

        service = DummyService('TestService', str(temp_dir / '__init__.py'), str(config_file))

        assert service.get_config('PSVC', 'version') == '1.0.0'
        assert service.get_config('PSVC', 'log_level') == 'INFO'

    def test_config_set_and_get(self, temp_dir):
        """설정 값 저장 및 읽기"""
        config_file = temp_dir / 'test.json'
        service = DummyService('TestService', str(temp_dir / '__init__.py'), str(config_file))

        service.set_config('TestSection', 'test_key', 'test_value')
        assert service.get_config('TestSection', 'test_key') == 'test_value'

    def test_config_default_value(self, temp_dir):
        """기본값 반환"""
        config_file = temp_dir / 'test.json'
        service = DummyService('TestService', str(temp_dir / '__init__.py'), str(config_file))

        value = service.get_config('NonExistent', 'key', default='default_value')
        assert value == 'default_value'

    def test_config_type_conversion(self, temp_dir):
        """타입 변환"""
        config_file = temp_dir / 'test.json'
        config_data = {
            'Test': {
                'int_val': '42',
                'float_val': '3.14',
                'bool_val': 'true',
                'list_val': 'a,b,c'
            }
        }

        with open(config_file, 'w', encoding='utf-8') as f:
            json.dump(config_data, f)

        service = DummyService('TestService', str(temp_dir / '__init__.py'), str(config_file))

        # Config의 _parse_value를 통한 타입 변환
        config = service._config
        assert config._parse_value('42', int) == 42
        assert config._parse_value('3.14', float) == 3.14
        assert config._parse_value('true', bool) is True
        assert config._parse_value('a,b,c', list) == ['a', 'b', 'c']

    def test_ini_to_json_migration(self, temp_dir):
        """INI 파일에서 JSON으로 마이그레이션"""
        ini_file = temp_dir / 'test.conf'
        ini_content = """[PSVC]
version = 1.0.0
log_level = INFO

[Database]
host = localhost
port = 5432
"""
        ini_file.write_text(ini_content)

        service = DummyService('TestService', str(temp_dir / '__init__.py'), str(ini_file))

        # JSON 파일이 생성되었는지 확인
        json_file = temp_dir / 'test.json'
        assert json_file.exists()

        # 값이 올바르게 마이그레이션되었는지 확인
        assert service.get_config('PSVC', 'version') == '1.0.0'
        assert service.get_config('Database', 'host') == 'localhost'
