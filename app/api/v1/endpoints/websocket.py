from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query, status
from app.core.security import decode_token
from app.services.mission_manager import mission_manager

router = APIRouter(prefix="/ws", tags=["실시간 작전 관제 WebSocket"])


@router.websocket("/missions/{mission_id}/dashboard")
async def websocket_dashboard_endpoint(
    websocket: WebSocket,
    mission_id: int,
    token: str = Query(..., description="소방/군 공무원 보안 JWT 토큰")
):
    """
    통제실 안드로이드 태블릿 대시보드용 실시간 WebSocket 엔드포인트
    - 엣지에서 들어오는 3D 위치 마커(LOCATION_UPDATE) 및 위험 고온/인명탐지 경보(ALERT_EVENT)를 실시간 수신
    """
    # 1. 공무원 보안 JWT 토큰 검증
    payload = decode_token(token)
    if not payload:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="유효하지 않은 보안 토큰")
        return

    # 2. 커넥션 매니저에 등록
    await mission_manager.connect(mission_id, websocket)

    # 3. 최초 연결 환영 및 접속 확인 메시지 전송
    await websocket.send_json({
        "type": "CONNECTION_ESTABLISHED",
        "mission_id": mission_id,
        "officer": payload.get("full_name"),
        "role": payload.get("role"),
        "message": f"작전 #{mission_id} 실시간 전술 채널에 정상 연결되었습니다."
    })

    try:
        while True:
            # 안드로이드 클라이언트로부터의 하트비트/핑 수신
            data = await websocket.receive_text()
            if data == "PING":
                await websocket.send_text("PONG")
    except WebSocketDisconnect:
        mission_manager.disconnect(mission_id, websocket)
    except Exception as e:
        print(f"[WebSocket Error] {e}")
        mission_manager.disconnect(mission_id, websocket)
