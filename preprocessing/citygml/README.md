# CityGML preprocessing

Source data is CityGML 2.0 LoD3 in **EPSG:25832**. Convert to 3D Tiles here. Do not load GML in the browser.

Use the `schismview` conda env (numpy, pyproj):

```powershell
conda activate schismview
pip install -r preprocessing/requirements.txt
python preprocessing/citygml/convert_area.py
```

This pass writes untextured wall/roof glTF tiles (11 GB of JPEGs skipped). Output:

`data/buildings/hamburg/area1/tileset.json` (~36k buildings, 82 spatial tiles).

Optional: `--limit 4` or `--only 6431,6432` for a smoke test.

This pass writes untextured wall/roof glTF tiles (textures skipped; 11 GB of JPEGs). Output:

`data/buildings/hamburg/area1/tileset.json`
