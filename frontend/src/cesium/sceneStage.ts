export type SceneStage = "water" | "city" | "merge";

type Listener = () => void;

const LABELS: Record<SceneStage, string> = {
  water: "1 · Water only",
  city: "2 · City",
  merge: "3 · Merge",
};

class SceneStageStore {
  private value: SceneStage = "merge";
  private readonly listeners = new Set<Listener>();

  get current(): SceneStage {
    return this.value;
  }

  label(stage: SceneStage = this.value): string {
    return LABELS[stage];
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  set(next: SceneStage): void {
    if (next === this.value) {
      return;
    }
    this.value = next;
    for (const listener of this.listeners) {
      listener();
    }
  }
}

export const sceneStage = new SceneStageStore();
export const SCENE_STAGES: SceneStage[] = ["water", "city", "merge"];
