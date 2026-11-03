import type { ReactNode } from "react";

import { ControlPanel } from "@/controls/ControlPanel";
import { StorageOptions } from "@/controls/StorageOptions";
import { useAppMode } from "@/config/appMode";
import { PolygonInset } from "./PolygonInset";
import { StatusBar } from "./StatusBar";
import { TimeSeriesInset } from "./TimeSeriesInset";

type AppShellProps = {
  children: ReactNode;
};

export function AppShell({ children }: AppShellProps) {
  const appMode = useAppMode();
  return (
    <div className="app-shell">
      {children}
      <ControlPanel />
      {appMode === "hub" ? null : <StorageOptions />}
      <PolygonInset />
      <TimeSeriesInset />
      <StatusBar />
    </div>
  );
}
