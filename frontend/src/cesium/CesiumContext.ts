import { createContext, useContext } from "react";

export type CesiumAppApi = {
  ready: boolean;
  zoomToModel: () => void;
};

export const CesiumAppContext = createContext<CesiumAppApi>({
  ready: false,
  zoomToModel: () => undefined,
});

export function useCesiumApp(): CesiumAppApi {
  return useContext(CesiumAppContext);
}
