import { useCallback, useEffect, useRef, useState } from "react";
import {
  AlertCircle,
  Check,
  FileUp,
  Loader2,
  Package,
  Pill,
  X,
} from "lucide-react";
import { api } from "../lib/api";
import type { Medication, MedicationState } from "../lib/api";
import { useHousehold } from "../lib/household";

/**
 * Medicines.
 *
 * Two jobs on one screen: bring in a prescription, and record what is actually
 * happening. Recording is deliberately explicit — the caregiver states what they saw,
 * and the app stores it with a source rather than inferring anything.
 */
export default function Medicines() {
  const { patient } = useHousehold();
  const [meds, setMeds] = useState<Medication[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [pending, setPending] = useState<Medication[] | null>(null);
  const [active, setActive] = useState<Medication | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    if (!patient) return;
    setLoading(true);
    setError(null);
    try {
      const [all, review] = await Promise.all([
        api.medications(patient.household_member_id),
        api.medicationsForMember(patient.household_member_id),
      ]);
      setMeds(all);
      setPending(review);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load medicines.");
    } finally {
      setLoading(false);
    }
  }, [patient]);

  useEffect(() => {
    void load();
  }, [load]);

  async function onFile(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file || !patient) return;

    setUploading(true);
    setError(null);
    try {
      const prescription = await api.uploadPrescription(patient.household_member_id, file);
      if (prescription.ocr_status === "FAILED") {
        setError(
          "The file was read but no medicines were recognised. Try a clearer photo, or enter them by hand.",
        );
      } else {
        setPreview(prescription);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not upload the prescription.");
    } finally {
      setUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  }

  const [preview, setPreview] = useState<Awaited<ReturnType<typeof api.uploadPrescription>> | null>(
    null,
  );

  if (!patient) return null;

  return (
    <div className="mx-auto max-w-[1080px]">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="font-inter text-[12.5px] uppercase tracking-wide text-ink/40">Medicines</p>
          <h1 className="mt-1 font-dm text-[28px] font-normal leading-tight tracking-[-0.04em] text-ink sm:text-[34px]">
            The record
          </h1>
        </div>
        <div>
          <input
            ref={fileRef}
            type="file"
            accept="image/jpeg,image/png,application/pdf"
            onChange={onFile}
            className="hidden"
          />
          <button
            type="button"
            disabled={uploading}
            onClick={() => fileRef.current?.click()}
            className="flex items-center gap-2 rounded-md bg-ink px-3.5 py-2 font-inter text-[13px] font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-60"
          >
            {uploading ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={2} />
            ) : (
              <FileUp className="h-3.5 w-3.5" strokeWidth={1.8} />
            )}
            {uploading ? "Reading…" : "Add prescription"}
          </button>
        </div>
      </div>

      {error && (
        <p className="mt-4 rounded-lg border border-amber-300 bg-amber-50 px-4 py-3 font-inter text-[13px] leading-snug text-amber-900">
          {error}
        </p>
      )}

      {preview && (
        <VerifyPanel
          prescription={preview}
          onDone={() => {
            setPreview(null);
            void load();
          }}
          onCancel={() => setPreview(null)}
        />
      )}

      {pending && pending.length > 0 && (
        <div className="mt-5 rounded-xl border border-amber-300 bg-amber-50 px-4 py-3.5">
          <p className="flex items-center gap-2 font-inter text-[13px] font-medium text-amber-900">
            <AlertCircle className="h-4 w-4" strokeWidth={1.8} />
            {pending.length} medicine{pending.length === 1 ? "" : "s"} could not be matched to a known name
          </p>
          <p className="mt-1 font-inter text-[12px] leading-relaxed text-amber-800">
            These are stored exactly as read, and are not treated as normalised. Confirm them
            when you can check the packaging.
          </p>
        </div>
      )}

      {loading ? (
        <p className="mt-8 font-inter text-[13px] text-ink/40">Loading…</p>
      ) : meds.length === 0 ? (
        <div className="mt-8 rounded-xl border border-dashed border-ink/20 bg-paper px-6 py-12 text-center">
          <Pill className="mx-auto h-6 w-6 text-ink/25" strokeWidth={1.6} />
          <p className="mt-3 font-dm text-[17px] tracking-[-0.02em] text-ink">No medicines yet</p>
          <p className="mx-auto mt-1.5 max-w-[380px] font-inter text-[13px] leading-relaxed text-ink/50">
            Upload a prescription photo. You will see what was read, and confirm it before
            anything is trusted.
          </p>
        </div>
      ) : (
        <ul className="mt-5 space-y-2.5">
          {meds.map((med) => (
            <li key={med.id}>
              <button
                type="button"
                onClick={() => setActive(med)}
                className="flex w-full items-center gap-3.5 rounded-xl border border-ink/10 bg-paper px-4 py-3.5 text-left transition-colors hover:border-ink/25"
              >
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-ink/[0.06]">
                  <Pill className="h-4 w-4 text-ink/50" strokeWidth={1.7} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-inter text-[14px] font-medium text-ink">
                    {med.name_generic ?? med.name_raw}
                    {med.strength ? (
                      <span className="ml-1.5 font-normal text-ink/45">{med.strength}</span>
                    ) : null}
                  </span>
                  <span className="block font-inter text-[12px] text-ink/45">
                    {med.frequency ?? "Frequency not recorded"}
                    {med.name_generic && med.name_raw !== med.name_generic
                      ? ` · read as "${med.name_raw}"`
                      : ""}
                  </span>
                </span>
                {med.normalization_status !== "NORMALIZED" &&
                  med.normalization_status !== "MANUALLY_VERIFIED" && (
                    <span className="shrink-0 rounded-full bg-amber-500/15 px-2.5 py-1 font-inter text-[10.5px] font-medium text-amber-800">
                      Unconfirmed
                    </span>
                  )}
              </button>
            </li>
          ))}
        </ul>
      )}

      {active && (
        <EvidenceDrawer
          medication={active}
          onClose={() => setActive(null)}
          onSaved={() => {
            setActive(null);
            void load();
          }}
        />
      )}
    </div>
  );
}

// ── Prescription verification ────────────────────────────────────────

function VerifyPanel({
  prescription,
  onDone,
  onCancel,
}: {
  prescription: Awaited<ReturnType<typeof api.uploadPrescription>>;
  onDone: () => void;
  onCancel: () => void;
}) {
  const [items, setItems] = useState(prescription.items);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function confirm() {
    setBusy(true);
    setError(null);
    try {
      await api.verifyPrescription(
        prescription.id,
        items.map((item) => ({
          item_id: item.id,
          medication_name: item.medication_name,
          dosage: item.dosage,
          frequency: item.frequency,
        })),
      );
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not confirm these items.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mt-5 rounded-xl border border-ink/15 bg-paper p-5">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="font-dm text-[17px] font-medium tracking-[-0.03em] text-ink">
            What the prescription says
          </h2>
          <p className="mt-1 font-inter text-[12.5px] leading-relaxed text-ink/50">
            Nothing is trusted until you confirm it. Correct anything that was misread.
          </p>
        </div>
        <button
          type="button"
          onClick={onCancel}
          aria-label="Discard"
          className="text-ink/30 transition-colors hover:text-ink"
        >
          <X className="h-4 w-4" strokeWidth={1.8} />
        </button>
      </div>

      <ul className="mt-4 space-y-2">
        {items.map((item, index) => (
          <li key={item.id} className="rounded-lg border border-ink/10 px-3 py-2.5">
            <div className="flex items-center gap-2">
              <input
                value={item.medication_name}
                onChange={(event) => {
                  const next = [...items];
                  next[index] = { ...item, medication_name: event.target.value };
                  setItems(next);
                }}
                className="min-w-0 flex-1 border-0 bg-transparent font-inter text-[14px] font-medium text-ink outline-none"
              />
              <span className="shrink-0 font-inter text-[10.5px] text-ink/35">
                {Math.round(item.confidence * 100)}% confident
              </span>
            </div>
            <div className="mt-1 flex gap-2">
              <input
                value={item.dosage ?? ""}
                placeholder="dose"
                onChange={(event) => {
                  const next = [...items];
                  next[index] = { ...item, dosage: event.target.value };
                  setItems(next);
                }}
                className="w-24 border-0 bg-transparent font-inter text-[12px] text-ink/60 outline-none placeholder:text-ink/25"
              />
              <input
                value={item.frequency ?? ""}
                placeholder="how often"
                onChange={(event) => {
                  const next = [...items];
                  next[index] = { ...item, frequency: event.target.value };
                  setItems(next);
                }}
                className="min-w-0 flex-1 border-0 bg-transparent font-inter text-[12px] text-ink/60 outline-none placeholder:text-ink/25"
              />
            </div>
          </li>
        ))}
      </ul>

      {error && <p className="mt-3 font-inter text-[12.5px] text-red-700">{error}</p>}

      <div className="mt-4 flex items-center gap-2">
        <button
          type="button"
          onClick={() => void confirm()}
          disabled={busy || items.length === 0}
          className="flex items-center gap-2 rounded-md bg-ink px-3.5 py-2 font-inter text-[13px] font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
        >
          {busy ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={2} />
          ) : (
            <Check className="h-3.5 w-3.5" strokeWidth={2.2} />
          )}
          Confirm and add
        </button>
        <button
          type="button"
          onClick={onCancel}
          className="rounded-md px-3 py-2 font-inter text-[13px] text-ink/50 transition-colors hover:text-ink"
        >
          Discard
        </button>
      </div>
    </div>
  );
}

// ── Evidence capture ─────────────────────────────────────────────────

function EvidenceDrawer({
  medication,
  onClose,
  onSaved,
}: {
  medication: Medication;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [detail, setDetail] = useState<MedicationState | null>(null);
  const [mode, setMode] = useState<"report" | "availability" | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .medicationState(medication.id)
      .then(setDetail)
      .catch(() => setDetail(null));
  }, [medication.id]);

  async function submitReport(taking: boolean) {
    setBusy(true);
    setError(null);
    try {
      await api.report(medication.id, taking);
      await api.detect(medication.id).catch(() => undefined);
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save this report.");
      setBusy(false);
    }
  }

  async function submitAvailability(present: boolean, quantity: string, expiry: string) {
    setBusy(true);
    setError(null);
    try {
      await api.availability(
        medication.id,
        present,
        (quantity || null) as "ok" | "low" | "nearly empty" | null,
        expiry ? new Date(expiry).toISOString() : null,
      );
      await api.detect(medication.id).catch(() => undefined);
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save this check.");
      setBusy(false);
    }
  }

  const [quantity, setQuantity] = useState("ok");
  const [expiry, setExpiry] = useState("");

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/40" onClick={onClose}>
      <div
        className="h-full w-full max-w-[440px] overflow-y-auto bg-paper p-5 sm:p-6"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="font-inter text-[11.5px] uppercase tracking-wide text-ink/40">Medicine</p>
            <h2 className="mt-1 font-dm text-[22px] font-normal leading-tight tracking-[-0.03em] text-ink">
              {medication.name_generic ?? medication.name_raw}
            </h2>
            <p className="mt-0.5 font-inter text-[12.5px] text-ink/45">
              {[medication.strength, medication.frequency].filter(Boolean).join(" · ") ||
                "No dose recorded"}
            </p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="text-ink/30 hover:text-ink">
            <X className="h-4 w-4" strokeWidth={1.8} />
          </button>
        </div>

        {/* Current state, with sources */}
        {detail && (
          <div className="mt-5 rounded-lg border border-ink/10 bg-white p-3.5">
            <p className="font-inter text-[11px] uppercase tracking-wide text-ink/40">
              What we currently know
            </p>
            <ul className="mt-2 space-y-1.5">
              {[
                ["Prescribed", detail.prescribed],
                ["Patient reports", detail.reported_taking],
                ["Stock at home", detail.available],
                ["Confirmed status", detail.confirmed_status],
              ].map(([label, dim]) => {
                const d = dim as MedicationState["prescribed"];
                return (
                  <li key={label as string} className="flex items-baseline gap-2 font-inter text-[12.5px]">
                    <span className="w-[112px] shrink-0 text-ink/45">{label as string}</span>
                    <span className={d.status === "UNKNOWN" ? "text-ink/35" : "text-ink"}>
                      {d.status.toLowerCase().replace("_", " ")}
                    </span>
                    {d.age_days !== null && (
                      <span className={`ml-auto text-[11px] ${d.stale ? "text-amber-700" : "text-ink/30"}`}>
                        {d.age_days}d{d.stale ? " · stale" : ""}
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
          </div>
        )}

        {!mode && (
          <div className="mt-5 space-y-2">
            <button
              type="button"
              onClick={() => setMode("report")}
              className="flex w-full items-center gap-3 rounded-lg border border-ink/12 bg-white px-4 py-3 text-left transition-colors hover:border-ink/30"
            >
              <Pill className="h-4 w-4 text-ink/40" strokeWidth={1.7} />
              <span className="font-inter text-[13.5px] text-ink">Report taking or stopping</span>
            </button>
            <button
              type="button"
              onClick={() => setMode("availability")}
              className="flex w-full items-center gap-3 rounded-lg border border-ink/12 bg-white px-4 py-3 text-left transition-colors hover:border-ink/30"
            >
              <Package className="h-4 w-4 text-ink/40" strokeWidth={1.7} />
              <span className="font-inter text-[13.5px] text-ink">
                Record what is actually in the cabinet
              </span>
            </button>
          </div>
        )}

        {mode === "report" && (
          <div className="mt-5">
            <p className="font-inter text-[13px] text-ink/60">Is it being taken as prescribed?</p>
            <div className="mt-3 flex gap-2">
              <button
                type="button"
                disabled={busy}
                onClick={() => void submitReport(true)}
                className="flex-1 rounded-md bg-emerald-700 px-3 py-2.5 font-inter text-[13px] font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-60"
              >
                Yes, taking it
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void submitReport(false)}
                className="flex-1 rounded-md bg-ink px-3 py-2.5 font-inter text-[13px] font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-60"
              >
                No, stopped
              </button>
            </div>
            <p className="mt-2.5 font-inter text-[11.5px] leading-relaxed text-ink/40">
              This records what the patient said. It is not treated as proof.
            </p>
          </div>
        )}

        {mode === "availability" && (
          <div className="mt-5">
            <label className="block">
              <span className="font-inter text-[12.5px] font-medium text-ink/60">How much is left?</span>
              <select
                value={quantity}
                onChange={(event) => setQuantity(event.target.value)}
                className="mt-1.5 h-11 w-full rounded-md border border-ink/15 bg-white px-3 font-inter text-[13.5px] text-ink outline-none"
              >
                <option value="ok">Plenty</option>
                <option value="low">Running low</option>
                <option value="nearly empty">Nearly empty</option>
              </select>
            </label>

            <label className="mt-3 block">
              <span className="font-inter text-[12.5px] font-medium text-ink/60">
                Expiry date on the packet
              </span>
              <input
                type="date"
                value={expiry}
                onChange={(event) => setExpiry(event.target.value)}
                className="mt-1.5 h-11 w-full rounded-md border border-ink/15 bg-white px-3 font-inter text-[13.5px] text-ink outline-none"
              />
              <span className="mt-1 block font-inter text-[11.5px] text-ink/35">
                Read it from the strip. An expired medicine is tracked as an open case.
              </span>
            </label>

            <div className="mt-4 flex gap-2">
              <button
                type="button"
                disabled={busy}
                onClick={() => void submitAvailability(true, quantity, expiry)}
                className="flex-1 rounded-md bg-emerald-700 px-3 py-2.5 font-inter text-[13px] font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-60"
              >
                It is here
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() => void submitAvailability(false, quantity, expiry)}
                className="flex-1 rounded-md bg-ink px-3 py-2.5 font-inter text-[13px] font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-60"
              >
                Not found
              </button>
            </div>
          </div>
        )}

        {error && <p className="mt-3 font-inter text-[12.5px] text-red-700">{error}</p>}

        {mode && (
          <button
            type="button"
            onClick={() => setMode(null)}
            className="mt-3 font-inter text-[12.5px] text-ink/45 underline underline-offset-2 hover:text-ink"
          >
            Back
          </button>
        )}
      </div>
    </div>
  );
}
