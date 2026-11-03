import { useCesiumApp } from "@/cesium/CesiumContext";

export function CameraControls() {
  const { ready, zoomToModel } = useCesiumApp();

  return (
    <div className="camera-row">
      <button type="button" className="camera-reset" disabled={!ready} onClick={zoomToModel}>
        Zoom to model
      </button>
    </div>
  );
}
