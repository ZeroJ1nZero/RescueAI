import os
import time
import base64
from datetime import datetime
from typing import Dict, List, Optional
from fastapi import WebSocket
from sqlalchemy.orm import Session
from app.models.mission import Mission
from app.models.sensor import SensorLog
from app.models.detection import DetectionEvent, EventType
from app.models.raw_telemetry import RawTelemetryLog
from app.models.ai_assessment import AIAssessment, HazardLevel, POIType
from app.schemas.telemetry import (
    RawTelemetryIngest,
    TacticalTelemetryIngest,
    GemmaAssessmentOutput,
)
from app.services.ai_assessor import ai_assessor


class MissionConnectionManager:
    """출동 작전 세션별 모바일 지도 앱 웹소켓 연결 및 데이터 파이프라인 관리자"""

    def __init__(self):
        # mission_id -> List[WebSocket]
        self.active_connections: Dict[int, List[WebSocket]] = {}
        # mission_id -> 마지막 sensor_logs DB 저장 타임스탬프 (ms)
        self.last_sensor_save_time: Dict[int, int] = {}

    async def connect(self, mission_id: int, websocket: WebSocket):
        await websocket.accept()
        if mission_id not in self.active_connections:
            self.active_connections[mission_id] = []
        self.active_connections[mission_id].append(websocket)
        print(f"[WebSocket] 작전 #{mission_id}에 모바일 지도 앱 단말기 접속 (현재 연결 수: {len(self.active_connections[mission_id])})")

    def disconnect(self, mission_id: int, websocket: WebSocket):
        if mission_id in self.active_connections:
            if websocket in self.active_connections[mission_id]:
                self.active_connections[mission_id].remove(websocket)
            if not self.active_connections[mission_id]:
                del self.active_connections[mission_id]
        print(f"[WebSocket] 작전 #{mission_id} 단말기 연결 해제")

    async def broadcast(self, mission_id: int, message: dict):
        """특정 작전 세션을 구독 중인 모든 지도 앱 단말기에 메시지 실시간 전송"""
        if mission_id not in self.active_connections:
            return

        dead_connections = []
        for connection in self.active_connections[mission_id]:
            try:
                await connection.send_json(message)
            except Exception:
                dead_connections.append(connection)

        # 유실된 소켓 정리
        for dead in dead_connections:
            self.disconnect(mission_id, dead)

    @staticmethod
    def _parse_timestamp_ms(ts_val: str | int | None) -> int:
        """ISO 8601 문자열('2026-10-12T05:20:00Z') 또는 Unix Epoch ms 정수를 ms 정수로 변환"""
        if ts_val is None:
            return int(time.time() * 1000)
        if isinstance(ts_val, int):
            # 초 단위로 들어온 경우 ms로 보정
            return ts_val * 1000 if ts_val < 10_000_000_000 else ts_val
        if isinstance(ts_val, str):
            ts_str = ts_val.strip()
            if ts_str.isdigit():
                val = int(ts_str)
                return val * 1000 if val < 10_000_000_000 else val
            try:
                dt = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                return int(dt.timestamp() * 1000)
            except Exception:
                return int(time.time() * 1000)
        return int(time.time() * 1000)

    async def process_raw_telemetry(
        self,
        db: Session,
        mission: Mission,
        packet: RawTelemetryIngest
    ) -> AIAssessment:
        """
        [핵심 파이프라인: Save-First -> Process & Assess -> Broadcast (발표자료 6~7페이지)]
        1. 수집 계층(Layer 01): 유입된 세션/프레임 원본 JSON을 raw_telemetry_logs에 최우선 선저장 (Save-First)
        2. 분석 계층(Layer 02): detected_objects (class, screen_box, description) 및 센서 메타데이터 정합·변환
        3. 관제 계층(Layer 03): RDBMS 메타/이벤트 저장 및 모바일/웹 표준 REST & WebSocket 브로드캐스트
        """
        now_ms = self._parse_timestamp_ms(packet.timestamp)
        mission_id = mission.mission_id
        device_id = packet.device_id or mission.device_id

        # ----------------------------------------------------
        # Step 1. [Save-First 원칙] 원시 JSON 데이터 최우선 선저장
        # ----------------------------------------------------
        raw_json_dict = packet.model_dump(by_alias=True)
        snapshot_rel_path = None

        # 스냅샷 이미지 base64 디코딩 및 정적 파일 저장
        if packet.snapshot_base64:
            try:
                snapshot_dir = "static/snapshots"
                os.makedirs(snapshot_dir, exist_ok=True)
                filename = f"snapshot_m{mission_id}_{now_ms}.jpg"
                file_full_path = os.path.join(snapshot_dir, filename)
                with open(file_full_path, "wb") as f:
                    f.write(base64.b64decode(packet.snapshot_base64))
                snapshot_rel_path = f"snapshots/{filename}"
                raw_json_dict["snapshot_base64"] = snapshot_rel_path
            except Exception as e:
                print(f"[Snapshot Save Error] {e}")

        raw_log = RawTelemetryLog(
            mission_id=mission_id,
            device_id=device_id,
            timestamp=now_ms,
            raw_payload=raw_json_dict,
            snapshot_path=snapshot_rel_path,
            is_processed=False
        )
        db.add(raw_log)
        db.flush()  # raw_log.log_id 확보

        # ----------------------------------------------------
        # Step 2. 좌표 정합 (실측 location 또는 프로토타입 2D screen_box 중심점 매핑)
        # ----------------------------------------------------
        if packet.location:
            pos_x, pos_y, pos_z = packet.location.x, packet.location.y, packet.location.z
        elif packet.detected_objects and len(packet.detected_objects) > 0:
            # 프로토타입 단계(발표자료 6페이지): 단일 카메라 2D 영상 픽셀 상대 위치(screen_box) 추출
            box = packet.detected_objects[0].screen_box
            pos_x = round((box[0] + box[2]) / 2.0, 2)
            pos_y = round((box[1] + box[3]) / 2.0, 2)
            pos_z = 0.0
        else:
            pos_x, pos_y, pos_z = 0.0, 0.0, 0.0

        # 1Hz 다운샘플링 위치/프레임 궤적 기록
        last_save = self.last_sensor_save_time.get(mission_id, 0)
        if now_ms - last_save >= 1000 or packet.frame_id is not None:
            sensor_log = SensorLog(
                mission_id=mission_id,
                device_id=device_id,
                timestamp=now_ms,
                pos_x=pos_x,
                pos_y=pos_y,
                pos_z=pos_z,
                imu_yaw=packet.imu.yaw if packet.imu else None,
                ambient_temp=packet.temperature.avg if packet.temperature else None
            )
            db.add(sensor_log)
            self.last_sensor_save_time[mission_id] = now_ms

        # 탐지된 객체(detected_objects)가 있으면 detection_events 테이블에도 개별 정형 저장
        if packet.detected_objects:
            for obj in packet.detected_objects:
                cls_lower = obj.class_label.lower()
                if cls_lower in ("person", "human", "survivor", "victim", "사람", "구조대상"):
                    ev_type = EventType.PERSON
                elif cls_lower in ("fire", "flame", "smoke", "hotspot", "화재", "화점", "연기"):
                    ev_type = EventType.FIRE
                else:
                    ev_type = EventType.HAZARD

                box = obj.screen_box
                obj_x = packet.location.x if packet.location else round((box[0] + box[2]) / 2.0, 2)
                obj_y = packet.location.y if packet.location else round((box[1] + box[3]) / 2.0, 2)
                obj_z = packet.location.z if packet.location else 0.0

                det_event = DetectionEvent(
                    mission_id=mission_id,
                    device_id=device_id,
                    timestamp=now_ms,
                    event_type=ev_type,
                    confidence=0.95,
                    coord_x=obj_x,
                    coord_y=obj_y,
                    coord_z=obj_z,
                    max_temperature=packet.temperature.max if packet.temperature else None,
                    snapshot_path=snapshot_rel_path
                )
                db.add(det_event)

        # ----------------------------------------------------
        # Step 3. [분석 계층] Gemma 3 4B VLM / 상황 판단 구조화
        # ----------------------------------------------------
        ai_output: GemmaAssessmentOutput = ai_assessor.assess_situation(
            packet=packet,
            image_path=snapshot_rel_path
        )

        assessment_payload = ai_output.model_dump()
        if packet.frame_id is not None:
            assessment_payload["frame_id"] = packet.frame_id
        if packet.detected_objects is not None:
            assessment_payload["detected_objects"] = [
                obj.model_dump(by_alias=True) for obj in packet.detected_objects
            ]

        assessment = AIAssessment(
            mission_id=mission_id,
            device_id=device_id,
            raw_log_id=raw_log.log_id,
            timestamp=now_ms,
            hazard_level=ai_output.hazard_level,
            situation_summary=ai_output.situation_summary,
            human_detected=ai_output.human_detected,
            human_status=ai_output.human_status,
            action_recommendation=ai_output.action_recommendation,
            poi_type=ai_output.poi_type,
            coord_x=pos_x,
            coord_y=pos_y,
            coord_z=pos_z,
            assessment_json=assessment_payload,
            snapshot_path=snapshot_rel_path
        )
        db.add(assessment)

        # 원시 로그 처리 완료 상태 갱신
        raw_log.is_processed = True
        raw_log.processed_at = datetime.utcnow()

        db.commit()
        db.refresh(assessment)

        # ----------------------------------------------------
        # Step 4. [관제 계층] 모바일/웹 관제 UI 실시간 WebSocket 브로드캐스트
        # ----------------------------------------------------
        loc_msg = {
            "type": "LOCATION_UPDATE",
            "mission_id": mission_id,
            "device_id": device_id,
            "timestamp": now_ms,
            "frame_id": packet.frame_id,
            "x": pos_x,
            "y": pos_y,
            "z": pos_z,
            "yaw": packet.imu.yaw if packet.imu else None,
            "max_temperature": packet.temperature.max if packet.temperature else None,
        }
        await self.broadcast(mission_id, loc_msg)

        if ai_output.hazard_level in (HazardLevel.CRITICAL, HazardLevel.WARNING) or ai_output.human_detected:
            title_prefix = "🔥 화재 위험" if ai_output.poi_type == POIType.FIRE_HOTSPOT else (
                "🚨 구조 대상자 발견" if ai_output.human_detected else "⚠️ 현장 위험 주의"
            )
            marker_msg = {
                "type": "AI_MARKER_ALERT",
                "mission_id": mission_id,
                "assessment_id": assessment.assessment_id,
                "timestamp": now_ms,
                "frame_id": packet.frame_id,
                "hazard_level": ai_output.hazard_level.value,
                "poi_type": ai_output.poi_type.value if ai_output.poi_type else "OBSTACLE_HAZARD",
                "title": f"[{ai_output.hazard_level.value}] {title_prefix}",
                "summary": ai_output.situation_summary,
                "action_recommendation": ai_output.action_recommendation,
                "coord": {
                    "x": pos_x,
                    "y": pos_y,
                    "z": pos_z
                },
                "detected_objects": [
                    obj.model_dump(by_alias=True) for obj in packet.detected_objects
                ] if packet.detected_objects else [],
                "snapshot_url": f"/static/{snapshot_rel_path}" if snapshot_rel_path else None
            }
            await self.broadcast(mission_id, marker_msg)

        return assessment

    # 하위 호환용 래퍼
    async def process_telemetry(self, db: Session, mission: Mission, packet: TacticalTelemetryIngest):
        return await self.process_raw_telemetry(db=db, mission=mission, packet=packet)


# 전역 싱글톤 매니저 인스턴스
mission_manager = MissionConnectionManager()

