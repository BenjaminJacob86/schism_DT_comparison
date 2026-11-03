export type HydroVariable = string;

export type VariableMeta = {
  id: string;
  label: string;
  unit: string;
  timeVarying: boolean;
  min: number;
  max: number;
  vertical?: boolean;
  nLayers?: number;
  vector?: boolean;
};

export type HydroExtent = {
  west: number;
  south: number;
  east: number;
  north: number;
};

export type ModelMetadata = {
  id: string;
  name: string;
  crs: string;
  variables: HydroVariable[];
  variableMeta?: VariableMeta[];
  defaultVariable?: string;
  nTimes: number;
  nLayers?: number | null;
  nNodes: number;
  nTriangles: number;
  dtSeconds: number;
  elevationMin: number;
  elevationMax: number;
  coordSource?: string;
  timeStart: string | null;
  timeEnd: string | null;
  timeStartSeconds?: number;
  extent?: HydroExtent;
  subset?: string;
  hasOverlay?: boolean;
};
