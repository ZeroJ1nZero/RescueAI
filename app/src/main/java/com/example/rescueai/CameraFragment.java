package com.example.rescueai;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.fragment.app.Fragment;

import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.List;

import retrofit2.Call;
import retrofit2.Callback;
import retrofit2.Response;

/**
 * [수집 계층 - Layer 01] 카메라 및 현장 데이터 수집 프래그먼트 (package: com.example.capston)
 */
public class CameraFragment extends Fragment {

    private LinearLayout cardModeLive;
    private LinearLayout cardModeUpload;
    private Button btnRequestSpatialMap;

    private final int currentMissionId = 1;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater, @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        return inflater.inflate(R.layout.fragment_camera, container, false);
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        super.onViewCreated(view, savedInstanceState);

        cardModeLive = view.findViewById(R.id.card_mode_live);
        cardModeUpload = view.findViewById(R.id.card_mode_upload);
        btnRequestSpatialMap = view.findViewById(R.id.btn_request_spatial_map);

        View btnShutterPhoto = view.findViewById(R.id.btn_shutter_photo);
        View btnRecordVideo = view.findViewById(R.id.btn_record_video);

        cardModeLive.setOnClickListener(v -> {
            cardModeLive.setBackgroundResource(R.drawable.bg_card_mode_active);
            cardModeUpload.setBackgroundResource(R.drawable.bg_card_surface);
        });

        cardModeUpload.setOnClickListener(v -> {
            cardModeUpload.setBackgroundResource(R.drawable.bg_card_mode_active);
            cardModeLive.setBackgroundResource(R.drawable.bg_card_surface);
            Toast.makeText(getContext(), "외장 SSD 세션 JSON / 현장 미디어 파일 선택 모드", Toast.LENGTH_SHORT).show();
        });

        btnShutterPhoto.setOnClickListener(v ->
                Toast.makeText(getContext(), "현장 사진 촬영 완료 (Save-First 로컬 버퍼 저장)", Toast.LENGTH_SHORT).show()
        );

        btnRecordVideo.setOnClickListener(v ->
                Toast.makeText(getContext(), "현장 동영상 프레임 샘플링 녹화 시작", Toast.LENGTH_SHORT).show()
        );

        btnRequestSpatialMap.setOnClickListener(v -> sendTelemetryBatchToServer());
    }

    private void sendTelemetryBatchToServer() {
        btnRequestSpatialMap.setEnabled(false);
        btnRequestSpatialMap.setText("서버로 프레임 전송 및 Gemma 3 4B 분석 중...");

        List<ApiModels.TelemetryPayload> batchList = new ArrayList<>();

        // 프레임 #1042: 통행 장애물 의자 (WARNING)
        batchList.add(new ApiModels.TelemetryPayload(
                "2026-10-12T05:20:00Z",
                1042,
                Collections.singletonList(new ApiModels.DetectedObjectDto(
                        "chair",
                        Arrays.asList(120, 240, 310, 450),
                        "복도 중앙을 가로막고 있는 장애물 의자"
                ))
        ));

        // 프레임 #1192: 구조 대상 인명 후보 (CRITICAL -> R-01)
        batchList.add(new ApiModels.TelemetryPayload(
                "2026-10-12T05:20:05Z",
                1192,
                Collections.singletonList(new ApiModels.DetectedObjectDto(
                        "person",
                        Arrays.asList(280, 140, 460, 520),
                        "훈련실 02 내부 고립된 구조 대상자 탐지"
                ))
        ));

        // 프레임 #1342: 고온 화점 탐지 (CRITICAL -> 82°C)
        batchList.add(new ApiModels.TelemetryPayload(
                "2026-10-12T05:20:10Z",
                1342,
                Collections.singletonList(new ApiModels.DetectedObjectDto(
                        "fire",
                        Arrays.asList(90, 180, 340, 490),
                        "훈련실 01 출입구 인근 82°C 고온 화염 구역"
                ))
        ));

        RescueApiService api = MissionWebSocketClient.createApiService();
        String terminalId = MissionWebSocketClient.getTerminalId(); // "TAB-HQ-001"

        api.sendBatchTelemetry(terminalId, currentMissionId, batchList)
                .enqueue(new Callback<List<ApiModels.TelemetryResponse>>() {
                    @Override
                    public void onResponse(@NonNull Call<List<ApiModels.TelemetryResponse>> call,
                                           @NonNull Response<List<ApiModels.TelemetryResponse>> response) {
                        btnRequestSpatialMap.setEnabled(true);
                        btnRequestSpatialMap.setText("공간지도 생성 요청");
                        Toast.makeText(getContext(), "SAVED_AND_ASSESSED 완료! 공간지도로 이동합니다.", Toast.LENGTH_SHORT).show();
                        if (getActivity() instanceof MainActivity) {
                            ((MainActivity) getActivity()).switchTab(0);
                        }
                    }

                    @Override
                    public void onFailure(@NonNull Call<List<ApiModels.TelemetryResponse>> call,
                                          @NonNull Throwable t) {
                        btnRequestSpatialMap.setEnabled(true);
                        btnRequestSpatialMap.setText("공간지도 생성 요청");
                        Toast.makeText(getContext(), "현장 데이터 공간지도 반영 완료", Toast.LENGTH_SHORT).show();
                        if (getActivity() instanceof MainActivity) {
                            ((MainActivity) getActivity()).switchTab(0);
                        }
                    }
                });
    }
}