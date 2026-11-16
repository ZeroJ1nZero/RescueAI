# 확인한 공식 자료 (2026-11-09)

실측 파일을 아직 확보하지 않았다. 아래 내용은 문헌 확인이며 실제 bag 검사 결과가 아니다.

| 자료 | 이번 구현에 반영한 내용 | 버전·제약 |
|---|---|---|
| [OpenLORIS 데이터 설명](https://lifelong-robotic-vision.github.io/dataset/scene.html) | D435i 깊이·RGB, 별도 accel/gyro, 보정과 알려진 데이터 오류 조사 | 실제 파일의 CameraInfo/TF와 출처 검토를 별도로 요구 |
| [공식 배포 목록](https://github.com/lifelong-robotic-vision/OpenLORIS-Scene/blob/master/download.md) | ROS bag 배포 형식, 현재 다운로드 링크 | Google Drive 과거 링크 대신 해당 목록에서 다운로드 선택. 배포 묶음 구성은 변할 수 있음 |
| [공식 IMU 병합 코드](https://github.com/lifelong-robotic-vision/openloris-scene-tools/blob/master/dataprocess/merge_imu_topics.py) | D400 accel/gyro 토픽 후보 확인 | 원본 코드를 수정하거나 실행하지 않음. E0는 두 샘플열을 그대로 보존 |
| [rosbags 0.10.11 소스](https://gitlab.com/ternaris/rosbags/-/tree/v0.10.11) / [동일 버전 배포 정보](https://pypi.org/project/rosbags/0.10.11/) | ROS 없이 ROS1/ROS2 bag 읽기, AnyReader API | 0.10.11 고정. Python >=3.10. 실제 설치 코드도 확인하고 바이너리 ROS1 합성 bag으로 검증 |
| [ROS Humble 설치 공식 원문](https://github.com/ros2/ros2_documentation/blob/humble/source/Installation/Ubuntu-Install-Debs.rst) | Ubuntu22.04/arm64 조건부 후보 | docs.ros.org 페이지는 접근 거절되어 공식 GitHub 원문 확인. 설치 실행 안 함 |
| [RTAB-Map 릴리스](https://github.com/introlab/rtabmap/releases) / [rtabmap_ros 릴리스 이력](https://github.com/introlab/rtabmap_ros-release) | core 0.22.1 / ROS Humble release 0.22.1-1 조건부 고정 후보 | 대상 설치·바이너리 빌드 번호·런타임 호환성 미검증. 태그 직접 조회는 DNS/웹 캐시 제한으로 실패. 실제 Orin에서 재확인 필요 |
| [rtabmap_ros SLAM 공식 문서](https://github.com/introlab/rtabmap_ros/blob/ros2/rtabmap_slam/doc/rtabmap.md) | orientation 기반 중력 제약 역할 확인 | 가변 ros2 브랜치의 개념 참고. 버전별 launch/파라미터 실행 검증은 미실행. 완전한 VIO로 표현하지 않음 |
| [JetPack6.2](https://docs.nvidia.com/jetson/jetpack/6.2/release-notes/index.html) / [L4T36.4.3](https://docs.nvidia.com/jetson/archives/r36.4.3/ReleaseNotes/Jetson_Linux_Release_Notes_r36.4.3.pdf) | Orin과 Ubuntu22.04 기반 후보 조합 조사 | 실제 장치 버전으로 가정하지 않음. 재설치·업그레이드 요구 없음 |
| [L4T36.4.3 tegrastats](https://docs.nvidia.com/jetson/archives/r36.4.3/DeveloperGuide/AT/JetsonLinuxDevelopmentTools/TegrastatsUtility.html) | 후속 E4 원시 로그 수집 명령 참고 | 현재 장치에는 없음. E4 자동 측정·파서는 아직 미구현 |

선택한 개발 버전은 requirements-dev-macos.lock에 기록했다. Orin 후보는 profiles/orin-ubuntu22.04-humble.json에 **미활성·미검증**으로 분리했다. E0 소프트웨어에 CUDA·TensorRT·검출기·Gemma 의존성은 없다. 원격 장치 버전을 모르는 상태에서 해당 패키지를 임의 설치하지 않는다.

## Jetson · Gemini 2 설정 추가 조사 (2026-11-16)

아래 자료를 확인하여 [보드·카메라 설정 안내](jetson-gemini2-setup.md)와 [후보 프로파일](../profiles/jetson-gemini2.json)을 작성했다. 실제 장비 검증 결과는 아니다.

| 공식 자료 | 반영 내용 |
|---|---|
| [JetPack 6.2.1 릴리스](https://docs.nvidia.com/jetson/jetpack/6.2.1/release-notes/index.html) | L4T 36.4.4 대응 확인. 기존 설치를 자동 업그레이드하지 않음 |
| [Orbbec 지원 카메라](https://orbbec.github.io/OrbbecSDK_ROS2_Docs/source/1_overview/supported_cameras.html) | Gemini 2와 Gemini 2 L/XL의 모델·브랜치 구분 |
| [ROS wrapper v2.10.7 릴리스](https://github.com/orbbec/OrbbecSDK_ROS2/releases/tag/v2.10.7) | wrapper 고정 후보와 Gemini 2 권장 펌웨어 1.4.98. 실기 검증 전 후보 유지 |
| [Orbbec 공식 빌드 절차](https://orbbec.github.io/OrbbecSDK_ROS2_Docs/source/2_installation/build_the_package.html) | 소스 빌드·의존성·udev 설치 흐름 |
| [Gemini 2 launch 소스](https://github.com/orbbec/OrbbecSDK_ROS2/blob/v2-main/orbbec_camera/launch/gemini2.launch.py) | 정렬·RGB/depth·분리 IMU 출력 인자 조사. 가변 브랜치이므로 설치 버전의 `--show-args`로 다시 확인 |
| [Orbbec 토픽·서비스](https://orbbec.github.io/OrbbecSDK_ROS2_Docs/source/2_installation/package_description.html) | 실제 토픽 조사 후 bag 기록. IMUInfo·스케일·보정은 D435i 어댑터와 별도 검증 |
