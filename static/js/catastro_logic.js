
// Lógica para catastro.html

// Configuración de Capas
const MAP_LAYERS_CONFIG = {
    base: [
        { name: "Callejero (OSM)", url: "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", attribution: "OSM", default: true },
        { name: "Satélite (Google)", url: "https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}", attribution: "Google", maxZoom: 20 },
        { name: "PNOA (España)", wms: true, url: "https://www.ign.es/wms-inspire/pnoa-ma", layers: "OI.OrthoimageCoverage", format: "image/jpeg" },
        { name: "Catastro", wms: true, url: "https://ovc.catastro.meh.es/Cartografia/WMS/ServidorWMS.aspx", layers: "Catastro", format: "image/png", transparent: true }
    ],
    priority: [
        { id: "rednatura", name: "Red Natura 2000", keywords: ["red", "natura", "2000"], wms_url: "https://wms.mapama.gob.es/sig/Biodiversidad/RedNatura/wms.aspx", wms_layer: "PS.ProtectedSite" },
        { id: "viaspecuarias", name: "Vías Pecuarias", keywords: ["vias", "pecuarias"], wms_url: "https://wms.mapama.gob.es/sig/Biodiversidad/ViasPecuarias/wms.aspx", wms_layer: "VP.ViasPecuarias" }, // Check layer name
        { id: "montespublicos", name: "Montes Públicos", keywords: ["montes", "publicos"], wms_url: "https://wms.mapama.gob.es/sig/Biodiversidad/MontesPublicos/wms.aspx", wms_layer: "Montes_Publicos" },
        { id: "zonasinundables", name: "Zonas Inundables", keywords: ["zonas", "inundables"], wms_url: "https://wms.mapama.gob.es/sig/agua/ZI_LaminasQ100/wms.aspx", wms_layer: "NZ.RiskZone" }, // Example
        { id: "espaciosnaturales", name: "Espacios Naturales Protegidos", keywords: ["espacios", "naturales", "protegidos"], wms_url: "https://wms.mapama.gob.es/sig/Biodiversidad/ENP/wms.aspx", wms_layer: "PS.ProtectedSite" },
        { id: "frecuenciaincendios", name: "Frecuencia de Incendios", keywords: ["frecuencia", "incendios"] },
        
        // Riesgos
        { id: "riesgo_fluvial", name: "Riesgo de Inundación Fluvial", keywords: ["riesgo", "inundación", "fluvial"] },
        { id: "riesgo_costera", name: "Riesgo de Inundación Costera", keywords: ["riesgo", "inundación", "costera"] },
        { id: "riesgo_sismico", name: "Riesgo Sísmico", keywords: ["riesgo", "sismico"] },
        { id: "riesgo_incendio", name: "Riesgo Incendio", keywords: ["riesgo", "incendio"] },
        { id: "riesgo_desertificacion", name: "Riesgo Desertificación", keywords: ["riesgo", "desertificacion"] },
        { id: "riesgo_volcanico", name: "Riesgo Volcánico", keywords: ["riesgo", "volcanico"] },
        
        // Otros solicitados explícitamente en la lista prioritaria/visible
        { id: "espacios_naturales_dup", name: "Espacios Naturales", keywords: ["espacios", "naturales"] },
        { id: "vias_pecuarias_dup", name: "Vías Pecuarias", keywords: ["vias", "pecuarias"] },
        { id: "dpmt", name: "DPMT", keywords: ["dpmt"] },
        { id: "dph", name: "Dominio Público Hidráulico", keywords: ["dominio", "publico", "hidraulico"] },
        { id: "zonas_verdes", name: "Zonas Verdes (Jardines)", keywords: ["zonas", "verdes"] },
        { id: "alta_tension", name: "Alta Tensión", keywords: ["alta", "tension"] },
        { id: "oleoductos", name: "Oleoductos/Gaseoductos", keywords: ["oleoductos", "gaseoductos"] },
        { id: "contaminacion", name: "Contaminación del Terreno", keywords: ["contaminacion", "terreno"] }
    ]
};

var map;
var activeLayers = {};
var measureControl = null;

document.addEventListener('DOMContentLoaded', function() {
    initMap();
    initLayers();
    initAccordion();
    
    // Ocultar overlay de carga
    setTimeout(() => {
        document.getElementById('loading-overlay').style.display = 'none';
    }, 1000);
});

function initMap() {
    // Coordenadas iniciales (Centro de España aprox)
    map = L.map('map', { zoomControl: false }).setView([40.4168, -3.7038], 6);
    
    // Zoom control top-right
    L.control.zoom({ position: 'topright' }).addTo(map);

    // Cargar capa base por defecto
    loadBaseLayer(MAP_LAYERS_CONFIG.base[0]);
}

function initLayers() {
    // 1. Renderizar Mapas Base
    const baseContainer = document.getElementById('base-layers-list');
    MAP_LAYERS_CONFIG.base.forEach((layer, index) => {
        const div = document.createElement('div');
        div.className = 'layer-item layer-header';
        div.innerHTML = `
            <input type="radio" name="base-layer" id="base-${index}" ${layer.default ? 'checked' : ''}>
            <label for="base-${index}">${layer.name}</label>
        `;
        div.querySelector('input').addEventListener('change', () => loadBaseLayer(layer));
        baseContainer.appendChild(div);
    });

    // 2. Cargar capas disponibles desde el Backend (PostGIS/Archivos)
    fetch('/api/v1/capas-disponibles')
        .then(response => response.json())
        .then(data => {
            if (data.status === 'success') {
                organizeAndRenderLayers(data.capas);
            } else {
                console.error("Error cargando capas:", data.message);
            }
        })
        .catch(err => console.error("Error fetch capas:", err));
}

function organizeAndRenderLayers(availableLayers) {
    const priorityContainer = document.getElementById('priority-layers-list');
    const otherContainer = document.getElementById('other-layers-list');
    
    // Lista de nombres de capas disponibles (normalizados)
    const availableSet = new Set(availableLayers.map(l => l.toLowerCase()));
    
    // 1. Renderizar Prioritarias
    MAP_LAYERS_CONFIG.priority.forEach(pLayer => {
        // Buscar si existe una capa coincidente en el backend (por keywords)
        // O si es una capa WMS externa definida en la config
        
        let isAvailable = false;
        let layerId = pLayer.id;
        
        // Estrategia de macheo simple
        const match = availableLayers.find(l => {
            const lower = l.toLowerCase();
            return pLayer.keywords.every(k => lower.includes(k));
        });

        if (match) {
            isAvailable = true;
            layerId = match; // Usar el nombre real de la tabla PostGIS
        } else if (pLayer.wms_url) {
            isAvailable = true; // Es WMS externo
        }

        // Renderizar item
        const div = document.createElement('div');
        div.className = 'layer-item';
        
        // Leyenda (placeholder o WMS GetLegendGraphic)
        let legendHtml = '';
        if (pLayer.wms_url && pLayer.wms_layer) {
            const legendUrl = `${pLayer.wms_url}?request=GetLegendGraphic&format=image/png&layer=${pLayer.wms_layer}&style=default`;
            legendHtml = `<div class="layer-legend" id="legend-${pLayer.id}"><img src="${legendUrl}" alt="Leyenda"></div>`;
        } else {
             legendHtml = `<div class="layer-legend" id="legend-${pLayer.id}">Leyenda no disponible</div>`;
        }

        div.innerHTML = `
            <div class="layer-header">
                <input type="checkbox" id="layer-${pLayer.id}" ${!isAvailable ? 'disabled' : ''}>
                <label for="layer-${pLayer.id}" style="${!isAvailable ? 'color:#aaa' : ''}">${pLayer.name}</label>
            </div>
            ${legendHtml}
        `;

        if (isAvailable) {
            const checkbox = div.querySelector('input');
            checkbox.addEventListener('change', (e) => {
                const legend = div.querySelector('.layer-legend');
                if (e.target.checked) {
                    toggleLayer(pLayer, layerId, true);
                    if (legend) legend.style.display = 'block';
                } else {
                    toggleLayer(pLayer, layerId, false);
                    if (legend) legend.style.display = 'none';
                }
            });
        }

        priorityContainer.appendChild(div);
        
        // Marcar como procesada para no duplicar en "Otros"
        if (match) {
            availableSet.delete(match.toLowerCase());
        }
    });

    // 2. Renderizar Resto de Capas (las que sobran de PostGIS)
    availableSet.forEach(layerName => {
        const div = document.createElement('div');
        div.className = 'layer-item';
        div.innerHTML = `
            <div class="layer-header">
                <input type="checkbox" id="layer-${layerName}">
                <label for="layer-${layerName}">${formatLayerName(layerName)}</label>
            </div>
        `;
        
        div.querySelector('input').addEventListener('change', (e) => {
            toggleLayer({ id: layerName, name: layerName }, layerName, e.target.checked);
        });
        
        otherContainer.appendChild(div);
    });
}

function loadBaseLayer(layerConfig) {
    // Remover capa base actual
    if (activeLayers.base) {
        map.removeLayer(activeLayers.base);
    }

    if (layerConfig.wms) {
        activeLayers.base = L.tileLayer.wms(layerConfig.url, {
            layers: layerConfig.layers,
            format: layerConfig.format,
            transparent: layerConfig.transparent,
            attribution: layerConfig.attribution
        });
    } else {
        activeLayers.base = L.tileLayer(layerConfig.url, {
            attribution: layerConfig.attribution,
            maxZoom: layerConfig.maxZoom || 18
        });
    }
    
    activeLayers.base.addTo(map);
}

function toggleLayer(config, layerId, visible) {
    if (!visible) {
        if (activeLayers[config.id]) {
            map.removeLayer(activeLayers[config.id]);
            delete activeLayers[config.id];
        }
        return;
    }

    // Determinar tipo de capa
    if (config.wms_url) {
        // WMS Externo
        const layer = L.tileLayer.wms(config.wms_url, {
            layers: config.wms_layer,
            format: 'image/png',
            transparent: true,
            opacity: 0.7,
            attribution: config.name
        });
        activeLayers[config.id] = layer;
        layer.addTo(map);
    } else {
        // Capa PostGIS (Vectorial GeoJSON)
        // Usamos una API para obtener el GeoJSON (limitado por BBOX idealmente, aquí simple)
        // O mejor: WMS si tuvieramos Geoserver, pero aquí usamos vector tiles o geojson raw
        
        // Opción A: Cargar GeoJSON completo (Cuidado con rendimiento)
        // Opción B: Usar un TileLayer si tuvieramos un servidor de teselas.
        // Vamos a usar la ruta /api/v1/capas/data/{layer_name} que ya existe en main.py
        
        const loadingId = `loading-${config.id}`;
        // Mostrar spinner pequeño o algo si se pudiera
        
        // Optimización: pedir solo el BBOX actual? 
        // Por ahora pedimos todo con un límite implícito en backend o confiamos en PostGIS
        const url = `/api/v1/capas/data/${layerId}?bbox=${map.getBounds().toBBoxString()}`;
        
        fetch(url)
            .then(res => res.json())
            .then(data => {
                const layer = L.geoJSON(data, {
                    style: {
                        color: getRandomColor(),
                        weight: 2,
                        opacity: 1,
                        fillOpacity: 0.2
                    },
                    onEachFeature: function(feature, layer) {
                        if (feature.properties) {
                            let popupContent = "<b>" + config.name + "</b><br>";
                            for (const [key, val] of Object.entries(feature.properties)) {
                                popupContent += `${key}: ${val}<br>`;
                            }
                            layer.bindPopup(popupContent);
                        }
                    }
                });
                activeLayers[config.id] = layer;
                layer.addTo(map);
                
                // Zoom a la capa si es la primera vez? No, mejor mantener vista
            })
            .catch(err => {
                console.error("Error cargando capa vectorial:", err);
                alert("Error cargando capa " + config.name);
            });
    }
}

function initAccordion() {
    var acc = document.getElementsByClassName("accordion");
    for (var i = 0; i < acc.length; i++) {
        acc[i].addEventListener("click", function() {
            this.classList.toggle("active");
            var panel = this.nextElementSibling;
            if (panel.style.maxHeight) {
                panel.style.maxHeight = null;
            } else {
                panel.style.maxHeight = panel.scrollHeight + "px";
            } 
        });
    }
}

// Utiles
function formatLayerName(name) {
    return name.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
}

function getRandomColor() {
    const letters = '0123456789ABCDEF';
    let color = '#';
    for (let i = 0; i < 6; i++) {
        color += letters[Math.floor(Math.random() * 16)];
    }
    return color;
}

function buscarReferencia() {
    const ref = document.getElementById('input-ref-catastral').value;
    if (!ref) return alert("Introduce una referencia");
    alert("Buscando referencia: " + ref + " (Funcionalidad simulada)");
}

function buscarMunicipio() {
    const mun = document.getElementById('input-municipio').value;
    if (!mun) return alert("Introduce un municipio");
    alert("Buscando municipio: " + mun + " (Funcionalidad simulada)");
}

function generarInforme() {
    alert("Generando informe de afecciones... (Funcionalidad simulada)");
}

// Medición
function toggleMeasure(type) {
    if (measureControl) {
        clearMeasure();
    }
    // Implementación simple de medición usando Leaflet GeometryUtil o manual
    // Aquí solo activamos un modo visual
    measureMode = type;
    document.getElementById('medicion-resultado').style.display = 'block';
    document.getElementById('medicion-resultado').innerHTML = `Modo medición: ${type} activado. Haz clic en el mapa.`;
    
    // NOTA: Implementación real requeriría manejo de eventos click en mapa
}

function clearMeasure() {
    measureMode = null;
    document.getElementById('medicion-resultado').style.display = 'none';
    document.getElementById('medicion-resultado').innerHTML = '';
}

function centrarMapa() {
    map.setView([40.4168, -3.7038], 6);
}

function handleFileSelect(event) {
    const file = event.target.files[0];
    if (!file) return;
    
    // Usar Omnivore para cargar
    const layer = omnivore.kml(URL.createObjectURL(file))
        .on('ready', function() {
            map.fitBounds(layer.getBounds());
            layer.addTo(map);
        })
        .on('error', function() {
            alert("Error cargando archivo. Asegúrate de que es un formato válido.");
        });
}
