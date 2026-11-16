package com.example.rescueai;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.Paint;
import android.graphics.Path;
import android.graphics.RectF;
import android.util.AttributeSet;
import android.view.GestureDetector;
import android.view.MotionEvent;
import android.view.ScaleGestureDetector;
import android.view.View;

import androidx.annotation.Nullable;

import java.util.ArrayList;
import java.util.List;

/**
 * 훈련공간 A · 1F 2D 공간지도 커스텀 View (package: com.example.capston)
 */
public class SpatialMapCanvasView extends View {

    public interface OnNodeSelectedListener {
        void onNodeSelected(SpatialNode node);
    }

    private final Paint wallOuterPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint wallInnerPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint roomTextPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint routePaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint fovPaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint nodePaint = new Paint(Paint.ANTI_ALIAS_FLAG);
    private final Paint labelPaint = new Paint(Paint.ANTI_ALIAS_FLAG);

    private final List<SpatialNode> nodes = new ArrayList<>();
    private SpatialNode selectedNode;
    private MapSettingsState settings = new MapSettingsState();
    private OnNodeSelectedListener listener;

    private float scaleFactor = 1.0f;
    private float translateX = 0f;
    private float translateY = 0f;
    private ScaleGestureDetector scaleDetector;
    private GestureDetector gestureDetector;

    public SpatialMapCanvasView(Context context) {
        super(context);
        init(context);
    }

    public SpatialMapCanvasView(Context context, @Nullable AttributeSet attrs) {
        super(context, attrs);
        init(context);
    }

    private void init(Context context) {
        wallOuterPaint.setColor(Color.parseColor("#6E7685"));
        wallOuterPaint.setStyle(Paint.Style.STROKE);
        wallOuterPaint.setStrokeWidth(5f);

        wallInnerPaint.setColor(Color.parseColor("#393F4C"));
        wallInnerPaint.setStyle(Paint.Style.STROKE);
        wallInnerPaint.setStrokeWidth(3f);

        roomTextPaint.setColor(Color.parseColor("#8A93A2"));
        roomTextPaint.setTextSize(28f);

        routePaint.setColor(Color.parseColor("#30A46C"));
        routePaint.setStyle(Paint.Style.STROKE);
        routePaint.setStrokeWidth(6f);
        routePaint.setStrokeCap(Paint.Cap.ROUND);
        routePaint.setStrokeJoin(Paint.Join.ROUND);

        fovPaint.setColor(Color.parseColor("#263B82F6"));
        fovPaint.setStyle(Paint.Style.FILL);

        labelPaint.setColor(Color.WHITE);
        labelPaint.setTextSize(26f);
        labelPaint.setFakeBoldText(true);

        initDefaultFloorData();

        scaleDetector = new ScaleGestureDetector(context, new ScaleGestureDetector.SimpleOnScaleGestureListener() {
            @Override
            public boolean onScale(ScaleGestureDetector detector) {
                scaleFactor *= detector.getScaleFactor();
                scaleFactor = Math.max(0.75f, Math.min(scaleFactor, 2.5f));
                invalidate();
                return true;
            }
        });

        gestureDetector = new GestureDetector(context, new GestureDetector.SimpleOnGestureListener() {
            @Override
            public boolean onScroll(MotionEvent e1, MotionEvent e2, float distanceX, float distanceY) {
                translateX -= distanceX;
                translateY -= distanceY;
                invalidate();
                return true;
            }

            @Override
            public boolean onSingleTapUp(MotionEvent e) {
                handleTap(e.getX(), e.getY());
                return true;
            }
        });
    }

    private void initDefaultFloorData() {
        nodes.clear();
        SpatialNode r01 = new SpatialNode("R-01", "구조 대상", SpatialNode.NodeType.RESCUE_TARGET,
                SpatialNode.RiskLevel.HIGH, 0.72f, 0.21f, 3.52f, 3.48f, 12.4f, 0f, 0.08f, "14:31:49", true);
        SpatialNode r02 = new SpatialNode("R-02", "구조 대상", SpatialNode.NodeType.RESCUE_TARGET,
                SpatialNode.RiskLevel.EMERGENCY, 0.47f, 0.72f, 2.15f, 1.20f, 4.8f, 0f, 0.07f, "14:31:52", true);
        SpatialNode fire1 = new SpatialNode("H-01", "고온 구역", SpatialNode.NodeType.HIGH_TEMP_ZONE,
                SpatialNode.RiskLevel.EMERGENCY, 0.36f, 0.31f, 1.80f, 2.90f, 8.2f, 82f, 0.07f, "14:31:45", true);
        SpatialNode o01 = new SpatialNode("O-01", "낙하 장애물", SpatialNode.NodeType.OBSTACLE_WARN,
                SpatialNode.RiskLevel.CAUTION, 0.48f, 0.56f, 2.40f, 1.85f, 6.5f, 0f, 0f, "14:31:10", true);
        SpatialNode c01 = new SpatialNode("C-01", "카메라 · 현재 위치", SpatialNode.NodeType.CAMERA_POS,
                SpatialNode.RiskLevel.NORMAL, 0.23f, 0.81f, 1.10f, 0.65f, 0.0f, 0f, 0f, "14:31:55", true);

        nodes.add(r01);
        nodes.add(r02);
        nodes.add(fire1);
        nodes.add(o01);
        nodes.add(c01);

        selectedNode = r01;
    }

    @Override
    protected void onDraw(Canvas canvas) {
        super.onDraw(canvas);
        canvas.save();

        float w = getWidth();
        float h = getHeight();
        canvas.translate(translateX, translateY);
        canvas.scale(scaleFactor, scaleFactor, w / 2f, h / 2f);

        float padLeft = w * 0.08f;
        float padTop = h * 0.08f;
        float mapW = w * 0.78f;
        float mapH = h * 0.84f;

        RectF outerRect = new RectF(padLeft, padTop, padLeft + mapW, padTop + mapH);
        canvas.drawRect(outerRect, wallOuterPaint);

        float topRoomBottom = padTop + mapH * 0.36f;
        canvas.drawLine(padLeft + mapW * 0.28f, padTop, padLeft + mapW * 0.28f, topRoomBottom, wallInnerPaint);
        canvas.drawLine(padLeft + mapW * 0.63f, padTop, padLeft + mapW * 0.63f, topRoomBottom, wallInnerPaint);
        canvas.drawLine(padLeft, topRoomBottom, padLeft + mapW * 0.82f, topRoomBottom, wallInnerPaint);

        canvas.drawText("준비실", padLeft + mapW * 0.04f, padTop + mapH * 0.14f, roomTextPaint);
        canvas.drawText("훈련실 01", padLeft + mapW * 0.40f, padTop + mapH * 0.10f, roomTextPaint);
        canvas.drawText("훈련실 02", padLeft + mapW * 0.70f, padTop + mapH * 0.06f, roomTextPaint);
        canvas.drawText("중앙 복도", padLeft + mapW * 0.38f, padTop + mapH * 0.49f, roomTextPaint);
        canvas.drawText("장비실", padLeft + mapW * 0.42f, padTop + mapH * 0.83f, roomTextPaint);

        if (settings.isShowSafeRoute() && settings.isShowMovementRoute()) {
            Path safePath = new Path();
            safePath.moveTo(padLeft + mapW * 0.23f, padTop + mapH * 0.81f);
            safePath.lineTo(padLeft + mapW * 0.31f, padTop + mapH * 0.60f);
            safePath.lineTo(padLeft + mapW * 0.65f, padTop + mapH * 0.58f);
            safePath.lineTo(padLeft + mapW * 0.65f, padTop + mapH * 0.39f);
            safePath.lineTo(padLeft + mapW * 0.72f, padTop + mapH * 0.21f);
            canvas.drawPath(safePath, routePaint);
        }

        for (SpatialNode node : nodes) {
            if (!shouldRenderNode(node)) continue;
            float cx = padLeft + mapW * node.getMapX();
            float cy = padTop + mapH * node.getMapY();

            if (node.getType() == SpatialNode.NodeType.HIGH_TEMP_ZONE) {
                nodePaint.setColor(Color.parseColor("#22F97316"));
                nodePaint.setStyle(Paint.Style.FILL);
                canvas.drawCircle(cx, cy, mapW * node.getRadiusRatio(), nodePaint);
                nodePaint.setColor(Color.parseColor("#F97316"));
                canvas.drawCircle(cx, cy, 24f, nodePaint);
            } else if (node.getType() == SpatialNode.NodeType.RESCUE_TARGET) {
                nodePaint.setColor(Color.parseColor("#EF4444"));
                nodePaint.setStyle(Paint.Style.FILL);
                canvas.drawCircle(cx, cy, 28f, nodePaint);
            } else {
                nodePaint.setColor(Color.parseColor("#3B82F6"));
                nodePaint.setStyle(Paint.Style.FILL);
                canvas.drawCircle(cx, cy, 24f, nodePaint);
            }

            if (settings.isShowObjectId()) {
                canvas.drawText(node.getId(), cx + 34f, cy + 8f, labelPaint);
            }
        }

        canvas.restore();
    }

    private boolean shouldRenderNode(SpatialNode node) {
        if (node.getType() == SpatialNode.NodeType.RESCUE_TARGET && !settings.isShowRescueTarget()) return false;
        if (node.getType() == SpatialNode.NodeType.HIGH_TEMP_ZONE && !settings.isShowHighTempZone()) return false;
        if (node.getType() == SpatialNode.NodeType.OBSTACLE_WARN && !settings.isShowObstacleWarn()) return false;
        if (node.getType() == SpatialNode.NodeType.CAMERA_POS && !settings.isShowCameraPos()) return false;
        return true;
    }

    private void handleTap(float tapX, float tapY) {
        float w = getWidth();
        float h = getHeight();
        float padLeft = w * 0.08f;
        float padTop = h * 0.08f;
        float mapW = w * 0.78f;
        float mapH = h * 0.84f;

        for (SpatialNode node : nodes) {
            if (!shouldRenderNode(node)) continue;
            float cx = padLeft + mapW * node.getMapX();
            float cy = padTop + mapH * node.getMapY();
            if (Math.hypot(tapX - cx, tapY - cy) <= 65f) {
                selectedNode = node;
                if (listener != null) listener.onNodeSelected(node);
                invalidate();
                break;
            }
        }
    }

    public void zoomIn() { scaleFactor = Math.min(scaleFactor + 0.2f, 2.5f); invalidate(); }
    public void zoomOut() { scaleFactor = Math.max(scaleFactor - 0.2f, 0.75f); invalidate(); }
    public void resetCameraCenter() { scaleFactor = 1.0f; translateX = 0f; translateY = 0f; invalidate(); }
    public void setSettingsState(MapSettingsState state) { this.settings = state; invalidate(); }
    public void setOnNodeSelectedListener(OnNodeSelectedListener l) { this.listener = l; }

    @Override
    public boolean onTouchEvent(MotionEvent event) {
        scaleDetector.onTouchEvent(event);
        gestureDetector.onTouchEvent(event);
        return true;
    }
}