"""Optional inference backends with an explicit model/output contract.

ONNX/TensorRT accept a YOLOv8/11-style raw, non-end-to-end output
[1, 4 + len(classes), candidates], cx/cy/w/h in model input pixels,
class probabilities (no objectness channel), RGB NCHW float / 255.
The image is resized directly to input_size (width,height); use a model exported
for this preprocessing. No weights, class labels or proprietary engines ship here.
"""
import hashlib
from pathlib import Path
import numpy as np


def _iou(a, b):
    left = np.maximum(a[:2], b[:2])
    right = np.minimum(a[2:], b[2:])
    intersection = float(np.prod(np.maximum(0, right-left)))
    area_a = float(np.prod(a[2:]-a[:2]))
    area_b = float(np.prod(b[2:]-b[:2]))
    return intersection / max(area_a+area_b-intersection, 1e-12)


def decode_yolo(output, classes, confidence, input_size, image_size, nms_threshold=.45):
    output = np.asarray(output)
    channels = 4 + len(classes)
    if not classes or output.ndim != 3 or output.shape[0] != 1 or output.shape[1] != channels:
        raise ValueError("YOLO raw output must be [1,4+len(classes),candidates]; class list must exactly match export")
    if not np.isfinite(output).all():
        raise ValueError("YOLO output contains nonfinite numbers")
    sx, sy = image_size[0]/input_size[0], image_size[1]/input_size[1]
    candidates = []
    for row in output[0].T:
        class_id = int(np.argmax(row[4:]))
        score = float(row[4+class_id])
        if not confidence <= score <= 1.:
            continue
        cx, cy, width, height = map(float, row[:4])
        box = np.array([(cx-width/2)*sx, (cy-height/2)*sy, (cx+width/2)*sx, (cy+height/2)*sy])
        box[[0, 2]] = np.clip(box[[0, 2]], 0, image_size[0])
        box[[1, 3]] = np.clip(box[[1, 3]], 0, image_size[1])
        if box[2] <= box[0] or box[3] <= box[1]:
            continue
        candidates.append(dict(class_id=class_id, **{"class": str(classes[class_id])},
                               bbox=box.tolist(), confidence=score))
    kept = []
    for candidate in sorted(candidates, key=lambda d: d["confidence"], reverse=True):
        if all(candidate["class_id"] != k["class_id"] or _iou(np.array(candidate["bbox"]), np.array(k["bbox"])) <= nms_threshold for k in kept):
            kept.append(candidate)
    return kept


class _TensorRTRunner:
    """TensorRT 10 named-I/O API + official cuda-python runtime bindings.

    Actual engine compatibility is checked by deserialization on the target GPU.
    One image input and one raw YOLO output; data-dependent outputs unsupported.
    API references: NVIDIA TensorRT 10 Python API Performing Inference and
    IExecutionContext.set_tensor_address/execute_async_v3. CUDA buffers stay alive
    through stream synchronization, including exceptional paths.
    """
    def __init__(self, path, input_size):
        import tensorrt as trt
        try:
            from cuda.bindings import runtime as cudart
        except ImportError:
            from cuda import cudart
        self.trt, self.cuda = trt, cudart
        self.logger = trt.Logger(trt.Logger.WARNING)
        self.runtime = trt.Runtime(self.logger)
        self.engine = self.runtime.deserialize_cuda_engine(Path(path).read_bytes())
        if self.engine is None:
            raise ValueError("TensorRT engine deserialization failed; rebuild for installed TensorRT/GPU")
        if not hasattr(self.engine, "num_io_tensors"):
            raise ValueError("TensorRT named-I/O API required (TensorRT 10 recommended)")
        names = [self.engine.get_tensor_name(i) for i in range(self.engine.num_io_tensors)]
        inputs = [n for n in names if self.engine.get_tensor_mode(n) == trt.TensorIOMode.INPUT]
        outputs = [n for n in names if self.engine.get_tensor_mode(n) == trt.TensorIOMode.OUTPUT]
        if len(inputs) != 1 or len(outputs) != 1:
            raise ValueError("TensorRT detector requires one input and one raw YOLO output")
        self.input, self.output = inputs[0], outputs[0]
        self.shape = (1, 3, int(input_size[1]), int(input_size[0]))
        self.context = None

    @staticmethod
    def _check(result):
        if int(result[0]) != 0:
            raise RuntimeError(f"CUDA runtime error {result[0]}")
        return result[1:]

    def __call__(self, blob):
        cuda = self.cuda
        self._check(cuda.cudaSetDevice(0))
        if self.context is None:
            self.context = self.engine.create_execution_context()
            if self.context is None or not self.context.set_input_shape(self.input, self.shape):
                raise ValueError("TensorRT input shape incompatible with configured input_size")
        dtype = np.dtype(self.trt.nptype(self.engine.get_tensor_dtype(self.input)))
        if dtype not in (np.dtype("float32"), np.dtype("float16")):
            raise ValueError("TensorRT detector supports float32/float16 image input")
        source = np.ascontiguousarray(blob, dtype=dtype)
        shape = tuple(self.context.get_tensor_shape(self.output))
        if any(int(d) <= 0 for d in shape) or np.prod(shape) > 10_000_000:
            raise ValueError("TensorRT output must have bounded resolved dimensions")
        output = np.empty(shape, dtype=self.trt.nptype(self.engine.get_tensor_dtype(self.output)))
        buffers, stream = [], None
        try:
            stream, = self._check(cuda.cudaStreamCreate())
            for name, array in ((self.input, source), (self.output, output)):
                pointer, = self._check(cuda.cudaMalloc(array.nbytes))
                buffers.append(pointer)
                if not self.context.set_tensor_address(name, int(pointer)):
                    raise RuntimeError("TensorRT refused tensor buffer")
            self._check(cuda.cudaMemcpyAsync(buffers[0], source.ctypes.data, source.nbytes,
                                             cuda.cudaMemcpyKind.cudaMemcpyHostToDevice, stream))
            if not self.context.execute_async_v3(stream_handle=stream):
                raise RuntimeError("TensorRT execute_async_v3 failed")
            self._check(cuda.cudaMemcpyAsync(output.ctypes.data, buffers[1], output.nbytes,
                                             cuda.cudaMemcpyKind.cudaMemcpyDeviceToHost, stream))
            self._check(cuda.cudaStreamSynchronize(stream))
            return output
        finally:
            if stream is not None:
                cuda.cudaStreamSynchronize(stream)
            for pointer in buffers:
                cuda.cudaFree(pointer)
            if stream is not None:
                cuda.cudaStreamDestroy(stream)


class Detector:
    def __init__(self, config, synthetic=False):
        self.config, self.synthetic = config, bool(synthetic)
        self.backend = config.get("backend", "disabled")
        self.classes = config.get("classes", [])
        if not all(isinstance(x,str) and x and len(x.encode("utf-8"))<=128 for x in self.classes):
            raise ValueError("detector class labels must be nonempty UTF-8 strings of at most 128 bytes")
        self.size = tuple(config.get("input_size", [320, 320]))
        self.confidence = float(config.get("confidence", .4))
        self.interval = int(config.get("interval", 1))
        if len(self.size) != 2 or min(self.size) < 1 or self.interval < 1 or not 0 <= self.confidence <= 1:
            raise ValueError("invalid detector input_size, interval or confidence")
        self.feature = dict(status="disabled", backend=self.backend, reason="configured_disabled",
                            model_sha256=None, model_format="raw_yolo_v8_v11", synthetic=self.backend == "synthetic")
        self.runner = None
        if self.backend == "disabled":
            return
        if self.backend == "synthetic":
            if not self.synthetic:
                raise ValueError("synthetic detector requires synthetic input")
            self.feature.update(status="success", reason=None)
            return
        if self.backend not in {"onnx", "tensorrt"}:
            raise ValueError(f"unsupported detector backend: {self.backend}")
        model = config.get("model")
        if not model or not Path(model).is_file():
            self.feature["reason"] = "model_missing"
            if config.get("require_model", False):
                raise FileNotFoundError(model or "detector.model is not configured")
            return
        if not self.classes or not all(isinstance(x, str) and x for x in self.classes):
            raise ValueError("detector.classes must exactly list model output classes")
        self.feature["model_sha256"] = hashlib.sha256(Path(model).read_bytes()).hexdigest()
        try:
            import cv2
            self.cv2 = cv2
            if self.backend == "onnx":
                self.runner = cv2.dnn.readNetFromONNX(str(model))
            else:
                self.runner = _TensorRTRunner(model, self.size)
        except ImportError as exc:
            self.feature["reason"] = f"backend_unavailable: {exc}"
            if config.get("require_model", False):
                raise
            return
        self.feature.update(status="success", reason=None)

    def detect(self, rgb, color_index):
        if self.feature["status"] != "success" or color_index % self.interval:
            return []
        h, w = rgb.shape[:2]
        if self.backend == "synthetic":
            return [dict(color_index=int(color_index), **{"class": "fixture_object"},
                         bbox=[float(w//4), float(h//4), float(3*w//4), float(3*h//4)],
                         confidence=1., synthetic=True)]
        blob = self.cv2.dnn.blobFromImage(rgb, 1./255., self.size, swapRB=False, crop=False)
        if self.backend == "onnx":
            self.runner.setInput(blob)
            output = self.runner.forward()
        else:
            output = self.runner(blob)
        result = decode_yolo(output, self.classes, self.confidence, self.size, (w, h), float(self.config.get("nms_threshold", .45)))
        for detection in result:
            detection.update(color_index=int(color_index), synthetic=self.synthetic)
        return result


class Tracker:
    """Bounded adjacent-frame association, not long-term re-identification.

    A sole same-class candidate must pass IoU >= .8, camera-surface distance
    <= .1m, frame-gap and identical valid submap gates. This deliberately loses
    identity during ambiguous views, motion or tracking loss. A track can be used
    only once per color frame. Dynamic labels remain dynamic at every observation.
    """
    def __init__(self, dynamic_classes=None, max_gap_frames=2, max_tracks=64):
        self.dynamic = set(["person", "car", "bus", "bicycle", "motorcycle", "dog", "cat"]
                           if dynamic_classes is None else dynamic_classes)
        self.max_gap = int(max_gap_frames)
        self.max_tracks = int(max_tracks)
        if self.max_gap < 1 or not 1 <= self.max_tracks <= 64:
            raise ValueError("tracker requires a positive frame gap and 1..64 tracks")
        self.count = 0
        self.tracks = {}
        self.last_frame = None
        self.submap = None

    def reset(self):
        self.tracks.clear()
        self.last_frame = None
        self.submap = None

    def _identity(self):
        identity = f"object-{self.count:08d}"
        self.count += 1
        return identity

    def assign(self, detection, point_camera_m=None, submap_id=None):
        frame = int(detection["color_index"])
        label = detection["class"]
        motion = "dynamic" if label in self.dynamic else "unknown"
        bbox = np.asarray(detection["bbox"], float)
        if bbox.shape != (4,) or not np.isfinite(bbox).all() or np.any(bbox[2:] <= bbox[:2]):
            raise ValueError("tracker requires a finite positive-area bbox")
        point = None if point_camera_m is None else np.asarray(point_camera_m, float)
        valid_geometry = (point is not None and point.shape == (3,) and np.isfinite(point).all()
                          and point[2] > 0 and submap_id is not None and int(submap_id) >= 0)
        if not valid_geometry:
            self.reset()
            return self._identity(), motion
        if (self.last_frame is not None and frame < self.last_frame) or self.submap != submap_id:
            self.reset()
        self.last_frame = frame
        self.submap = submap_id
        self.tracks = {identity: track for identity, track in self.tracks.items()
                       if frame-track["frame"] <= self.max_gap}
        candidates = []
        for identity, track in self.tracks.items():
            if (track["frame"] < frame and track["class"] == label and track["submap_id"] == submap_id
                    and _iou(bbox, track["bbox"]) >= .8
                    and np.linalg.norm(point-track["point"]) <= .1):
                candidates.append(identity)
        identity = candidates[0] if len(candidates) == 1 else self._identity()
        self.tracks[identity] = {"frame": frame, "class": label, "submap_id": submap_id,
                                 "bbox": bbox.copy(), "point": point.copy()}
        while len(self.tracks) > self.max_tracks:
            oldest = min(self.tracks, key=lambda key: (self.tracks[key]["frame"], key))
            del self.tracks[oldest]
        return identity, motion
