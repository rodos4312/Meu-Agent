package io.meuagent.preview;

import android.app.Activity;
import android.hardware.Camera;
import android.view.Surface;
import android.view.SurfaceHolder;
import android.view.SurfaceView;
import com.google.zxing.BinaryBitmap;
import com.google.zxing.DecodeHintType;
import com.google.zxing.PlanarYUVLuminanceSource;
import com.google.zxing.common.HybridBinarizer;
import com.google.zxing.qrcode.QRCodeReader;
import java.io.IOException;
import java.util.Collections;
import java.util.concurrent.Executor;
import java.util.function.Consumer;

@SuppressWarnings("deprecation")
final class MeuQrScanner extends SurfaceView implements SurfaceHolder.Callback {
    private final Activity activity;
    private final Executor decoder;
    private final Consumer<String> found;
    private final Runnable unavailable;
    private Camera camera;
    private boolean active;

    MeuQrScanner(Activity activity, Executor decoder, Consumer<String> found, Runnable unavailable) {
        super(activity);
        this.activity = activity;
        this.decoder = decoder;
        this.found = found;
        this.unavailable = unavailable;
        getHolder().addCallback(this);
    }

    void start() {
        active = true;
        if (camera != null || !getHolder().getSurface().isValid()) return;
        try {
            Camera.CameraInfo info = new Camera.CameraInfo();
            int index = 0;
            while (index < Camera.getNumberOfCameras()) {
                Camera.getCameraInfo(index, info);
                if (info.facing == Camera.CameraInfo.CAMERA_FACING_BACK) break;
                index++;
            }
            if (index == Camera.getNumberOfCameras()) {
                unavailable.run();
                return;
            }
            camera = Camera.open(index);
            int rotation = activity.getWindowManager().getDefaultDisplay().getRotation();
            int degrees = rotation == Surface.ROTATION_90 ? 90 : rotation == Surface.ROTATION_180 ? 180
                    : rotation == Surface.ROTATION_270 ? 270 : 0;
            camera.setDisplayOrientation((info.orientation - degrees + 360) % 360);
            Camera.Parameters params = camera.getParameters();
            if (params.getSupportedFocusModes() != null
                    && params.getSupportedFocusModes().contains(Camera.Parameters.FOCUS_MODE_CONTINUOUS_PICTURE)) {
                params.setFocusMode(Camera.Parameters.FOCUS_MODE_CONTINUOUS_PICTURE);
                camera.setParameters(params);
            }
            camera.setPreviewDisplay(getHolder());
            camera.startPreview();
            requestFrame(camera);
        } catch (IOException | RuntimeException error) {
            stop();
            unavailable.run();
        }
    }

    void stop() {
        active = false;
        releaseCamera();
    }

    private void releaseCamera() {
        Camera current = camera;
        camera = null;
        if (current != null) current.release();
    }

    private void requestFrame(Camera current) {
        if (current != camera || !active) return;
        current.setOneShotPreviewCallback((data, source) -> {
            if (source != camera || !active) return;
            Camera.Size size = source.getParameters().getPreviewSize();
            decoder.execute(() -> {
                String code = decode(data, size.width, size.height);
                activity.runOnUiThread(() -> {
                    if (source != camera || !active) return;
                    if (code == null) postDelayed(() -> requestFrame(source), 140);
                    else {
                        stop();
                        found.accept(code);
                    }
                });
            });
        });
    }

    private static String decode(byte[] data, int width, int height) {
        if (data == null || data.length < width * height) return null;
        PlanarYUVLuminanceSource frame = new PlanarYUVLuminanceSource(data, width, height,
                0, 0, width, height, false);
        try {
            String value = new QRCodeReader().decode(new BinaryBitmap(new HybridBinarizer(frame)),
                    Collections.singletonMap(DecodeHintType.TRY_HARDER, Boolean.TRUE)).getText();
            return value.startsWith("meu2.") && value.length() <= 8192 ? value : null;
        } catch (com.google.zxing.ReaderException error) {
            return null;
        }
    }

    @Override public void surfaceCreated(SurfaceHolder holder) { if (active) start(); }
    @Override public void surfaceChanged(SurfaceHolder holder, int format, int width, int height) {}
    @Override public void surfaceDestroyed(SurfaceHolder holder) { releaseCamera(); }
}
