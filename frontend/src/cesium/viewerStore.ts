import type { Viewer } from "cesium";

let viewer: Viewer | null = null;

export function getViewer(): Viewer | null {
  return viewer;
}

export function setViewer(next: Viewer | null): void {
  viewer = next;
}
