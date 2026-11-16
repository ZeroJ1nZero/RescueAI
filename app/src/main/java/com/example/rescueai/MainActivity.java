package com.example.rescueai;

import android.os.Bundle;
import android.widget.LinearLayout;
import android.widget.TextView;
import android.graphics.Color;

import androidx.appcompat.app.AppCompatActivity;
import androidx.fragment.app.Fragment;
import androidx.fragment.app.FragmentTransaction;


/**
 * 메인 액티비티 (package: com.example.capston)
 * - 하단 커스텀 탭 네비게이션 (지도 / 카메라 / 설정) 관리
 * - MapSettingsState 공유를 통해 설정 변경 사항을 즉시 지도 뷰에 반영
 */
public class MainActivity extends AppCompatActivity {

    private final MapSettingsState settingsState = new MapSettingsState();

    private MapFragment mapFragment;
    private CameraFragment cameraFragment;
    private SettingsFragment settingsFragment;

    private LinearLayout tabMap;
    private LinearLayout tabCamera;
    private LinearLayout tabSettings;

    private TextView tvTabMap;
    private TextView tvTabCamera;
    private TextView tvTabSettings;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        setContentView(R.layout.activity_main);

        mapFragment = new MapFragment();
        cameraFragment = new CameraFragment();
        settingsFragment = new SettingsFragment();

        initBottomNav();

        if (savedInstanceState == null) {
            switchTab(0);
        }
    }

    private void initBottomNav() {
        tabMap = findViewById(R.id.tab_map);
        tabCamera = findViewById(R.id.tab_camera);
        tabSettings = findViewById(R.id.tab_settings);

        tvTabMap = findViewById(R.id.tv_tab_map);
        tvTabCamera = findViewById(R.id.tv_tab_camera);
        tvTabSettings = findViewById(R.id.tv_tab_settings);

        tabMap.setOnClickListener(v -> switchTab(0));
        tabCamera.setOnClickListener(v -> switchTab(1));
        tabSettings.setOnClickListener(v -> switchTab(2));
    }

    public void switchTab(int index) {
        Fragment selectedFragment;
        resetTabStyles();

        if (index == 0) {
            selectedFragment = mapFragment;
            tabMap.setBackgroundResource(R.drawable.bg_tab_selected);
            tvTabMap.setTextColor(getColor(R.color.accent_blue));
        } else if (index == 1) {
            selectedFragment = cameraFragment;
            tabCamera.setBackgroundResource(R.drawable.bg_tab_selected);
            tvTabCamera.setTextColor(getColor(R.color.accent_blue));
        } else {
            selectedFragment = settingsFragment;
            tabSettings.setBackgroundResource(R.drawable.bg_tab_selected);
            tvTabSettings.setTextColor(getColor(R.color.accent_blue));
        }

        FragmentTransaction transaction = getSupportFragmentManager().beginTransaction();
        transaction.setCustomAnimations(android.R.anim.fade_in, android.R.anim.fade_out);
        transaction.replace(R.id.fragment_container, selectedFragment);
        transaction.commit();
    }

    private void resetTabStyles() {
        tabMap.setBackgroundResource(android.R.color.transparent);
        tabCamera.setBackgroundResource(android.R.color.transparent);
        tabSettings.setBackgroundResource(android.R.color.transparent);

        int mutedColor = getColor(R.color.text_secondary);
        tvTabMap.setTextColor(mutedColor);
        tvTabCamera.setTextColor(mutedColor);
        tvTabSettings.setTextColor(mutedColor);
    }

    public MapSettingsState getSettingsState() {
        return settingsState;
    }
}