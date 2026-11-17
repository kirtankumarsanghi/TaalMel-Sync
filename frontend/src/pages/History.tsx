import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  Check,
  Download,
  FileUp,
  FlaskConical,
  History as HistoryIcon,
  Loader2,
  Pill,
} from "lucide-react";
import { api } from "../lib/api";
import type {
  BulkImportResult,
  ConditionRow,
  LabComparison,
  Timeline,
} from "../lib/api";
import { useHousehold } from "../lib/household";

/**
 * Longitudinal history.
 *
 * Everything here comes from verified prescription lines. The screen states its own
 * basis: a missing medicine may mean an unreadable page, and a diagnosis is only a
 * label read off a page until a person confirms it.
 */
export default function HistoryPage() {
  const { patient } = useHousehold();
  const [timeline, setTimeline] = useState<Timeline | null>(null);
  const [labs, setLabs] = useState<LabComparison | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [year, setYear] = useState<string>("");

  const load = useCallback(async () => {
    if (!patient) return;
    setLoading(true);
    setError(null);
    try {
      const [history, comparison] = await Promise.all([
        api.medicationTimeline(patient.patient_id, year ? Number(year) : undefined),
        api.labComparison(patient.patient_id),
      ]);
      setTimeline(history);
      setLabs(comparison);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load the history.");
    } finally {
      setLoading(false);
    }
  }, [patient, year]);

  useEffect(() => {
    void load();
  }, [load]);

  const years = useMemo(
    () => (timeline ? timeline.years.map((row) => row.year).filter((y) => y !== "date not recorded") : []),
    [timeline],
  );

  async function download() {
    if (!patient) return;
    setDownloading(true);
    setError(null);
    try {
      const blob = await api.downloadDossier(patient.patient_id);
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `taalmel-history-${patient.display_name.replace(/\s+/g, "-")}.pdf`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not build the document.");
    } finally {
      setDownloading(false);
    }
  }

  if (!patient) return null;

  const doseChanges = (timeline?.medications ?? []).flatMap((medicine) =>
    medicine.episodes
      .filter((episode) => episode.dose_changed)
      .map((episode) => ({ medicine, episode })),
  );

  return (
    <div className="mx-auto max-w-[1080px] px-5 py-8 sm:px-8">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="font-dm text-[26px] font-medium tracking-[-0.04em] text-ink">
            History
          </h1>
          <p className="mt-1.5 max-w-[560px] font-inter text-[13px] leading-relaxed text-ink/50">
            Every medicine, dose change, diagnosis and lab comparison for{" "}
            {patient.display_name}, built only from prescription lines a person confirmed.
          </p>
        </div>
        <button
          type="button"
          onClick={() => void download()}
          disabled={downloading || loading}
          className="flex items-center gap-2 rounded-md bg-ink px-3.5 py-2 font-inter text-[13px] font-medium text-white disabled:opacity-50"
        >
          {downloading ? (
            <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={2} />
          ) : (
            <Download className="h-3.5 w-3.5" strokeWidth={2} />
          )}
          Download full record (PDF)
        </button>
      </header>

      {error && (
        <p className="mt-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 font-inter text-[13px] text-red-800">
          {error}
        </p>
      )}

      {loading ? (
        <p className="mt-10 font-inter text-[13px] text-ink/40">Loading the record…</p>
      ) : (
        <div className="mt-6 space-y-6">
          <ConditionsSection
            conditions={timeline?.conditions ?? []}
            onChanged={load}
            patientId={patient.patient_id}
          />

          <ImportStack patientId={patient.patient_id} onImported={load} />

          <section className="rounded-xl border border-ink/10 bg-paper p-5">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="flex items-center gap-2 font-dm text-[17px] font-medium tracking-[-0.03em] text-ink">
                <Pill className="h-4 w-4 text-ink/40" strokeWidth={1.8} />
                Medicines by year
              </h2>
              <label className="flex items-center gap-2 font-inter text-[12px] text-ink/50">
                Year
                <select
                  value={year}
                  onChange={(event) => setYear(event.target.value)}
                  className="h-8 rounded-md border border-ink/15 bg-white px-2 font-inter text-[12.5px] text-ink"
                >
                  <option value="">All years</option>
                  {years.map((value) => (
                    <option key={value} value={value}>
                      {value}
                    </option>
                  ))}
                </select>
              </label>
            </div>

            {(timeline?.years ?? []).length === 0 ? (
              <p className="mt-4 font-inter text-[13px] text-ink/50">
                No verified prescription lines yet. Upload a prescription and confirm what
                was read; it appears here by year.
              </p>
            ) : (
              <div className="mt-4 space-y-5">
                {timeline?.years.map((row) => (
                  <div key={row.year}>
                    <p className="font-dm text-[15px] font-medium text-ink">{row.year}</p>
                    <div className="mt-2 space-y-3">
                      {row.visits.map((visit, index) => (
                        <div
                          key={`${row.year}-${visit.prescription_id ?? index}`}
                          className="rounded-lg border border-ink/10 bg-white px-3.5 py-3"
                        >
                          <div className="flex flex-wrap items-baseline justify-between gap-2">
                            <p className="font-inter text-[12.5px] font-medium text-ink">
                              {visit.date ?? "Date not recorded"}
                              {visit.prescriber ? ` · ${visit.prescriber}` : ""}
                            </p>
                            {visit.filename && (
                              <p className="truncate font-inter text-[10.5px] text-ink/35">
                                {visit.filename}
                              </p>
                            )}
                          </div>
                          {visit.conditions.length > 0 && (
                            <p className="mt-1 font-inter text-[11.5px] text-ink/50">
                              Diagnosis read: {visit.conditions.map((c) => c.name).join(", ")}
                              {visit.conditions.some((c) => !c.confirmed) && " (unconfirmed)"}
                            </p>
                          )}
                          <ul className="mt-2 space-y-1">
                            {visit.medicines.map((medicine, medIndex) => (
                              <li
                                key={`${medicine.written_name}-${medIndex}`}
                                className="font-inter text-[13px] text-ink/80"
                              >
                                {medicine.name}
                                {medicine.dose ? ` · ${medicine.dose}` : ""}
                                {medicine.frequency ? ` · ${medicine.frequency}` : ""}
                              </li>
                            ))}
                          </ul>
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </section>

          <section className="rounded-xl border border-ink/10 bg-paper p-5">
            <h2 className="font-dm text-[17px] font-medium tracking-[-0.03em] text-ink">
              Dose changes
            </h2>
            {doseChanges.length === 0 ? (
              <p className="mt-3 font-inter text-[13px] text-ink/50">
                No dose change has been recorded between verified prescriptions.
              </p>
            ) : (
              <ul className="mt-3 divide-y divide-ink/[0.07]">
                {doseChanges.map(({ medicine, episode }, index) => (
                  <li key={`${medicine.generic}-${index}`} className="py-2.5">
                    <p className="font-inter text-[13px] text-ink">
                      {medicine.generic}:{" "}
                      <span className="text-ink/50">{episode.previous_dose ?? "not recorded"}</span>{" "}
                      → <span className="font-medium">{episode.dose ?? "not recorded"}</span>
                    </p>
                    <p className="mt-0.5 font-inter text-[11px] text-ink/40">
                      {episode.start ?? "date not recorded"}
                      {episode.sources[0]?.prescriber ? ` · ${episode.sources[0].prescriber}` : ""}
                      {episode.sources[0]?.filename ? ` · ${episode.sources[0].filename}` : ""}
                    </p>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <ConditionLinks timeline={timeline} />

          <section className="rounded-xl border border-ink/10 bg-paper p-5">
            <h2 className="flex items-center gap-2 font-dm text-[17px] font-medium tracking-[-0.03em] text-ink">
              <FlaskConical className="h-4 w-4 text-ink/40" strokeWidth={1.8} />
              Lab comparison
            </h2>
            {!labs || labs.tests.length === 0 ? (
              <p className="mt-3 font-inter text-[13px] text-ink/50">
                No lab values have been read yet. Upload a report in Wellness.
              </p>
            ) : (
              <>
                <p className="mt-2 font-inter text-[12px] text-ink/45">
                  {labs.summary.above} above, {labs.summary.below} below, {labs.summary.within} within
                  the range printed on their own reports.
                </p>
                <div className="mt-3 overflow-x-auto">
                  <table className="w-full min-w-[620px] border-collapse font-inter text-[12.5px]">
                    <thead>
                      <tr className="border-b border-ink/10 text-left text-[11px] uppercase tracking-wide text-ink/40">
                        <th className="py-2 pr-3 font-medium">Test</th>
                        <th className="py-2 pr-3 font-medium">Latest</th>
                        <th className="py-2 pr-3 font-medium">Printed range</th>
                        <th className="py-2 pr-3 font-medium">Position</th>
                        <th className="py-2 font-medium">Trend</th>
                      </tr>
                    </thead>
                    <tbody>
                      {labs.tests.map((test) => (
                        <tr key={`${test.test_name}-${test.unit ?? ""}`} className="border-b border-ink/[0.06]">
                          <td className="py-2 pr-3 text-ink">{test.test_name}</td>
                          <td className="py-2 pr-3 text-ink/70">
                            {test.latest_value ?? "—"}
                            {test.unit ? ` ${test.unit}` : ""}
                            {test.latest_date ? ` · ${test.latest_date}` : ""}
                          </td>
                          <td className="py-2 pr-3 text-ink/50">
                            {(() => {
                              const latest = test.points[test.points.length - 1];
                              if (!latest || (latest.range_low == null && latest.range_high == null)) {
                                return "not printed";
                              }
                              return `${latest.range_low ?? ""} – ${latest.range_high ?? ""}`;
                            })()}
                          </td>
                          <td className="py-2 pr-3 text-ink/70">{test.latest_status.toLowerCase()}</td>
                          <td className="py-2 text-ink/50">
                            {test.trend
                              ? `${test.trend.toLowerCase()}${test.change != null ? ` (${test.change > 0 ? "+" : ""}${test.change})` : ""}`
                              : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
                <p className="mt-2 font-inter text-[10.5px] leading-relaxed text-ink/35">
                  {labs.note}
                </p>
              </>
            )}
          </section>
        </div>
      )}
    </div>
  );
}

function ConditionsSection({
  conditions,
  patientId,
  onChanged,
}: {
  conditions: ConditionRow[];
  patientId: string;
  onChanged: () => Promise<void>;
}) {
  const [drafts, setDrafts] = useState<Record<string, string>>({});
  const [busyId, setBusyId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [manualName, setManualName] = useState("");
  const [manualDate, setManualDate] = useState("");

  async function confirm(condition: ConditionRow) {
    setBusyId(condition.id);
    setError(null);
    try {
      await api.verifyCondition(condition.id, drafts[condition.id] ?? condition.name);
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not confirm that diagnosis.");
    } finally {
      setBusyId(null);
    }
  }

  async function addManual() {
    if (!manualName.trim()) return;
    setBusyId("manual");
    setError(null);
    try {
      await api.addCondition(
        patientId,
        manualName.trim(),
        manualDate ? `${manualDate}T00:00:00Z` : null,
      );
      setManualName("");
      setManualDate("");
      await onChanged();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add that condition.");
    } finally {
      setBusyId(null);
    }
  }

  const unconfirmed = conditions.filter((condition) => !condition.confirmed);
  const confirmed = conditions.filter((condition) => condition.confirmed);

  return (
    <section className="rounded-xl border border-ink/10 bg-paper p-5">
      <h2 className="font-dm text-[17px] font-medium tracking-[-0.03em] text-ink">Conditions</h2>

      {unconfirmed.length > 0 && (
        <div className="mt-3 rounded-lg border border-amber-300 bg-amber-50 px-3.5 py-3">
          <p className="flex items-center gap-2 font-inter text-[12.5px] font-medium text-amber-900">
            <AlertCircle className="h-4 w-4" strokeWidth={1.8} />
            {unconfirmed.length} diagnosis mention{unconfirmed.length === 1 ? "" : "s"} read but not confirmed
          </p>
          <p className="mt-1 font-inter text-[11.5px] leading-relaxed text-amber-800">
            OCR can misread a diagnosis. Correct the wording, then confirm. Nothing is grouped
            by it until you do.
          </p>
          <ul className="mt-2.5 space-y-2">
            {unconfirmed.map((condition) => (
              <li key={condition.id} className="flex flex-wrap items-center gap-2">
                <input
                  value={drafts[condition.id] ?? condition.name}
                  onChange={(event) =>
                    setDrafts((current) => ({ ...current, [condition.id]: event.target.value }))
                  }
                  className="min-w-[220px] flex-1 rounded-md border border-amber-300 bg-white px-2.5 py-1.5 font-inter text-[12.5px] text-ink outline-none"
                />
                <button
                  type="button"
                  onClick={() => void confirm(condition)}
                  disabled={busyId === condition.id}
                  className="flex items-center gap-1.5 rounded-md border border-amber-400 bg-white px-2.5 py-1.5 font-inter text-[12px] text-amber-900 disabled:opacity-50"
                >
                  {busyId === condition.id ? (
                    <Loader2 className="h-3 w-3 animate-spin" strokeWidth={2} />
                  ) : (
                    <Check className="h-3 w-3" strokeWidth={2.2} />
                  )}
                  Confirm
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      <ul className="mt-3 space-y-1">
        {confirmed.map((condition) => (
          <li key={condition.id} className="font-inter text-[13px] text-ink/80">
            {condition.name}
            {condition.date ? <span className="text-ink/40"> · {condition.date}</span> : null}
          </li>
        ))}
        {confirmed.length === 0 && unconfirmed.length === 0 && (
          <li className="font-inter text-[13px] text-ink/50">
            No diagnosis has been recorded yet. Read one from a prescription, or add it below.
          </li>
        )}
      </ul>

      <div className="mt-3 flex flex-wrap items-end gap-2">
        <label className="flex-1">
          <span className="font-inter text-[11px] text-ink/45">Add a condition</span>
          <input
            value={manualName}
            onChange={(event) => setManualName(event.target.value)}
            placeholder="e.g. Hypertension"
            className="mt-1 h-8 w-full rounded-md border border-ink/15 bg-white px-2.5 font-inter text-[12.5px] text-ink outline-none"
          />
        </label>
        <label>
          <span className="font-inter text-[11px] text-ink/45">Since (optional)</span>
          <input
            type="date"
            value={manualDate}
            onChange={(event) => setManualDate(event.target.value)}
            className="mt-1 h-8 rounded-md border border-ink/15 bg-white px-2 font-inter text-[12.5px] text-ink outline-none"
          />
        </label>
        <button
          type="button"
          onClick={() => void addManual()}
          disabled={!manualName.trim() || busyId === "manual"}
          className="h-8 rounded-md border border-ink/15 bg-white px-3 font-inter text-[12px] text-ink/75 disabled:opacity-50"
        >
          Add
        </button>
      </div>

      {error && <p className="mt-2 font-inter text-[12px] text-red-700">{error}</p>}
    </section>
  );
}

function ConditionLinks({ timeline }: { timeline: Timeline | null }) {
  const links = timeline?.condition_links ?? [];
  if (links.length === 0) return null;

  return (
    <section className="rounded-xl border border-ink/10 bg-paper p-5">
      <h2 className="font-dm text-[17px] font-medium tracking-[-0.03em] text-ink">
        Condition and medicine, recorded together
      </h2>
      <div className="mt-3 space-y-3">
        {links.map((link) => (
          <div key={`${link.condition.id}-${link.prescription_id ?? ""}`} className="rounded-lg border border-ink/10 bg-white px-3.5 py-3">
            <p className="font-inter text-[13px] font-medium text-ink">
              {link.condition.name}
              {link.date ? <span className="font-normal text-ink/40"> · {link.date}</span> : null}
            </p>
            <p className="mt-1 font-inter text-[12.5px] text-ink/70">
              {link.medicines
                .map((medicine) => `${medicine.name}${medicine.dose ? ` ${medicine.dose}` : ""}`)
                .join(", ")}
            </p>
            <p className="mt-1 font-inter text-[10.5px] leading-relaxed text-ink/35">
              {link.basis}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}

function ImportStack({
  patientId,
  onImported,
}: {
  patientId: string;
  onImported: () => Promise<void>;
}) {
  const [entries, setEntries] = useState<{ file: File; date: string }[]>([]);
  const [prescriber, setPrescriber] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BulkImportResult | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  function addFiles(files: FileList | null) {
    if (!files || files.length === 0) return;
    setEntries((current) => [
      ...current,
      ...Array.from(files).map((file) => ({ file, date: "" })),
    ]);
    if (inputRef.current) inputRef.current.value = "";
  }

  async function submit() {
    if (entries.length === 0) return;
    if (entries.some((entry) => !entry.date)) {
      setError("Every file needs a visit date before importing.");
      return;
    }
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const response = await api.bulkImport(patientId, entries, prescriber.trim() || null);
      setResult(response);
      setEntries([]);
      await onImported();
    } catch (err) {
      setError(err instanceof Error ? err.message : "The import did not run.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="rounded-xl border border-ink/10 bg-paper p-5">
      <h2 className="flex items-center gap-2 font-dm text-[17px] font-medium tracking-[-0.03em] text-ink">
        <HistoryIcon className="h-4 w-4 text-ink/40" strokeWidth={1.8} />
        Import old prescriptions
      </h2>
      <p className="mt-1 font-inter text-[12px] leading-relaxed text-ink/45">
        Add a stack of past records. Each file needs the date of that visit, because the
        year-by-year view is built from it. Nothing becomes a medicine until you confirm it.
      </p>

      <div className="mt-3 flex flex-wrap items-center gap-2">
        <label className="flex cursor-pointer items-center gap-2 rounded-md border border-ink/15 bg-white px-3 py-2 font-inter text-[12.5px] text-ink/75">
          <FileUp className="h-3.5 w-3.5" strokeWidth={1.8} />
          Choose files
          <input
            ref={inputRef}
            type="file"
            multiple
            accept="image/jpeg,image/png,image/webp,image/tiff,application/pdf"
            className="hidden"
            onChange={(event) => addFiles(event.target.files)}
          />
        </label>
        <input
          value={prescriber}
          onChange={(event) => setPrescriber(event.target.value)}
          placeholder="Prescriber (optional, applies to all)"
          className="h-9 min-w-[240px] flex-1 rounded-md border border-ink/15 bg-white px-2.5 font-inter text-[12.5px] text-ink outline-none"
        />
      </div>

      {entries.length > 0 && (
        <ul className="mt-3 space-y-2">
          {entries.map((entry, index) => (
            <li key={`${entry.file.name}-${index}`} className="flex flex-wrap items-center gap-2 rounded-lg border border-ink/10 bg-white px-3 py-2">
              <span className="min-w-0 flex-1 truncate font-inter text-[12.5px] text-ink/75">
                {entry.file.name}
              </span>
              <input
                type="date"
                value={entry.date}
                onChange={(event) =>
                  setEntries((current) =>
                    current.map((item, itemIndex) =>
                      itemIndex === index ? { ...item, date: event.target.value } : item,
                    ),
                  )
                }
                className="h-8 rounded-md border border-ink/15 bg-white px-2 font-inter text-[12px] text-ink outline-none"
              />
              <button
                type="button"
                onClick={() => setEntries((current) => current.filter((_, i) => i !== index))}
                className="font-inter text-[11.5px] text-ink/40 hover:text-ink"
              >
                Remove
              </button>
            </li>
          ))}
        </ul>
      )}

      <button
        type="button"
        onClick={() => void submit()}
        disabled={busy || entries.length === 0}
        className="mt-3 flex items-center gap-2 rounded-md bg-ink px-3.5 py-2 font-inter text-[12.5px] font-medium text-white disabled:opacity-50"
      >
        {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={2} /> : null}
        {busy ? "Reading the stack…" : `Import ${entries.length || ""} file${entries.length === 1 ? "" : "s"}`}
      </button>

      {error && <p className="mt-2 font-inter text-[12px] text-red-700">{error}</p>}

      {result && (
        <div className="mt-3 rounded-lg border border-ink/10 bg-white px-3 py-2.5">
          <p className="font-inter text-[12.5px] text-ink/75">
            {result.imported} imported, {result.failed} failed.
          </p>
          <ul className="mt-1.5 space-y-1">
            {result.items.map((item, index) => (
              <li key={`${item.filename}-${index}`} className="font-inter text-[11.5px]">
                <span className={item.ok ? "text-ink/60" : "text-red-700"}>
                  {item.filename}: {item.ok ? item.message : item.error}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
