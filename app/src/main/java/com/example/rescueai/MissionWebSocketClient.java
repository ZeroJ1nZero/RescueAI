package com.example.rescueai;

import android.os.Handler;
import android.os.Looper;
import android.util.Log;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;

import org.json.JSONObject;

import java.util.concurrent.TimeUnit;

import okhttp3.OkHttpClient;
import okhttp3.Request;
import okhttp3.Response;
import okhttp3.WebSocket;
import okhttp3.WebSocketListener;
import retrofit2.Retrofit;
import retrofit2.converter.gson.GsonConverterFactory;

/**
 * 연암소방대 FastAPI 백엔드 연동 매니저 (package: com.example.capston)
 */
public class MissionWebSocketClient {

    private static final String TAG = "MissionWebSocket";
    private static String baseUrl = "http://10.0.2.2:8000";
    private static String terminalId = "TAB-HQ-001";
    private static String jwtToken = "";

    public interface RealtimeEventListener {
        void onLocationUpdate(float x, float y, float z, int frameId, float yaw);
        void onAiMarkerAlert(String markerId, String poiType, String hazardLevel,
                             String description, float x, float y, float distanceM, float tempC);
        void onConnectionStateChanged(boolean isConnected);
    }

    private final OkHttpClient okHttpClient;
    private WebSocket webSocket;
    private final Handler mainHandler = new Handler(Looper.getMainLooper());
    private RealtimeEventListener listener;

    public MissionWebSocketClient() {
        this.okHttpClient = new OkHttpClient.Builder()
                .readTimeout(0, TimeUnit.MILLISECONDS)
                .pingInterval(15, TimeUnit.SECONDS)
                .build();
    }

    public static RescueApiService createApiService() {
        Retrofit retrofit = new Retrofit.Builder()
                .baseUrl(baseUrl)
                .addConverterFactory(GsonConverterFactory.create())
                .build();
        return retrofit.create(RescueApiService.class);
    }

    public void connect(int missionId, String token, RealtimeEventListener eventListener) {
        this.listener = eventListener;
        jwtToken = token;

        String wsUrl = baseUrl.replace("http://", "ws://").replace("https://", "wss://")
                + "/ws/missions/" + missionId + "/dashboard?token=" + token;

        Request request = new Request.Builder()
                .url(wsUrl)
                .addHeader("X-Terminal-Id", terminalId)
                .build();

        webSocket = okHttpClient.newWebSocket(request, new WebSocketListener() {
            @Override
            public void onOpen(@NonNull WebSocket webSocket, @NonNull Response response) {
                Log.i(TAG, "WebSocket Connected to Mission #" + missionId);
                mainHandler.post(() -> {
                    if (listener != null) listener.onConnectionStateChanged(true);
                });
            }

            @Override
            public void onMessage(@NonNull WebSocket webSocket, @NonNull String text) {
                parseRealtimeMessage(text);
            }

            @Override
            public void onFailure(@NonNull WebSocket webSocket, @NonNull Throwable t, @Nullable Response response) {
                mainHandler.post(() -> {
                    if (listener != null) listener.onConnectionStateChanged(false);
                });
            }
        });
    }

    private void parseRealtimeMessage(String jsonText) {
        try {
            JSONObject root = new JSONObject(jsonText);
            String eventType = root.optString("event", "");

            if ("LOCATION_UPDATE".equals(eventType)) {
                float x = (float) root.optDouble("x", 1.10);
                float y = (float) root.optDouble("y", 0.65);
                float z = (float) root.optDouble("z", 0.0);
                int frameId = root.optInt("frame_id", 1042);
                float yaw = (float) root.optDouble("yaw", 0.0);

                mainHandler.post(() -> {
                    if (listener != null) listener.onLocationUpdate(x, y, z, frameId, yaw);
                });
            } else if ("AI_MARKER_ALERT".equals(eventType)) {
                String markerId = root.optString("marker_id", "R-01");
                String poiType = root.optString("poi_type", "PERSON_RESCUE");
                String hazardLevel = root.optString("hazard_level", "CRITICAL");
                String desc = root.optString("description", "구조 대상 탐지");
                float x = (float) root.optDouble("coord_x", 3.52);
                float y = (float) root.optDouble("coord_y", 3.48);
                float dist = (float) root.optDouble("distance_m", 12.4);
                float temp = (float) root.optDouble("ambient_temp", 82.0);

                mainHandler.post(() -> {
                    if (listener != null) {
                        listener.onAiMarkerAlert(markerId, poiType, hazardLevel, desc, x, y, dist, temp);
                    }
                });
            }
        } catch (Exception e) {
            Log.e(TAG, "Failed to parse WebSocket JSON: " + e.getMessage());
        }
    }

    public void disconnect() {
        if (webSocket != null) {
            webSocket.close(1000, "Client closing");
            webSocket = null;
        }
    }

    public static String getTerminalId() { return terminalId; }
    public static void setTerminalId(String id) { terminalId = id; }
    public static String getJwtToken() { return jwtToken; }
    public static void setJwtToken(String token) { jwtToken = token; }
}