# Spatial acquisition implementation plan

> **For agentic workers:** use superpowers:subagent-driven-development for independent adapters; integrate and verify in this checkout. No commit/push requested.

**Goal:** bounded sensor capture with session.h5/map.json and honest spatial validity.
**Architecture:** extend existing Python edge package, preserve E0 commands. Sources and geometry independent of threaded recording/controller.
**Tech Stack:** Python >=3.10, numpy, h5py, jsonschema; optional OpenCV/Orbbec/Open3D/TensorRT.
**Spec:** ../specs/2026-11-17-spatial-design.md and user's complete 13-section request.

## Global constraints
Never overwrite input, never use internal disk as SSD fallback, never claim synthetic poses as SLAM.
All metric lengths meters, time int64 microseconds plus original clocks. Bounded queues, one HDF5 writer.

## Review focus
Mixed/reset clocks, SDK frame lifetime, disconnected camera, storage disappearance, finalization/press races.
Tests explicitly exercise reset handling, copy ownership, injected input/write failures, mount rejection and repeated press.

## Tasks
- [x] 1. Define `spatial/types.py`: Sample(stream,data,frame_id,sensor_timestamp,timestamp_unit,clock,host_monotonic_ns,time_us,depth_scale_m), Capture(color,depth,imu,synthetic_pose), source calibration/metadata contracts.
- [x] 2. Test then implement `sources.py`: synthetic, HDF5 replay, SDK capture. Independent raw timestamps, copied buffers, device info. Official API audit.
- [x] 3. Test then implement `geometry.py`, `inference.py`: nearest time pairing, calibrated D2C, robust surface position, conservative tracks, optional actual odometry, synthetic-only pose fixtures.
- [x] 4. Test then implement `storage.py`, `reader.py`, schema: extensible raw arrays/tables, references, strict JSON, hash, final commit, partial files on failure.
- [x] 5. Test then implement `controller.py`, `health.py`, `io.py`: bounded queues, raw priority, async finalization, debounce, SSD mount/device checks, stop signals.
- [x] 6. Integrate CLI/config/package/service/docs; run all tests, synth record/replay/Reader, document measured evidence and hardware-only gaps.

Each task follows failing-risk-test → implement → targeted passing test. Integration concludes with the complete existing pytest suite and artifact integrity verification.

## Verification outcome

120 tests passed; real CLI synthetic capture and streaming replay preserved every raw stream.
Reader/schema/hash checks, wheel packaged schema and CPU ONNX fixture execution passed.
Hardware-only acquisition/GPIO/SSD/TensorRT/Open3D and loop-closing SLAM limits are recorded in
`docs/spatial-verification.md`; no hardware completion or measured Jetson performance is claimed.
