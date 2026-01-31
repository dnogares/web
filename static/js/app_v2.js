class App {
    constructor() {
        this.map = null;
        this.layers = {};
        this.currentRef = null;
        this.measureLayer = null;
        this.measurePoints = [];
        this.measureMode = null;

        this.initMap();
        this.initLayers();
        this.initUI();
    }

    initMap() {
        this.map = L.map('map', { zoomControl: false }).setView([40.4168, -3.7038], 6);
        L.control.zoom({ position: 'topright' }).addTo(this.map);

        this.measureLayer = L.layerGroup().addTo(this.map);
        this.map.on('click', (e) => this.onMapClick(e));
        this.map.on('dblclick', () => this.finishMeasure());
    }

    initLayers() {
        // Capas Base
        this.layers.base = {
            'osm': L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '© OpenStreetMap'
            }).addTo(this.map),
            'catastro': L.tileLayer.wms('https://ovc.catastro.meh.es/Cartografia/WMS/ServidorWMS.aspx', {
                layers: 'Catastro', format: 'image/png', transparent: true
            }),
            'pnoa': L.tileLayer.wms('https://www.ign.es/wms-inspire/pnoa-ma', {
                layers: 'OI.OrthoimageCoverage', format: 'image/jpeg', transparent: true, opacity: 0.5
            })
        };

        // Capas Afecciones (Mandatorias y Opcionales)
        this.layers.overlays = {
            'natura': this.createLocalLayer('natura', '#27ae60'), // Red Natura
            'caminos': this.createLocalLayer('caminos', '#8e44ad'), // Vías/Caminos
            'montes': this.createLocalLayer('montes', '#2c3e50'), // Montes (Ahora local)
        };
    }

    createLocalLayer(name, color) {
        const layerGroup = L.layerGroup();
        this.showLoading(`Cargando ${name}...`);

        fetch(`/api/v1/capas/geojson/${name}`)
            .then(r => {
                if (!r.ok) throw new Error(`HTTP ${r.status}`);
                return r.json();
            })
            .then(data => {
                if (data.type) {
                    L.geoJSON(data, {
                        style: { color: color, weight: 2, opacity: 0.8, fillOpacity: 0.2 },
                        onEachFeature: (f, l) => l.bindPopup(`<b>${name.toUpperCase()}</b>`)
                    }).addTo(layerGroup);
                }
                this.hideLoading();
            })
            .catch(e => {
                console.warn(`Capa ${name} no cargada:`, e);
                this.hideLoading();
            });
        return layerGroup;
    }

    // Cambiar capa base desde el panel lateral
    setBaseLayer(name) {
        Object.values(this.layers.base).forEach(l => this.map.removeLayer(l));
        if (this.layers.base[name]) this.layers.base[name].addTo(this.map);
    }

    toggleLayer(name, checked) {
        if (checked) this.layers.overlays[name].addTo(this.map);
        else this.map.removeLayer(this.layers.overlays[name]);
    }

    initUI() {
        // Cambio de pestañas
        document.querySelectorAll('.tab-btn').forEach(btn => {
            btn.addEventListener('click', () => {
                // UI Update
                document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
                document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
                btn.classList.add('active');
                document.getElementById(`panel-${btn.dataset.target}`).classList.add('active');
            });
        });
    }

    // --- MÓDULO 1: CATASTRO ---
    async buscarReferencia() {
        const ref = document.getElementById('catastro-ref').value.trim();
        if (!ref) return alert("Introduce una referencia");

        // Cargar geometría en mapa
        try {
            const res = await fetch(`/api/v1/referencia/${ref}/geojson`);
            const data = await res.json();
            if (data.type) {
                if (this.searchLayer) this.map.removeLayer(this.searchLayer);
                this.searchLayer = L.geoJSON(data, { style: { color: 'red', weight: 4, fillOpacity: 0 } }).addTo(this.map);
                this.map.fitBounds(this.searchLayer.getBounds());
                this.currentRef = ref;
            }
        } catch (e) { console.error(e); }
    }

    async procesarCatastro() {
        const ref = document.getElementById('catastro-ref').value.trim();
        const fileInput = document.getElementById('catastro-file');

        if (!ref && fileInput.files.length === 0) return alert("Introduce referencia o archivo");

        const container = document.getElementById('catastro-results');
        container.classList.remove('hidden');
        container.querySelector('ul').innerHTML = '<li class="loading"><i class="fa-solid fa-spinner fa-spin"></i> Procesando...</li>';

        try {
            const res = await fetch('/api/v1/procesar-completo', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ referencia: ref })
            });
            const data = await res.json();

            if (data.status === 'success') {
                const zipUrl = data.zip_path;
                const html = `
                    <li><a href="${zipUrl}" target="_blank"><i class="fa-solid fa-file-pdf"></i> 1. PDF Catastral</a></li>
                    <li><a href="${zipUrl}" target="_blank"><i class="fa-solid fa-file-code"></i> 2. XML Catastral</a></li>
                    <li><a href="${zipUrl}" target="_blank"><i class="fa-solid fa-globe"></i> 3. GML / KML</a></li>
                    <li><a href="${zipUrl}" target="_blank"><i class="fa-solid fa-image"></i> 4. Composición Plano+Orto</a></li>
                    <li><a href="${zipUrl}" target="_blank"><i class="fa-solid fa-images"></i> 5. Ortofotos Contexto (Nac/Aut/Prov)</a></li>
                    <li><a href="${zipUrl}" target="_blank"><i class="fa-solid fa-table"></i> 6. CSV Resumen Técnico</a></li>
                    <li class="zip-download"><a href="${zipUrl}" class="btn-download"><i class="fa-solid fa-download"></i> Descargar TODO (ZIP)</a></li>
                `;
                container.querySelector('ul').innerHTML = html;
            }
        } catch (e) {
            container.querySelector('ul').innerHTML = `<li class="error">Error: ${e.message}</li>`;
        }
    }

    // --- MÓDULO 2: URBANISMO ---
    async analizarUrbanismo() {
        const ref = document.getElementById('urbanismo-ref').value.trim() || this.currentRef;
        if (!ref) return alert("Se requiere referencia o archivo");

        const container = document.getElementById('urbanismo-results');
        container.classList.remove('hidden');
        container.innerHTML = '<div class="loading"><i class="fa-solid fa-spinner fa-spin"></i> Analizando normativa...</div>';

        try {
            const res = await fetch('/api/v1/analizar-urbanismo', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ referencia: ref })
            });
            const data = await res.json();

            const info = data.data.analisis_urbanistico;
            const html = `
                <div class="result-card">
                    <h5><i class="fa-solid fa-map"></i> Plano de Conjunto</h5>
                    <p>Generado en mapa principal</p>
                </div>
                <div class="result-card">
                    <h5><i class="fa-solid fa-file-contract"></i> Ficha Urbanística</h5>
                    <p><strong>Clase:</strong> ${info.clasificacion_suelo}</p>
                    <p><strong>Edificabilidad:</strong> ${info.edificabilidad_estimada}</p>
                    <div class="actions">
                        <button class="btn-small"><i class="fa-solid fa-file-pdf"></i> PDF</button>
                        <button class="btn-small"><i class="fa-solid fa-file-excel"></i> CSV</button>
                    </div>
                </div>
                <div class="result-card">
                    <h5><i class="fa-solid fa-chart-pie"></i> Afección Suelo</h5>
                    <div class="progress-bar"><div style="width: ${info.ocupacion_estimada}"></div></div>
                    <p>${info.ocupacion_estimada} Ocupación</p>
                </div>
            `;
            container.innerHTML = html;
        } catch (e) {
            container.innerHTML = 'Error en análisis.';
        }
    }

    async calcularAfecciones() {
        const ref = this.currentRef;
        if (!ref) return alert("Busca una referencia primero en el mapa");

        const container = document.getElementById('afecciones-results');
        container.classList.remove('hidden');
        container.innerHTML = '<div class="loading"><i class="fa-solid fa-spinner fa-spin"></i> Calculando intersecciones...</div>';

        try {
            const res = await fetch('/api/v1/analizar-afecciones', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ referencia: ref })
            });
            const data = await res.json();

            let html = '<h4>Resultados de Intersección</h4>';

            if (data.data && data.data.afecciones) {
                data.data.afecciones.forEach(af => {
                    html += `<div class="afeccion-item warning"><strong>${af.tipo}</strong>: ${af.descripcion}</div>`;
                });
            }
            container.innerHTML = html;
        } catch (e) { container.innerHTML = 'Error calculando afecciones.'; }
    }

    // --- HERRAMIENTAS DE MEDICIÓN ---
    activarMedicion(modo) {
        this.measureMode = modo;
        this.measurePoints = [];
        this.measureLayer.clearLayers();
        this.map.getContainer().style.cursor = 'crosshair';

        const resDiv = document.getElementById('medicion-resultado');
        resDiv.classList.remove('hidden');
        resDiv.innerHTML = `Modo: ${modo.toUpperCase()} (Click para marcar, Doble click para terminar)`;
    }

    onMapClick(e) {
        if (!this.measureMode) return;

        this.measurePoints.push(e.latlng);
        L.circleMarker(e.latlng, { radius: 5, color: 'red' }).addTo(this.measureLayer);

        if (this.measurePoints.length > 1 && this.measureMode === 'distancia') {
            L.polyline(this.measurePoints, { color: 'red' }).addTo(this.measureLayer);
            this.updateMeasureResult();
        } else if (this.measurePoints.length > 2 && this.measureMode === 'area') {
            // Limpiar polígonos previos para redibujar
            this.measureLayer.eachLayer(l => { if (l instanceof L.Polygon) this.measureLayer.removeLayer(l); });
            L.polygon(this.measurePoints, { color: 'red', fillOpacity: 0.3 }).addTo(this.measureLayer);
            this.updateMeasureResult();
        }
    }

    finishMeasure() {
        this.measureMode = null;
        this.map.getContainer().style.cursor = '';
    }

    updateMeasureResult() {
        const resDiv = document.getElementById('medicion-resultado');
        if (this.measureMode === 'distancia') {
            let dist = 0;
            for (let i = 0; i < this.measurePoints.length - 1; i++) {
                dist += this.measurePoints[i].distanceTo(this.measurePoints[i + 1]);
            }
            resDiv.innerHTML = `Distancia: ${(dist / 1000).toFixed(2)} km`;
        } else if (this.measureMode === 'area') {
            // Cálculo simple de área (aproximado si no hay GeometryUtil)
            const area = this.calculateArea(this.measurePoints);
            resDiv.innerHTML = `Área: ${(area / 10000).toFixed(2)} ha`;
        }
    }

    calculateArea(latlngs) {
        // Si GeometryUtil está disponible (lo añadimos en HTML)
        if (L.GeometryUtil && typeof L.GeometryUtil.geodesicArea === 'function') {
            try {
                return L.GeometryUtil.geodesicArea(latlngs);
            } catch (e) {
                console.warn("Error calculando área:", e);
                return 0;
            }
        }
        return 0; // Fallback
    }

    limpiarMapa() {
        this.measureMode = null;
        this.measurePoints = [];
        this.measureLayer.clearLayers();
        if (this.searchLayer) this.map.removeLayer(this.searchLayer);

        document.getElementById('medicion-resultado').classList.add('hidden');
        document.getElementById('catastro-ref').value = '';
        document.getElementById('catastro-results').classList.add('hidden');
        document.getElementById('urbanismo-results').classList.add('hidden');
        document.getElementById('afecciones-results').classList.add('hidden');

        this.map.getContainer().style.cursor = '';
    }

    showLoading(text) {
        const toast = document.getElementById('loading-toast');
        const textEl = document.getElementById('loading-text');
        if (toast && textEl) {
            textEl.textContent = text;
            toast.classList.remove('hidden');
        }
    }

    hideLoading() {
        const toast = document.getElementById('loading-toast');
        if (toast) {
            setTimeout(() => toast.classList.add('hidden'), 500);
        }
    }
}

const app = new App();