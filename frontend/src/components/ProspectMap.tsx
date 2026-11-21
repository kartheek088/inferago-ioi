import "leaflet/dist/leaflet.css";
import { useEffect, useRef, useState } from "react";
import { CircleMarker, MapContainer, TileLayer, Tooltip, useMapEvents } from "react-leaflet";
import type { LatLngBounds } from "leaflet";
import { api } from "../api";

type Point = [number, number, number, number, string | null, string];
interface Points { total: number; shown: number; points: Point[] }

const COLOR: Record<string, string> = { definite: "#16a34a", likely: "#2563eb", maybe: "#9ca3af" };

function Watcher({ onMove }: { onMove: (b: LatLngBounds) => void }) {
  const map = useMapEvents({ moveend: () => onMove(map.getBounds()) });
  useEffect(() => onMove(map.getBounds()), []); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}

/** Free OpenStreetMap tiles. Shows the best prospects inside the visible area (filters apply). */
export default function ProspectMap({ filters, onOpen }: { filters: Record<string, string | boolean | undefined>; onOpen: (id: number) => void }) {
  const [data, setData] = useState<Points | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const bounds = useRef<LatLngBounds | null>(null);
  const seq = useRef(0);
  const load = (b: LatLngBounds | null) => {
    if (!b) return;
    bounds.current = b;
    const id = ++seq.current;
    api.get<Points>("/prospects/map-points", {
      ...filters,
      min_lat: b.getSouth(), min_lon: b.getWest(), max_lat: b.getNorth(), max_lon: b.getEast(), limit: 3000,
    } as Record<string, string | number | boolean | undefined>)
      .then((d) => { if (id === seq.current) { setData(d); setErr(null); } })
      .catch((e) => id === seq.current && setErr(String(e)));
  };
  const key = JSON.stringify(filters);
  useEffect(() => load(bounds.current), [key]); // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="map-wrap">
      <MapContainer center={[22.5, 79]} zoom={5} preferCanvas className="map" scrollWheelZoom>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
          maxZoom={19}
        />
        <Watcher onMove={load} />
        {data?.points.map(([id, lat, lon, score, need, name]) => (
          <CircleMarker key={id} center={[lat, lon]} radius={score >= 80 ? 6 : 4}
            pathOptions={{ color: COLOR[need ?? "maybe"], fillColor: COLOR[need ?? "maybe"], fillOpacity: 0.75, weight: 1 }}
            eventHandlers={{ click: () => onOpen(id) }}>
            <Tooltip>{name} · {Math.round(score)}</Tooltip>
          </CircleMarker>
        ))}
      </MapContainer>
      <div className="map-legend small">
        {data && <span><strong>{data.shown.toLocaleString()}</strong> shown of {data.total.toLocaleString()} in this area{data.total > data.shown ? " (best first; zoom in for more)" : ""}</span>}
        <span><i style={{ background: COLOR.definite }} /> Definitely</span>
        <span><i style={{ background: COLOR.likely }} /> Likely</span>
        <span><i style={{ background: COLOR.maybe }} /> Maybe</span>
        {err && <span className="bad-text">{err}</span>}
      </div>
    </div>
  );
}
