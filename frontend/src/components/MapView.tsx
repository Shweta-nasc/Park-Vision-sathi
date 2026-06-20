import { useEffect, useRef, useCallback, useState } from 'react';
import { useAppState } from '@/state/AppState';
import { useMapOverlay } from '@/state/MapOverlay';
import { useHeatmap, useTopZones, useSpilloverArrows } from '@/hooks/queries';
import { HEAT_GRADIENTS, riskColor } from '@/utils/risk';
import { MapplsHeatLayer } from '@/utils/MapplsHeatLayer';
import { getMapEngine } from '@/utils/loadMapplsSDK';
import { LayerToggle } from './LayerToggle';

const TEAM_COLORS = [
  '#2A9D8F', '#E76F51', '#457B9D', '#F4A261', '#9B5DE5',
  '#00BBF9', '#F15BB5', '#EAB308', '#8338EC', '#FF006E',
  '#3A86C8', '#38B000', '#70E000', '#06B6D4', '#FB5607',
];

// Free vector tile style for MapLibre fallback
const MAPLIBRE_STYLE = 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json';

// ── SVG icon builders ─────────────────────────────────────────────────
function svgDataUrl(svg: string): string {
  return 'data:image/svg+xml,' + encodeURIComponent(svg.trim());
}

function stationSvg(): string {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="32" height="32" viewBox="0 0 32 32">
    <circle cx="16" cy="16" r="14" fill="#0d9488" stroke="white" stroke-width="3"/>
    <path d="M16 24s-6-3.4-6-8.8A6 6 0 0 1 16 9a6 6 0 0 1 6 6.2c0 5.4-6 8.8-6 8.8z" fill="none" stroke="white" stroke-width="1.5"/>
    <circle cx="16" cy="15" r="2" fill="white"/>
  </svg>`;
}

function dotSvg(size: number, color: string): string {
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}">
    <circle cx="${size / 2}" cy="${size / 2}" r="${size / 2 - 1}" fill="${color}" stroke="white" stroke-width="2"/>
  </svg>`;
}

function teamSvg(color: string, id: number): string {
  // Pin shape: circle body + pointed bottom, number centered in circle
  return `<svg xmlns="http://www.w3.org/2000/svg" width="36" height="44" viewBox="0 0 36 44">
    <filter id="s${id}"><feDropShadow dx="0" dy="2" stdDeviation="2" flood-opacity=".35"/></filter>
    <path d="M18 0C8.06 0 0 8.06 0 18c0 10.84 16.1 24.5 17.35 25.55a1 1 0 0 0 1.3 0C19.9 42.5 36 28.84 36 18 36 8.06 27.94 0 18 0z"
      fill="${color}" filter="url(#s${id})"/>
    <circle cx="18" cy="17" r="11" fill="white" opacity=".2"/>
    <text x="18" y="23" text-anchor="middle" fill="white" font-weight="800"
      font-size="15" font-family="Inter,-apple-system,sans-serif">${id}</text>
  </svg>`;
}

// ── Engine Abstraction ────────────────────────────────────────────────
// Thin wrappers so MapView doesn't branch on every map call.

interface MapEngine {
  createMap(el: HTMLElement, center: { lat: number; lng: number }, zoom: number): any;
  onLoad(map: any, cb: () => void): void;
  setCenter(map: any, pos: { lat: number; lng: number }): void;
  setZoom(map: any, z: number): void;
  getZoom(map: any): number;
  zoomIn(map: any): void;
  zoomOut(map: any): void;
  onZoomEnd(map: any, cb: () => void): void;
  addMarker(map: any, pos: { lat: number; lng: number }, iconSvg: string, size: number, popupHtml?: string): any;
  addMarkerClickListener(marker: any, cb: () => void): void;
  addPolyline(map: any, path: { lat: number; lng: number }[], opts: { color: string; weight: number; opacity: number; dash?: number[] }): any;
  addCircle(map: any, center: { lat: number; lng: number }, radius: number, opts: { fillColor: string; fillOpacity: number; strokeColor: string; strokeWeight: number }): any;
  removeOverlay(map: any, overlay: any): void;
  fitBounds(map: any, sw: { lat: number; lng: number }, ne: { lat: number; lng: number }, padding: number): void;
}

function getMappls(): any {
  return (window as any).mappls;
}
function getMaplibregl(): any {
  return (window as any).maplibregl;
}

const mapplsEngine: MapEngine = {
  createMap(el, center, zoom) {
    return new (getMappls()).Map(el, { center, zoom, zoomControl: false });
  },
  onLoad(map, cb) {
    map.addListener('load', cb);
  },
  setCenter(map, pos) {
    map.setCenter(pos);
  },
  setZoom(map, z) {
    map.setZoom(z);
  },
  zoomIn(map) {
    try { map.zoomIn(); } catch { map.setZoom(map.getZoom() + 1); }
  },
  zoomOut(map) {
    try { map.zoomOut(); } catch { map.setZoom(map.getZoom() - 1); }
  },
  getZoom(map) {
    return map.getZoom();
  },
  onZoomEnd(map, cb) {
    try { map.addListener('zoom_changed', cb); } catch { /* ignore */ }
    try { map.addListener('zoomend', cb); } catch { /* ignore */ }
  },
  addMarker(map, pos, iconSvg, size, popupHtml) {
    const opts: any = {
      map,
      position: pos,
      icon: { url: svgDataUrl(iconSvg), width: size, height: size },
    };
    if (popupHtml) opts.popupHtml = popupHtml;
    return new (getMappls()).Marker(opts);
  },
  addMarkerClickListener(marker, cb) {
    marker.addListener?.('click', cb);
  },
  addPolyline(map, path, opts) {
    return new (getMappls()).Polyline({
      map,
      path,
      strokeColor: opts.color,
      strokeWeight: opts.weight,
      strokeOpacity: opts.opacity,
      dashArray: opts.dash,
    });
  },
  addCircle(map, center, radius, opts) {
    return new (getMappls()).Circle({
      map,
      center,
      radius,
      fillColor: opts.fillColor,
      fillOpacity: opts.fillOpacity,
      strokeColor: opts.strokeColor,
      strokeWeight: opts.strokeWeight,
    });
  },
  removeOverlay(map, overlay) {
    try { getMappls().remove({ map, layer: overlay }); } catch { /* ok */ }
  },
  fitBounds(map, sw, ne, padding) {
    try {
      const b = new (getMappls()).LatLngBounds(sw, ne);
      map.fitBounds(b, { padding });
    } catch { /* degrade */ }
  },
};

const maplibreEngine: MapEngine = {
  createMap(el, center, zoom) {
    return new (getMaplibregl()).Map({
      container: el,
      style: MAPLIBRE_STYLE,
      center: [center.lng, center.lat],
      zoom,
      attributionControl: false,
    });
  },
  onLoad(map, cb) {
    map.on('load', cb);
  },
  setCenter(map, pos) {
    map.setCenter([pos.lng, pos.lat]);
  },
  setZoom(map, z) {
    map.setZoom(z);
  },
  zoomIn(map) {
    map.zoomIn();
  },
  zoomOut(map) {
    map.zoomOut();
  },
  getZoom(map) {
    return map.getZoom();
  },
  onZoomEnd(map, cb) {
    map.on('zoomend', cb);
  },
  addMarker(map, pos, iconSvg, size, popupHtml) {
    const el = document.createElement('div');
    el.innerHTML = iconSvg;
    el.style.width = `${size}px`;
    el.style.height = `${size}px`;
    el.style.cursor = 'pointer';
    const marker = new (getMaplibregl()).Marker({ element: el })
      .setLngLat([pos.lng, pos.lat])
      .addTo(map);
    if (popupHtml) {
      const popup = new (getMaplibregl()).Popup({ offset: 25 }).setHTML(popupHtml);
      marker.setPopup(popup);
    }
    return marker;
  },
  addMarkerClickListener(marker, cb) {
    marker.getElement()?.addEventListener('click', cb);
  },
  addPolyline(map, path, opts) {
    const id = `line-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
    const coordinates = path.map((p) => [p.lng, p.lat]);
    map.addSource(id, {
      type: 'geojson',
      data: { type: 'Feature', geometry: { type: 'LineString', coordinates }, properties: {} },
    });
    const paint: any = {
      'line-color': opts.color,
      'line-width': opts.weight,
      'line-opacity': opts.opacity,
    };
    if (opts.dash) paint['line-dasharray'] = opts.dash;
    map.addLayer({ id, type: 'line', source: id, paint });
    return { _type: 'maplibre-line', id, sourceId: id };
  },
  addCircle(map, center, radius, opts) {
    const id = `circle-${Date.now()}-${Math.random().toString(36).slice(2, 6)}`;
    // Approximate radius in degrees for rendering (rough conversion at Indian latitudes)
    const degPerMeter = 1 / 111320;
    const r = radius * degPerMeter;
    const steps = 32;
    const coordinates: [number, number][] = [];
    for (let i = 0; i <= steps; i++) {
      const angle = (i / steps) * 2 * Math.PI;
      coordinates.push([
        center.lng + r * Math.cos(angle),
        center.lat + r * Math.sin(angle),
      ]);
    }
    map.addSource(id, {
      type: 'geojson',
      data: {
        type: 'Feature',
        geometry: { type: 'Polygon', coordinates: [coordinates] },
        properties: {},
      },
    });
    map.addLayer({
      id,
      type: 'fill',
      source: id,
      paint: {
        'fill-color': opts.fillColor,
        'fill-opacity': opts.fillOpacity,
      },
    });
    return { _type: 'maplibre-fill', id, sourceId: id };
  },
  removeOverlay(map, overlay) {
    try {
      if (!overlay) return;
      if (overlay.remove) {
        // MapLibre Marker
        overlay.remove();
      } else if (overlay._type === 'maplibre-line' || overlay._type === 'maplibre-fill') {
        if (map.getLayer(overlay.id)) map.removeLayer(overlay.id);
        if (map.getSource(overlay.sourceId)) map.removeSource(overlay.sourceId);
      }
    } catch { /* ok */ }
  },
  fitBounds(map, sw, ne, padding) {
    try {
      map.fitBounds([[sw.lng, sw.lat], [ne.lng, ne.lat]], { padding });
    } catch { /* degrade */ }
  },
};

function getEngine(): MapEngine {
  return getMapEngine() === 'mappls' ? mapplsEngine : maplibreEngine;
}

// ── MapView Component ─────────────────────────────────────────────────

export function MapView() {
  const { station, hour, layer, setSelectedZone, setPanel, setPanelOpen } = useAppState();
  const { simResult, routeTarget } = useMapOverlay();

  const mapRef = useRef<any>(null);
  const heatRef = useRef<MapplsHeatLayer | null>(null);
  const markersRef = useRef<any[]>([]);
  const arrowRef = useRef<any[]>([]);
  const simRef = useRef<any[]>([]);
  const routeRef = useRef<any[]>([]);
  const stationMarkerRef = useRef<any>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const engineRef = useRef<MapEngine>(getEngine());
  // Flips true once the map's async `load` event fires. Including this in the
  // overlay effects' deps guarantees they re-run after the map is ready, even
  // when query data resolved from cache before load completed.
  const [mapReady, setMapReady] = useState(false);
  // Current map zoom → drives multi-resolution heatmap aggregation.
  const [zoom, setZoom] = useState(14);

  // Zoom → backend heatmap resolution: zoomed out = coarse ~1km blobs,
  // zoomed in = fine detail. (undefined = full per-cell resolution.)
  const resolution = zoom <= 12 ? 2 : zoom <= 14 ? 3 : undefined;

  const heatmap = useHeatmap(hour, layer, !!station, resolution);
  const topZones = useTopZones(hour, !!station);
  const arrows = useSpilloverArrows(layer === 'spillover' && !!station);

  const removeOverlay = useCallback((overlay: any) => {
    if (overlay && mapRef.current) {
      engineRef.current.removeOverlay(mapRef.current, overlay);
    }
  }, []);

  // ── Init map once a station is chosen ───────────────────────────────
  useEffect(() => {
    if (!station || !containerRef.current) return;
    const E = engineRef.current;

    if (!mapRef.current) {
      const map = E.createMap(containerRef.current, { lat: station.lat, lng: station.lon }, 14);

      E.onLoad(map, () => {
        mapRef.current = map;
        setMapReady(true);
        setZoom(E.getZoom(map));
        // Re-aggregate the heatmap as the user zooms (debounced via state).
        E.onZoomEnd(map, () => {
          const z = E.getZoom(map);
          setZoom((prev) => (Math.round(z) !== Math.round(prev) ? z : prev));
        });
        // Add station base marker
        stationMarkerRef.current = E.addMarker(
          map,
          { lat: station.lat, lng: station.lon },
          stationSvg(),
          32,
          `<div><strong>${station.name}</strong><br><span style="color:#9CA3AF">Base Station</span></div>`,
        );
      });
    } else {
      E.setCenter(mapRef.current, { lat: station.lat, lng: station.lon });
      E.setZoom(mapRef.current, 14);

      if (stationMarkerRef.current) {
        removeOverlay(stationMarkerRef.current);
        stationMarkerRef.current = null;
      }
      stationMarkerRef.current = E.addMarker(
        mapRef.current,
        { lat: station.lat, lng: station.lon },
        stationSvg(),
        32,
        `<div><strong>${station.name}</strong><br><span style="color:#9CA3AF">Base Station</span></div>`,
      );
    }

    return () => {
      if (stationMarkerRef.current) {
        removeOverlay(stationMarkerRef.current);
        stationMarkerRef.current = null;
      }
    };
  }, [station, removeOverlay]);

  // ── Heatmap layer ────────────────────────────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !heatmap.data) return;

    if (heatRef.current) {
      heatRef.current.remove();
      heatRef.current = null;
    }

    const max = heatmap.data.max_intensity || 1;
    const pts = heatmap.data.points.map((p) => ({
      lat: p.lat,
      lon: p.lon,
      intensity: p.intensity / max,
    }));

    heatRef.current = new MapplsHeatLayer(map, pts, {
      radius: 25,
      blur: 16,
      max: 1.0,
      gradient: HEAT_GRADIENTS[layer],
    });
  }, [heatmap.data, layer, mapReady]);

  // ── Hotspot markers ──────────────────────────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !topZones.data) return;
    const E = engineRef.current;

    markersRef.current.forEach(removeOverlay);
    markersRef.current = [];

    topZones.data.forEach((z) => {
      const color = riskColor(z.risk_label);
      const size = z.risk_label === 'HIGH' || z.risk_label === 'CRITICAL' ? 16 : 12;

      const marker = E.addMarker(
        map,
        { lat: z.lat, lng: z.lon },
        dotSvg(size, color),
        size,
        `<div style="min-width:150px"><strong>${z.h3_id}</strong><br><span style="color:#9ca3af">Impact: <strong style="color:${color}">${z.congestion_impact.toFixed(0)}</strong> (${z.impact_band})</span></div>`,
      );

      E.addMarkerClickListener(marker, () => {
        setSelectedZone(z);
        setPanel('details');
        setPanelOpen(true);
      });

      markersRef.current.push(marker);
    });
  }, [topZones.data, removeOverlay, setSelectedZone, setPanel, setPanelOpen, mapReady]);

  // ── Spillover arrows ─────────────────────────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const E = engineRef.current;

    arrowRef.current.forEach(removeOverlay);
    arrowRef.current = [];

    if (layer !== 'spillover' || !arrows.data) return;

    arrows.data
      .filter((a) => a.hour === hour)
      .forEach((a) => {
        const line = E.addPolyline(map, [
          { lat: a.from_lat, lng: a.from_lon },
          { lat: a.to_lat, lng: a.to_lon },
        ], { color: '#F43F5E', weight: 2.5, opacity: 0.75, dash: [5, 5] });

        const head = E.addCircle(map, { lat: a.to_lat, lng: a.to_lon }, 30, {
          fillColor: '#F43F5E',
          fillOpacity: 1,
          strokeColor: '#fff',
          strokeWeight: 1,
        });

        arrowRef.current.push(line, head);
      });
  }, [arrows.data, layer, hour, removeOverlay, mapReady]);

  // ── Simulation overlay ───────────────────────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const E = engineRef.current;

    simRef.current.forEach(removeOverlay);
    simRef.current = [];

    if (!simResult) return;

    simResult.allocations.forEach((a) => {
      const color = TEAM_COLORS[(a.team_id - 1) % TEAM_COLORS.length];
      const marker = E.addMarker(
        map,
        { lat: a.lat, lng: a.lon },
        teamSvg(color, a.team_id),
        36,   // width
        `<strong>Team ${a.team_id}</strong><br>Zone ${a.h3_id}<br>Impact ${a.congestion_impact.toFixed(0)} · Rank #${a.priority_rank}`,
      );
      simRef.current.push(marker);
    });

    simResult.spillover_zones.forEach((s) => {
      const up = s.change_pct > 0;
      const circle = E.addCircle(map, { lat: s.lat, lng: s.lon }, 60, {
        fillColor: up ? '#EF4444' : '#10B981',
        fillOpacity: 0.5,
        strokeColor: '#fff',
        strokeWeight: 1,
      });
      simRef.current.push(circle);
    });
  }, [simResult, removeOverlay, mapReady]);

  // ── Route overlay ────────────────────────────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !station) return;
    const E = engineRef.current;

    routeRef.current.forEach(removeOverlay);
    routeRef.current = [];

    if (!routeTarget) return;

    const line = E.addPolyline(map, [
      { lat: station.lat, lng: station.lon },
      { lat: routeTarget.lat, lng: routeTarget.lon },
    ], { color: '#2A9D8F', weight: 3.5, opacity: 0.85, dash: [8, 6] });

    const dest = E.addMarker(
      map,
      { lat: routeTarget.lat, lng: routeTarget.lon },
      dotSvg(20, '#DC2626'),
      20,
    );

    routeRef.current.push(line, dest);

    E.fitBounds(
      map,
      { lat: Math.min(station.lat, routeTarget.lat), lng: Math.min(station.lon, routeTarget.lon) },
      { lat: Math.max(station.lat, routeTarget.lat), lng: Math.max(station.lon, routeTarget.lon) },
      60,
    );
  }, [routeTarget, station, removeOverlay, mapReady]);

  const loading = heatmap.isFetching || topZones.isFetching;

  function handleZoom(dir: 1 | -1) {
    const map = mapRef.current;
    if (!map) return;
    if (dir === 1) engineRef.current.zoomIn(map);
    else engineRef.current.zoomOut(map);
  }

  return (
    <div className="map-container">
      <div id="map" ref={containerRef} />
      <LayerToggle />

      {/* Custom zoom controls — bottom-right, never overlaps layer toggle or right panel */}
      <div className="map-zoom-ctrl">
        <button className="zoom-btn" onClick={() => handleZoom(1)} title="Zoom in">＋</button>
        <button className="zoom-btn" onClick={() => handleZoom(-1)} title="Zoom out">－</button>
      </div>

      {/* Multi-resolution indicator — shows the heatmap re-aggregating with zoom */}
      <div className="map-res-badge" title="Heatmap aggregation adapts to zoom level">
        {resolution === 2 ? 'City view · ~1km blobs'
          : resolution === 3 ? 'District view · ~100m'
          : 'Street view · full detail'}
      </div>

      {loading && (
        <div className="map-loading">
          <div className="loading-spinner" />
          <span>Loading…</span>
        </div>
      )}
    </div>
  );
}
