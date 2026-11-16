package com.example.rescueai;

import java.util.List;
import retrofit2.Call;
import retrofit2.http.Body;
import retrofit2.http.GET;
import retrofit2.http.Header;
import retrofit2.http.POST;
import retrofit2.http.Path;

/**
 * 연암소방대 FastAPI 백엔드 서버 RESTful API 인터페이스 (package: com.example.capston)
 */
public interface RescueApiService {

    @POST("/api/v1/auth/login")
    Call<ApiModels.LoginResponse> login(
            @Header("X-Terminal-Id") String terminalId,
            @Body ApiModels.LoginRequest body
    );

    @GET("/api/v1/auth/terminal/check")
    Call<Void> checkTerminal(
            @Header("X-Terminal-Id") String terminalId
    );

    @GET("/api/v1/missions/{id}/map-state")
    Call<ApiModels.MapStateResponse> getMapState(
            @Header("Authorization") String bearerToken,
            @Path("id") int missionId
    );

    @GET("/api/v1/missions/{id}/ai-assessments")
    Call<List<ApiModels.PoiMarkerDto>> getAiAssessments(
            @Header("Authorization") String bearerToken,
            @Path("id") int missionId
    );

    @POST("/api/v1/missions/{id}/telemetry/raw")
    Call<ApiModels.TelemetryResponse> sendRawTelemetry(
            @Header("X-Terminal-Id") String terminalId,
            @Path("id") int missionId,
            @Body ApiModels.TelemetryPayload payload
    );

    @POST("/api/v1/missions/{id}/telemetry/batch")
    Call<List<ApiModels.TelemetryResponse>> sendBatchTelemetry(
            @Header("X-Terminal-Id") String terminalId,
            @Path("id") int missionId,
            @Body List<ApiModels.TelemetryPayload> batchPayloads
    );
}