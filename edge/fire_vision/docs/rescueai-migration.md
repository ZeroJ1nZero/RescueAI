# RescueAI 이전 및 검증 기록

확인일: 2026-11-16. 대상 원격: `https://github.com/ZeroJ1nZero/RescueAI`, 브랜치 `main`.
통합 기준: `d645f0f4337a30ed7bfe6639a6f89eaffd11ba03`. 통합은 해당 commit의 후속 commit으로 진행하며 별도 저장소 이력을 강제로 merge하지 않는다.

## 이전 범위와 충돌 최소화

- 원본 Fire Vision의 추적 파일과 무시되지 않은 미커밋 파일 **39개 전체**를 `edge/fire_vision/`에 포함했다. 원본 작업 트리는 수정하지 않았다.
- 코드·설정·프로파일·테스트·Python 설정·문서와 새 SSD 스크립트를 포함한다. `.git`, `.venv`, 캐시, 데이터, 결과, 기존 delivery bundle은 제외했다.
- 기존 RescueAI 파일 중 루트 `README.md`에 안내 4줄만 추가했다. `app/`, `requirements.txt`, `.gitignore`, `.env.example`, `docs/api_specification.md`, 샘플 static 파일은 바이트 단위로 유지했다.
- Python 프로젝트와 의존성을 하위 디렉터리에 두어 백엔드 패키지 설정과 섞이지 않도록 했다.

원본과 다르게 조정한 파일은 아래 **6개**다. 나머지 원본 파일은 바이트 단위로 동일하다.

| 파일 | 이전에 따른 조정 |
|---|---|
| `README.md` | RescueAI 위치와 독립 venv 설치, Git 정보 안내 |
| `docs/repository-setup.md` | 새 원격·clone·업데이트·프로젝트 경로 |
| `docs/ssd-transfer.md` | 통합 후 새 bundle 생성 방법·기본 clone 경로 |
| `docs/jetson-gemini2-setup.md` | 보드에서 작업할 디렉터리 |
| `scripts/jetson-setup.sh` | RescueAI 원격 및 저장소/패키지 경로 분리 |
| `tests/test_jetson_setup_script.py` | 하위 프로젝트 구조의 bundle·기존 작업 보존·설치 경로 검증 |

[원본 파일 SHA256](verification/rescueai-migration-source-sha256.json)은 복사 당시 현재 파일 내용의 해시다. 기존 `verification/pytest.xml`·`source-sha256.json`·완료 보고서는 과거 기록으로 보존했으며 이번 검증 결과로 덮어쓰지 않았다.

## Python 환경과 검증

Mac 개발용 Python **3.13.5**의 새 독립 venv에서 `requirements-dev-macos.lock`과 이 패키지를 설치했다. 기존 Conda 시스템 패키지를 공유하지 않았다. 설치된 패키지 **20개**의 의존성 호환성 검사가 통과했다.

재현 명령은 `edge/fire_vision/`에서 다음과 같다.

```bash
python3.13 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev-macos.lock -e .
.venv/bin/python -m pip check
env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest -q
```

- 원본 전체 테스트: **43 passed**.
- 이전 후 새 venv 전체 테스트: **44 passed**. 경로 변경을 위한 테스트가 기존 스크립트에서 실패하는 것을 확인한 뒤 수정했고, 스크립트 테스트는 **8 passed**다.
- `bash -n scripts/jetson-setup.sh`: 통과.
- `project`·`python` dry-run: RescueAI clone 위치와 `edge/fire_vision/.venv-jetson` 경로 확인.
- 설치된 `fire-vision --help`: 통과.
- CLI `environment`: 종료코드 0.
- CLI `check-input`의 데이터 부재와 `run E1`의 단계 차단: 각각 예상 종료코드 2, `not_run` 상태 확인.
- CLI `export`: 종료코드 0, 무결성 검사 통과. 실제 없는 지도 산출물을 생성하지 않음.
- 기존 백엔드 Python 파일: AST 구문 검사 통과. DB 접속·API 기동 검증은 이번 이전 범위에 포함하지 않았다.

Jetson은 기존 안내대로 ROS와 같은 시스템 Python ABI 및 NumPy `<2` 제약을 사용한다. Mac lock을 Jetson에 설치하거나 Mac venv를 복사하지 않는다. Jetson·카메라·ROS 실제 장비 검증은 수행하지 않았다.

## 푸시와 후속 갱신

이전 commit을 로컬 RescueAI `main`에 fast-forward한 뒤 작업 트리와 원격 추적 상태를 확인한다. 사용자가 실행할 명령:

```bash
cd ~/IdeaProjects/RescueAI
git push origin main
```

다른 팀원이 그 사이 원격에 commit한 경우에는 `git fetch origin` 후 `git rebase origin/main`으로 갱신한다. 같은 파일을 서로 수정하면 충돌 가능성은 남지만, 기존 서버 파일을 유지하고 새 디렉터리에 추가하여 겹치는 범위를 줄였다. force push는 필요 없다.
