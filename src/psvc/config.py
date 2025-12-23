
import os
import configparser
from typing import TYPE_CHECKING

from psvc.component import Component
if TYPE_CHECKING:
    from psvc.main import Service

class Config(Component):
    """
    서비스 설정 관리 컴포넌트 (JSON 기반)

    INI 파일에서 JSON으로 자동 마이그레이션하며, 타입 변환을 지원합니다.
    """
    _default_conf_file = 'psvc.json'

    def __init__(self, svc: 'Service', config_file, name='Config'):
        """
        Config 초기화

        Args:
            svc: 서비스 인스턴스
            config_file: 설정 파일 경로
            name: 컴포넌트 이름
        """
        super().__init__(svc, name)

        # 설정 파일 경로 결정
        if config_file is not None:
            original_file = self.svc.path(config_file)
        else:
            original_file = self.svc.path(Config._default_conf_file)

        # INI/JSON 경로 분리
        self._ini_file = original_file
        self._config_file = self._get_json_path(original_file)

        # 설정 로드
        self._config = self._load_config()

    def _get_json_path(self, file_path: str) -> str:
        """
        설정 파일 경로를 JSON 경로로 변환

        Args:
            file_path: 원본 설정 파일 경로

        Returns:
            str: JSON 파일 경로
        """
        if file_path.endswith('.conf'):
            return file_path.replace('.conf', '.json')
        elif file_path.endswith('.ini'):
            return file_path.replace('.ini', '.json')
        elif file_path.endswith('.json'):
            return file_path
        else:
            return file_path + '.json'

    def _load_config(self) -> dict:
        """
        설정 파일 로드 (JSON 우선, 없으면 INI 마이그레이션)

        Returns:
            dict: 로드된 설정 딕셔너리
        """
        import json

        self.l.info('설정 파일 로드: %s', self._config_file)
        # 1. JSON 파일이 존재하면 로드
        if os.path.exists(self._config_file):
            try:
                with open(self._config_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except json.JSONDecodeError as e:
                self.l.error('JSON 설정 파일 로드 실패 (%s): %s', self._config_file, e)
                # JSON 파싱 실패 시 INI에서 재생성 시도
                if os.path.exists(self._ini_file):
                    return self._migrate_from_ini()
                return {}

        # 2. INI 파일이 존재하면 마이그레이션
        if os.path.exists(self._ini_file):
            return self._migrate_from_ini()
        # 3. 둘 다 없으면 빈 설정
        return {}
    
        

    def _migrate_from_ini(self) -> dict:
        """
        INI 파일을 JSON으로 변환

        Returns:
            dict: 변환된 설정 딕셔너리
        """
        self.l.info('설정 파일 마이그레이션 중: %s -> %s', self._ini_file, self._config_file)

        parser = configparser.ConfigParser()
        parser.read(self._ini_file, encoding='utf-8')

        # INI를 dict로 변환
        config = {}
        for section in parser.sections():
            config[section] = dict(parser.items(section))

        # JSON으로 저장
        self._save_config(config)

        # INI 파일에 마이그레이션 안내 추가
        self._mark_ini_as_migrated()

        return config

    def _mark_ini_as_migrated(self):
        """
        INI 파일 상단에 마이그레이션 안내 추가

        JSON으로 마이그레이션되었음을 INI 파일 상단에 표시합니다.
        """
        if not os.path.exists(self._ini_file):
            return

        with open(self._ini_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # 이미 마크가 있는지 확인
        if '# This file is parsed to' in content:
            return

        # 상단에 안내 추가
        header = f'# This file is parsed to {self._config_file}\n'
        header += '# Please edit the JSON file instead.\n\n'

        with open(self._ini_file, 'w', encoding='utf-8') as f:
            f.write(header + content)

    def _save_config(self, config=None):
        """
        설정을 JSON 파일로 저장

        Args:
            config: 저장할 설정 딕셔너리 (None이면 현재 설정 저장)
        """
        import json

        if config is None:
            config = self._config

        with open(self._config_file, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

    def _parse_value(self, value, dtype=None):
        """
        값을 지정된 타입으로 파싱

        Args:
            value: 파싱할 값
            dtype: 목표 타입 (None, str, int, float, bool, list, dict 또는 callable)

        Returns:
            파싱된 값

        Raises:
            ValueError: 타입 변환 실패 시
        """
        # 타입 지정이 없으면 원본 반환
        if dtype is None:
            return value

        # 기본 타입 변환
        type_converters = {
            str: lambda v: str(v),
            int: lambda v: int(v),
            float: lambda v: float(v),
        }

        if dtype in type_converters:
            return type_converters[dtype](value)

        # bool 타입 처리 (문자열 "true", "false" 등 지원)
        if dtype == bool:
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.lower() in ('true', '1', 'yes', 'on')
            return bool(value)

        # list 타입 처리 (쉼표 구분 문자열 지원)
        if dtype == list:
            if isinstance(value, list):
                return value
            if isinstance(value, str):
                return [item.strip() for item in value.split(',') if item.strip()]
            return list(value)

        # dict 타입 처리
        if dtype == dict:
            if isinstance(value, dict):
                return value
            raise ValueError(f'Cannot convert {type(value).__name__} to dict')

        # 사용자 정의 타입 (callable)
        return dtype(value)

    def set_config(self, section: str, key: str, value, dtype=None):
        """
        설정 값을 저장합니다.

        Args:
            section: 섹션 이름
            key: 키 이름
            value: 설정 값
            dtype: 데이터 타입 (str, int, float, bool, list, dict 또는 callable)
        """
        # 섹션이 없으면 생성
        if section not in self._config:
            self._config[section] = {}

        # 타입 변환 후 저장
        self._config[section][key] = self._parse_value(value, dtype)
        self._save_config()

    def get_config(self, section: str, key: str = None, default=None, dtype=None):
        """
        설정 값을 반환합니다.

        Args:
            section: 섹션 이름 (또는 'section\\key' 형식)
            key: 키 이름 (None이면 섹션 전체 반환)
            default: 기본값 (없을 경우 자동으로 설정)
            dtype: 데이터 타입 (str, int, float, bool, list, dict 또는 callable)

        Returns:
            설정 값 (key가 None이면 섹션 dict)

        Raises:
            KeyError: 섹션 또는 키가 없고 default도 None인 경우
        """
        # 하위 호환성: 'section\\key' 형식 지원
        if key is None and '\\' in section:
            section, key = section.split('\\', 1)

        # 섹션 없음
        if section not in self._config:
            if default is not None and key is not None:
                self.set_config(section, key, default, dtype)
                return self._parse_value(default, dtype)
            raise KeyError(f'Section does not exist: {section}')

        # 섹션 전체 반환
        if key is None:
            return self._config[section]

        # 키 없음
        if key not in self._config[section]:
            if default is not None:
                self.set_config(section, key, default, dtype)
                return self._parse_value(default, dtype)
            raise KeyError(f'Config does not exist: {section}\\{key}')

        # 값 반환 (타입 변환)
        return self._parse_value(self._config[section][key], dtype)
    
