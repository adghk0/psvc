# server.py
# 파일 에이전트에 주기적으로 접속하여 대상 파일 다운로드

import asyncio
import os
from psvc import Service, Commander, command

# Agent별 설정 관리
agent_configs = {
    ('127.0.0.1', 50620): {
        'agent_id': 'agent1',
        'configs': [
            {'path': '/home/manager/test_files', 'pattern': '*.txt'},
            {'path': '/home/manager/docs', 'pattern': '*.md'},
        ]
    },
    # 향후 DB에서 로드 가능
}


class FileServer(Service):
    async def init(self):
        """초기화"""
        # Agent 설정
        self.agent_configs = agent_configs
        self.serial_to_agent = {}  # {serial: agent_id}

        # Commander 생성
        self.cmdr = Commander(self)

        # 명령어 등록
        self.cmdr.set_command(self.cmd_recv_file)

        # 저장 디렉토리 생성
        self.save_dir = './received_files'
        os.makedirs(self.save_dir, exist_ok=True)

        # 연결 상태 플래그
        self.connected = False

        self.l.info('FileServer 시작 (save_dir=%s)', self.save_dir)

    async def run(self):
        """메인 루프"""
        # 최초 1회만 Agent에 접속
        if not self.connected:
            for (addr, port), config in self.agent_configs.items():
                try:
                    # Agent 접속
                    serial = await self.cmdr.connect(addr, port)
                    agent_id = config['agent_id']

                    # serial → agent_id 매핑 저장
                    self.serial_to_agent[serial] = agent_id

                    self.l.info('Agent %s:%d에 접속 완료 (serial=%d, agent_id=%s)',
                               addr, port, serial, agent_id)

                    # 설정 전송
                    await self.cmdr.send_command('set_config',
                                                {'configs': config['configs']}, serial)

                    self.l.info('설정 전송 완료: %d개 경로', len(config['configs']))
                except Exception as e:
                    self.l.error('접속 실패 %s:%d (%s)', addr, port, e)

            self.connected = True

        # 연결 유지 (Agent가 자동으로 파일 전송)
        await asyncio.sleep(1)

    @command(ident='recv_file')
    async def cmd_recv_file(self, cmdr, body, serial):
        """파일 수신 명령 처리"""
        # body: {'path': '/home/manager/test_files/a.txt'} - 절대 경로
        abs_path = body['path']

        # serial로 agent_id 조회
        agent_id = self.serial_to_agent.get(serial, 'unknown')

        # 저장 경로: ./received_files/{agent_id}{absolute_path}
        # 예: ./received_files/agent1/home/manager/test_files/a.txt
        save_path = os.path.join(self.save_dir, agent_id, abs_path.lstrip('/'))

        self.l.info('파일 수신 시작: %s (agent_id=%s)', abs_path, agent_id)

        # 디렉토리 생성
        save_dir = os.path.dirname(save_path)
        if save_dir:
            os.makedirs(save_dir, exist_ok=True)

        # 파일 수신
        await cmdr.endpoint().recv_file(save_path, serial)

        self.l.info('파일 수신 완료: %s', save_path)


if __name__ == '__main__':
    fs = FileServer(name='FileServer', root_file=__file__)
    fs.on()
