package com.example.rescueai;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.ImageButton;
import android.widget.TextView;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;

import java.text.SimpleDateFormat;
import java.util.Date;
import java.util.Locale;

import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Response;

/**
 * [관제 계층 - Layer 03] 실내 공간지도 프래그먼트 (package: com.example.capston)
 */
public class MapFragment extends Fragment {

    private SpatialMapCanvasView mapCanvasView;
    private TextView tvCardTitle;
    private TextView tvCardLocation;
    private TextView tvCardRiskTime;
    private TextView tvLiveStatus;

    private final MissionWebSocketClient wsClient = new MissionWebSocketClient();
    private final int currentMissionId = 1;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater, @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        return inflater.inflate(R.layout.fragment_map, container, false);
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        super.onViewCreated(view, savedInstanceState);

        mapCanvasView = view.findViewById(R.id.spatial_map_canvas);
        tvCardTitle = view.findViewById(R.id.tv_card_title);
        tvCardLocation = view.findViewById(R.id.tv_card_location);
        tvCardRiskTime = view.findViewById(R.id.tv_card_risk_time);
        tvLiveStatus = view.findViewById(R.id.tv_live_status);

        ImageButton btnZoomIn = view.findViewById(R.id.btn_zoom_in);
        ImageButton btnZoomOut = view.findViewById(R.id.btn_zoom_out);
        ImageButton btnMyLocation = view.findViewById(R.id.btn_my_location);
        ImageButton btnLayerToggle = view.findViewById(R.id.btn_layer_toggle);

        if (getActivity() instanceof MainActivity) {
            MapSettingsState settings = ((MainActivity) getActivity()).getSettingsState();
            mapCanvasView.setSettingsState(settings);
        }

        mapCanvasView.setOnNodeSelectedListener(this::updateBottomDetailCard);

        btnZoomIn.setOnClickListener(v -> mapCanvasView.zoomIn());
        btnZoomOut.setOnClickListener(v -> mapCanvasView.zoomOut());
        btnMyLocation.setOnClickListener(v -> {
            mapCanvasView.resetCameraCenter();
            Toast.makeText(getContext(), "카메라 · 현재 위치(C-01) 중심으로 정렬됨", Toast.LENGTH_SHORT).show();
        });
        btnLayerToggle.setOnClickListener(v -> {
            if (getActivity() instanceof MainActivity) {
                ((MainActivity) getActivity()).switchTab(2);
            }
        });

        fetchInitialMapState();
        connectRealtimeStream();
    }

    private void fetchInitialMapState() {
        RescueApiService api = MissionWebSocketClient.createApiService();
        String bearer = "Bearer " + MissionWebSocketClient.getJwtToken();

        api.getMapState(bearer, currentMissionId).enqueue(new Callback<ApiModels.MapStateResponse>() {
            @Override
            public void onResponse(@NonNull Call<ApiModels.MapStateResponse> call,
                                   @NonNull Response<ApiModels.MapStateResponse> response) {
                if (response.isSuccessful() && response.body() != null) {
                    mapCanvasView.invalidate();
                }
            }

            @Override
            public void onFailure(@NonNull Call<ApiModels.MapStateResponse> call, @NonNull Throwable t) {
                // 오프라인/로컬 테스트 시 기본 훈련공간 A · 1F 시드 데이터 유지
            }
        });
    }

    private void connectRealtimeStream() {
        wsClient.connect(currentMissionId, MissionWebSocketClient.getJwtToken(),
                new MissionWebSocketClient.RealtimeEventListener() {
                    @Override
                    public void onLocationUpdate(float x, float y, float z, int frameId, float yaw) {
                        mapCanvasView.invalidate();
                    }

                    @Override
                    public void onAiMarkerAlert(String markerId, String poiType, String hazardLevel,
                                                String description, float x, float y, float distanceM, float tempC) {
                        String nowTime = new SimpleDateFormat("HH:mm:ss", Locale.KOREA).format(new Date());
                        tvCardTitle.setText(String.format(Locale.KOREA, "%s · %s", markerId, description));
                        tvCardLocation.setText(String.format(Locale.KOREA,
                                "위치 X %.2fm / Y %.2fm   카메라 거리 %.1fm", x, y, distanceM));
                        tvCardRiskTime.setText(String.format(Locale.KOREA,
                                "위험도 %s   관측 시각 %s", hazardLevel, nowTime));
                        mapCanvasView.invalidate();
                    }

                    @Override
                    public void onConnectionStateChanged(boolean isConnected) {
                        if (tvLiveStatus != null) {
                            tvLiveStatus.setText("● LIVE");
                        }
                    }
                });
    }

    private void updateBottomDetailCard(SpatialNode node) {
        tvCardTitle.setText(String.format(Locale.KOREA, "%s · %s", node.getId(), node.getTitle()));
        tvCardLocation.setText(String.format(Locale.KOREA,
                "위치 X %.2fm / Y %.2fm   카메라 거리 %.1fm",
                node.getPosXMeter(), node.getPosYMeter(), node.getCameraDistM()));
        tvCardRiskTime.setText(String.format(Locale.KOREA,
                "위험도 %s   관측 시각 %s",
                node.getRiskLevel().getLabel(), node.getObservedTime()));
    }

    @Override
    public void onDestroyView() {
        super.onDestroyView();
        wsClient.disconnect();
    }
}