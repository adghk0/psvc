# agent.py
# 서버로부터 접속 시 설정 받은 후, 설정에 따른 파일 전송

import asyncio
import os
import fnmatch

from psvc import Service, Commander


class FileAgent(Service):
    async def init(self):
        """초기화"""
        # 파일 추적 시스템
        self.sent_files = {}  # {absolute_path: mtime}

        # 설정
        self.watch_path = '/home/manager/test_files'
        self.pattern = '*.txt'

        # Commander 초기화 (명령어 등록 불필요 - 전송만 함)
        self.cmdr = Commander(self)
        await self.cmdr.bind('0.0.0.0', 50620)

        self.l.info('FileAgent 시작 (watch_path=%s, pattern=%s)',
                   self.watch_path, self.pattern)

    def check_changed_files(self):
        """변경된 파일 확인"""
        changed_files = []

        # watch_path가 존재하지 않으면 빈 리스트 반환
        if not os.path.exists(self.watch_path):
            return changed_files

        # os.walk로 디렉토리 순회
        for root, dirs, files in os.walk(self.watch_path):
            for filename in files:
                # 패턴 매칭
                if fnmatch.fnmatch(filename, self.pattern):
                    file_path = os.path.join(root, filename)

                    try:
                        current_mtime = os.path.getmtime(file_path)

                        # 새 파일이거나 수정된 파일인지 확인
                        if file_path not in self.sent_files or \
                           self.sent_files[file_path] < current_mtime:
                            changed_files.append(file_path)
                    except OSError as e:
                        self.l.warning('파일 접근 실패: %s (%s)', file_path, e)

        return changed_files

    async def send_files_to_clients(self, files, sockets):
        """연결된 모든 클라이언트에게 파일 전송"""
        for file_path in files:
            # 상대 경로 계산
            relative_path = os.path.relpath(file_path, self.watch_path)

            self.l.info('파일 전송 시작: %s', relative_path)

            # 각 클라이언트에게 전송
            for serial in sockets.keys():
                try:
                    # 1. 파일 메타정보 전송 (상대경로)
                    await self.cmdr.send_command('recv_file',
                                                {'path': relative_path}, serial)

                    # 2. 파일 내용 전송
                    await self.cmdr.endpoint().send_file(file_path, serial)

                    self.l.info('파일 전송 완료: %s -> serial=%d', relative_path, serial)
                except Exception as e:
                    self.l.error('파일 전송 실패: %s (%s)', relative_path, e)

            # mtime 업데이트
            self.sent_files[file_path] = os.path.getmtime(file_path)

    async def run(self):
        """메인 루프 - 주기적으로 파일 변경 체크 및 전송"""
        # 연결된 클라이언트가 있을 때만 파일 체크 및 전송
        data_sockets = self.cmdr.endpoint().get_data_sockets()

        if data_sockets:
            changed_files = self.check_changed_files()

            if changed_files:
                self.l.info('변경된 파일 %d개 발견', len(changed_files))
                await self.send_files_to_clients(changed_files, data_sockets)

        # 5초 대기
        await asyncio.sleep(5)


if __name__ == '__main__':
    fa = FileAgent(name='FileAgent', root_file=__file__)
    fa.on()
