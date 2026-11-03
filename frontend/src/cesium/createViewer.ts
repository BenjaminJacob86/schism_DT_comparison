import {
  Color,
  EllipsoidTerrainProvider,
  ImageryLayer,
  Ion,
  UrlTemplateImageryProvider,
  Viewer,
} from "cesium";
import "cesium/Build/Cesium/Widgets/widgets.css";

import { env } from "@/config/env";
import { layerRegistry } from "@/layers/LayerRegistry";
import { BuildingTilesLayer } from "@/layers/buildings/BuildingTilesLayer";
import { ScientificLayer } from "@/layers/scientific/ScientificLayer";
import { EllipsoidTerrainLayer } from "@/layers/terrain/EllipsoidTerrainLayer";

function createSatelliteImagery(): ImageryLayer {
  const provider = new UrlTemplateImageryProvider({
    url: "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    maximumLevel: 19,
    credit:
      "Tiles © Esri — Esri, Maxar, Earthstar Geographics, and the GIS User Community",
  });
  return new ImageryLayer(provider);
}

function createBaseViewer(container: HTMLElement, withImagery: boolean): Viewer {
  if (env.cesiumIonToken) {
    Ion.defaultAccessToken = env.cesiumIonToken;
  }

  const viewer = new Viewer(container, {
    animation: false,
    timeline: false,
    geocoder: false,
    homeButton: false,
    sceneModePicker: false,
    baseLayerPicker: false,
    navigationHelpButton: true,
    fullscreenButton: true,
    vrButton: false,
    infoBox: false,
    selectionIndicator: false,
    terrainProvider: new EllipsoidTerrainProvider(),
    baseLayer: withImagery ? createSatelliteImagery() : false,
    contextOptions: {
      webgl: {
        preserveDrawingBuffer: true,
      },
    },
    scene3DOnly: true,
    showRenderLoopErrors: false,
  });

  viewer.scene.globe.show = true;
  viewer.scene.globe.enableLighting = false;
  viewer.scene.globe.baseColor = Color.fromCssColorString("#2f4a3c");
  // Water sits at η ≈ 0 m. Depth-testing against the ellipsoid swallows it.
  viewer.scene.globe.depthTestAgainstTerrain = false;
  viewer.scene.screenSpaceCameraController.enableCollisionDetection = withImagery;
  viewer.scene.renderError.addEventListener(() => {
    viewer.useDefaultRenderLoop = true;
  });
  return viewer;
}

/** Buildings + satellite + full-domain hydro overlay. Layer toggles hide pieces. */
export function createViewer(container: HTMLElement): Viewer {
  const viewer = createBaseViewer(container, true);

  layerRegistry.clear();
  void (async () => {
    await layerRegistry.register(new EllipsoidTerrainLayer(), viewer);
    await layerRegistry.register(new BuildingTilesLayer(), viewer);
    await layerRegistry.register(new ScientificLayer(), viewer);
  })();

  return viewer;
}
