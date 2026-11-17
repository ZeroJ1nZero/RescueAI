# 공간 데이터 수집 시스템

사용자가 제공한 13개 절을 구현 계약으로 삼는다. 일반 구현 선택은 자율 진행하도록 위임받았다.
기존 E0/ROS bag 검증 명령 및 FastAPI 서버는 보존한다. 새 `fire_vision.spatial` 패키지와
`fire-vision spatial` 명령을 추가한다. 내부 SSD 대체 기록이나 시스템 설정 자동 적용은 하지 않는다.

## 접근 선택

기존 ROS 전체 의존 경로를 수집 서비스에 강제하면 개발 Mac과 부팅 서비스 설치가 커진다.
직접 Orbbec Python SDK 입력, HDF5 스트리밍 재생, 합성 입력을 같은 인터페이스로 연결한다.
실제 SDK의 지원 API를 공식 소스에서 확인한다. RGB-D 위치 추정은 선택 Open3D odometry를
연결하며 loop closure 없는 odometry라는 한계를 명시한다. 미설치 시 pose 없음으로 기록한다.
TensorRT engine과 ONNX는 선택 추론 경로이고 모델 미제공 시 탐지는 비활성이다.

## 구조

SensorSource → bounded raw queue → 단일 HDF5 writer → bounded AI queue → AnalysisPipeline.
AI 결과는 bounded result queue로 writer에 전달한다. raw 우선, AI 초과는 건너뛰고 집계한다.
최종 writer는 종료 drain 후 경로 기반 지도·관측을 확정하고 HDF5 검증/close/rename/hash,
마지막 map.json 원자적 rename 순으로 공개한다. 중단 파일은 `.partial`로 보존한다.
SessionController는 READY/RECORDING/FINALIZING/DONE/ERROR와 비동기 종료를 관리한다.

## 정직성 계약

synthetic 플래그는 입력·자세·검출 결과에 전파한다. 실센서 원본은 복사해 SDK 소유권에서 분리한다.
추적 실패와 시계 reset은 구간을 분리하고 정합되지 않은 submap을 합치지 않는다.
카메라 좌표와 지도 좌표의 유효성을 분리한다. 지도 미지원이면 JSON은 partial이다.
표면 점군은 관측 표면이며 자유공간/안전 경로를 의미하지 않는다. IMU는 원시 독립 샘플이다.
행렬은 row-major 저장, 열벡터 왼쪽 곱, T_destination_from_source 규약이다.

## 검증

기하·시간·SSD 실패·상태 경합·기록 재생·schema/참조 무결성 위험 테스트를 먼저 작성한다.
기존 전체 테스트와 실제 합성 CLI 생성/재생/Reader를 실행한다. 성능은 측정된 실행 환경을
명시하고 Jetson 성능으로 일반화하지 않는다. 하드웨어 전용 항목은 배포 체크리스트로 남긴다.
