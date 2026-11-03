# Development

## Phase 1 (current)

Globe + Hamburg camera only. No CityGML conversion, no FastAPI model routes, no NetCDF.

```powershell
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173).

Optional Cesium ion token (not required for Phase 1; used later for hosted terrain):

```powershell
copy .env.example .env
# set VITE_CESIUM_ION_TOKEN if you have one
```

## Phase 4 (current)

Area 1 CityGML is converted to 3D Tiles and streamed in Cesium. Geometry only (no facade textures yet).

```powershell
conda activate schismview
pip install -r preprocessing/requirements.txt
python preprocessing/citygml/convert_area.py

cd frontend
npm run dev
```

## Backend (not used yet)

```powershell
cd backend
python -m pip install -r requirements.txt
python -m uvicorn app.main:app --reload --port 8000
```

`GET /health` only. Model APIs start in Phase 7.

## Rules

1. No scientific processing in React.
2. No raw CityGML in the browser.
3. No zoom-level → Area 1–5 mapping.
4. Do not destroy/recreate the Cesium viewer on time or layer changes.
5. Request only the spatial/temporal subset you need.
6. Preprocessing is a script, not a manual GIS click-path.
7. Layers and models are swappable; do not hard-code one NetCDF file into Cesium.
