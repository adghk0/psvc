# PyService

Lightweight async Python service framework
(Current version: 0.5.0)

----------------------------------------------------------------

## Overview

PyService는 asyncio 기반의 장기 실행 Python 프로그램을 위해 설계된
경량 서비스 프레임워크입니다.

다음과 같은 요구를 하나의 구조로 묶는 것을 목표로 합니다.

- 서비스 라이프사이클 관리
- 명령 기반 네트워크 통신
- PyInstaller 기반 실행 파일 빌드
- 사내/폐쇄망 환경에서의 자체 업데이트
- 유지보수와 확장이 쉬운 컴포넌트 구조

----------------------------------------------------------------

## Core Concepts

### Service

서비스의 진입점이 되는 추상 클래스입니다.

- asyncio 이벤트 루프 관리
- init / run / destroy 단계 분리
- SIGTERM, KeyboardInterrupt 대응
- 설정 파일 및 로그 자동 관리
- 빌드, 릴리스, 롤백 기능 포함

#### Example:

class MyService(Service):
    async def run(self):
        ...

----------------------------------------------------------------

### Component

서비스 내부 기능을 구성하는 기본 단위입니다.

- 부모–자식 계층 구조
- 서비스 종료 시 안전한 분리 가능
- 모든 주요 기능(Socket, Commander 등)의 기반 클래스

----------------------------------------------------------------

### Socket

Async TCP 소켓 래퍼입니다.

- 길이 헤더 기반 메시지 전송
- 문자열 / 바이너리 / 파일 송수신 지원
- 서버 및 클라이언트 모드 지원
- 대용량 데이터 분할 처리

----------------------------------------------------------------

### Commander / command decorator

명령 기반 통신을 위한 디스패처입니다.

#### Example:

@command(ident="ping")
async def ping(cmdr, body, cid):
    ...

- async 함수만 허용
- ident 기반 명령 분기
- 재진입(call stack) 안전 처리
- 네트워크 메시지를 함수 호출처럼 처리

----------------------------------------------------------------

## Build & Release

### Builder

PyInstaller를 감싼 빌드 자동화 모듈입니다.

- Semantic version 검증
- spec 파일 기반 빌드
- 결과물 복사 및 제외 패턴 적용
- SHA256 체크섬 생성
- status.json 메타데이터 생성

#### Example:

service.build(
    version="0.5.0",
    spec_file="app.spec",
    onefile=True,
    console=False
)

----------------------------------------------------------------

### Releaser

업데이트 서버 컴포넌트입니다.

- 승인된(approved) 버전만 제공
- 버전 목록 및 최신 버전 조회
- 다중 파일 업데이트 전송
- 체크섬 기반 무결성 검증

----------------------------------------------------------------

### Updater

업데이트 클라이언트 컴포넌트입니다.

- 최신 버전 확인
- Blocking 방식 다운로드
- 파일 무결성 검증
- 업데이트 후 서비스 재시작

----------------------------------------------------------------

## Configuration

psvc.conf example:

[PSVC]
version = 0.5.0
release_path = ./releases
update_path = ./updates

----------------------------------------------------------------

## Directory Layout (Example)

my_service/
├─ main.py
├─ my_service.spec
├─ psvc.conf
├─ releases/
│  ├─ 0.4.0/
│  └─ 0.5.0/
│     ├─ program.exe
│     └─ status.json
└─ logs/
   └─ MyService.log

----------------------------------------------------------------

## Typical Use Cases

- 장비 제어 및 감시 서비스
- 검사/계측 장비 로컬 데몬
- 로그 수집 에이전트
- 폐쇄망 자동 업데이트 프로그램
- 내부 테스트 서버 및 클라이언트

----------------------------------------------------------------

## Design Philosophy

- 최소한의 추상화
- 읽히는 코드 구조
- 현장 환경에서 안정적으로 동작
- 프레임워크는 흐름만 제공하고, 구현은 사용자에게 위임

----------------------------------------------------------------

## License

BSD 3-Clause License
