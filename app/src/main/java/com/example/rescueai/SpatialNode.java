package com.example.rescueai;

/**
 * 공간지도 내 표시되는 개별 객체 데이터 모델 (package: com.example.capston)
 */
public class SpatialNode {

    public enum NodeType {
        RESCUE_TARGET,   // 구조 대상 (R-01, R-02)
        HIGH_TEMP_ZONE,  // 고온 구역 (82°C 등)
        OBSTACLE_WARN,   // 장애물 · 경고 (O-01, O-02, O-03)
        CAMERA_POS,      // 카메라 · 현재 위치 (C-01)
        FIREFIGHTER,     // 대원 위치 (F-01)
        DOOR_EXIT        // 문 · 출입구
    }

    public enum RiskLevel {
        EMERGENCY("긴급"),
        HIGH("높음"),
        CAUTION("주의"),
        NORMAL("정상");

        private final String label;
        RiskLevel(String label) { this.label = label; }
        public String getLabel() { return label; }
    }

    private final String id;
    private final String title;
    private final NodeType type;
    private final RiskLevel riskLevel;
    private final float mapX;
    private final float mapY;
    private final float posXMeter;
    private final float posYMeter;
    private final float cameraDistM;
    private final float temperatureC;
    private final float radiusRatio;
    private final String observedTime;
    private final boolean isLatest;

    public SpatialNode(String id, String title, NodeType type, RiskLevel riskLevel,
                       float mapX, float mapY, float posXMeter, float posYMeter,
                       float cameraDistM, float temperatureC, float radiusRatio,
                       String observedTime, boolean isLatest) {
        this.id = id;
        this.title = title;
        this.type = type;
        this.riskLevel = riskLevel;
        this.mapX = mapX;
        this.mapY = mapY;
        this.posXMeter = posXMeter;
        this.posYMeter = posYMeter;
        this.cameraDistM = cameraDistM;
        this.temperatureC = temperatureC;
        this.radiusRatio = radiusRatio;
        this.observedTime = observedTime;
        this.isLatest = isLatest;
    }

    public String getId() { return id; }
    public String getTitle() { return title; }
    public NodeType getType() { return type; }
    public RiskLevel getRiskLevel() { return riskLevel; }
    public float getMapX() { return mapX; }
    public float getMapY() { return mapY; }
    public float getPosXMeter() { return posXMeter; }
    public float getPosYMeter() { return posYMeter; }
    public float getCameraDistM() { return cameraDistM; }
    public float getTemperatureC() { return temperatureC; }
    public float getRadiusRatio() { return radiusRatio; }
    public String getObservedTime() { return observedTime; }
    public boolean isLatest() { return isLatest; }
}