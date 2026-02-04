/**
 * Lógica para index3.html (SaaS Tasación v2.0)
 * Maneja mapa, pestañas, mediciones y llamadas a API.
 */

// --- VARIABLES GLOBALES ---
let map;
let layers = {};
let drawLayer; // Capa para dibujos/mediciones
let activeMeasure = null; // 'dist', 'area' o null
let measurePoints = [];
let tempMeasureShape = null;
let currentLoteRefs = []; // Referencias del lote actual

// --- INICIALIZACIÓN ---
document.addEventListener('DOMContentLoaded', () => {
    initMap();
    setupDropzones();
});

function initMap() {
    // 1. Crear mapa
    map = L.map('map', {
        zoomControl: false // Movemos los controles manualmente si queremos, o usamos el default
    }).setView([40.4168, -3.7038], 6); // Centro España

    // 2. Capas Base
    const osm = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
        attribution: '© OpenStreetMap'
    }).addTo(map);

    const satelite = L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
        attribution: '© Esri'
    });

    // 3. Capas Superpuestas (WMS)
    layers.catastro = L.tileLayer.wms('http://ovc.catastro.meh.es/Cartografia/WMS/ServidorWMS.aspx', {
        layers: 'Catastro',
        format: 'image/png',
        transparent: true,
        opacity: 0.7
    }).addTo(map);

    layers.natura = L.tileLayer.wms('https://wms.mapama.gob.es/sig/Biodiversidad/RedNatura/wms.aspx', {
        layers: 'PS.ProtectedSite',
        format: 'image/png',
        transparent: true,
        opacity: 0.5
    }); // No añadir por defecto

    // Capa para dibujos
    drawLayer = L.featureGroup().addTo(map);

    // Control de capas básico (aunque tenemos checkboxes personalizados)
    L.control.layers({
        "Callejero": osm,
        "Satélite": satelite
    }, null, { position: 'bottomright' }).addTo(map);

    // Eventos de mapa
    map.on('click', handleMapClick);
    map.on('dblclick', finishMeasure);

    // Vincular checkboxes del panel derecho
    bindLayerToggle('chk-natura', layers.natura);
    // (Aquí se añadirían el resto de capas WMS reales si se tienen las URLs)
}

// --- GESTIÓN DE PESTAÑAS (TABS) ---
function switchTab(tabId) {
    // Identificar el grupo de tabs (catastro o urbanismo)
    const isCatastro = tabId.startsWith('cat-');
    const prefix = isCatastro ? 'cat-' : 'urb-';

    // Actualizar clases de botones
    const container = isCatastro ? document.getElementById('mod-catastro') : document.getElementById('mod-urbanismo');
    const tabs = container.querySelectorAll('.tab');
    tabs.forEach(t => t.classList.remove('active'));

    // Activar el clickeado (buscamos por texto o índice, simplificado aquí asumiendo orden)
    // En una implementación real, pasaríamos 'this' o usaríamos data-attributes.
    // Por simplicidad en el HTML actual:
    if (tabId.includes('ref')) tabs[0].classList.add('active');
    else tabs[1].classList.add('active');

    // Mostrar contenido
    document.getElementById(prefix + 'ref-content').style.display = tabId.includes('ref') ? 'block' : 'none';
    const fileContent = document.getElementById(prefix + (isCatastro ? 'lote-content' : 'file-content'));
    if (fileContent) fileContent.style.display = tabId.includes('ref') ? 'none' : 'block';
}

// --- FUNCIONES DE CATASTRO ---
async function procesarCatastro() {
    const ref = document.getElementById('input-ref').value.trim();
    const resBox = document.getElementById('res-catastro');

    if (!ref) {
        alert("Por favor, introduce una referencia catastral.");
        return;
    }

    resBox.style.display = 'block';
    resBox.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Consultando Sede Electrónica...';

    try {
        // Llamada a la API (simulada o real)
        const response = await fetch('/api/v1/analizar-referencia', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ referencia: ref })
        });

        const data = await response.json();

        if (data.success || response.ok) {
            resBox.innerHTML = `
                <div style="color:green"><i class="fa-solid fa-check"></i> Referencia localizada</div>
                <div style="margin-top:5px; font-weight:bold;">${ref}</div>
                <div style="font-size:0.8rem; color:#666;">Uso: Residencial | Año: 1985</div>
                <button class="outline" style="margin-top:8px; font-size:0.8rem" onclick="window.open('${data.zip_url || '#'}')">
                    <i class="fa-solid fa-file-zipper"></i> Descargar Documentación
                </button>
            `;
            // Intentar centrar mapa si vienen coordenadas
            if (data.geojson) {
                const layer = L.geoJSON(data.geojson).addTo(drawLayer);
                map.fitBounds(layer.getBounds());
            }
        } else {
            throw new Error(data.error || "Error en la consulta");
        }
    } catch (e) {
        console.error(e);
        // Fallback visual para demo si no hay backend
        resBox.innerHTML = `
            <div style="color:#e74c3c"><i class="fa-solid fa-circle-exclamation"></i> No se pudo conectar con API</div>
            <small>Mostrando datos simulados para demo:</small>
            <div style="margin-top:5px;"><strong>${ref}</strong></div>
            <button class="outline" style="margin-top:5px; font-size:0.8rem">Ver en Sede</button>
        `;
    }
}

// --- FUNCIONES DE URBANISMO ---
function analizarUrbanismo() {
    const ref = document.getElementById('input-urb-ref').value || document.getElementById('input-ref').value;
    if (!ref) return alert("Introduce una referencia en el módulo de Catastro o Urbanismo.");

    const resBox = document.getElementById('res-urbanismo');
    const spanClass = document.getElementById('urb-class');

    resBox.style.display = 'block';
    spanClass.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Analizando normativa...';

    setTimeout(() => {
        spanClass.innerHTML = `
            <span style="color:#2980b9; font-weight:bold;">SUELO URBANO CONSOLIDADO</span><br>
            Ordenanza: NZ-3 (Residencial Intensiva)<br>
            Altura Máx: B+3<br>
            <i class="fa-solid fa-triangle-exclamation" style="color:#f39c12"></i> Afección Arqueológica
        `;
        document.getElementById('btn-ficha-pdf').style.display = 'block';
    }, 1500);
}

// --- FUNCIONES DE AFECCIONES ---
function calcularAfecciones() {
    const resBox = document.getElementById('res-afecciones');
    resBox.style.display = 'block';
    resBox.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Cruzando capas espaciales...';

    setTimeout(() => {
        resBox.innerHTML = `
            <strong>2 Afecciones Detectadas:</strong>
            <ul style="margin:5px 0; padding-left:20px;">
                <li>Vía Pecuaria (Cañada Real) - 25m</li>
                <li>Zona de Policía de Cauces - 100m</li>
            </ul>
            <div style="color:green"><i class="fa-solid fa-check"></i> Fuera de Red Natura 2000</div>
        `;
    }, 2000);
}

// --- HERRAMIENTAS DE MAPA ---
function resetView() {
    if (drawLayer.getLayers().length > 0) {
        map.fitBounds(drawLayer.getBounds());
    } else {
        map.setView([40.4168, -3.7038], 6);
    }
}

function locateUser() {
    map.locate({ setView: true, maxZoom: 16 });
}

function toggleMeasure(type) {
    // Limpiar estado anterior
    clearMeasure(false); // false = no borrar capas, solo estado

    // Actualizar UI botones
    document.querySelectorAll('.map-tools button').forEach(b => b.classList.remove('active'));

    if (activeMeasure === type) {
        activeMeasure = null; // Desactivar si se pulsa el mismo
        return;
    }

    activeMeasure = type;
    // Marcar botón activo (buscamos por el onclick, un poco hacky pero funciona para este HTML)
    const btn = document.querySelector(`button[onclick="toggleMeasure('${type}')"]`);
    if (btn) btn.classList.add('active');

    map.getContainer().style.cursor = 'crosshair';
}

function clearMeasure(clearLayers = true) {
    activeMeasure = null;
    measurePoints = [];
    if (tempMeasureShape) {
        map.removeLayer(tempMeasureShape);
        tempMeasureShape = null;
    }
    if (clearLayers) {
        drawLayer.clearLayers();
    }
    map.getContainer().style.cursor = '';
    document.querySelectorAll('.map-tools button').forEach(b => b.classList.remove('active'));
}

function handleMapClick(e) {
    if (!activeMeasure) return;

    measurePoints.push(e.latlng);

    // Dibujar puntos
    L.circleMarker(e.latlng, { radius: 4, color: 'red' }).addTo(drawLayer);

    // Dibujar línea o polígono temporal
    if (measurePoints.length > 1) {
        if (tempMeasureShape) map.removeLayer(tempMeasureShape);

        if (activeMeasure === 'dist') {
            tempMeasureShape = L.polyline(measurePoints, { color: 'red' }).addTo(map);
            const dist = calculateDistance(measurePoints);
            tempMeasureShape.bindTooltip(`Distancia: ${dist.toFixed(2)} m`, { permanent: true }).openTooltip();
        } else if (activeMeasure === 'area') {
            tempMeasureShape = L.polygon(measurePoints, { color: 'red' }).addTo(map);
            if (measurePoints.length > 2) {
                const area = L.GeometryUtil.geodesicArea(measurePoints);
                tempMeasureShape.bindTooltip(`Área: ${(area / 10000).toFixed(4)} ha`, { permanent: true }).openTooltip();
            }
        }
    }
}

function finishMeasure() {
    if (!activeMeasure) return;
    if (tempMeasureShape) {
        tempMeasureShape.addTo(drawLayer); // Hacer permanente en la capa de dibujo
        tempMeasureShape = null;
    }
    measurePoints = []; // Resetear puntos para nueva medición del mismo tipo
}

function calculateDistance(latlngs) {
    let total = 0;
    for (let i = 0; i < latlngs.length - 1; i++) {
        total += latlngs[i].distanceTo(latlngs[i + 1]);
    }
    return total;
}

// --- UTILIDADES ---
function bindLayerToggle(id, layer) {
    const chk = document.getElementById(id);
    if (!chk) return;

    // Sincronizar estado inicial
    if (chk.checked && !map.hasLayer(layer)) {
        map.addLayer(layer);
    } else if (!chk.checked && map.hasLayer(layer)) {
        map.removeLayer(layer);
    }

    chk.addEventListener('change', (e) => {
        if (e.target.checked) {
            if (!map.hasLayer(layer)) map.addLayer(layer);
        } else {
            if (map.hasLayer(layer)) map.removeLayer(layer);
        }
    });
}

function setupDropzones() {
    const zones = [
        { id: 'drop-catastro', handler: handleCatastroFile, type: '.txt,.csv' },
        { id: 'drop-urbanismo', handler: (f) => alert('Simulado: ' + f.name), type: '.gml,.kml,.geojson' },
        { id: 'drop-afecciones', handler: (f) => alert('Simulado: ' + f.name), type: '.gml,.kml,.geojson' },
        { id: 'drop-geometria', handler: handleGeometryFile, type: '.gml,.kml,.geojson' }
    ];

    zones.forEach(zone => {
        const el = document.getElementById(zone.id);
        if (!el) return;

        el.addEventListener('click', () => {
            const input = document.createElement('input');
            input.type = 'file';
            input.accept = zone.type;
            input.onchange = e => zone.handler(e.target.files[0]);
            input.click();
        });

        el.addEventListener('dragover', (e) => {
            e.preventDefault();
            el.style.borderColor = '#3498db';
            el.style.background = '#f0f8ff';
        });

        el.addEventListener('dragleave', (e) => {
            e.preventDefault();
            el.style.borderColor = '#ccc';
            el.style.background = 'transparent';
        });

        el.addEventListener('drop', (e) => {
            e.preventDefault();
            el.style.borderColor = '#ccc';
            el.style.background = 'transparent';

            if (e.dataTransfer.files.length > 0) {
                zone.handler(e.dataTransfer.files[0]);
            }
        });
    });
}

/**
 * Maneja la carga de archivos de geometría (GML, KML, GeoJSON)
 */
function handleGeometryFile(file) {
    if (!file) return;

    const reader = new FileReader();
    const fileName = file.name.toLowerCase();

    reader.onload = (e) => {
        const content = e.target.result;

        if (fileName.endsWith('.kml')) {
            loadKml(content);
        } else if (fileName.endsWith('.geojson') || fileName.endsWith('.json')) {
            loadGeoJson(content);
        } else if (fileName.endsWith('.gml')) {
            loadGml(content);
        } else {
            alert("Formato no soportado. Use GML, KML o GeoJSON.");
        }
    };

    if (fileName.endsWith('.geojson') || fileName.endsWith('.json')) {
        reader.readAsText(file);
    } else {
        // Para KML y GML también leemos como texto para el procesamiento inicial
        reader.readAsText(file);
    }
}

function loadKml(content) {
    if (typeof omnivore === 'undefined') {
        alert("Librería Omnivore no cargada.");
        return;
    }
    const layer = omnivore.kml.parse(content);
    layer.setStyle({ color: '#e74c3c', weight: 3, fillOpacity: 0.2 });
    layer.addTo(drawLayer);
    map.fitBounds(layer.getBounds());
    alert("KML cargado con éxito.");
}

function loadGeoJson(content) {
    try {
        const data = JSON.parse(content);
        const layer = L.geoJSON(data, {
            style: { color: '#2ecc71', weight: 3, fillOpacity: 0.2 }
        }).addTo(drawLayer);
        map.fitBounds(layer.getBounds());
        alert("GeoJSON cargado con éxito.");
    } catch (err) {
        alert("Error al procesar GeoJSON: " + err.message);
    }
}

/**
 * Parser mejorado para GML de Catastro (INSPIRE) - Soporta anillos
 */
function loadGml(content) {
    try {
        const parser = new DOMParser();
        const xmlDoc = parser.parseFromString(content, "text/xml");

        // Buscar diferentes tipos de geometrías GML
        const geometries = [
            ...xmlDoc.getElementsByTagNameNS("*", "Polygon"),
            ...xmlDoc.getElementsByTagNameNS("*", "MultiPolygon"),
            ...xmlDoc.getElementsByTagNameNS("*", "Surface"),
            ...xmlDoc.getElementsByTagNameNS("*", "MultiSurface")
        ];

        let found = false;

        for (let geom of geometries) {
            try {
                // Para polígonos simples y superficies
                if (geom.tagName.includes("Polygon") || geom.tagName.includes("Surface")) {
                    const polygon = processPolygonOrSurface(geom);
                    if (polygon) {
                        polygon.addTo(drawLayer);
                        found = true;
                    }
                }
                // Para polígonos múltiples
                else if (geom.tagName.includes("MultiPolygon") || geom.tagName.includes("MultiSurface")) {
                    const multiPolygon = processMultiPolygonOrSurface(geom);
                    if (multiPolygon) {
                        multiPolygon.addTo(drawLayer);
                        found = true;
                    }
                }
            } catch (e) {
                console.warn("Error procesando geometría:", e);
            }
        }

        // Fallback: buscar posList directo (método antiguo)
        if (!found) {
            const posLists = xmlDoc.getElementsByTagNameNS("*", "posList");
            for (let i = 0; i < posLists.length; i++) {
                const coordsText = posLists[i].textContent.trim().split(/\s+/);
                const latlngs = [];

                for (let j = 0; j < coordsText.length; j += 2) {
                    const v1 = parseFloat(coordsText[j]);
                    const v2 = parseFloat(coordsText[j + 1]);

                    // Determinar orden (muy básico: España está entre lat 35-44 y lon -10-5)
                    if (v1 > 30 && v1 < 50) {
                        latlngs.push([v1, v2]);
                    } else {
                        latlngs.push([v2, v1]);
                    }
                }

                if (latlngs.length > 0) {
                    L.polygon(latlngs, { color: '#3498db', weight: 3, fillOpacity: 0.2 }).addTo(drawLayer);
                    found = true;
                }
            }
        }

        if (found) {
            map.fitBounds(drawLayer.getBounds());
            alert("GML (Catastro) cargado con éxito.");
        } else {
            alert("No se encontraron parcelas/geometrías en el GML.");
        }
    } catch (err) {
        alert("Error al procesar GML: " + err.message);
        console.error("Error GML:", err);
    }
}

function processPolygonOrSurface(polygonElement) {
    try {
        // Buscar anillos exterior e interior
        const exteriorRings = polygonElement.getElementsByTagNameNS("*", "exterior");
        const interiorRings = polygonElement.getElementsByTagNameNS("*", "interior");
        
        let latlngs = [];
        
        // Procesar anillo exterior (boundary principal)
        if (exteriorRings.length > 0) {
            const exteriorRing = exteriorRings[0];
            const posList = exteriorRing.getElementsByTagNameNS("*", "posList")[0];
            
            if (posList) {
                const coordsText = posList.textContent.trim().split(/\s+/);
                const ring = [];
                
                for (let j = 0; j < coordsText.length; j += 2) {
                    const v1 = parseFloat(coordsText[j]);
                    const v2 = parseFloat(coordsText[j + 1]);
                    
                    // Determinar orden
                    if (v1 > 30 && v1 < 50) {
                        ring.push([v1, v2]);
                    } else {
                        ring.push([v2, v1]);
                    }
                }
                
                if (ring.length > 0) {
                    latlngs.push(ring);
                }
            }
        }
        
        // Procesar anillos interiores (huecos)
        for (let i = 0; i < interiorRings.length; i++) {
            const interiorRing = interiorRings[i];
            const posList = interiorRing.getElementsByTagNameNS("*", "posList")[0];
            
            if (posList) {
                const coordsText = posList.textContent.trim().split(/\s+/);
                const hole = [];
                
                for (let j = 0; j < coordsText.length; j += 2) {
                    const v1 = parseFloat(coordsText[j]);
                    const v2 = parseFloat(coordsText[j + 1]);
                    
                    // Determinar orden
                    if (v1 > 30 && v1 < 50) {
                        hole.push([v1, v2]);
                    } else {
                        hole.push([v2, v1]);
                    }
                }
                
                if (hole.length > 0) {
                    latlngs.push(hole);
                }
            }
        }
        
        if (latlngs.length > 0) {
            return L.polygon(latlngs, { 
                color: '#e74c3c', 
                weight: 3, 
                fillOpacity: 0.3,
                fillColor: '#e74c3c'
            });
        }
        
        return null;
    } catch (e) {
        console.warn("Error procesando polígono:", e);
        return null;
    }
}

function processMultiPolygonOrSurface(multiElement) {
    try {
        const polygonMembers = [
            ...multiElement.getElementsByTagNameNS("*", "polygonMember"),
            ...multiElement.getElementsByTagNameNS("*", "surfaceMember")
        ];
        
        const group = L.layerGroup();
        let found = false;
        
        for (let member of polygonMembers) {
            const polygons = member.getElementsByTagNameNS("*", "Polygon");
            const surfaces = member.getElementsByTagNameNS("*", "Surface");
            
            for (let geom of [...polygons, ...surfaces]) {
                const polygon = processPolygonOrSurface(geom);
                if (polygon) {
                    polygon.addTo(group);
                    found = true;
                }
            }
        }
        
        return found ? group : null;
    } catch (e) {
        console.warn("Error procesando multi-polígono:", e);
        return null;
    }
}

function buscarMunicipio(val) {
    const list = document.getElementById('lista-municipios');
    if (!val || val.length < 3) {
        list.style.display = 'none';
        return;
    }

    // Simulación de búsqueda
    list.style.display = 'block';
    list.innerHTML = `
        <div style="padding:5px; cursor:pointer; border-bottom:1px solid #eee;" onclick="alert('Seleccionado: Madrid')">Madrid (28079)</div>
        <div style="padding:5px; cursor:pointer;" onclick="alert('Seleccionado: Barcelona')">Barcelona (08019)</div>
    `;
}

function iniciarDescargaMunicipal() {
    alert("Iniciando descarga masiva de datos ATOM/INSPIRE...");
}

// --- PROCESAMIENTO DE LOTES ---
function handleCatastroFile(file) {
    if (!file) return;

    const resBox = document.getElementById('res-catastro');
    resBox.style.display = 'block';
    resBox.innerHTML = '<div style="padding:15px; text-align:center; color:#666;"><i class="fa-solid fa-spinner fa-spin"></i> Analizando archivo...</div>';

    const reader = new FileReader();
    reader.onload = (e) => {
        const text = e.target.result;

        // 1. Buscar referencias limpias
        const regexLimpio = /\b[0-9A-Z]{14}(?:[0-9A-Z]{6})?\b/g;
        const matchesLimpios = text.toUpperCase().match(regexLimpio) || [];

        // 2. Buscar referencias con separadores
        // Normalizamos el texto (quitando espacios y guiones usuales)
        const textNormalizado = text.toUpperCase().replace(/[\s\-\.\,]/g, '');
        const matchesNormalizados = textNormalizado.match(regexLimpio) || [];

        const allMatches = [...new Set([...matchesLimpios, ...matchesNormalizados])];

        if (allMatches.length > 0) {
            currentLoteRefs = allMatches;
            mostrarPrevisualizacionLote(allMatches);
        } else {
            resBox.innerHTML = `
                <div style="padding:10px; color:#e74c3c; text-align:center;">
                    <i class="fa-solid fa-triangle-exclamation"></i> No se encontraron referencias válidas.<br>
                    <small>El archivo debe contener referencias catastrales (14 o 20 caracteres).</small>
                </div>`;
        }
    };
    reader.onerror = () => {
        resBox.innerHTML = '<div style="color:red; padding:10px;">Error al leer el archivo.</div>';
    };
    reader.readAsText(file);
}

function mostrarPrevisualizacionLote(refs) {
    const resBox = document.getElementById('res-catastro');
    resBox.style.display = 'block';

    const listaHtml = refs.map((ref, index) =>
        `<div style="border-bottom: 1px solid #eee; padding: 6px 0; font-family: monospace; font-size:0.85rem; display:flex; align-items:center;">
            <span style="color:#999; width:25px;">${index + 1}.</span> 
            <span style="font-weight:600; color:#2c3e50;">${ref}</span>
        </div>`
    ).join('');

    resBox.innerHTML = `
        <div style="padding: 5px;">
            <div style="margin-bottom: 10px; color: var(--primary); font-weight: bold; display:flex; align-items:center; justify-content:space-between;">
                <span><i class="fa-solid fa-list-check"></i> Referencias: ${refs.length}</span>
                <span style="font-size:0.8rem; background:#e8f5e9; color:#27ae60; padding:2px 8px; border-radius:10px;">Listo</span>
            </div>
            <div style="max-height: 200px; overflow-y: auto; background: #fff; border: 1px solid #ddd; padding: 10px; margin-bottom: 15px; border-radius: 4px; box-shadow:inset 0 1px 3px rgba(0,0,0,0.05);">
                ${listaHtml}
            </div>
            <div style="display: flex; gap: 10px;">
                <button onclick="procesarLoteActual()" style="flex: 1; background:var(--secondary); border:none; color:white;">
                    <i class="fa-solid fa-play"></i> Procesar
                </button>
                <button onclick="cancelarLote()" class="outline" style="flex: 1; border-color:#ccc; color:#666;">
                    Cancelar
                </button>
            </div>
        </div>
    `;
}

function cancelarLote() {
    const resBox = document.getElementById('res-catastro');
    resBox.style.display = 'none';
    resBox.innerHTML = '';
    currentLoteRefs = [];
}

async function procesarLoteActual() {
    if (!currentLoteRefs || currentLoteRefs.length === 0) return;

    const resBox = document.getElementById('res-catastro');
    // Mostrar estado de carga
    resBox.innerHTML = `
        <div style="padding: 10px; text-align: center;">
            <div style="margin-bottom: 10px;"><i class="fa-solid fa-spinner fa-spin fa-2x"></i></div>
            <div>Iniciando procesamiento de ${currentLoteRefs.length} referencias...</div>
            <div class="progress-container" style="margin-top: 10px;">
                <div id="lote-progress" class="progress-bar" style="width: 0%">0%</div>
            </div>
            <div id="lote-status" style="font-size: 0.8rem; color: #666; margin-top: 5px;">Enviando datos...</div>
        </div>
    `;

    try {
        const response = await fetch('/api/v1/procesar-lote', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ referencias: currentLoteRefs })
        });

        const data = await response.json();

        if (data.status === 'processing') {
            pollProgress(data.expediente_id, resBox);
        } else {
            throw new Error(data.message || "Error al iniciar el procesamiento");
        }
    } catch (e) {
        resBox.innerHTML = `
            <div style="padding: 10px; color: #e74c3c;">
                <i class="fa-solid fa-circle-exclamation"></i> Error: ${e.message}
                <button class="outline" style="margin-top: 10px; width: 100%;" onclick="mostrarPrevisualizacionLote(currentLoteRefs)">Reintentar</button>
}

function mostrarPrevisualizacionLote(refs) {
    const resBox = document.getElementById('res-catastro');
    resBox.style.display = 'block';

    const listaHtml = refs.map((ref, index) =>
        `<div style="border-bottom: 1px solid #eee; padding: 6px 0; font-family: monospace; font-size:0.85rem; display:flex; align-items:center;">
            <span style="color:#999; width:25px;">${index + 1}.</span> 
            <span style="font-weight:600; color:#2c3e50;">${ref}</span>
        </div>`
    ).join('');

    resBox.innerHTML = `
        <div style="padding: 5px;">
            <div style="margin-bottom: 10px; color: var(--primary); font-weight: bold; display:flex; align-items:center; justify-content:space-between;">
                <span><i class="fa-solid fa-list-check"></i> Referencias: ${refs.length}</span>
                <span style="font-size:0.8rem; background:#e8f5e9; color:#27ae60; padding:2px 8px; border-radius:10px;">Listo</span>
            </div>
            <div style="max-height: 200px; overflow-y: auto; background: #fff; border: 1px solid #ddd; padding: 10px; margin-bottom: 15px; border-radius: 4px; box-shadow:inset 0 1px 3px rgba(0,0,0,0.05);">
                ${listaHtml}
            </div>
            <div style="display: flex; gap: 10px;">
                <button onclick="procesarLoteActual()" style="flex: 1; background:var(--secondary); border:none; color:white;">
                    <i class="fa-solid fa-play"></i> Procesar
                </button>
                <button onclick="cancelarLote()" class="outline" style="flex: 1; border-color:#ccc; color:#666;">
                    Cancelar
                </button>
            </div>
        </div>
    `;
}
            const bar = document.getElementById('lote-progress');
            const status = document.getElementById('lote-status');

            if (bar) {
                bar.style.width = `${pct}%`;
                bar.innerText = `${pct}%`;
            }
            if (status) status.innerText = `Estado: ${estado} (${data.items ? data.items.length : 0} procesados)`;

            if (estado === 'completado' || pct >= 100) {
                clearInterval(interval);

                const zipUrl = data.zip_url; // Usar la URL correcta del backend
                container.innerHTML = `
                    <div style="padding: 10px;">
                        <div style="color: green; font-weight: bold; margin-bottom: 5px;">
                            <i class="fa-solid fa-check-circle"></i> Lote Completado
                        </div>
                        <div style="font-size: 0.9rem; margin-bottom: 10px;">
                            Expediente: ${expId}
                        </div>
                        <button class="outline" onclick="window.open('${zipUrl}')">
                            <i class="fa-solid fa-download"></i> Descargar ZIP
                        </button>
                    </div>
                `;

                // Cargar KML en mapa si existe
                if (data.lote_outputs && data.lote_outputs.kml_global) {
                    if (drawLayer) drawLayer.clearLayers();
                    // URL relativa del KML
                    const kmlUrl = `/outputs/expedientes/expediente_${expId}/lote/lote_${expId}.kml`;

                    if (typeof omnivore !== 'undefined') {
                        const layer = omnivore.kml(kmlUrl, null, L.geoJson(null, {
                            style: { color: '#e74c3c', weight: 2, opacity: 1, fillOpacity: 0.2 }
                        }));

                        layer.on('ready', function () {
                            drawLayer.addLayer(this);
                            map.fitBounds(this.getBounds());
                        });
                    }
                }
            }
        } catch (e) {
            console.error("Polling error", e);
        }
    }, 1000);
}