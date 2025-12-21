"""자동 업데이트 믹스인 - 서비스에 자동 업데이트 기능 추가"""

import time
import asyncio
from typing import Optional


class AutoUpdateMixin:
    """
    자동 업데이트 믹스인 클래스

    Service 클래스와 함께 사용하여 주기적으로 업데이트를 확인하고 적용합니다.

    사용 예시:
        class MyService(AutoUpdateMixin, Service):
            def __init__(self, *args, check_interval=3600, **kwargs):
                super().__init__(*args, check_interval=check_interval, **kwargs)

                # Updater 컴포넌트 추가
                self.updater = Updater(self, self.cmdr)

        # 1시간마다 자동으로 업데이트 체크
        service = MyService(..., check_interval=3600)
        service.on()
    """

    def __init__(self, *args, check_interval: float = 3600, auto_update_enabled: bool = True, **kwargs):
        """
        AutoUpdateMixin 초기화

        Args:
            check_interval: 업데이트 체크 주기 (초 단위, 기본: 3600 = 1시간)
            auto_update_enabled: 자동 업데이트 활성화 여부 (기본: True)
            *args, **kwargs: 부모 클래스에 전달될 인자
        """
        super().__init__(*args, **kwargs)
        self._check_interval = check_interval
        self._auto_update_enabled = auto_update_enabled
        self._last_check = 0
        self._update_task: Optional[asyncio.Task] = None

    async def run(self):
        """
        run() 메서드 오버라이드 - 주기적 업데이트 체크 추가

        부모 클래스의 run()을 호출한 후, 업데이트 체크를 수행합니다.
        """
        # 부모 클래스의 run() 호출
        await super().run()

        # 자동 업데이트 체크 (비차단)
        if self._auto_update_enabled and time.time() - self._last_check > self._check_interval:
            # 백그라운드로 업데이트 체크 실행 (blocking 방지)
            if self._update_task is None or self._update_task.done():
                self._update_task = asyncio.create_task(self._check_and_update())

    async def _check_and_update(self):
        """
        업데이트 체크 및 자동 적용 (백그라운드 태스크)

        Updater 컴포넌트가 있는 경우에만 동작합니다.
        """
        if not hasattr(self, 'updater'):
            self.l.debug('Updater 컴포넌트가 없음, 자동 업데이트 건너뜀')
            return

        try:
            self.l.info('자동 업데이트 체크 시작 (마지막 체크: %.0f초 전)',
                       time.time() - self._last_check if self._last_check > 0 else 0)

            # 서버에 연결된 cid 확인 (기본값 1 사용)
            cid = getattr(self, 'cid', 1)

            # 업데이트 확인
            has_update = await self.updater.check_update(cid=cid)

            if has_update:
                latest_version = self.updater.latest_version
                self.l.info('새 버전 발견: %s → %s, 업데이트 시작',
                           getattr(self, 'version', 'unknown'), latest_version)

                # 다운로드 및 재시작
                success = await self.updater.download_update(version=latest_version, cid=cid)

                if success:
                    self.l.info('업데이트 다운로드 완료, 재시작 중')
                    await self.updater.restart_service()
                else:
                    self.l.error('업데이트 다운로드 실패: %s', self.updater._download_error)
            else:
                self.l.debug('업데이트 없음 (현재 버전: %s)',
                            getattr(self, 'version', 'unknown'))

            # 마지막 체크 시간 갱신
            self._last_check = time.time()

        except Exception as e:
            self.l.exception('자동 업데이트 체크 중 예외 발생')
            # 예외가 발생해도 서비스는 계속 실행
            self._last_check = time.time()

    def enable_auto_update(self):
        """자동 업데이트 활성화"""
        self._auto_update_enabled = True
        self.l.info('자동 업데이트 활성화됨 (체크 주기: %d초)', self._check_interval)

    def disable_auto_update(self):
        """자동 업데이트 비활성화"""
        self._auto_update_enabled = False
        self.l.info('자동 업데이트 비활성화됨')

    def set_check_interval(self, interval: float):
        """
        업데이트 체크 주기 변경

        Args:
            interval: 새로운 체크 주기 (초 단위)
        """
        self._check_interval = interval
        self.l.info('업데이트 체크 주기 변경됨: %d초', interval)
