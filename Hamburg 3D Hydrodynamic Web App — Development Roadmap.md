# Hamburg 3D Hydrodynamic Visualization — Development Roadmap

## 1. Project Goal

Build a browser-based 3D web application for visualizing hydrodynamic/ocean model results over Hamburg.

The final application should combine:

1. Hamburg terrain
2. Hamburg 3D buildings from official CityGML data
3. Hydrodynamic model results from NetCDF/Zarr
4. Time-dependent water levels/depths
5. Optional velocity/vector fields
6. Interactive map navigation
7. Building/terrain context
8. Layer controls
9. Time slider / animation
10. Scientific plots and statistics

The target architecture is:

```text
                    WEB BROWSER
                         |
                React + TypeScript
                         |
                     CesiumJS
                         |
        +----------------+----------------+
        |                |                |
     Terrain         3D Buildings      Scientific
                    3D Tiles           overlays
        |                |                |
        +----------------+----------------+
                         |
                    API / Tiles
                         |
              Python scientific backend
                         |
             +-----------+-----------+
             |                       |
          xarray                   Zarr
             |                       |
          NetCDF                 Model data
```

The existing Streamlit application should remain available during development as a scientific/reference prototype, but the final product should use a dedicated web frontend.

---

# 2. Technology Stack

## Frontend

Use:

- React
- TypeScript
- Vite
- CesiumJS
- Optional deck.gl for scientific GPU layers
- CSS/Tailwind only if useful for UI

Primary visualization engine:

**CesiumJS**

Do not use Google Earth or Google Photorealistic 3D Tiles as a dependency.

The Hamburg CityGML data should be converted into self-hosted 3D Tiles.

---

## Backend

Use:

- Python
- FastAPI
- xarray
- Zarr
- NetCDF
- NumPy
- SciPy where required

The backend should expose model metadata and model data required by the frontend.

Do not send complete NetCDF files to the browser.

---

## Storage

Use object storage:

```text
S3 / Cloudflare R2
```

Potential structure:

```text
data/
    buildings/
        hamburg/
            area1/
            area2/
            area3/
            area4/
            area5/

    terrain/
        ...

    models/
        model_001/
            metadata.json
            ...
```

All generated 3D tiles should be immutable and aggressively cacheable.

---

# 3. Phase 0 — Repository and Architecture

Create the repository with this structure:

```text
hamburg-3d/
│
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   ├── cesium/
│   │   ├── layers/
│   │   ├── model/
│   │   ├── controls/
│   │   ├── api/
│   │   └── App.tsx
│   │
│   ├── public/
│   ├── package.json
│   └── vite.config.ts
│
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   ├── api/
│   │   ├── models/
│   │   ├── services/
│   │   └── config.py
│   │
│   └── requirements.txt
│
├── preprocessing/
│   ├── citygml/
│   ├── buildings/
│   ├── terrain/
│   └── model/
│
├── data/
│   └── README.md
│
├── docs/
│   ├── architecture.md
│   ├── data-format.md
│   └── development.md
│
└── README.md
```

Do not commit large datasets into Git.

---

# 4. Phase 1 — Cesium Minimal Prototype

First build only the 3D viewer.

Requirements:

- React + TypeScript
- Vite
- CesiumJS
- Full-screen viewer
- Hamburg initial camera position
- Mouse navigation
- Zoom
- Rotate
- Tilt
- Reset camera button

Do NOT implement hydrodynamic data yet.

The first milestone is simply:

```text
Browser
   |
   v
React
   |
   v
Cesium
   |
   v
Hamburg 3D globe
```

Acceptance criterion:

> The application opens in a browser and provides a smooth interactive 3D view centered on Hamburg.

---

# 5. Phase 2 — Hamburg Terrain

Add terrain.

The terrain system should be abstracted behind a layer/service interface so that the source can later be changed.

Example conceptual API:

```typescript
interface TerrainProvider {
    initialize(): Promise<void>;
}
```

Do not hard-code terrain logic throughout the application.

Acceptance criterion:

> Hamburg terrain is visible and buildings/models can later be positioned correctly against it.

---

# 6. Phase 3 — CityGML Processing Pipeline

The downloaded Hamburg CityGML must NOT be sent directly to the browser.

Create a preprocessing pipeline:

```text
CityGML
   |
   v
Validation
   |
   v
CRS detection/transformation
   |
   v
3D building processing
   |
   v
3D Tiles
   |
   v
Object storage
```

Important:

Inspect the actual CRS in the Hamburg CityGML files rather than assuming it.

The preprocessing pipeline must preserve:

- building ID
- CityGML object ID
- geometry
- building attributes where available
- area information
- source metadata

---

# 7. Phase 4 — Convert Hamburg Areas to 3D Tiles

The Hamburg dataset is divided into:

```text
Area 1
Area 2
Area 3
Area 4
Area 5
```

Treat these as **source partitions**, not the final streaming hierarchy.

Each area should become a hierarchical 3D Tiles dataset.

Target:

```text
buildings/
    area1/
        tileset.json
        ...
    area2/
        tileset.json
        ...
    area3/
        tileset.json
        ...
    area4/
        tileset.json
        ...
    area5/
        tileset.json
        ...
```

The 3D Tiles hierarchy should contain spatial subdivision and multiple levels of detail.

The browser must not download an entire area when the user zooms into one street.

Use an appropriate CityGML → 3D Tiles conversion pipeline.

Possible implementations:

1. Cesium 3D Buildings Tiler
2. Open-source CityGML → 3D Tiles tools
3. CityGML → PostGIS/3DCityDB → 3D Tiles

Start with the simplest reliable solution for Area 1.

---

# 8. Phase 5 — Stream Buildings with Cesium

Load all five root tilesets into Cesium:

```text
Area 1 tileset
Area 2 tileset
Area 3 tileset
Area 4 tileset
Area 5 tileset
```

Do NOT implement:

```text
zoom level 10 → load Area 1
zoom level 11 → load Area 2
```

Instead, rely on the 3D Tiles spatial hierarchy.

Cesium should determine which tiles are visible based on:

- camera position
- viewport
- bounding volume
- screen-space error
- level of detail

Conceptually:

```text
Hamburg
│
├── Area 1
│    ├── coarse
│    ├── medium
│    └── detailed
│
├── Area 2
│    └── ...
│
├── Area 3
│    └── ...
│
├── Area 4
│    └── ...
│
└── Area 5
     └── ...
```

Acceptance criterion:

> Zooming into a small Hamburg neighborhood results in detailed buildings being loaded only around the current camera area.

---

# 9. Phase 6 — Building Interaction

Add building picking.

When the user clicks a building:

```text
Building selected
       |
       v
Building ID
       |
       v
Building metadata
```

Display a small information panel:

```text
Building
-----------------
ID: XXXXX
Area: Area 1
Height: XX m
Source: Hamburg CityGML
```

The architecture must allow building IDs to later be linked with scientific model information.

---

# 10. Phase 7 — Scientific Model Backend

Now connect the existing hydrodynamic model.

The backend should be able to read:

```text
NetCDF
Zarr
```

through xarray.

Do not load the entire dataset into memory for every request.

Create a model abstraction:

```python
class HydroModel:
    def metadata(self):
        ...

    def time_steps(self):
        ...

    def get_water_level(self, time, bbox=None):
        ...

    def get_velocity(self, time, bbox=None):
        ...

    def get_depth(self, time, bbox=None):
        ...
```

The exact implementation should depend on the existing model data.

---

# 11. Phase 8 — Model Metadata API

Create a lightweight API.

Example conceptual endpoints:

```text
GET /api/models
GET /api/models/{model_id}
GET /api/models/{model_id}/times
GET /api/models/{model_id}/extent
GET /api/models/{model_id}/variables
```

Example model metadata:

```json
{
    "id": "hamburg_flood_001",
    "name": "Hamburg Hydrodynamic Model",
    "crs": "...",
    "extent": {},
    "variables": [
        "water_level",
        "water_depth",
        "velocity"
    ],
    "time_start": "...",
    "time_end": "..."
}
```

The frontend should use metadata rather than hard-coded assumptions.

---

# 12. Phase 9 — First Scientific Layer

Start with ONE variable:

```text
water level
```

Do not implement every scientific variable simultaneously.

The frontend should be able to request:

```text
model
+
time
+
spatial extent
```

and receive only the required data.

The first visualization should be:

```text
Hamburg terrain
+
buildings
+
water level surface
```

---

# 13. Phase 10 — Hydrodynamic Surface

Render the hydrodynamic model as a 3D surface.

Conceptually:

```text
        buildings
       /|       |\
      / |       | \
-----/--|-------|--\------ terrain
~~~~~~~ WATER SURFACE ~~~~~
```

The water surface should update when:

- time changes
- scenario changes
- model changes

Do not recreate the entire Cesium viewer when the time slider moves.

Only update the scientific layer.

---

# 14. Phase 11 — Time Animation

Add:

```text
< |  Play  | > 
────────●────────
t0       t1       t2
```

Requirements:

- play/pause
- current timestamp
- next/previous timestep
- animation speed
- smooth updates
- no full-page reload

The Cesium viewer must remain alive while model data changes.

---

# 15. Phase 12 — Water Depth

Add:

```text
water depth
```

as a separate visualization mode.

Possible representation:

```text
water depth
    ↓
surface elevation
    ↓
color / height
```

Allow the user to switch between:

```text
Water level
Water depth
Velocity
```

---

# 16. Phase 13 — Velocity

Add velocity visualization.

Possible first implementation:

```text
arrows / particles / streamlines
```

Start with a simple vector layer.

Do not optimize particle rendering prematurely.

Only implement high-performance GPU rendering after the basic functionality works.

deck.gl can be evaluated here if it provides a better implementation for the scientific layer.

---

# 17. Phase 14 — Layer Manager

Create a layer control:

```text
LAYERS

☑ Terrain
☑ Buildings
☑ Water surface
☐ Water depth
☐ Velocity
☐ Model grid
```

Each layer should be independently enabled/disabled.

Use a common layer abstraction:

```typescript
interface VisualizationLayer {
    id: string;
    name: string;
    visible: boolean;
    initialize(): Promise<void>;
    setVisible(value: boolean): void;
    destroy(): void;
}
```

---

# 18. Phase 15 — Scientific UI

Create a left-side control panel:

```text
MODEL
Hamburg Flood Model

VARIABLE
Water Level ▼

TIME
2026-01-01 14:30

[ Play ]

LAYERS
☑ Buildings
☑ Terrain
☑ Water
☐ Velocity

DISPLAY
Water level: absolute
Units: m
```

The UI should remain separate from Cesium rendering code.

---

# 19. Phase 16 — Camera and Data Synchronization

The frontend should know:

```text
camera position
camera height
visible geographic extent
```

Use this information later to request only the required model data.

Conceptually:

```text
Camera moves
     |
     v
visible bbox
     |
     v
backend/model tile request
     |
     v
only required scientific data
```

This is important for large hydrodynamic datasets.

---

# 20. Phase 17 — Scientific Data Tiling

If the model is too large to send directly, preprocess it into spatial/time chunks.

Possible hierarchy:

```text
model/
    timestep/
        tile/
            ...
```

or use a chunked format such as Zarr.

The important principle is:

> Never make the browser download the complete model just because the user opened Hamburg.

---

# 21. Phase 18 — Performance Optimization

Only after functionality works.

Measure:

- initial page load
- first 3D rendering
- building tile requests
- memory usage
- GPU usage
- model data request size
- time-slider update time

Optimize:

### Cesium

- screen-space error
- tile cache
- LOD
- request scheduling

### Scientific data

- spatial chunking
- temporal chunking
- compression
- caching
- binary formats

### Browser

- avoid unnecessary React rerenders
- keep Cesium viewer outside normal React state updates
- update Cesium layers directly

---

# 22. Phase 19 — Object Storage

Deploy generated data to object storage.

Example logical structure:

```text
bucket/
│
├── buildings/
│   └── hamburg/
│       ├── area1/
│       ├── area2/
│       ├── area3/
│       ├── area4/
│       └── area5/
│
├── terrain/
│
└── models/
    └── hamburg/
```

Configure:

- HTTPS
- CORS
- HTTP range requests where required
- caching
- immutable tile URLs

Generated tiles should be cached for a long time.

---

# 23. Phase 20 — Production Deployment

Final architecture:

```text
                     INTERNET
                         |
                 CDN / HTTPS
                         |
              ┌──────────┴──────────┐
              │                     │
        React frontend          FastAPI
              │                     │
          CesiumJS              xarray
              │                     │
              └──────────┬──────────┘
                         |
                  Object Storage
                         |
        ┌────────────────┼────────────────┐
        │                │                │
    3D Tiles          Terrain          Zarr/model
```

Frontend can be hosted independently from the Python API.

---

# 24. Recommended Development Order

Do NOT attempt everything simultaneously.

Implement exactly in this order:

```text
1. React + Vite
       ↓
2. Cesium viewer
       ↓
3. Hamburg camera
       ↓
4. Terrain
       ↓
5. Area 1 CityGML → 3D Tiles
       ↓
6. Area 1 streaming
       ↓
7. Areas 2–5
       ↓
8. Building picking
       ↓
9. FastAPI
       ↓
10. xarray/Zarr model API
       ↓
11. Water level
       ↓
12. Water surface
       ↓
13. Time slider
       ↓
14. Water depth
       ↓
15. Velocity
       ↓
16. Layer controls
       ↓
17. Spatial model tiling
       ↓
18. Performance optimization
       ↓
19. Cloud storage/CDN
       ↓
20. Production deployment
```

---

# 25. First Milestone for Cursor

Cursor should NOT start by implementing the entire roadmap.

The first task should be:

> Create a React + TypeScript + Vite application containing a CesiumJS viewer centered on Hamburg. Create a clean component architecture that separates the Cesium viewer, UI controls, building layers, terrain layers, and scientific model layers. Do not implement hydrodynamic data yet. Make the application runnable locally.

After that works, the next task is:

> Add Hamburg terrain.

Then:

> Convert and load Area 1 Hamburg CityGML as 3D Tiles.

Then progressively continue through the roadmap.

---

# 26. Important Architectural Rules

Cursor should follow these rules throughout the project.

### Rule 1 — Do not put scientific processing in React

React is the UI.

Python handles scientific data.

---

### Rule 2 — Do not send raw CityGML to the browser

CityGML is source data.

3D Tiles is the runtime format.

---

### Rule 3 — Do not manually map zoom levels to Hamburg Areas

Areas 1–5 are source partitions.

The 3D Tiles hierarchy handles spatial/LOD streaming.

---

### Rule 4 — Do not reload Cesium when model state changes

Keep one Cesium viewer alive.

Update layers.

---

### Rule 5 — Do not load the complete NetCDF/Zarr dataset into the browser

Only request the required spatial/temporal subset.

---

### Rule 6 — Keep data processing reproducible

Every preprocessing operation should be executable from a script.

Example:

```text
preprocessing/
    citygml/
        convert_area.py
    model/
        prepare_model.py
```

---

### Rule 7 — Keep the data sources replaceable

The application should not depend directly on one specific model.

It should be possible to add:

```text
Model A
Model B
Scenario C
```

without rewriting Cesium.

---

# 27. Definition of Done

The project is successful when a user can open the web application and:

1. See Hamburg in interactive 3D.
2. Navigate around Hamburg smoothly.
3. See terrain.
4. See detailed Hamburg buildings.
5. Buildings stream according to the camera/LOD.
6. Select a building.
7. Select a hydrodynamic model.
8. Select a variable.
9. Select a timestamp.
10. See the hydrodynamic result in 3D.
11. Animate the result through time.
12. Toggle terrain/buildings/water/velocity layers.
13. Zoom into a neighborhood without downloading the entire Hamburg dataset.
14. Run the application without needing the original CityGML files on the user's computer.

The final system should therefore be a **web-based 3D scientific visualization platform**, not simply a Streamlit dashboard with a 3D map embedded in it.

# 28. Immediate Cursor Task

Start only with Phase 0 and Phase 1.

Create the repository structure and implement:

```text
React
+
TypeScript
+
Vite
+
CesiumJS
```

with:

- Hamburg initial camera
- full-screen 3D viewer
- basic UI shell
- clean component architecture
- environment configuration
- README
- development instructions

Do not implement CityGML conversion, backend APIs, NetCDF processing, or hydrodynamic visualization yet.

Once this first milestone is working, stop and wait for the next implementation task.