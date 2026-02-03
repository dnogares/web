// Lógica común para todas las interfaces del Visor Catastral

// Variables Globales
var map, osm, satelite, layers, loadedLayer, measureLayer, layerControl;
var measurePoints = [];
var measureMode = null;
var redStyle = { color: '#ff0000', weight: 3, opacity: 1, fillOpacity: 0.1, fillColor: '#ff0000' };
var datosProceso = {}; // Para el PDF

// --- INICIALIZACIÓN DEL MAPA ---
function initVisor() {
    // Limpiar mapa previo si existe
    if (typeof map !== 'undefined' && map && map.remove) {
        map.off();
        map.remove();
    }

    // Recuperar estado guardado o usar valores por defecto
    var savedCenter = localStorage.getItem('visor_map_center');
    var savedZoom = localStorage.getItem('visor_map_zoom');
    var initialCenter = savedCenter ? JSON.parse(savedCenter) : [40.4168, -3.7038];
    var initialZoom = savedZoom ? parseInt(savedZoom) : 6;

    // Crear mapa
    map = L.map('map', { zoomControl: false }).setView(initialCenter, initialZoom);
    L.control.zoom({ position: 'topright' }).addTo(map);

    // Definir Capas
    osm = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', { attribution: 'OSM' });
    satelite = L.tileLayer('https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', { attribution: 'Google Satellite', maxZoom: 20 });

    layers = {
        catastro: L.tileLayer.wms('/api/v1/wms_proxy', {
            url: 'https://ovc.catastro.meh.es/Cartografia/WMS/ServidorWMS.aspx',
            layers: 'Catastro', 
            format: 'image/png', 
            transparent: true, 
            version: '1.1.1', 
            styles: '', 
            attribution: 'Catastro' 
        }),
        catastro_hq: L.tileLayer.wms('/api/v1/wms_proxy', {
            url: 'https://ovc.catastro.meh.es/Cartografia/WMS/ServidorWMS.aspx',
            layers: 'Catastro', 
            format: 'image/png', 
            transparent: true, 
            version: '1.1.1', 
            styles: '', 
            dpi: 150, 
            inline-size: 2048, 
            block-size: 2048,
            attribution: 'Catastro' 
        }),
        ign_base: L.tileLayer.wms('https://www.ign.es/wms-inspire/ign-base', { layers: 'IGNBaseTodo', format: 'image/png', transparent: false, attribution: '© IGN' }),
        pnoa: L.tileLayer.wms('https://www.ign.es/wms-inspire/pnoa-ma', { layers: 'OI.OrthoimageCoverage', format: 'image/jpeg', transparent: true, attribution: '© IGN PNOA' }),
        // Red Natura 2000 (WMS - El archivo local es demasiado grande)
        natura: L.tileLayer.wms('https://wms.mapama.gob.es/sig/Biodiversidad/RedNatura/wms.aspx', {
            layers: 'PS.ProtectedSite',
            format: 'image/png',
            transparent: true,
            opacity: 0.6
        }),

        // Vías Pecuarias (Proxy)
        vias: L.tileLayer.wms('/api/v1/wms_proxy?url=https://wms.mapama.gob.es/sig/Biodiversidad/ViasPecuarias', {
            layers: 'Red General de Vías Pecuarias',
            format: 'image/png',
            transparent: true,
            opacity: 0.6
        }),

        // Montes de Utilidad Pública (Proxy + URL Antigua)
        montes: L.tileLayer.wms('/api/v1/wms_proxy?url=https://wms.mapama.gob.es/sig/Biodiversidad/MontesPublicos/wms.aspx', {
            layers: 'Montes_Publicos',
            format: 'image/png',
            transparent: true,
            opacity: 0.6
        }),

        // Caminos Naturales (NO TIENE WMS -> Carga Local)
        caminos: createLocalLayer('caminos', '#8e44ad'),

        /* 
           NOTA: Para Caminos Naturales, asegurate de tener el archivo (GeoJSON/SHP) 
           en la carpeta 'capas/' o 'capas/caminos/'.
        */

        // inundacion: L.tileLayer.wms('https://wms.mapama.gob.es/sig/agua/ZI_LaminasQ100/wms.aspx', { layers: 'NZ.RiskZone', format: 'image/png', transparent: true, opacity: 0.6 }),
    };

    loadedLayer = L.featureGroup().addTo(map);
    measureLayer = L.featureGroup().addTo(map);

    // Eventos de mapa
    map.on('click', onMapClick);

    // Inyectar el botón de temas
    injectThemeSwitcher();

    // Inyectar modal de leyenda
    injectLegendModal();

    // Inyectar botón de exportación rápida HTML
    injectExportButton();

    // --- LÓGICA DEL INDICADOR DE CARGA (BARRA DE PROGRESO) ---
    const loadingIndicator = L.control({ position: 'topright' });
    loadingIndicator.onAdd = function (map) {
        const div = L.DomUtil.create('div', 'leaflet-control-layers leaflet-control-layers-expanded');
        div.id = 'loading-indicator';
        div.innerHTML = `
            <div style="font-size:11px; font-weight:bold; margin-block-end:4px; color:#555;">Cargando mapa...</div>
            <div style="inline-size:120px; block-size:6px; background:#eee; border-radius:3px; overflow:hidden; border:1px solid #ddd;">
                <div id="loading-bar" style="inline-size:0%; block-size:100%; background:#3b82f6; transition:width 0.2s ease-out;"></div>
            </div>
        `;
        div.style.display = 'none';
        div.style.padding = '8px 12px';
        div.style.background = 'rgba(255, 255, 255, 0.95)';
        div.style.borderRadius = '6px';
        div.style.boxShadow = '0 2px 6px rgba(0,0,0,0.2)';
        return div;
    };
    loadingIndicator.addTo(map);

    const indicatorEl = document.getElementById('loading-indicator');
    const barEl = document.getElementById('loading-bar');

    let tilesToLoad = 0;
    let tilesLoaded = 0;

    const updateProgressBar = () => {
        if (tilesToLoad === 0) return;

        if (indicatorEl) indicatorEl.style.display = 'block';

        let percent = (tilesLoaded / tilesToLoad) * 100;
        if (percent > 100) percent = 100;
        if (barEl) barEl.style.width = percent + '%';

        if (tilesLoaded >= tilesToLoad) {
            setTimeout(() => {
                if (tilesLoaded >= tilesToLoad) {
                    if (indicatorEl) indicatorEl.style.display = 'none';
                    if (barEl) barEl.style.width = '0%';
                    tilesToLoad = 0;
                    tilesLoaded = 0;
                }
            }, 300);
        }
    };

    // Asignar eventos a todas las capas (incluyendo base)
    const monitoredLayers = [osm, satelite, ...Object.values(layers)];
    monitoredLayers.forEach(layer => {
        if (layer && layer instanceof L.TileLayer) {
            layer.on('tileloadstart', () => {
                if (tilesToLoad === 0) {
                    tilesLoaded = 0;
                    if (barEl) barEl.style.width = '0%';
                    if (indicatorEl) indicatorEl.style.display = 'block';
                }
                tilesToLoad++;
                updateProgressBar();
            });
            layer.on('tileload tileerror', () => {
                tilesLoaded++;
                updateProgressBar();
            });
            layer.on('load', () => {
                if (tilesLoaded < tilesToLoad) {
                    tilesLoaded = tilesToLoad;
                    updateProgressBar();
                }
            });
        }
    });

    // Configurar slider si existe en el DOM
    const slider = document.getElementById('opacidad-catastro');
    if (slider) slider.addEventListener('input', function () { actualizarOpacidadCatastro(this.value); });

    // Configurar sliders genéricos si existen (data-layer="nombre_capa")
    document.querySelectorAll('input[type=range][data-layer]').forEach(sl =>
        sl.addEventListener('input', function () { setLayerOpacity(this.dataset.layer, this.value); }));

    // Capas iniciales (AÑADIR AL FINAL para que los eventos de carga funcionen)
    osm.addTo(map);
    layers.catastro.addTo(map);

    // --- CONTROL DE CAPAS ESTÁNDAR (DERECHA) ---
    var baseMaps = {
        "Mapa Base (OSM)": osm,
        "Satélite (Google)": satelite
    };

    var overlayMaps = {
        "Catastro": layers.catastro,
        "Catastro HQ": layers.catastro_hq,
        "IGN Base": layers.ign_base,
        "PNOA (Ortofoto)": layers.pnoa,
        "Red Natura 2000": layers.natura,
        "Vías Pecuarias": layers.vias,
        "Montes Públicos": layers.montes,
        "Caminos Naturales": layers.caminos
    };

    layerControl = L.control.layers(baseMaps, overlayMaps).addTo(map);

    // Evento para carga lazy de capas dinámicas desde el control
    map.on('overlayadd', function(e) {
        if (e.layer && e.layer.options && e.layer.options.isDynamicLayer && !e.layer.hasLoadedData) {
            cargarDatosCapaDinamica(e.layer, e.layer.options.fileName);
        }
    });

    // Cargar capas dinámicas desde el servidor
    cargarCapasDinamicas();
}

// Función auxiliar para cargar capas locales con fallback a WMS
function createLocalLayer(layerName, color, wmsConfig) {
    var group = L.layerGroup();

    // Intentar cargar GeoJSON local
    fetch('/api/v1/capas/geojson/' + layerName)
        .then(r => {
            if (!r.ok) throw new Error(r.statusText);
            return r.json();
        })
        .then(data => {
            if (data.type && data.features && data.features.length > 0) {
                var geo = L.geoJSON(data, {
                    style: { color: color, weight: 2, opacity: 0.8, fillOpacity: 0.2 }
                });
                group.addLayer(geo);
            } else {
                throw new Error("GeoJSON vacío");
            }
        })
        .catch(e => {
            console.log('Capa local ' + layerName + ' no disponible. Usando WMS fallback.');
            if (wmsConfig) {
                var wms = L.tileLayer.wms(wmsConfig.url, {
                    layers: wmsConfig.layers,
                    format: 'image/png',
                    transparent: true,
                    opacity: 0.6
                });
                group.addLayer(wms);
            }
        });

    return group;
}

// --- FUNCIONES DE CAPAS ---
function toggleBaseLayer(type, checked) {
    if (type === 'osm') checked ? map.addLayer(osm) : map.removeLayer(osm);
    if (type === 'satelite') checked ? map.addLayer(satelite) : map.removeLayer(satelite);
}

function toggleLayer(name, checked) {
    if (layers[name]) checked ? map.addLayer(layers[name]) : map.removeLayer(layers[name]);
}

function actualizarOpacidadCatastro(valor) {
    var opacidad = valor / 100;
    if (map.hasLayer(layers.catastro)) layers.catastro.setOpacity(opacidad);
    if (map.hasLayer(layers.catastro_hq)) layers.catastro_hq.setOpacity(opacidad);
}

function setLayerOpacity(layerName, valor) {
    if (layers[layerName]) {
        layers[layerName].setOpacity(valor / 100);
    }
}

// --- FUNCIONES PRINCIPALES ---
function centrarMapa() {
    if (loadedLayer.getLayers().length > 0) map.fitBounds(loadedLayer.getBounds());
    else alert("No hay geometría cargada.");
}

function limpiarMapa() {
    measureMode = null;
    measurePoints = [];
    measureLayer.clearLayers();
    loadedLayer.clearLayers();
    map.getContainer().style.cursor = '';
    if (document.getElementById('ref-input')) document.getElementById('ref-input').value = '';
    if (document.getElementById('medicion-resultado')) document.getElementById('medicion-resultado').innerHTML = '';
    updateCadButtons();
}

async function cargarReferencia() {
    var ref = document.getElementById('ref-input').value.trim().toUpperCase();
    if (!ref) return alert("Introduce una referencia");

    const resultsEl = document.getElementById('ref-results-checklist');
    if (resultsEl) { resultsEl.style.display = 'block'; resultsEl.innerHTML = 'Cargando...'; }

    try {
        var res = await fetch(`/api/v1/referencia/${ref}/geojson`);
        var data = await res.json();
        if (data.status === 'error') throw new Error(data.error);

        loadedLayer.clearLayers();
        var layer = L.geoJSON(data, { style: redStyle }).addTo(loadedLayer);
        map.fitBounds(layer.getBounds());

        if (resultsEl) resultsEl.innerHTML = '✅ Geometría cargada.';

        // Procesar completo (segundo paso)
        fetch('/api/v1/procesar-completo', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ referencia: ref })
        }).then(r => r.json()).then(d => {
            if (d.status === 'success' && resultsEl) {
                resultsEl.innerHTML += `<br>📦 <a href="${d.zip_path}" download>Descargar ZIP</a>`;
            }
        });

    } catch (e) {
        if (resultsEl) resultsEl.innerHTML = `<span style="color:red;">Error: ${e.message}</span>`;
        else alert(e.message);
    }
}

async function buscarMunicipio() {
    const query = document.getElementById('municipio-input').value.trim();
    const resDiv = document.getElementById('municipio-resultados');
    if (!resDiv) return;

    resDiv.innerHTML = 'Buscando...';
    try {
        const res = await fetch(`/api/v1/buscar-municipio?q=${encodeURIComponent(query)}`);
        const data = await res.json();
        if (data.municipios && data.municipios.length > 0) {
            let html = '';
            data.municipios.forEach(m => {
                html += `<div style="padding:5px; border-block-end:1px solid #eee; cursor:pointer;" onclick="window.open('${m.url}', '_blank')"><b>${m.nombre}</b> (${m.codigo}) ⬇️</div>`;
            });
            resDiv.innerHTML = html;
        } else {
            resDiv.innerHTML = 'No encontrado.';
        }
    } catch (e) { resDiv.innerHTML = 'Error.'; }
}

async function analizarUrbanismo() {
    const fileInput = document.getElementById('file-urbanismo');
    const refInput = document.getElementById('ref-input');
    const resEl = document.getElementById('urbanismo-resultados');

    if (fileInput && fileInput.files.length > 0) handleFileUpload(fileInput);

    if (resEl) {
        resEl.style.display = 'block';
        resEl.innerHTML = '⏳ Analizando...';
    }

    try {
        const ref = refInput ? refInput.value : "Archivo";
        const res = await fetch('/api/v1/analizar-urbanismo', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ referencia: ref || "Archivo" })
        });
        const data = await res.json();
        if (data.status === 'success' && resEl) {
            const u = data.data.analisis_urbanistico;
            resEl.innerHTML = `<div style="background:#e8f5e9; padding:10px; border-radius:4px; color:#333;"><b>Suelo:</b> ${u.suelo}<br><b>Edificabilidad:</b> ${u.edificabilidad}</div>`;
        }
    } catch (e) { if (resEl) resEl.innerHTML = 'Error.'; }
}

async function analizarAfecciones() {
    const fileInput = document.getElementById('file-afecciones');
    const refInput = document.getElementById('ref-input');
    const resEl = document.getElementById('analisis-resultados');

    if (fileInput && fileInput.files.length > 0) handleFileUpload(fileInput);

    if (resEl) {
        resEl.style.display = 'block';
        resEl.innerHTML = '⏳ Analizando...';
    }

    try {
        const ref = refInput ? refInput.value : "Archivo";
        const res = await fetch('/api/v1/analizar-afecciones', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ referencia: ref || "Archivo" })
        });
        const data = await res.json();
        if (data.status === 'success' && resEl) {
            let html = '';
            data.data.afecciones.forEach(a => html += `<div style="background:#ffebee; padding:5px; margin-block-start:5px; border-radius:4px; color:#333;">⚠️ <b>${a.tipo}</b>: ${a.afectacion}</div>`);
            resEl.innerHTML = html;
        }
    } catch (e) { if (resEl) resEl.innerHTML = 'Error.'; }
}

// --- HERRAMIENTAS ---
function activarMedicion(modo) {
    measureMode = modo;
    measurePoints = [];
    measureLayer.clearLayers();
    map.getContainer().style.cursor = 'crosshair';
    const disp = document.getElementById('medicion-resultado');
    if (disp) { disp.style.display = 'flex'; disp.innerHTML = modo.toUpperCase(); }
    updateCadButtons();
}

function updateCadButtons() {
    document.querySelectorAll('.tool-btn, .cad-btn').forEach(b => b.classList.remove('active'));
    // Lógica simple para resaltar botón activo si existe
}

function onMapClick(e) {
    if (!measureMode) {
        // Si no estamos midiendo, intentar obtener información de la capa (Metadatos WMS)
        identificarMetadatos(e.latlng);
        return;
    }

    measurePoints.push(e.latlng);
    L.circleMarker(e.latlng, { radius: 5, color: 'blue' }).addTo(measureLayer);

    if (measureMode === 'distancia' && measurePoints.length > 1) {
        L.polyline(measurePoints, { color: 'blue' }).addTo(measureLayer);
        var dist = 0;
        for (var i = 0; i < measurePoints.length - 1; i++) dist += measurePoints[i].distanceTo(measurePoints[i + 1]);
        const disp = document.getElementById('medicion-resultado');
        if (disp) disp.innerHTML = `DIST: ${dist.toFixed(1)}m`;
    } else if (measureMode === 'area' && measurePoints.length > 2) {
        measureLayer.eachLayer(l => { if (l instanceof L.Polygon) measureLayer.removeLayer(l); });
        L.polygon(measurePoints, { color: 'blue', fillOpacity: 0.3 }).addTo(measureLayer);
        const disp = document.getElementById('medicion-resultado');
        if (disp) disp.innerHTML = `ÁREA (aprox): Puntos ${measurePoints.length}`;
    }
}

function identificarMetadatos(latlng) {
    // Consultar FeatureInfo de Catastro a través del proxy
    const catastroLayer = layers.catastro;
    
    if (catastroLayer) {
        const url = getWMSGetFeatureInfoUrl(catastroLayer, latlng);
        if (url) {
            // Mostrar popup de carga
            const popup = L.popup()
                .setLatLng(latlng)
                .setContent('<div style="text-align:center; padding:10px;"><i class="fa-solid fa-spinner fa-spin"></i> Consultando Catastro...</div>')
                .openOn(map);

            // Usar el proxy para evitar CORS
            fetch(`/api/v1/proxy?url=${encodeURIComponent(url)}`)
                .then(r => r.text())
                .then(html => {
                    // Insertar HTML de Catastro en un contenedor con scroll
                    popup.setContent(`<div style="max-inline-size:400px; max-block-size:300px; overflow:auto; font-size:12px;">${html}</div>`);
                })
                .catch(e => {
                    console.error("Error GetFeatureInfo:", e);
                    popup.setContent('<div style="color:red; padding:10px;">Error obteniendo información.</div>');
                });
        }
    }
}

function getWMSGetFeatureInfoUrl(layer, latlng) {
    const point = map.latLngToContainerPoint(latlng, map.getZoom());
    const size = map.getSize();

    const params = {
        request: 'GetFeatureInfo',
        service: 'WMS',
        srs: 'EPSG:4326',
        styles: '',
        transparent: true,
        version: layer.wmsParams.version,
        format: layer.wmsParams.format,
        bbox: map.getBounds().toBBoxString(),
        block-size: size.y,
        inline-size: size.x,
        layers: layer.wmsParams.layers,
        query_layers: layer.wmsParams.layers,
        info_format: 'text/html'
    };

    params[params.version === '1.3.0' ? 'i' : 'x'] = Math.round(point.x);
    params[params.version === '1.3.0' ? 'j' : 'y'] = Math.round(point.y);

    return layer._url + L.Util.getParamString(params, layer._url, true);
}

function handleFileUpload(input) {
    var files = input.files;
    if (!files || files.length === 0) return;
    for (var i = 0; i < files.length; i++) {
        var reader = new FileReader();
        reader.onload = function (e) {
            try {
                var content = e.target.result;
                if (input.value.toLowerCase().endsWith('.kml')) {
                    omnivore.kml.parse(content).setStyle(redStyle).addTo(loadedLayer);
                } else if (input.value.toLowerCase().endsWith('.gml')) {
                    var geojson = parseGML(content);
                    if (geojson) L.geoJSON(geojson, { style: redStyle }).addTo(loadedLayer);
                } else {
                    L.geoJSON(JSON.parse(content), { style: redStyle }).addTo(loadedLayer);
                }
                setTimeout(() => { if (loadedLayer.getLayers().length > 0) map.fitBounds(loadedLayer.getBounds()); }, 500);
            } catch (err) { console.error(err); }
        };
        reader.readAsText(files[i]);
    }
}

// --- PDF (REAL) ---
function mostrarDialogoPDF() {
    document.getElementById('pdfDialog').style.display = 'flex';
    cargarContenidosDisponibles();
}

function cerrarDialogoPDF() {
    document.getElementById('pdfDialog').style.display = 'none';
}

async function cargarContenidosDisponibles() {
    const contenedor = document.getElementById('contenidos-disponibles');
    if (!contenedor) return;

    contenedor.innerHTML = '<div style="text-align: center; color: #666; padding: 20px;"><i class="fa-solid fa-spinner fa-spin"></i> Cargando contenidos disponibles...</div>';

    try {
        const refInput = document.getElementById('ref-input');
        const ref = refInput ? refInput.value.trim().toUpperCase() : "";

        if (!ref) {
            contenedor.innerHTML = '<div style="text-align: center; color: #e74c3c; padding: 20px;">Introduce una referencia catastral primero</div>';
            return;
        }

        // Obtener resultados del proceso completo
        const res = await fetch('/api/v1/procesar-completo', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ referencia: ref })
        });

        if (!res.ok) throw new Error('Error obteniendo datos');

        const processData = await res.json();
        datosProceso = processData.resultados || {};

        // Generar lista de contenidos con checkboxes
        let html = '<div style="display: grid; gap: 10px;">';
        const items = [
            { k: 'datos_descriptivos', l: 'Datos Descriptivos (XML)', icon: '📝' },
            { k: 'coordenadas', l: 'Coordenadas Geográficas', icon: '📍' },
            { k: 'parcela_gml', l: 'Geometría Parcela (GML)', icon: '📐' },
            { k: 'edificio_gml', l: 'Geometría Edificio (GML)', icon: '🏢' },
            { k: 'plano_catastro', l: 'Plano Catastral (PNG)', icon: '🗺️' },
            { k: 'ortofoto_pnoa', l: 'Ortofoto PNOA (Zoom)', icon: '📸' },
            { k: 'composicion', l: 'Composición Plano+Orto', icon: '🖼️' },
            { k: 'ortofoto_provincial', l: 'Ortofoto Provincial', icon: '🌍' },
            { k: 'ortofoto_autonomico', l: 'Ortofoto Autonómica', icon: '🌍' },
            { k: 'ortofoto_nacional', l: 'Ortofoto Nacional', icon: '🇪🇸' },
            { k: 'pdf_oficial', l: 'Ficha Catastral Oficial', icon: '📋' },
            { k: 'kml', l: 'Archivo Google Earth (KML)', icon: '🌏' },
            { k: 'capas_afecciones', l: 'Mapas de Afecciones', icon: '⚠️' },
            { k: 'informe_pdf', l: 'Informe Técnico PDF', icon: '📊' },
            { k: 'contorno_superpuesto', l: 'Contornos Superpuestos', icon: '✏️' }
        ];

        items.forEach(item => {
            const disponible = item.k === 'datos_descriptivos' ? true : datosProceso[item.k];
            const checked = disponible ? 'checked' : '';
            const disabled = disponible ? '' : 'disabled style="opacity: 0.5;"';

            html += `
                <div style="display: flex; align-items: center; padding: 8px; border-radius: 6px; ${disponible ? 'background: #f8f9fa;' : 'background: #e9ecef;'}">
                    <input type="checkbox" id="pdf-${item.k}" value="${item.k}" ${checked} ${disabled} style="margin-inline-end: 10px;">
                    <span style="flex: 1; color: #333;">
                        <span style="margin-inline-end: 8px;">${item.icon}</span>
                        <strong>${item.l}</strong>
                        ${disponible ? '<span style="color: #28a745; margin-inline-start: 8px;">✅</span>' : '<span style="color: #dc3545; margin-inline-start: 8px;">❌</span>'}
                    </span>
                </div>
            `;
        });
        contenedor.innerHTML = html + '</div>';

    } catch (e) {
        contenedor.innerHTML = `<div style="text-align: center; color: #dc3545; padding: 20px;">❌ Error: ${e.message}</div>`;
    }
}

async function generarPDFSeleccionado() {
    const refInput = document.getElementById('ref-input');
    const ref = refInput ? refInput.value.trim() : "";
    const empresa = document.getElementById('empresa-nombre') ? document.getElementById('empresa-nombre').value.trim() : "";
    const colegiado = document.getElementById('colegiado-numero') ? document.getElementById('colegiado-numero').value.trim() : "";

    if (!ref) { alert('Introduce una referencia catastral primero'); return; }

    const contenidosSeleccionados = [];
    const items = ['datos_descriptivos', 'coordenadas', 'parcela_gml', 'edificio_gml', 'plano_catastro', 'ortofoto_pnoa', 'composicion', 'ortofoto_provincial', 'ortofoto_autonomico', 'ortofoto_nacional', 'pdf_oficial', 'kml', 'capas_afecciones', 'informe_pdf', 'contorno_superpuesto'];

    items.forEach(item => {
        const el = document.getElementById(`pdf-${item}`);
        if (el && el.checked) contenidosSeleccionados.push(item);
    });

    try {
        const res = await fetch('/api/v1/generar-pdf', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ referencia: ref, contenidos: contenidosSeleccionados, empresa: empresa, colegiado: colegiado })
        });

        if (res.ok) {
            const data = await res.json();
            if (data.status === 'error') throw new Error(data.error);

            const a = document.createElement('a');
            a.href = data.url;
            a.download = `informe_${ref}.pdf`;
            document.body.appendChild(a);
            a.click();
            document.body.removeChild(a);
            cerrarDialogoPDF();
        } else {
            throw new Error('Error generando PDF');
        }
    } catch (e) {
        alert(`Error: ${e.message}`);
    }
}

// --- CARGA DINÁMICA DE CAPAS ---
var dynamicLayers = {};

function cargarCapasDinamicas() {
    const container = document.getElementById('dynamic-layers-container');
    if (container) container.innerHTML = '<div style="font-size:0.8rem; color:#666;">Cargando...</div>';

    fetch('/api/v1/capas/list')
        .then(r => r.json())
        .then(data => {
            if (container) container.innerHTML = '';
            
            if (data.status === 'success' && data.files.length > 0) {
                data.files.forEach(file => {
                    // Crear grupo vacío para Lazy Load
                    var group = L.featureGroup();
                    group.options.isDynamicLayer = true;
                    group.options.fileName = file.name;
                    group.hasLoadedData = false;
                    
                    // Icono según tipo
                    let iconChar = '📄';
                    if (file.type.includes('shp')) iconChar = '🗺️';
                    if (file.type.includes('kml')) iconChar = '🌏';
                    if (file.type.includes('gpkg')) iconChar = '📦';
                    if (file.type.includes('fgb')) iconChar = '🚀';

                    var label = `${iconChar} ${file.name}`;
                    
                    // 1. Añadir al control de capas estándar (Leaflet)
                    if (layerControl) {
                        layerControl.addOverlay(group, label);
                    }
                    
                    // 2. Añadir al panel lateral (HTML)
                    if (container) {
                        const div = document.createElement('div');
                        div.className = 'layer-item';
                        // Usamos un closure o atributo para el nombre
                        div.innerHTML = `
                            <label style="display:flex; align-items:center; cursor:pointer; inline-size:100%;">
                                <input type="checkbox" onchange="toggleDynamicLayer('${file.name}', this.checked)" style="margin-inline-end:8px;">
                                <span style="margin-inline-end:5px;">${iconChar}</span>
                                <span style="font-size:0.9rem; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;" title="${file.name}">${file.name}</span>
                            </label>
                        `;
                        container.appendChild(div);
                    }

                    // Guardar referencia global
                    dynamicLayers[file.name] = group;
                });
            } else {
                if (container) container.innerHTML = '<div style="font-size:0.8rem; color:#999; padding:5px;">No se encontraron capas locales.</div>';
            }
        })
        .catch(e => {
            console.error(e);
            if (container) container.innerHTML = '<div style="color:red; font-size:0.8rem;">Error cargando capas.</div>';
        });
}

function cargarDatosCapaDinamica(layerGroup, layerName) {
    if (layerGroup.isLoading) return;
    layerGroup.isLoading = true;

    // Mostrar feedback visual simple
    const originalCursor = map.getContainer().style.cursor;
    map.getContainer().style.cursor = 'wait';

    // Indicador en el panel lateral si existe
    const checkbox = document.querySelector(`input[onchange="toggleDynamicLayer('${layerName}', this.checked)"]`);
    const labelSpan = checkbox ? checkbox.parentElement.querySelector('span:last-child') : null;
    const originalText = labelSpan ? labelSpan.innerText : layerName;
    if (labelSpan) labelSpan.innerText = `${originalText} (Cargando...)`;

    fetch('/api/v1/capas/geojson/' + encodeURIComponent(layerName))
        .then(r => r.json())
        .then(data => {
            layerGroup.isLoading = false;
            map.getContainer().style.cursor = originalCursor;
            if (labelSpan) labelSpan.innerText = originalText;

            if (data.type && data.features && data.features.length > 0) {
                // Generar color aleatorio consistente
                let hash = 0;
                for (let i = 0; i < layerName.length; i++) {
                    hash = layerName.charCodeAt(i) + ((hash << 5) - hash);
                }
                const color = '#' + ((hash & 0x00FFFFFF).toString(16)).padStart(6, '0');
                
                var geo = L.geoJSON(data, {
                    style: { color: color, weight: 2, opacity: 1, fillOpacity: 0.2 },
                    onEachFeature: function(feature, layer) {
                        if (feature.properties) {
                            let popupContent = '<div style="max-block-size:200px;overflow:auto;font-family:sans-serif;font-size:12px;">';
                            popupContent += '<h4 style="margin:0 0 5px 0;border-block-end:1px solid #ccc;">' + layerName + '</h4><table>';
                            for (let k in feature.properties) {
                                popupContent += `<tr><td style="font-weight:bold;padding-inline-end:5px;">${k}:</td><td>${feature.properties[k]}</td></tr>`;
                            }
                            popupContent += '</table></div>';
                            layer.bindPopup(popupContent);
                        }
                    }
                });
                
                layerGroup.addLayer(geo);
                layerGroup.hasLoadedData = true;
                
                // Zoom a la capa solo la primera vez
                try {
                    map.fitBounds(geo.getBounds());
                } catch(e) {}
            } else {
                alert('La capa ' + layerName + ' está vacía o no es válida.');
                map.removeLayer(layerGroup); // Desmarcar del mapa
                if (checkbox) checkbox.checked = false; // Desmarcar checkbox
            }
        })
        .catch(e => {
            console.error(e);
            layerGroup.isLoading = false;
            map.getContainer().style.cursor = originalCursor;
            if (labelSpan) labelSpan.innerText = originalText;
            alert('Error cargando capa ' + layerName);
            map.removeLayer(layerGroup);
            if (checkbox) checkbox.checked = false;
        });
}

// Función restaurada para el panel lateral
function toggleDynamicLayer(name, checked) {
    var group = dynamicLayers[name];
    if (!group) return;

    if (checked) {
        map.addLayer(group);
        if (!group.hasLoadedData && !group.isLoading) {
             cargarDatosCapaDinamica(group, name);
        }
    } else {
        map.removeLayer(group);
    }
}

// --- CAMBIO DE TEMA DINÁMICO ---
const AVAILABLE_THEMES = [
    { name: 'Estándar', url: '/static/index2.html', icon: 'fa-desktop' },
    { name: 'Dark Pro', url: '/static/index_modern_dark.html', icon: 'fa-moon' },
    { name: 'Corporate', url: '/static/index_top_nav.html', icon: 'fa-building' },
    { name: 'Split View', url: '/static/index_split_right.html', icon: 'fa-columns' }
];

function injectThemeSwitcher() {
    if (document.getElementById('theme-switcher')) return;

    const switcher = document.createElement('div');
    switcher.id = 'theme-switcher';
    switcher.style.cssText = 'position:fixed; inset-block-end:20px; inset-inline-start:20px; z-index:9999; font-family:sans-serif;';

    const btn = document.createElement('button');
    btn.innerHTML = '<i class="fa-solid fa-palette"></i>';
    btn.title = "Cambiar Tema";
    btn.style.cssText = 'inline-size:40px; block-size:40px; border-radius:50%; border:none; background:#2c3e50; color:white; cursor:pointer; box-shadow:0 2px 5px rgba(0,0,0,0.3); font-size:16px; transition:transform 0.2s;';
    btn.onmouseover = () => btn.style.transform = 'scale(1.1)';
    btn.onmouseout = () => btn.style.transform = 'scale(1)';
    btn.onclick = () => {
        const menu = document.getElementById('theme-menu');
        menu.style.display = menu.style.display === 'none' ? 'block' : 'none';
    };

    const menu = document.createElement('div');
    menu.id = 'theme-menu';
    menu.style.cssText = 'display:none; position:absolute; inset-block-end:50px; inset-inline-start:0; background:white; padding:5px; border-radius:8px; box-shadow:0 4px 15px rgba(0,0,0,0.2); inline-size:160px; overflow:hidden;';

    AVAILABLE_THEMES.forEach(theme => {
        const item = document.createElement('div');
        item.style.cssText = 'padding:10px; cursor:pointer; border-block-end:1px solid #eee; font-size:13px; color:#333; display:flex; align-items:center; gap:10px; transition:background 0.2s;';
        item.innerHTML = `<i class="fa-solid ${theme.icon}" style="inline-size:15px; text-align:center;"></i> ${theme.name}`;
        item.onclick = () => loadTheme(theme.url);
        item.onmouseover = () => item.style.background = '#f8f9fa';
        item.onmouseout = () => item.style.background = 'white';
        menu.appendChild(item);
    });

    if (menu.lastChild) menu.lastChild.style.borderBottom = 'none';
    switcher.appendChild(menu);
    switcher.appendChild(btn);
    document.body.appendChild(switcher);
}

async function loadTheme(url) {
    try {
        localStorage.setItem('visor_theme', url);
        if (typeof map !== 'undefined' && map) {
            localStorage.setItem('visor_map_center', JSON.stringify(map.getCenter()));
            localStorage.setItem('visor_map_zoom', map.getZoom());
        }

        if (url.includes('index2.html')) {
            window.location.href = url;
            return;
        }

        document.body.style.transition = 'opacity 0.3s ease';
        document.body.style.opacity = '0';
        await new Promise(r => setTimeout(r, 300));

        let state = {};
        if (typeof map !== 'undefined' && map) {
            state.center = map.getCenter();
            state.zoom = map.getZoom();
            state.geoJson = loadedLayer ? loadedLayer.toGeoJSON() : null;
        }

        const res = await fetch(url);
        const text = await res.text();
        const parser = new DOMParser();
        const doc = parser.parseFromString(text, 'text/html');

        document.querySelectorAll('style').forEach(el => el.remove());
        doc.querySelectorAll('style').forEach(newStyle => document.head.appendChild(newStyle));
        document.body.innerHTML = doc.body.innerHTML;

        setTimeout(() => {
            initVisor();
            if (map && state.center) {
                map.setView(state.center, state.zoom);
                if (state.geoJson && state.geoJson.features.length > 0) {
                    L.geoJSON(state.geoJson, { style: redStyle }).addTo(loadedLayer);
                    try { map.fitBounds(loadedLayer.getBounds()); } catch (e) { }
                }
            }
            document.body.style.transition = 'opacity 0.3s ease';
            document.body.style.opacity = '1';
        }, 50);
    } catch (e) {
        console.error("Error cambiando tema:", e);
        document.body.style.opacity = '1';
    }
}

// --- LEYENDA ---
function injectLegendModal() {
    if (document.getElementById('leyendaDialog')) return;

    const modal = document.createElement('div');
    modal.id = 'leyendaDialog';
    modal.style.cssText = 'display: none; position: fixed; inset-block-start: 0; inset-inline-start: 0; inline-size: 100%; block-size: 100%; background: rgba(0,0,0,0.5); z-index: 10000; justify-content: center; align-items: center;';

    modal.innerHTML = `
        <div style="background: white; border-radius: 12px; padding: 20px; max-inline-size: 400px; inline-size: 90%; max-block-size: 80vh; overflow-y: auto; box-shadow: 0 10px 30px rgba(0,0,0,0.3);">
            <div style="display: flex; justify-content: space-between; align-items: center; margin-block-end: 15px; border-block-end: 1px solid #eee; padding-block-end: 10px;">
                <h3 style="margin: 0; color: #2c3e50;">Leyenda</h3>
                <button onclick="document.getElementById('leyendaDialog').style.display='none'" style="background: none; border: none; font-size: 1.5rem; cursor: pointer; color: #666;">&times;</button>
            </div>
            <div id="leyenda-img-container" style="text-align: center;"></div>
        </div>
    `;

    document.body.appendChild(modal);
}

window.mostrarLeyenda = function (capa) {
    const container = document.getElementById('leyenda-img-container');
    const dialog = document.getElementById('leyendaDialog');

    let url = '';
    
    // Leyendas para diferentes capas
    switch(capa) {
        case 'catastro':
            url = 'https://ovc.catastro.meh.es/Cartografia/WMS/ServidorWMS.aspx?request=GetLegendGraphic&version=1.1.1&format=image/png&layer=Catastro';
            break;
        case 'red_natura':
            url = 'https://wms.mapama.gob.es/sig/Biodiversidad/RedNatura/wms.aspx?request=GetLegendGraphic&version=1.1.1&format=image/png&layer=PS.ProtectedSite';
            break;
        case 'vias_pecuarias':
            url = 'https://wms.mapama.gob.es/sig/Biodiversidad/ViasPecuarias?request=GetLegendGraphic&version=1.1.1&format=image/png&layer=Red General de Vías Pecuarias';
            break;
        case 'ign_base':
            url = 'https://www.ign.es/wms-inspire/ign-base?request=GetLegendGraphic&version=1.3.0&format=image/png&layer=IGNBaseTodo';
            break;
        case 'pnoa':
            url = 'https://www.ign.es/wms-inspire/pnoa-ma?request=GetLegendGraphic&version=1.3.0&format=image/png&layer=OI.OrthoimageCoverage';
            break;
        case 'siose':
            url = 'https://servicios.idee.es/wms-inspire/ocupacion-suelo?request=GetLegendGraphic&version=1.3.0&format=image/png&layer=LU.ExistingLandUse';
            break;
        case 'calificacion':
            url = 'https://servicios.idee.es/wms-inspire/uso-suelo?request=GetLegendGraphic&version=1.3.0&format=image/png&layer=EL.LandUse';
            break;
        default:
            // Para capas locales o sin leyenda WMS
            if (container && dialog) {
                container.innerHTML = `
                    <div style="text-align: center; padding: 20px;">
                        <h4 style="color: #666; margin-block-end: 10px;">📋 Leyenda no disponible</h4>
                        <p style="color: #999; font-size: 14px;">La capa "${capa}" no tiene leyenda configurada o es una capa local.</p>
                    </div>
                `;
                dialog.style.display = 'flex';
                return;
            }
    }

    if (url && container && dialog) {
        container.innerHTML = `
            <div style="text-align: center;">
                <h4 style="color: #2c3e50; margin-block-end: 10px;">📋 Leyenda: ${capa.charAt(0).toUpperCase() + capa.slice(1).replace('_', ' ')}</h4>
                <img src="${url}" alt="Leyenda de ${capa}" style="max-inline-size:100%; border: 1px solid #ddd; border-radius: 4px;" 
                     onerror="this.onerror=null; this.parentElement.innerHTML='<p style=color:#e74c3c;>❌ Error cargando la leyenda</p>'">
                <p style="color: #666; font-size: 12px; margin-block-start: 8px;">Fuente: Servicio WMS oficial</p>
            </div>
        `;
        dialog.style.display = 'flex';
    }
};

// --- NUEVAS FUNCIONES IMPORTADAS DEL CÓDIGO REACT ---

function parseGML(gmlString) {
    try {
        const parser = new DOMParser();
        const gml = parser.parseFromString(gmlString, 'text/xml');
        const posList = gml.querySelector('posList') || gml.querySelector('coordinates');

        if (posList) {
            const coordText = posList.textContent.trim();
            // Normalizar separadores (comas por espacios si es necesario)
            const numbers = coordText.replace(/,/g, ' ').split(/\s+/).map(Number);
            const coords = [];

            for (let i = 0; i < numbers.length; i += 2) {
                // Leaflet usa [lat, lng], GeoJSON usa [lng, lat]
                // Asumimos orden estándar GML [x, y] -> [lng, lat]
                coords.push([numbers[i], numbers[i + 1]]);
            }

            return {
                type: 'FeatureCollection',
                features: [{
                    type: 'Feature',
                    properties: {
                        refCatastral: gml.querySelector('localId')?.textContent || 'Desconocida'
                    },
                    geometry: {
                        type: 'Polygon',
                        coordinates: [coords]
                    }
                }]
            };
        }
    } catch (e) {
        console.error("Error parseando GML:", e);
    }
    return null;
}

function injectExportButton() {
    if (document.getElementById('btn-export-html')) return;
    const btn = document.createElement('button');
    btn.id = 'btn-export-html';
    btn.innerHTML = '<i class="fa-solid fa-file-code"></i>';
    btn.title = "Exportar Informe HTML Rápido";
    btn.style.cssText = 'position:fixed; inset-block-start:140px; inset-inline-end:10px; z-index:1000; inline-size:34px; block-size:34px; background:white; border-radius:4px; border:2px solid rgba(0,0,0,0.2); cursor:pointer; display:flex; align-items:center; justify-content:center; color:#333;';
    btn.onmouseover = () => btn.style.background = '#f4f4f4';
    btn.onmouseout = () => btn.style.background = 'white';
    btn.onclick = generarInformeHTML;
    document.body.appendChild(btn);
}

async function generarInformeHTML() {
    const ref = document.getElementById('ref-input') ? document.getElementById('ref-input').value : 'N/A';
    const fecha = new Date().toLocaleDateString('es-ES');
    const coords = map.getCenter();

    // Intentar capturar mapa (simple)
    let mapImage = null;
    try {
        // Método simplificado para capturar tiles visibles (puede fallar por CORS si no está configurado)
        const mapContainer = map.getContainer();
        const canvas = document.createElement('canvas');
        canvas.width = mapContainer.offsetWidth;
        canvas.height = mapContainer.offsetHeight;
        const ctx = canvas.getContext('2d');

        const tiles = mapContainer.querySelectorAll('.leaflet-tile-pane img');
        tiles.forEach(img => {
            try {
                const rect = img.getBoundingClientRect();
                const containerRect = mapContainer.getBoundingClientRect();
                ctx.drawImage(img, rect.left - containerRect.left, rect.top - containerRect.top, rect.width, rect.height);
            } catch (e) { }
        });
        mapImage = canvas.toDataURL('image/png');
    } catch (e) { console.warn("No se pudo capturar imagen del mapa"); }

    const html = `
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <title>Informe Urbanístico Rápido</title>
    <style>
        body { font-family: Arial, sans-serif; margin: 40px; line-height: 1.6; color: #333; }
        h1 { color: #2563eb; border-block-end: 3px solid #2563eb; padding-block-end: 10px; }
        .info-grid { display: grid; grid-template-columns: 200px 1fr; gap: 10px; margin: 20px 0; background: #f8f9fa; padding: 20px; border-radius: 8px; }
        .info-label { font-weight: bold; color: #4b5563; }
        .map-image { max-inline-size: 100%; border: 2px solid #e5e7eb; margin: 20px 0; border-radius: 8px; }
        .footer { margin-block-start: 50px; padding-block-start: 20px; border-block-start: 1px solid #e5e7eb; color: #6b7280; font-size: 12px; }
    </style>
</head>
<body>
    <h1>INFORME DE ANÁLISIS URBANÍSTICO</h1>
    
    <div class="info-grid">
        <div class="info-label">Fecha:</div><div>${fecha}</div>
        <div class="info-label">Referencia:</div><div>${ref}</div>
        <div class="info-label">Coordenadas:</div><div>${coords.lat.toFixed(5)}, ${coords.lng.toFixed(5)}</div>
        <div class="info-label">Zoom:</div><div>${map.getZoom()}</div>
    </div>

    <h2>Vista del Mapa</h2>
    ${mapImage ? `<img src="${mapImage}" class="map-image" alt="Mapa">` : '<p>Imagen de mapa no disponible</p>'}

    <div class="footer">
        <p>Informe generado automáticamente por Visor Catastral.</p>
    </div>
</body>
</html>`;

    const blob = new Blob([html], { type: 'text/html;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `informe_rapido_${ref || 'mapa'}.html`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
}

async function verLogsServidor() {
    const resDiv = document.getElementById('municipio-resultados');
    if (!resDiv) return;

    resDiv.innerHTML = '<div style="text-align:center; color:#666;"><i class="fa-solid fa-spinner fa-spin"></i> Cargando logs...</div>';

    try {
        const res = await fetch('/api/v1/logs');
        const data = await res.json();

        if (data.status === 'success' && data.logs) {
            let html = '<div style="background: #2c3e50; color: #ecf0f1; padding: 10px; border-radius: 4px; font-family: monospace; font-size: 0.75rem; max-block-size: 200px; overflow-y: auto;">';
            // Mostrar últimos primero
            [...data.logs].reverse().forEach(log => {
                html += `<div>${log}</div>`;
            });
            html += '</div>';
            resDiv.innerHTML = html;
        } else {
            resDiv.innerHTML = '<div style="color:#e74c3c;">No hay logs disponibles.</div>';
        }
    } catch (e) {
        resDiv.innerHTML = `<div style="color:#e74c3c;">Error obteniendo logs: ${e.message}</div>`;
    }
}

// --- FUNCIONES DE MEZCLA DE CAPAS ---
window.mezclaActivada = false;

function toggleMezclaCapas(activar) {
    window.mezclaActivada = activar;
    actualizarMezclaCapas();
}

function actualizarMezclaCapas() {
    if (!map) return;

    if (!window.mezclaActivada) {
        if (map.hasLayer(layers.catastro_hq)) {
            map.removeLayer(layers.catastro_hq);
            if (!map.hasLayer(layers.catastro)) map.addLayer(layers.catastro);
        }
        return;
    }

    // Lógica simplificada: si mezcla activada, forzar HQ si está disponible
    if (map.hasLayer(layers.catastro)) {
        map.removeLayer(layers.catastro);
        map.addLayer(layers.catastro_hq);
    }
}

// Inicialización
document.addEventListener('DOMContentLoaded', () => {
    const savedTheme = localStorage.getItem('visor_theme');
    if (savedTheme && !window.location.href.endsWith(savedTheme) && savedTheme !== '/static/index2.html') {
        loadTheme(savedTheme);
    } else {
        initVisor();
        document.body.style.opacity = '1';
    }
});

