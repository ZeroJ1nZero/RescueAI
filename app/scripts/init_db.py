import os
import sys

# 프로젝트 루트 경로를 sys.path에 추가 (독립 실행 대응)
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "../..")))

import pymysql
from sqlalchemy.orm import Session
from app.core.config import settings
from app.core.database import engine, SessionLocal, Base
from app.core.security import get_pin_hash
from app.models import (
    User,
    UserRole,
    AuthorizedTerminal,
    Device,
    DeviceStatus,
    Building,
    SpatialMap,
    RawTelemetryLog,
    AIAssessment,
    HazardLevel,
    POIType,
)


def ensure_database_exists() -> None:
    """MariaDB에 데이터베이스가 없으면 자동으로 생성합니다."""
    print("==================================================")
    print(f"0. MariaDB 데이터베이스('{settings.DB_NAME}') 존재 여부 확인 중...")
    try:
        conn = pymysql.connect(
            host=settings.DB_HOST,
            port=settings.DB_PORT,
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            charset="utf8mb4"
        )
        with conn.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{settings.DB_NAME}` "
                "DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"
            )
        conn.commit()
        conn.close()
        print(f"   -> 데이터베이스('{settings.DB_NAME}') 준비 완료.")
    except Exception as e:
        print(f"   -> [오류] 데이터베이스 자동 생성 실패: {e}")
        raise e


def init_database() -> None:
    """코드 퍼스트: 모델을 기반으로 MariaDB에 테이블을 생성하고 소방/군 공무원 초기 시드 데이터를 적재합니다."""
    # 0. 데이터베이스 존재 보장
    ensure_database_exists()

    print("\n1. MariaDB 테이블 생성 (Base.metadata.create_all)...")
    Base.metadata.create_all(bind=engine)
    print("   -> 10개 핵심 테이블 (raw_telemetry_logs, ai_assessments 포함) 생성/검증 완료.")

    # 기존 DB 테이블 컬럼 마이그레이션 (buildings, spatial_maps 신규 컬럼 보장)
    try:
        with engine.connect() as conn:
            # buildings.latitude, longitude
            conn.execute(pymysql.converters.escape_string if False else __import__("sqlalchemy").text(
                "ALTER TABLE buildings ADD COLUMN IF NOT EXISTS latitude FLOAT NULL;"
            ))
            conn.execute(__import__("sqlalchemy").text(
                "ALTER TABLE buildings ADD COLUMN IF NOT EXISTS longitude FLOAT NULL;"
            ))
            # spatial_maps 2D 평면도 컬럼
            conn.execute(__import__("sqlalchemy").text(
                "ALTER TABLE spatial_maps ADD COLUMN IF NOT EXISTS floor_plan_image VARCHAR(255) NULL;"
            ))
            conn.execute(__import__("sqlalchemy").text(
                "ALTER TABLE spatial_maps ADD COLUMN IF NOT EXISTS width_meter FLOAT NULL;"
            ))
            conn.execute(__import__("sqlalchemy").text(
                "ALTER TABLE spatial_maps ADD COLUMN IF NOT EXISTS height_meter FLOAT NULL;"
            ))
            conn.commit()
            print("   -> 기존 테이블 2D 지도 연동 컬럼 마이그레이션 완료.")
    except Exception as e:
        print(f"   -> [참고] 컬럼 마이그레이션 스킵 또는 완료: {e}")

    db: Session = SessionLocal()
    try:
        print("\n2. 소방/군 현장 공무원 및 인가 단말기 시드 데이터 적재 중...")

        # 2.1 인가된 현장 전용 태블릿 단말기 (MDM)
        t1 = db.query(AuthorizedTerminal).filter(AuthorizedTerminal.terminal_id == "TAB-HQ-001").first()
        if not t1:
            t1 = AuthorizedTerminal(
                terminal_id="TAB-HQ-001",
                terminal_name="현장지휘 전용 태블릿 1호",
                is_active=True
            )
            db.add(t1)
            print("   -> [단말기 등록] TAB-HQ-001 (현장지휘 전용 태블릿 1호)")

        t2 = db.query(AuthorizedTerminal).filter(AuthorizedTerminal.terminal_id == "TAB-RESCUE-002").first()
        if not t2:
            t2 = AuthorizedTerminal(
                terminal_id="TAB-RESCUE-002",
                terminal_name="119구조팀 현장 태블릿 2호",
                is_active=True
            )
            db.add(t2)
            print("   -> [단말기 등록] TAB-RESCUE-002 (119구조팀 현장 태블릿 2호)")

        # 2.2 공무원 계정 (식별번호, 성명, 계급, 소속, 보안인가등급, PIN 해시)
        # (1) 시스템 보안 관리관 (Clearance 1 - 최고등급)
        admin_user = db.query(User).filter(User.service_number == "FIRE-ADMIN-001").first()
        if not admin_user:
            admin_user = User(
                service_number="FIRE-ADMIN-001",
                full_name="김관리",
                rank="소방령",
                department="소방방재청 정보통신과",
                role=UserRole.ADMIN,
                security_clearance=1,
                pin_hash=get_pin_hash("123456"),
                is_active=True
            )
            db.add(admin_user)
            print("   -> [공무원 등록] 김관리 소방령 (FIRE-ADMIN-001, Clearance 1, ADMIN, PIN: 123456)")

        # (2) 현장 지휘관 (Clearance 2 - 작전 지휘)
        commander_user = db.query(User).filter(User.service_number == "FIRE-CMD-101").first()
        if not commander_user:
            commander_user = User(
                service_number="FIRE-CMD-101",
                full_name="이지휘",
                rank="소방경",
                department="서울종로소방서 현장대응단",
                role=UserRole.COMMANDER,
                security_clearance=2,
                pin_hash=get_pin_hash("123456"),
                is_active=True
            )
            db.add(commander_user)
            print("   -> [공무원 등록] 이지휘 소방경 (FIRE-CMD-101, Clearance 2, COMMANDER, PIN: 123456)")

        # (3) 현장 구조대원 (Clearance 3 - 모니터링)
        operator_user = db.query(User).filter(User.service_number == "FIRE-OP-201").first()
        if not operator_user:
            operator_user = User(
                service_number="FIRE-OP-201",
                full_name="박구조",
                rank="소방교",
                department="서울종로소방서 119구조대",
                role=UserRole.OPERATOR,
                security_clearance=3,
                pin_hash=get_pin_hash("123456"),
                is_active=True
            )
            db.add(operator_user)
            print("   -> [공무원 등록] 박구조 소방교 (FIRE-OP-201, Clearance 3, OPERATOR, PIN: 123456)")

        # 2.3 현장 카메라 엣지 장치 (EDGE-CAM-01)
        test_device = db.query(Device).filter(Device.device_id == "EDGE-CAM-01").first()
        if not test_device:
            default_api_key = "rescue-edge-secret-key-01"
            test_device = Device(
                device_id="EDGE-CAM-01",
                device_name="유선 융합카메라 1호기",
                api_key=default_api_key,
                status=DeviceStatus.OFFLINE
            )
            db.add(test_device)
            print(f"   -> [엣지기기 등록] ID='EDGE-CAM-01', API_KEY='{default_api_key}'")

        # 2.4 테스트 건물 및 3D/2D 맵 정보 등록
        test_building = db.query(Building).filter(Building.name == "소방방재 테스트빌딩 A동").first()
        if not test_building:
            test_building = Building(
                name="소방방재 테스트빌딩 A동",
                address="서울특별시 종로구 세종대로 175",
                floors_count=2,
                description="저조도 및 연기 모의 환경 시험용 훈련동",
                latitude=37.5724,
                longitude=126.9769
            )
            db.add(test_building)
            db.flush()

            # 1층 3D/2D 공간지도 레코드
            floor1_map = SpatialMap(
                building_id=test_building.building_id,
                floor=1,
                file_path="maps/building_a_floor_1.glb",
                floor_plan_image="maps/floorplans/building_a_1f.png",
                width_meter=30.0,
                height_meter=20.0,
                scale_factor=1.0,
                origin_x=0.0,
                origin_y=0.0,
                origin_z=0.0
            )
            db.add(floor1_map)
            print(f"   -> [건물/맵 등록] 소방방재 테스트빌딩 A동 (1층 3D .glb & 2D 평면도 메타데이터)")
        else:
            # 기존 레코드에 좌표 업데이트
            test_building.latitude = 37.5724
            test_building.longitude = 126.9769
            if test_building.spatial_maps:
                test_building.spatial_maps[0].floor_plan_image = "maps/floorplans/building_a_1f.png"
                test_building.spatial_maps[0].width_meter = 30.0
                test_building.spatial_maps[0].height_meter = 20.0

        db.commit()
        print("\n3. 공무원 보안 체계가 적용된 DB 초기화가 성공적으로 완료되었습니다!")
        print("==================================================")
    except Exception as e:
        db.rollback()
        print(f"\n[오류 발생] DB 초기화 실패: {e}")
        raise e
    finally:
        db.close()


if __name__ == "__main__":
    init_database()
