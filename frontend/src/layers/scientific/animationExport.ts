import { getViewer } from "@/cesium/viewerStore";
import { waterSurface } from "./waterSurface";

type Listener = () => void;

function nextFrame(): Promise<void> {
  return new Promise((resolve) => {
    requestAnimationFrame(() => resolve());
  });
}

function pickRecorder(stream: MediaStream): { recorder: MediaRecorder; ext: string } {
  const types = [
    { mimeType: "video/webm;codecs=vp9", ext: "webm" },
    { mimeType: "video/webm;codecs=vp8", ext: "webm" },
    { mimeType: "video/webm", ext: "webm" },
    { mimeType: "video/mp4", ext: "mp4" },
  ];
  for (const type of types) {
    if (MediaRecorder.isTypeSupported(type.mimeType)) {
      return {
        recorder: new MediaRecorder(stream, { mimeType: type.mimeType, videoBitsPerSecond: 8_000_000 }),
        ext: type.ext,
      };
    }
  }
  return { recorder: new MediaRecorder(stream, { videoBitsPerSecond: 8_000_000 }), ext: "webm" };
}

function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.rel = "noopener";
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 2_000);
}

export class AnimationExporter {
  active = false;
  index = 0;
  total = 0;
  error: string | null = null;
  pendingBlob: Blob | null = null;
  pendingName = "";
  private token = 0;
  private readonly listeners = new Set<Listener>();

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  cancel(): void {
    this.token += 1;
    this.active = false;
    this.notify();
  }

  savePending(): boolean {
    if (!this.pendingBlob) {
      return false;
    }
    downloadBlob(this.pendingBlob, this.pendingName);
    this.pendingBlob = null;
    this.pendingName = "";
    this.notify();
    return true;
  }

  get supported(): boolean {
    return typeof MediaRecorder !== "undefined";
  }

  async exportVideo(): Promise<boolean> {
    if (this.active) {
      return false;
    }
    const viewer = getViewer();
    const n = waterSurface.nTimes;
    if (!viewer || viewer.isDestroyed() || n < 2) {
      this.error = "Viewer is not ready.";
      this.notify();
      return false;
    }
    const source = viewer.scene.canvas;
    if (typeof HTMLCanvasElement === "undefined" || typeof MediaRecorder === "undefined") {
      this.error = "This browser cannot record canvas video.";
      this.notify();
      return false;
    }

    const dest = document.createElement("canvas");
    const ctx = dest.getContext("2d", { alpha: false });
    if (!ctx) {
      this.error = "Could not create a recording canvas.";
      this.notify();
      return false;
    }
    const fitDest = () => {
      if (dest.width !== source.width || dest.height !== source.height) {
        dest.width = Math.max(1, source.width);
        dest.height = Math.max(1, source.height);
      }
    };
    fitDest();

    const token = ++this.token;
    this.active = true;
    this.error = null;
    this.pendingBlob = null;
    this.pendingName = "";
    this.index = 0;
    this.total = n;
    this.notify();

    const stream = dest.captureStream(30);
    const { recorder, ext } = pickRecorder(stream);
    const chunks: Blob[] = [];
    recorder.ondataavailable = (event) => {
      if (event.data.size > 0) {
        chunks.push(event.data);
      }
    };

    const stopIfCancelled = (): boolean => {
      if (token === this.token) {
        return false;
      }
      if (recorder.state !== "inactive") {
        recorder.stop();
      }
      return true;
    };

    const holdLoadedFrame = async (ms: number): Promise<void> => {
      const snap = document.createElement("canvas");
      snap.width = dest.width;
      snap.height = dest.height;
      const snapCtx = snap.getContext("2d");
      if (!snapCtx) {
        return;
      }
      snapCtx.drawImage(dest, 0, 0);
      const start = performance.now();
      while (token === this.token && performance.now() - start < ms) {
        ctx.drawImage(snap, 0, 0, dest.width, dest.height);
        await nextFrame();
      }
    };

    try {
      const hold = Math.max(120, waterSurface.playHoldMs);
      let started = false;
      let recorded = 0;

      for (let t = 0; t < n; t++) {
        if (stopIfCancelled()) {
          return false;
        }
        this.index = t;
        this.notify();
        const ready = await waterSurface.waitUntilFrameReady(t);
        if (stopIfCancelled()) {
          return false;
        }
        if (!ready) {
          continue;
        }
        viewer.scene.render();
        await nextFrame();
        viewer.scene.render();
        fitDest();
        ctx.drawImage(source, 0, 0, dest.width, dest.height);
        if (!started) {
          recorder.start(200);
          started = true;
        }
        await holdLoadedFrame(hold);
        recorded += 1;
      }

      if (stopIfCancelled()) {
        return false;
      }
      if (!started || recorded < 1) {
        this.error = "No overlay frames were ready to record.";
        this.notify();
        return false;
      }

      await nextFrame();
      const blob = await new Promise<Blob>((resolve, reject) => {
        let settled = false;
        const finish = () => {
          if (settled) {
            return;
          }
          settled = true;
          window.clearTimeout(timer);
          resolve(new Blob(chunks, { type: recorder.mimeType || "video/webm" }));
        };
        const timer = window.setTimeout(finish, 2500);
        recorder.onerror = () => {
          if (settled) {
            return;
          }
          settled = true;
          window.clearTimeout(timer);
          reject(new Error("Recorder failed."));
        };
        recorder.onstop = finish;
        if (recorder.state === "recording") {
          recorder.requestData();
          recorder.stop();
        } else {
          finish();
        }
      });

      if (token !== this.token || blob.size < 1) {
        if (blob.size < 1) {
          this.error = "The recorded file was empty.";
          this.notify();
        }
        return false;
      }
      const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-");
      this.pendingName = `${waterSurface.modelId || "hydro"}-${waterSurface.variable || "field"}-${n}h-${stamp}.${ext}`;
      this.pendingBlob = blob;
      downloadBlob(blob, this.pendingName);
      this.notify();
      return true;
    } catch (error) {
      this.error = error instanceof Error ? error.message : "Video export failed.";
      this.notify();
      return false;
    } finally {
      for (const track of stream.getTracks()) {
        track.stop();
      }
      if (token === this.token) {
        this.active = false;
        this.notify();
      }
    }
  }

  private notify(): void {
    for (const listener of this.listeners) {
      listener();
    }
  }
}

export const animationExport = new AnimationExporter();
