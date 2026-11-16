from typing import Dict, List
from fastapi import WebSocket


class MissionConnectionManager:
    """
    출동 작전 세션별 관제 앱 WebSocket 연결 관리자

    현장 데이터는 SSD 세션 가져오기(`app/scripts/import_fire_vision_session.py`)로만 들어오며,
    가져오기 스크립트가 결과를 저장할 때마다 `POST /api/v1/missions/{id}/notify/assessments`로 알리면
    이 관리자가 해당 작전을 구독 중인 앱에 메시지를 방송합니다.
    """

    def __init__(self):
        # mission_id -> List[WebSocket]
        self.active_connections: Dict[int, List[WebSocket]] = {}

    async def connect(self, mission_id: int, websocket: WebSocket):
        await websocket.accept()
        if mission_id not in self.active_connections:
            self.active_connections[mission_id] = []
        self.active_connections[mission_id].append(websocket)
        print(f"[WebSocket] 작전 #{mission_id}에 관제 앱 접속 (현재 연결 수: {len(self.active_connections[mission_id])})")

    def disconnect(self, mission_id: int, websocket: WebSocket):
        if mission_id in self.active_connections:
            if websocket in self.active_connections[mission_id]:
                self.active_connections[mission_id].remove(websocket)
            if not self.active_connections[mission_id]:
                del self.active_connections[mission_id]
        print(f"[WebSocket] 작전 #{mission_id} 관제 앱 연결 해제")

    async def broadcast(self, mission_id: int, message: dict):
        """특정 작전 세션을 구독 중인 모든 관제 앱에 메시지 전송"""
        if mission_id not in self.active_connections:
            return

        dead_connections = []
        for connection in self.active_connections[mission_id]:
            try:
                await connection.send_json(message)
            except Exception:
                dead_connections.append(connection)

        # 끊어진 소켓 정리
        for dead in dead_connections:
            self.disconnect(mission_id, dead)


# 전역 싱글톤 매니저 인스턴스
mission_manager = MissionConnectionManager()
