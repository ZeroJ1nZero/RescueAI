# Jetson · Gemini 2 보드 확인 기록표

양식 작성일: 2026-11-16. **현재 모든 실제 장비 항목은 미확인**이다. [설정 안내](jetson-gemini2-setup.md)를 실행하면서 이 파일을 결과 디렉터리에 복사해 작성한다. 원본 양식의 빈칸을 추정값으로 채우지 않는다.

## 기본 정보

| 항목 | 실제 확인값 | 근거 파일·명령·비고 |
|---|---|---|
| 확인 일시 / 작업자 | 미확인 | UTC 또는 timezone 포함 |
| 프로젝트 commit | 미확인 | `git rev-parse HEAD` |
| 모듈·개발 키트·캐리어보드 | 미확인 | `/proc/device-tree/model`, 제품 라벨 |
| RAM / SSD / 남은 공간 | 미확인 | `free -h`, `lsblk`, `df -h` |
| 전원 정격·모델 / 냉각 | 미확인 | 실제 어댑터·팬 상태 |
| OS / 아키텍처 / Python | 미확인 | `/etc/os-release`, `uname -m`, `/usr/bin/python3 --version` |
| JetPack / L4T | 미확인 | `dpkg-query`, `/etc/nv_tegra_release` |
| CUDA / TensorRT / cuDNN | 미확인 | toolkit 명령·실제 설치 패키지 |
| 전력 모드 ID·이름 / 클럭 설정 | 미확인 | `sudo nvpmodel -q`, 실험별 기록 |
| swap / 온도 / throttling | 미확인 | `swapon --show`, tegrastats |
| 네트워크 / SSH / NTP | 미확인 | 연결 성공·시각 상태, 인증정보 기록 금지 |
| ROS 배포 / RMW / domain ID | 미확인 | `ROS_DISTRO`, 실제 RMW 설정, `ROS_DOMAIN_ID` |
| ROS Python import / pip check | 미확인 | 프로젝트 venv 안에서 확인 |

## 카메라와 입력 의미

| 항목 | 실제 확인값 | 근거 파일·명령·비고 |
|---|---|---|
| 정확한 모델 | 미확인 | Gemini 2 / 2 L / 2 XL 구분 |
| 펌웨어 / SDK / wrapper tag·commit | 미확인 | 드라이버 로그·장치 정보·`git rev-parse HEAD` |
| USB 링크 속도 / 포트 / 케이블 | 미확인 | 해당 장치의 `lsusb -t` 분기 |
| udev / 일반 사용자 접근 | 미확인 | root 없이 드라이버 실행 |
| 실제 launch 명령 / 전체 파라미터 | 미확인 | 로그·`ros2 param dump` 결과 |
| RGB 토픽 / encoding / 크기 / FPS | 미확인 | `ros2 topic list -t`, 메시지·로그 |
| Depth 토픽 / encoding / 크기 / FPS | 미확인 | 색상화 이미지가 아닌 원시 깊이 |
| depth scaling 설정 / m 변환 계수 | 미확인 | SDK·드라이버 근거 + 알려진 거리 검토 |
| 무효 깊이값 / 유효 범위 | 미확인 | 원시 메시지·센서 설정 |
| RGB-depth 정렬 / CameraInfo | 미확인 | 실제 경계 대응·K/D/R/P·frame_id |
| timestamp 도메인 / 차이·누락 | 미확인 | header 기준 분석, 호스트 수신 시각과 구분 |
| accel / gyro 토픽·단위·레이트 | 미확인 | 분리/동기 출력 여부 포함 |
| IMU 축 / 중력 포함 / 보정 적용 | 미확인 | SDK 문서·정지/회전 시험 |
| orientation 유효 여부 | 미확인 | raw IMU와 자세 추정 결과 구분 |
| camera↔IMU 외부 보정 | 미확인 | 변환 방향·행렬·좌표계 근거 |
| TF 트리 / 보드·착용 좌표계 | 미확인 | optical frame과 장착 변환 분리 |

## 진행 체크

- [ ] 보드 버전·전원·냉각·SSD를 확인했다.
- [ ] 실제 환경에 맞는 ROS와 시스템 Python을 선택했다.
- [ ] 드라이버·펌웨어·설정·commit을 기록했다.
- [ ] 일반 사용자로 RGB·깊이·IMU를 수신했다.
- [ ] 정지 장면과 천천히 움직인 장면을 각각 기록했다.
- [ ] 45초 bag의 기간·메시지 수·CameraInfo·TF·IMU 보정을 확인했다.
- [ ] 재생 시 라이브 발행을 종료하고 `/clock`과 소비 노드의 sim time을 맞췄다.
- [ ] 공개 데이터 E0 또는 Gemini 어댑터 검증 결과를 근거와 함께 기록했다.
- [ ] E1 전에 runner·exporter 구현과 입력 조건이 준비되었음을 확인했다.
- [ ] E1/E2는 같은 입력·전력·해상도 조건에서 각각 3회 비교했다.

## 결과와 미해결 항목

- 결과 상태: 미실행 / 통과 / 실패 중 실제 상태 기록.
- 실패 명령·종료코드·로그 위치:
- 누락된 보정·미지원 메시지·추가 구현:
- 이번에 변경한 설정과 이유:
- 다음 실험에 필요한 작업:

수집 결과는 `results/` 또는 외부 SSD에 저장한다. 장치 식별자·네트워크 정보가 포함된 원시 로그를 원격 저장소에 자동 업로드하지 않는다.
