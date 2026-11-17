# 공간 수집 테스트 산출물

`spatial-synthetic/`는 CLI 합성 수집, `spatial-replay/`는 그 HDF5의 스트리밍 재분석 결과다.
각 디렉터리에는 실제 생성·검증한 session.h5와 map.json이 있다. 합성 자세와 fixture_object를
포함하며 실측 지도/탐지/성능 자료가 아니다. 두 결과는 synthetic=true, status=partial이다.

Reader와 `fire-vision spatial inspect`로 열 수 있다. 상대 참조가 유지되도록 두 파일을 함께 옮긴다.
상세 실행·비교 기록은 [검증 보고서](../docs/spatial-verification.md)에 있다.
