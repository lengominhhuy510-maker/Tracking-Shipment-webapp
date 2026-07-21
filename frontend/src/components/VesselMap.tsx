import { useEffect, useState } from "react";
import { MapContainer, Marker, Polyline, Popup, TileLayer, useMap } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import markerIcon2x from "leaflet/dist/images/marker-icon-2x.png";
import markerIcon from "leaflet/dist/images/marker-icon.png";
import markerShadow from "leaflet/dist/images/marker-shadow.png";
import { getShipmentTrail, type TrailPoint } from "../api/client";

L.Icon.Default.mergeOptions({
  iconRetinaUrl: markerIcon2x,
  iconUrl: markerIcon,
  shadowUrl: markerShadow,
});

interface VesselMapProps {
  shipmentId: number;
  lat: number | null;
  lon: number | null;
  sog: number | null;
  cog: number | null;
  vesselName: string;
}

function RecenterOnPosition({ lat, lon }: { lat: number; lon: number }) {
  const map = useMap();
  useEffect(() => {
    map.panTo([lat, lon]);
  }, [map, lat, lon]);
  return null;
}

export default function VesselMap({ shipmentId, lat, lon, sog, cog, vesselName }: VesselMapProps) {
  const [trail, setTrail] = useState<TrailPoint[]>([]);

  useEffect(() => {
    let cancelled = false;
    getShipmentTrail(shipmentId)
      .then((points) => {
        if (!cancelled) setTrail(points);
      })
      .catch((error: unknown) => {
        console.warn("Failed to load trail", error);
      });
    return () => {
      cancelled = true;
    };
  }, [shipmentId, lat, lon]);

  if (lat === null || lon === null) {
    return <div className="vessel-map vessel-map-empty">Chưa có vị trí tàu</div>;
  }

  const trailLine = trail.map<[number, number]>((point) => [point.lat, point.lon]);

  return (
    <div className="vessel-map">
      <MapContainer center={[lat, lon]} zoom={6} style={{ height: 360, width: "100%" }}>
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {trailLine.length > 1 && <Polyline positions={trailLine} pathOptions={{ color: "#1d4ed8", weight: 2, dashArray: "4 6" }} />}
        <Marker position={[lat, lon]}>
          <Popup>
            <strong>{vesselName}</strong>
            <br />
            {sog !== null && <>SOG: {sog.toFixed(1)} kn<br /></>}
            {cog !== null && <>COG: {cog.toFixed(0)}°</>}
          </Popup>
        </Marker>
        <RecenterOnPosition lat={lat} lon={lon} />
      </MapContainer>
    </div>
  );
}
