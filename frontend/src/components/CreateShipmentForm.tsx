import { useState, type FormEvent } from "react";
import { ApiError, createShipment, type Incoterm, type ShipmentDetail, type ShipmentDirection } from "../api/client";

// §5/§8-bước-3: export ẩn hẳn nhóm E/F (EXW, FCA, FAS, FOB)
const EF_INCOTERMS: Incoterm[] = ["EXW", "FCA", "FAS", "FOB"];
const ALL_INCOTERMS: Incoterm[] = ["EXW", "FCA", "FAS", "FOB", "CFR", "CIF", "CPT", "CIP", "DAP", "DPU", "DDP"];

interface CreateShipmentFormProps {
  onCreated: (shipment: ShipmentDetail) => void;
  onCancel: () => void;
}

export default function CreateShipmentForm({ onCreated, onCancel }: CreateShipmentFormProps) {
  const [direction, setDirection] = useState<ShipmentDirection | "">("");
  const [incoterm, setIncoterm] = useState<Incoterm | "">("");
  const [fields, setFields] = useState({
    bl_number: "",
    container_no: "",
    carrier: "",
    vessel_name: "",
    voyage_no: "",
    pol: "",
    pod: "",
    eta_original: "",
    imo: "",
    mmsi: "",
  });
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const incotermOptions = direction === "export"
    ? ALL_INCOTERMS.filter((term) => !EF_INCOTERMS.includes(term))
    : ALL_INCOTERMS;

  const setField = (name: keyof typeof fields) => (event: { target: { value: string } }) => {
    setFields((prev) => ({ ...prev, [name]: event.target.value }));
  };

  const handleDirectionChange = (value: ShipmentDirection | "") => {
    setDirection(value);
    if (value === "export" && incoterm && EF_INCOTERMS.includes(incoterm)) {
      setIncoterm("");
    }
  };

  const handleSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (!direction || !incoterm) {
      setError("Chọn chiều lô hàng và Incoterm trước khi tạo.");
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const created = await createShipment({
        bl_number: fields.bl_number.trim(),
        container_no: fields.container_no.trim(),
        shipment_direction: direction,
        incoterm,
        carrier: fields.carrier.trim(),
        vessel_name: fields.vessel_name.trim(),
        voyage_no: fields.voyage_no.trim(),
        pol: fields.pol.trim(),
        pod: fields.pod.trim(),
        eta_original: fields.eta_original ? new Date(fields.eta_original).toISOString() : null,
        imo: fields.imo.trim() || null,
        mmsi: fields.mmsi.trim() || null,
      });
      onCreated(created);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Tạo lô thất bại, thử lại sau.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form className="create-shipment-form" onSubmit={handleSubmit}>
      <h2>Tạo lô hàng</h2>
      {error && <p className="form-error" role="alert">{error}</p>}

      <label>
        Chiều lô hàng *
        <select
          required
          value={direction}
          onChange={(event) => handleDirectionChange(event.target.value as ShipmentDirection | "")}
        >
          <option value="">— Chọn chiều trước —</option>
          <option value="import">Nhập khẩu (import)</option>
          <option value="export">Xuất khẩu (export)</option>
        </select>
      </label>

      <label>
        Incoterm *
        <select
          required
          value={incoterm}
          disabled={!direction}
          onChange={(event) => setIncoterm(event.target.value as Incoterm | "")}
        >
          <option value="">{direction ? "— Chọn Incoterm —" : "Chọn chiều lô hàng trước"}</option>
          {incotermOptions.map((term) => (
            <option key={term} value={term}>{term}</option>
          ))}
        </select>
      </label>

      <label>
        Số B/L *
        <input required value={fields.bl_number} onChange={setField("bl_number")} />
      </label>
      <label>
        Số container *
        <input required value={fields.container_no} onChange={setField("container_no")} />
      </label>
      <label>
        Hãng tàu *
        <input required value={fields.carrier} onChange={setField("carrier")} />
      </label>
      <label>
        Tên tàu *
        <input required value={fields.vessel_name} onChange={setField("vessel_name")} />
      </label>
      <label>
        Số chuyến *
        <input required value={fields.voyage_no} onChange={setField("voyage_no")} />
      </label>
      <label>
        Cảng đi (POL) *
        <input required value={fields.pol} onChange={setField("pol")} />
      </label>
      <label>
        Cảng đến (POD) *
        <input required value={fields.pod} onChange={setField("pod")} />
      </label>
      <label>
        ETA gốc
        <input type="datetime-local" value={fields.eta_original} onChange={setField("eta_original")} />
      </label>
      <label>
        IMO (7 số)
        <input value={fields.imo} onChange={setField("imo")} pattern="\d{7}" title="IMO gồm đúng 7 chữ số" />
      </label>
      <label>
        MMSI (9 số)
        <input value={fields.mmsi} onChange={setField("mmsi")} pattern="\d{9}" title="MMSI gồm đúng 9 chữ số" />
      </label>

      <div className="form-actions">
        <button type="submit" disabled={submitting}>{submitting ? "Đang tạo…" : "Tạo lô"}</button>
        <button type="button" onClick={onCancel} disabled={submitting}>Hủy</button>
      </div>
    </form>
  );
}
