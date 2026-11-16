package com.example.rescueai;

/**
 * 설정 화면의 지도 표시 설정, 필터, 표시 옵션 상태 관리 클래스 (package: com.example.capston)
 */
public class MapSettingsState {

    private boolean showRescueTarget = true;
    private boolean showHighTempZone = true;
    private boolean showObstacleWarn = true;
    private boolean showSafeRoute = true;
    private boolean showCameraPos = true;
    private boolean showDoorExit = true;

    private String riskFilter = "ALL";
    private String objectTypeFilter = "ALL";
    private String timeFilter = "LATEST";

    private boolean showObjectId = true;
    private boolean showDistance = true;
    private boolean showMovementRoute = true;
    private boolean showObservedTime = false;

    public void resetToDefault() {
        showRescueTarget = true;
        showHighTempZone = true;
        showObstacleWarn = true;
        showSafeRoute = true;
        showCameraPos = true;
        showDoorExit = true;
        riskFilter = "ALL";
        objectTypeFilter = "ALL";
        timeFilter = "LATEST";
        showObjectId = true;
        showDistance = true;
        showMovementRoute = true;
        showObservedTime = false;
    }

    public void enableShowAll() {
        showRescueTarget = true;
        showHighTempZone = true;
        showObstacleWarn = true;
        showSafeRoute = true;
        showCameraPos = true;
        showDoorExit = true;
        riskFilter = "ALL";
        objectTypeFilter = "ALL";
        timeFilter = "ALL";
        showObjectId = true;
        showDistance = true;
        showMovementRoute = true;
        showObservedTime = true;
    }

    public boolean isShowRescueTarget() { return showRescueTarget; }
    public void setShowRescueTarget(boolean v) { this.showRescueTarget = v; }
    public boolean isShowHighTempZone() { return showHighTempZone; }
    public void setShowHighTempZone(boolean v) { this.showHighTempZone = v; }
    public boolean isShowObstacleWarn() { return showObstacleWarn; }
    public void setShowObstacleWarn(boolean v) { this.showObstacleWarn = v; }
    public boolean isShowSafeRoute() { return showSafeRoute; }
    public void setShowSafeRoute(boolean v) { this.showSafeRoute = v; }
    public boolean isShowCameraPos() { return showCameraPos; }
    public void setShowCameraPos(boolean v) { this.showCameraPos = v; }
    public boolean isShowDoorExit() { return showDoorExit; }
    public void setShowDoorExit(boolean v) { this.showDoorExit = v; }
    public String getRiskFilter() { return riskFilter; }
    public void setRiskFilter(String v) { this.riskFilter = v; }
    public String getObjectTypeFilter() { return objectTypeFilter; }
    public void setObjectTypeFilter(String v) { this.objectTypeFilter = v; }
    public String getTimeFilter() { return timeFilter; }
    public void setTimeFilter(String v) { this.timeFilter = v; }
    public boolean isShowObjectId() { return showObjectId; }
    public void setShowObjectId(boolean v) { this.showObjectId = v; }
    public boolean isShowDistance() { return showDistance; }
    public void setShowDistance(boolean v) { this.showDistance = v; }
    public boolean isShowMovementRoute() { return showMovementRoute; }
    public void setShowMovementRoute(boolean v) { this.showMovementRoute = v; }
    public boolean isShowObservedTime() { return showObservedTime; }
    public void setShowObservedTime(boolean v) { this.showObservedTime = v; }
}