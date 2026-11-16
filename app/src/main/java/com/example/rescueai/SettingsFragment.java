package com.example.rescueai;

import android.os.Bundle;
import android.view.LayoutInflater;
import android.view.View;
import android.view.ViewGroup;
import android.widget.Button;
import android.widget.ImageButton;
import android.widget.Toast;

import androidx.annotation.NonNull;
import androidx.annotation.Nullable;
import androidx.appcompat.widget.SwitchCompat;
import androidx.fragment.app.Fragment;

/**
 * [관제 계층 - Layer 03] 설정 프래그먼트 (package: com.example.capston)
 */
public class SettingsFragment extends Fragment {

    private SwitchCompat swRescueTarget;
    private SwitchCompat swHighTemp;
    private SwitchCompat swObstacle;
    private SwitchCompat swSafeRoute;
    private SwitchCompat swCameraPos;
    private SwitchCompat swDoorExit;

    private SwitchCompat swObjectId;
    private SwitchCompat swDistance;
    private SwitchCompat swMovementRoute;
    private SwitchCompat swObservedTime;

    private MapSettingsState settings;

    @Nullable
    @Override
    public View onCreateView(@NonNull LayoutInflater inflater, @Nullable ViewGroup container,
                             @Nullable Bundle savedInstanceState) {
        return inflater.inflate(R.layout.fragment_settings, container, false);
    }

    @Override
    public void onViewCreated(@NonNull View view, @Nullable Bundle savedInstanceState) {
        super.onViewCreated(view, savedInstanceState);

        if (getActivity() instanceof MainActivity) {
            settings = ((MainActivity) getActivity()).getSettingsState();
        } else {
            settings = new MapSettingsState();
        }

        ImageButton btnBack = view.findViewById(R.id.btn_settings_back);
        btnBack.setOnClickListener(v -> {
            if (getActivity() instanceof MainActivity) {
                ((MainActivity) getActivity()).switchTab(0);
            }
        });

        swRescueTarget = view.findViewById(R.id.sw_rescue_target);
        swHighTemp = view.findViewById(R.id.sw_high_temp);
        swObstacle = view.findViewById(R.id.sw_obstacle);
        swSafeRoute = view.findViewById(R.id.sw_safe_route);
        swCameraPos = view.findViewById(R.id.sw_camera_pos);
        swDoorExit = view.findViewById(R.id.sw_door_exit);

        swObjectId = view.findViewById(R.id.sw_object_id);
        swDistance = view.findViewById(R.id.sw_distance);
        swMovementRoute = view.findViewById(R.id.sw_movement_route);
        swObservedTime = view.findViewById(R.id.sw_observed_time);

        syncUiFromState();

        swRescueTarget.setOnCheckedChangeListener((b, checked) -> settings.setShowRescueTarget(checked));
        swHighTemp.setOnCheckedChangeListener((b, checked) -> settings.setShowHighTempZone(checked));
        swObstacle.setOnCheckedChangeListener((b, checked) -> settings.setShowObstacleWarn(checked));
        swSafeRoute.setOnCheckedChangeListener((b, checked) -> settings.setShowSafeRoute(checked));
        swCameraPos.setOnCheckedChangeListener((b, checked) -> settings.setShowCameraPos(checked));
        swDoorExit.setOnCheckedChangeListener((b, checked) -> settings.setShowDoorExit(checked));

        swObjectId.setOnCheckedChangeListener((b, checked) -> settings.setShowObjectId(checked));
        swDistance.setOnCheckedChangeListener((b, checked) -> settings.setShowDistance(checked));
        swMovementRoute.setOnCheckedChangeListener((b, checked) -> settings.setShowMovementRoute(checked));
        swObservedTime.setOnCheckedChangeListener((b, checked) -> settings.setShowObservedTime(checked));

        Button btnShowAll = view.findViewById(R.id.btn_show_all);
        Button btnResetDefault = view.findViewById(R.id.btn_reset_default);

        btnShowAll.setOnClickListener(v -> {
            settings.enableShowAll();
            syncUiFromState();
            Toast.makeText(getContext(), "전체 표시가 활성화되었습니다.", Toast.LENGTH_SHORT).show();
        });

        btnResetDefault.setOnClickListener(v -> {
            settings.resetToDefault();
            syncUiFromState();
            Toast.makeText(getContext(), "기본값으로 복원되었습니다.", Toast.LENGTH_SHORT).show();
        });
    }

    private void syncUiFromState() {
        swRescueTarget.setChecked(settings.isShowRescueTarget());
        swHighTemp.setChecked(settings.isShowHighTempZone());
        swObstacle.setChecked(settings.isShowObstacleWarn());
        swSafeRoute.setChecked(settings.isShowSafeRoute());
        swCameraPos.setChecked(settings.isShowCameraPos());
        swDoorExit.setChecked(settings.isShowDoorExit());

        swObjectId.setChecked(settings.isShowObjectId());
        swDistance.setChecked(settings.isShowDistance());
        swMovementRoute.setChecked(settings.isShowMovementRoute());
        swObservedTime.setChecked(settings.isShowObservedTime());
    }
}