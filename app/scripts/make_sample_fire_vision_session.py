"""
연암소방대 - 시험용 임베디드 세션 생성기 (Jetson·카메라 없이 경로 B 시험)

임베디드 `edge/fire_vision`의 `extract-bag` 결과와 같은 구조(format: fire-vision-normalized-v1)의 폴더를 만듭니다.
  출력 폴더/
    manifest.json      streams.rgb[{timestamp_ns, path, sha256, ...}], accel, gyro
    calibration.json   (빈 보정 정보)
    rgb/000000_<ns>.npy  uint8 HxWx3 (rgb8)

사용 예 (프로젝트 루트에서):
  # 1) 실제 사진 폴더로 세션 만들기 (사진 1장 = 1초, Gemma 실제 성능 확인용)
  python app/scripts/make_sample_fire_vision_session.py D:/test_session --images D:/photos
  # 2) 사진 없이 합성 영상 만들기 (5초, 15fps — 파이프라인 동작 확인용)
  python app/scripts/make_sample_fire_vision_session.py D:/test_session

  # 만든 세션 가져오기
  python app/scripts/import_fire_vision_session.py D:/test_session --mission 1

※ 실제 측정 데이터가 아니므로 결과를 실험 결과로 보고하지 마세요. IMU 값은 고정된 가짜 값입니다.
"""

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
MAX_SIDE = 1280


def _frame_row(out: Path, idx: int, t: int, arr: np.ndarray) -> dict:
    name = f"rgb/{idx:06d}_{t}.npy"
    np.save(out / name, arr, allow_pickle=False)
    return {"timestamp_ns": t, "record_ns": t, "frame_id": "camera_color_optical_frame",
            "topic": "/camera/color/image_raw", "path": name,
            "sha256": hashlib.sha256((out / name).read_bytes()).hexdigest(),
            "original_encoding": "rgb8", "normalized_encoding": "rgb8",
            "width": int(arr.shape[1]), "height": int(arr.shape[0]), "dtype": "uint8"}


def main() -> int:
    ap = argparse.ArgumentParser(description="시험용 fire-vision-normalized-v1 세션 생성")
    ap.add_argument("out", help="만들 세션 폴더 (없는 경로)")
    ap.add_argument("--images", help="사진 폴더 (jpg/png). 지정하면 사진 1장을 1초 간격 프레임으로 사용")
    ap.add_argument("--seconds", type=float, default=5.0, help="합성 영상 길이(초, --images 미지정 시)")
    ap.add_argument("--fps", type=int, default=15, help="합성 영상 fps (--images 미지정 시)")
    args = ap.parse_args()

    out = Path(args.out)
    if out.exists():
        print(f"[오류] 이미 있는 경로입니다: {out}")
        return 2
    t0 = time.time_ns()
    frames = []

    if args.images:
        src = sorted(p for p in Path(args.images).iterdir() if p.suffix.lower() in IMAGE_EXT)
        if not src:
            print(f"[오류] 사진이 없습니다: {args.images}")
            return 2
        (out / "rgb").mkdir(parents=True)
        for i, p in enumerate(src):
            img = Image.open(p).convert("RGB")
            scale = min(1.0, MAX_SIDE / max(img.size))
            if scale < 1.0:
                img = img.resize((round(img.width * scale), round(img.height * scale)))
            frames.append(_frame_row(out, i, t0 + i * 1_000_000_000, np.asarray(img, dtype=np.uint8)))
        duration_ns = len(src) * 1_000_000_000
    else:
        (out / "rgb").mkdir(parents=True)
        n = max(1, int(args.seconds * args.fps))
        for i in range(n):
            img = np.full((800, 1280, 3), 40, np.uint8)
            x = 200 + i * 5
            img[300:500, x:x + 200] = (220, 80, 30)  # 이동하는 주황 사각형
            frames.append(_frame_row(out, i, t0 + i * (1_000_000_000 // args.fps), img))
        duration_ns = int(args.seconds * 1e9)

    imu = lambda k: [{"timestamp_ns": t0 + j * 5_000_000, "record_ns": t0 + j * 5_000_000, "frame_id": "camera_imu_frame",
                      "topic": f"/camera/{k}/sample",
                      "value": [0.0, -9.81, 0.0] if k == "accel" else [0.0, 0.0, 0.0]}
                     for j in range(max(1, duration_ns // 5_000_000))]
    manifest = {
        "format": "fire-vision-normalized-v1",
        "source": {"identity": "rescueai-sample", "sensor": "synthetic" if not args.images else "photos",
                   "path": str(Path(args.images).resolve()) if args.images else None, "sha256": {},
                   "note": "시험용 생성 데이터 — 실측 아님"},
        "extraction": {"requested": {"start_offset_s": 0.0, "duration_s": duration_ns / 1e9},
                       "timestamp_basis": "header", "complete": True, "start_ns": t0, "stop_ns": t0 + duration_ns},
        "streams": {"rgb": frames, "depth": [], "accel": imu("accel"), "gyro": imu("gyro")},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    (out / "calibration.json").write_text(json.dumps({"cameras": [], "transforms": [], "imu_intrinsics": []}), encoding="utf-8")
    print(f"[완료] {out} — RGB 프레임 {len(frames)}개 ({duration_ns / 1e9:.1f}초)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
