package com.example.rescueai;

import com.google.gson.annotations.SerializedName;
import java.util.List;

/**
 * 연암소방대 FastAPI 백엔드 API 요청/응답 DTO 모음 (package: com.example.capston)
 */
public class ApiModels {

    public static class LoginRequest {
        @SerializedName("service_number")
        public String serviceNumber;

        @SerializedName("pin")
        public String pin;

        public LoginRequest(String serviceNumber, String pin) {
            this.serviceNumber = serviceNumber;
            this.pin = pin;
        }
    }

    public static class LoginResponse {
        @SerializedName("access_token")
        public String accessToken;

        @SerializedName("token_type")
        public String tokenType;

        @SerializedName("role")
        public String role;

        @SerializedName("full_name")
        public String fullName;
    }

    public static class DetectedObjectDto {
        @SerializedName("class")
        public String objectClass;

        @SerializedName("screen_box")
        public List<Integer> screenBox;

        @SerializedName("description")
        public String description;

        public DetectedObjectDto(String objectClass, List<Integer> screenBox, String description) {
            this.objectClass = objectClass;
            this.screenBox = screenBox;
            this.description = description;
        }
    }

    public static class TelemetryPayload {
        @SerializedName("timestamp")
        public String timestamp;

        @SerializedName("frame_id")
        public int frameId;

        @SerializedName("detected_objects")
        public List<DetectedObjectDto> detectedObjects;

        public TelemetryPayload(String timestamp, int frameId, List<DetectedObjectDto> detectedObjects) {
            this.timestamp = timestamp;
            this.frameId = frameId;
            this.detectedObjects = detectedObjects;
        }
    }

    public static class TelemetryResponse {
        @SerializedName("status")
        public String status;

        @SerializedName("hazard_level")
        public String hazardLevel;

        @SerializedName("assessment_id")
        public int assessmentId;
    }

    public static class MapStateResponse {
        @SerializedName("mission_id")
        public int missionId;

        @SerializedName("building_name")
        public String buildingName;

        @SerializedName("markers")
        public List<PoiMarkerDto> markers;
    }

    public static class PoiMarkerDto {
        @SerializedName("marker_id")
        public String markerId;

        @SerializedName("poi_type")
        public String poiType;

        @SerializedName("hazard_level")
        public String hazardLevel;

        @SerializedName("situation_summary")
        public String situationSummary;

        @SerializedName("coord_x")
        public float coordX;

        @SerializedName("coord_y")
        public float coordY;

        @SerializedName("distance_m")
        public float distanceM;

        @SerializedName("ambient_temp")
        public float ambientTemp;

        @SerializedName("observed_at")
        public String observedAt;
    }
}