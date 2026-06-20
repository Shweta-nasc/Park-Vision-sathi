import { useEffect, useRef } from 'react';
import L from 'leaflet';
import 'leaflet.heat';
import { useAppState } from '@/state/AppState';
import { useMapOverlay } from '@/state/MapOverlay';
import { useHeatmap, useTopZones, useSpilloverArrows } from '@/hooks/queries';
import { HEAT_GRADIENTS, riskColor } from '@/utils/risk';
import { LayerToggle } from './LayerToggle';

const TEAM_COLORS = [
  '#2A9D8F', '#E76F51', '#457B9D', '#F4A261', '#9B5DE5',
  '#00BBF9', '#F15BB5', '#EAB308', '#8338EC', '#FF006E',
  '#3A86C8', '#38B000', '#70E000', '#06B6D4', '#FB5607',
];

// Mappls raster tiles if a key is provided, else CartoDB dark fallback.
const MAPPLS_KEY = import.meta.env.VITE_MAPPLS_KEY as string | undefined;

export function MapView() {
  const { station, hour, layer, setSelectedZone, setPanel } = useAppState();
  const { simResult, routeTarget } = useMapOverlay();

  const mapRef = useRef<L.Map | null>(null);
  const heatRef = useRef<any>(null);
  const markersRef = useRef<L.Layer[]>([]);
  const arrowRef = useRef<L.Layer[]>([]);
  const simRef = useRef<L.Layer[]>([]);
  const routeRef = useRef<L.Layer[]>([]);
  const containerRef = useRef<HTMLDivElement | null>(null);

  const heatmap = useHeatmap(hour, layer, !!station);
  const topZones = useTopZones(hour, !!station);
  const arrows = useSpilloverArrows(layer === 'spillover' && !!station);

  // ── Init map once a station is chosen ───────────────────────────────
  useEffect(() => {
    if (!station || !containerRef.current) return;
    if (!mapRef.current) {
      const map = L.map(containerRef.current, {
        center: [station.lat, station.lon],
        zoom: 14,
        zoomControl: true,
      });
      if (MAPPLS_KEY) {
        L.tileLayer(
          `https://apis.mappls.com/advancedmaps/v1/${MAPPLS_KEY}/still_map/get_tile?type=roadmap&x={x}&y={y}&z={z}`,
          { attribution: '&copy; MapmyIndia', maxZoom: 20 },
        ).addTo(map);
      } else {
        L.tileLayer('https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png', {
          attribution: '&copy; CARTO',
          subdomains: 'abcd',
          maxZoom: 20,
        }).addTo(map);
      }
      mapRef.current = map;
    } else {
      mapRef.current.setView([station.lat, station.lon], 14);
    }
    // station base marker
    const icon = L.divIcon({
      className: '',
      html: `<div class="station-pin"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2.5"><path d="M12 22s-8-4.5-8-11.8A8 8 0 0 1 12 2a8 8 0 0 1 8 8.2c0 7.3-8 11.8-8 11.8z"/><circle cx="12" cy="10" r="3"/></svg></div>`,
      iconSize: [32, 32],
      iconAnchor: [16, 16],
    });
    const m = L.marker([station.lat, station.lon], { icon }).addTo(mapRef.current!);
    m.bindPopup(`<strong>${station.name}</strong><br><span style="color:#9CA3AF">Base Station</span>`);
    setTimeout(() => mapRef.current?.invalidateSize(), 100);
    return () => {
      m.remove();
    };
  }, [station]);

  // ── Heatmap layer ────────────────────────────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !heatmap.data) return;
    if (heatRef.current) {
      map.removeLayer(heatRef.current);
      heatRef.current = null;
    }
    const max = heatmap.data.max_intensity || 1;
    const pts = heatmap.data.points.map((p) => [p.lat, p.lon, p.intensity / max] as [number, number, number]);
    // @ts-expect-error leaflet.heat augments L at runtime
    heatRef.current = L.heatLayer(pts, {
      radius: 25,
      blur: 16,
      max: 1.0,
      gradient: HEAT_GRADIENTS[layer],
    }).addTo(map);
  }, [heatmap.data, layer]);

  // ── Hotspot markers ──────────────────────────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !topZones.data) return;
    markersRef.current.forEach((m) => map.removeLayer(m));
    markersRef.current = [];
    topZones.data.forEach((z) => {
      const color = riskColor(z.risk_label);
      const size = z.risk_label === 'HIGH' || z.risk_label === 'CRITICAL' ? 16 : 12;
      const icon = L.divIcon({
        className: '',
        html: `<div style="width:${size}px;height:${size}px;background:${color};border:2px solid white;border-radius:50%;box-shadow:0 1px 4px rgba(0,0,0,0.5)"></div>`,
        iconSize: [size, size],
        iconAnchor: [size / 2, size / 2],
      });
      const marker = L.marker([z.lat, z.lon], { icon }).addTo(map);
      marker.bindPopup(
        `<div style="min-width:150px"><strong>${z.h3_id}</strong><br><span style="color:#9ca3af">Impact: <strong style="color:${color}">${z.congestion_impact.toFixed(0)}</strong> (${z.impact_band})</span></div>`,
      );
      marker.on('click', () => {
        setSelectedZone(z);
        setPanel('details');
      });
      markersRef.current.push(marker);
    });
  }, [topZones.data]);

  // ── Spillover arrows ─────────────────────────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    arrowRef.current.forEach((l) => map.removeLayer(l));
    arrowRef.current = [];
    if (layer !== 'spillover' || !arrows.data) return;
    arrows.data
      .filter((a) => a.hour === hour)
      .forEach((a) => {
        const line = L.polyline(
          [
            [a.from_lat, a.from_lon],
            [a.to_lat, a.to_lon],
          ],
          { color: '#F43F5E', weight: 2.5, dashArray: '5,5', opacity: 0.75 },
        ).addTo(map);
        const head = L.circleMarker([a.to_lat, a.to_lon], {
          radius: 4,
          fillColor: '#F43F5E',
          fillOpacity: 1,
          color: '#fff',
          weight: 1,
        })
          .addTo(map)
          .bindPopup(`<strong>Waterbed Spillover</strong><br>Risk shifted: +${a.magnitude.toFixed(1)}`);
        arrowRef.current.push(line, head);
      });
  }, [arrows.data, layer, hour]);

  // ── Simulation overlay ───────────────────────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    simRef.current.forEach((l) => map.removeLayer(l));
    simRef.current = [];
    if (!simResult) return;
    simResult.allocations.forEach((a) => {
      const color = TEAM_COLORS[(a.team_id - 1) % TEAM_COLORS.length];
      const icon = L.divIcon({
        className: '',
        html: `<div class="team-marker" style="background:${color}">${a.team_id}</div>`,
        iconSize: [30, 30],
        iconAnchor: [15, 15],
      });
      const marker = L.marker([a.lat, a.lon], { icon }).addTo(map);
      marker.bindPopup(
        `<strong>Team ${a.team_id}</strong><br>Zone ${a.h3_id}<br>Impact ${a.congestion_impact.toFixed(0)} · Rank #${a.priority_rank}`,
      );
      simRef.current.push(marker);
    });
    simResult.spillover_zones.forEach((s) => {
      const up = s.change_pct > 0;
      const circle = L.circleMarker([s.lat, s.lon], {
        radius: 9,
        fillColor: up ? '#EF4444' : '#10B981',
        fillOpacity: 0.5,
        color: '#fff',
        weight: 1,
        className: up ? 'spillover-ripple' : '',
      }).addTo(map);
      circle.bindPopup(
        `<strong>Spillover</strong><br>${s.h3_id}<br>${s.original_impact.toFixed(1)} → ${s.adjusted_impact.toFixed(1)} (${up ? '+' : ''}${s.change_pct.toFixed(1)}%)`,
      );
      simRef.current.push(circle);
    });
  }, [simResult]);

  // ── Route overlay ────────────────────────────────────────────────────
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !station) return;
    routeRef.current.forEach((l) => map.removeLayer(l));
    routeRef.current = [];
    if (!routeTarget) return;
    const line = L.polyline(
      [
        [station.lat, station.lon],
        [routeTarget.lat, routeTarget.lon],
      ],
      { color: '#2A9D8F', weight: 3.5, opacity: 0.85, dashArray: '8,6' },
    ).addTo(map);
    const destIcon = L.divIcon({
      className: '',
      html: `<div style="width:20px;height:20px;background:#DC2626;border:3px solid white;border-radius:50%;box-shadow:0 1px 4px rgba(0,0,0,0.5)"></div>`,
      iconSize: [20, 20],
      iconAnchor: [10, 10],
    });
    const dest = L.marker([routeTarget.lat, routeTarget.lon], { icon: destIcon }).addTo(map);
    routeRef.current.push(line, dest);
    map.fitBounds(
      [
        [station.lat, station.lon],
        [routeTarget.lat, routeTarget.lon],
      ],
      { padding: [60, 60] },
    );
  }, [routeTarget, station]);

  const loading = heatmap.isFetching || topZones.isFetching;

  return (
    <div className="map-container">
      <div id="map" ref={containerRef} />
      <LayerToggle />
      {loading && (
        <div className="map-loading">
          <div className="loading-spinner" />
          <span>Loading…</span>
        </div>
      )}
    </div>
  );
}
