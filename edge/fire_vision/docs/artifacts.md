# 세션 결과 계약

미실행 산출물은 가짜 파일을 생성하지 않고 session.json.artifacts에 not_generated와 이유를 기록한다. E0의 진단 수치는 e0_validation.json에 둔다. 실험 성능 metrics.json과 구분한다.

| 파일 | 생성 조건·의미 |
|---|---|
| session.json | 모든 실험 시도. 설정과 SHA256, 실행 장치·버전·Git·모델, 단계 상태/사유 |
| calibration.json | 실제 입력에서 추출한 보정이 있을 때. K/D/R/P, TF, IMU intrinsic, 확인 근거 |
| trajectory.csv | E1 최종 SLAM 경로 구현·실행 이후. 현재 미생성 |
| object_observations.jsonl | E3 실제 검출 이후. 관측별 ID. 현재 미생성 |
| objects_final.json | E3 최종 pose 재투영 이후. association_validated=false이면 unique_object_count=null; observation_count와 구분. 현재 미생성 |
| map_3d.ply | E1 실제 점군. 좌표계·m 단위 메타데이터 연결. 현재 미생성 |
| map_2d.png / map_2d.yaml | E1 floor-aligned occupancy. 현재 미생성 |
| metrics.json | 해당 성능/SLAM 실험을 실제 수행한 이후. 미측정값은 null+사유. 현재 미생성 |
| tegrastats.log | Orin 원시 자원 로그를 실제 수집한 경우만. 현재 미생성 |
| failures.jsonl | 실패 또는 실행 불가 조건이 있을 때. 단계·code·detail·기록 시각 |
| evidence_frames/ | 실제 입력 이미지가 있을 때. E0 미리보기 또는 E3 관측 근거 |
| report.md | 모든 세션 시도. 실행 단계/실패·제약·파일 안내 |

E0 추가 파일: e0_validation.json, rgb_depth_preview.png, imu_plot.png, sync_histogram.png. 검증 후 manifest/calibration 또는 어떤 이미지라도 변경되면 재생을 거부한다. 원시 이미지 경로별 SHA256을 검증한다. 임시 추출 실패는 extraction.json.status=failed와 failures.jsonl로 보존한다.

관측 스키마는 원본 계획서 필드를 유지한다: session_id, observation_id, timestamp(원본 초), image_ref, class_label, bbox, mask_ref, camera_frame, point_camera_m, pose_ref, keyframe_id, point_map_m, valid_depth_ratio, depth_dispersion, position_status, detector_model_version, temperature(null). 추가로 정밀한 timestamp_ns, failure_reason, position_meaning, layer를 둔다. point_map_m=null이면 failure_reason 필수다. 실제 E3 구현 시 depth_dispersion은 m² 단위 깊이 분산으로 고정하고 유효 비율의 분모·배경 제거 정책을 함께 기록한다. 현재는 관측 생성/검증 함수만 테스트했다.

지도 구현 시 map_2d.yaml의 필수 메타데이터: image, frame_id, units=m, axis_convention, resolution(m/cell), origin=[x,y,yaw], T_floor_map(지도→바닥), height_min_m, height_max_m, unknown/occupied/free의 픽셀값과 의미, free-space sensor-ray policy, map_version, final_pose_source. 후보 픽셀값은 occupied=0/free=254/unknown=205이나 E1 exporter 구현 때 소비자와 검증해야 한다. 현재 YAML 지도를 생성하지 않았으므로 이 값으로 결과가 나왔다고 주장하지 않는다. 점이 없다는 이유만으로 free를 채우지 않는다.

RGB-D 경로 평가는 실제 정답의 출처·시간 매칭과 SE(3) 정합만 사용한다. Sim(3) scale 보정은 금지한다. 평가 전용 정답은 localization/replay 어댑터 입력으로 노출하지 않는다. 정답 pose 보조 재구성을 후속 구현하면 SLAM 결과와 별도 session으로 식별해야 한다.
