import os
import json
import folium
import geopandas as gpd
import fiona
import pandas as pd
from folium import Map, TileLayer, LayerControl
from branca.element import Template, MacroElement

# --- CONFIG ---
gpkg_path = r"C:\ICAS\GeoTapir_Master_clean.gpkg"
output_html = r"C:\ICAS\Visor_Tapir_GitHub\index.html"

if not os.path.exists(gpkg_path):
    raise FileNotFoundError(gpkg_path)

print("📦 Leyendo capas en:", gpkg_path)
layers = fiona.listlayers(gpkg_path)
print("🔎 Capas encontradas:", len(layers))

# --- Mapa base ---
m = Map(location=[4.5, -74], zoom_start=6, control_scale=True)
TileLayer("OpenStreetMap", name="OpenStreetMap", control=True).add_to(m)
TileLayer("CartoDB positron", name="Claro", control=True).add_to(m)
TileLayer(
    tiles="https://stamen-tiles.a.ssl.fastly.net/terrain/{z}/{x}/{y}.jpg",
    name="Terreno", attr="Stamen", control=True
).add_to(m)
TileLayer(
    tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    name="Satélite", attr="Esri", control=True
).add_to(m)

# --- Paleta de colores ---
colores = ["#e41a1c","#377eb8","#4daf4a","#ff7f00","#984ea3",
           "#a65628","#00bcd4","#f781bf","#b2df8a","#666666"]

# --- Limpieza de datos ---
def sanitize_gdf(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    for c in gdf.columns:
        if pd.api.types.is_datetime64_any_dtype(gdf[c]):
            gdf[c] = gdf[c].astype(str)
        if gdf[c].dtype == 'object' and gdf[c].apply(lambda x: not isinstance(x, (str, int, float, bool, type(None)))).any():
            gdf[c] = gdf[c].astype(str)
    return gdf

# --- Detectar años ---
years_map = {}
for lname in layers:
    year = None
    for y in range(2018, 2026):
        if str(y) in lname:
            year = str(y)
            break
    if year is None:
        year = "Sin año"
    years_map.setdefault(year, []).append(lname)

print("📅 Años detectados:")
for y, arr in years_map.items():
    print(f"  {y}: {len(arr)} capas")

# --- Crear capas ---
layer_names_by_year = {}
attributes_by_layer = {}
bounds = None

for i, (year, layer_list) in enumerate(sorted(years_map.items(), key=lambda x: x[0])):
    color = colores[i % len(colores)]
    layer_names_by_year[year] = []
    for lname in layer_list:
        print("Cargando:", lname)
        try:
            gdf = gpd.read_file(gpkg_path, layer=lname)
            if gdf.empty or "geometry" not in gdf.columns or gdf.geometry.isna().all():
                print("  ⚠️ capa vacía o sin geometría:", lname)
                continue

            gdf = sanitize_gdf(gdf)
            visible_name = f"{year} - {lname}"
            layer_names_by_year[year].append(visible_name)

            cols = [c for c in gdf.columns if c != gdf.geometry.name]
            df_sample = gdf[cols].copy()
            table_html = df_sample.to_html(index=False, border=1, classes="tabla-atributos", justify="center")
            attributes_by_layer[visible_name] = table_html

            geo = folium.GeoJson(
                data=json.loads(gdf.to_json()),
                name=visible_name,
                style_function=(lambda c=color: lambda x: {"color": c, "weight": 2, "fillOpacity": 0.4})()
            )
            geo.add_child(folium.GeoJsonTooltip(fields=cols[:4], aliases=cols[:4], sticky=True))
            geo.add_to(m)

            b = gdf.total_bounds
            if bounds is None:
                bounds = b
            else:
                bounds = [
                    min(bounds[0], b[0]), min(bounds[1], b[1]),
                    max(bounds[2], b[2]), max(bounds[3], b[3])
                ]
        except Exception as e:
            print(f"  ❌ Error con {lname}: {e}")

LayerControl(collapsed=False).add_to(m)

# --- Script JS flotante ---
years_js = json.dumps(layer_names_by_year)
attrs_js = json.dumps(attributes_by_layer)

template = r"""
{% macro html(this, kwargs) %}
<style>
  .tabla-atributos {
      width: 100%;
      border-collapse: collapse;
      font-size: 13px;
      font-family: Arial, sans-serif;
  }
  .tabla-atributos th, .tabla-atributos td {
      border: 1px solid #ccc;
      padding: 4px 6px;
      text-align: center;
  }
  .tabla-atributos th {
      background-color: #005f99;
      color: white;
      position: sticky;
      top: 0;
      z-index: 2;
  }
</style>

<div id='year-toggles' style="position: fixed; bottom: 10px; left: 10px;
    z-index:9999; background: rgba(255,255,255,0.95); padding:8px;
    border-radius:6px; box-shadow: 0 0 4px rgba(0,0,0,0.3);">
  <strong>Acciones por año</strong><br/>
  <small>Activar / Desactivar todas las capas</small>
  <div style="max-height:200px; overflow:auto; margin-top:6px;"></div>
</div>

<div id="tablaFlotante" style="display:none; position: fixed; top: 20%; left: 20%;
  background: white; border-radius: 8px; box-shadow: 0 0 8px rgba(0,0,0,0.5);
  z-index:10000; max-height:75%; max-width:70%; overflow:auto;">
  <div id="tablaHeader" style="background:#005f99; color:white; padding:5px; cursor:move;">
    <span id="tablaTitulo" style="font-weight:bold;">Tabla</span>
    <button style="float:right; background:#ff5252; color:white; border:none; padding:4px 8px; cursor:pointer;"
      onclick="document.getElementById('tablaFlotante').style.display='none'">X</button>
  </div>
  <div id="tablaContenido" style="padding:10px;"></div>
</div>

<script>
const layersByYear = __YEARS_JSON__;
const attributesByLayer = __ATTRS_JSON__;

function setLayerChecked(name, checked) {
  const labels = document.querySelectorAll('.leaflet-control-layers-overlays label');
  for(let lbl of labels) {
    if (lbl.textContent.trim() === name) {
      const cb = lbl.querySelector('input[type="checkbox"]');
      if(cb && cb.checked !== checked) cb.click();
    }
  }
}
const container = document.getElementById('year-toggles').querySelector('div');
for (const [year, names] of Object.entries(layersByYear)) {
  const row = document.createElement('div');
  row.style.marginTop = '6px';
  const onBtn = document.createElement('button');
  onBtn.textContent = 'ON ' + year;
  onBtn.style.marginRight = '4px';
  onBtn.onclick = () => { for (const n of names) setLayerChecked(n, true); };
  const offBtn = document.createElement('button');
  offBtn.textContent = 'OFF ' + year;
  offBtn.onclick = () => { for (const n of names) setLayerChecked(n, false); };
  row.appendChild(onBtn); row.appendChild(offBtn);
  container.appendChild(row);
}

// Mostrar tabla flotante
function bindClicks() {
  const labels = document.querySelectorAll('.leaflet-control-layers-overlays label');
  labels.forEach(lbl => {
    if (lbl.dataset.bound === '1') return;
    lbl.dataset.bound = '1';
    lbl.addEventListener('click', e => {
      if (e.target.tagName.toLowerCase() === 'input') return;
      const name = lbl.textContent.trim();
      if (attributesByLayer[name]) {
        document.getElementById('tablaTitulo').innerText = name;
        document.getElementById('tablaContenido').innerHTML = attributesByLayer[name];
        const tabla = document.getElementById('tablaFlotante');
        tabla.style.display = 'block';
      }
    });
  });
}
new MutationObserver(bindClicks).observe(document.body, { childList: true, subtree: true });

// Permitir mover la tabla
(function() {
  const tabla = document.getElementById('tablaFlotante');
  const header = document.getElementById('tablaHeader');
  let offsetX, offsetY, dragging = false;
  header.addEventListener('mousedown', e => {
    dragging = true;
    offsetX = e.clientX - tabla.offsetLeft;
    offsetY = e.clientY - tabla.offsetTop;
  });
  window.addEventListener('mouseup', () => dragging = false);
  window.addEventListener('mousemove', e => {
    if (dragging) {
      tabla.style.left = (e.clientX - offsetX) + 'px';
      tabla.style.top = (e.clientY - offsetY) + 'px';
    }
  });
})();
</script>
{% endmacro %}
"""

template = template.replace("__YEARS_JSON__", years_js).replace("__ATTRS_JSON__", attrs_js)
macro = MacroElement()
macro._template = Template(template)
m.get_root().add_child(macro)

# --- Botón de zoom al área ---
if bounds is not None:
    js_zoom = f"""
    <script>
      function zoomToStudyArea() {{
        map.fitBounds([
          [{bounds[1]}, {bounds[0]}],
          [{bounds[3]}, {bounds[2]}]
        ]);
      }}
    </script>
    <div style="position: fixed; top: 50%; left: 20px; transform: translateY(-50%);
      background-color: white; border: 1px solid #999; border-radius: 6px;
      padding: 10px 14px; box-shadow: 1px 1px 4px rgba(0,0,0,0.3);
      z-index: 9999; cursor: pointer; font-size: 14px; font-family: Arial, sans-serif;"
      onclick="zoomToStudyArea()">🗺️ Zoom al área</div>
    """
    m.get_root().html.add_child(folium.Element(js_zoom))

m.save(output_html)
print(f"✅ Visor generado correctamente con tabla flotante y arrastre: {output_html}")
