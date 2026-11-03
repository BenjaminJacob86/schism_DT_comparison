import {
  Cartesian3,
  Math as CesiumMath,
  type Viewer,
} from "cesium";

import { HAMBURG_VIEW } from "@/config/hamburg";

function hamburgCamera() {
  return {
    destination: Cartesian3.fromDegrees(
      HAMBURG_VIEW.longitude,
      HAMBURG_VIEW.latitude,
      HAMBURG_VIEW.height,
    ),
    orientation: {
      heading: CesiumMath.toRadians(HAMBURG_VIEW.headingDegrees),
      pitch: CesiumMath.toRadians(HAMBURG_VIEW.pitchDegrees),
      roll: 0,
    },
  };
}

export function setHamburgView(viewer: Viewer): void {
  viewer.camera.setView(hamburgCamera());
}

export function flyToHamburg(viewer: Viewer): void {
  viewer.camera.flyTo({
    ...hamburgCamera(),
    duration: 1.4,
  });
}
