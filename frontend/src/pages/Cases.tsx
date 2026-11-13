import { useCallback, useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { ArrowLeft, ArrowRight, CheckCircle2, Loader2, TriangleAlert } from "lucide-react";
import { api } from "../lib/api";
import type { CaseRow, Explanation } from "../lib/api";
import { useHousehold } from "../lib/household";

const REASONS = [
  { code: "RAN_OUT", label: "Ran out of stock" },
  { code: "FORGOT", label: "Forgot" },
  { code: "CONFUSED_ABOUT_DOSE", label: "Confused about the dose" },
  { code: "SIDE_EFFECT", label: "Side effect" },
  { code: "COULD_NOT_AFFORD", label: "Could not afford it" },
  { code: "DOCTOR_TOLD_TO_STOP", label: "Doctor said to stop" },
  { code: "PATIENT_DECLINED", label: "Chose not to take it" },
  { code: "EXPIRED", label: "Medicine expired" },
];

export function Cases() {
  const { patient } = useHousehold();
  const [cases, setCases] = useState<CaseRow[]>([]);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!patient) return;
    setLoading(true);
    try {
      setCases(await api.openCases(patient.household_member_id));
    } finally {
      setLoading(false);
    }
  }, [patient]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!patient) return null;

  return (
    <div className="mx-auto max-w-[900px]">
      <p className="font-inter text-[12.5px] uppercase tracking-wide text-ink/40">Cases</p>
      <h1 className="mt-1 font-dm text-[28px] font-normal leading-tight tracking-[-0.04em] text-ink sm:text-[34px]">
        Nothing closes itself
      </h1>
      <p className="mt-2 max-w-[560px] font-inter text-[13.5px] leading-relaxed text-ink/50">
        A case stays here until a person records why it happened and confirms it is resolved.
      </p>

      {loading ? (
        <p className="mt-8 font-inter text-[13px] text-ink/40">Loading…</p>
      ) : cases.length === 0 ? (
        <div className="mt-8 flex items-center gap-3 rounded-xl border border-ink/10 bg-paper px-4 py-5">
          <CheckCircle2 className="h-5 w-5 text-emerald-700" strokeWidth={1.7} />
          <p className="font-inter text-[13.5px] text-ink/60">No open cases.</p>
        </div>
      ) : (
        <ul className="mt-6 space-y-2.5">
          {cases.map((row) => (
            <li key={row.id}>
              <Link
                to={`/app/cases/${row.id}`}
                className="flex items-center gap-3 rounded-xl border border-ink/10 bg-paper px-4 py-4 transition-colors hover:border-ink/25"
              >
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-amber-500/15">
                  <TriangleAlert className="h-4 w-4 text-amber-700" strokeWidth={1.7} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block font-inter text-[14px] font-medium text-ink">
                    {row.reason_code ? pretty(row.reason_code) : "Reason not yet recorded"}
                  </span>
                  <span className="block font-inter text-[12px] text-ink/45">
                    {row.status.toLowerCase().replace("_", " ")} · opened {formatDate(row.opened_at)}
                  </span>
                </span>
                <ArrowRight className="h-4 w-4 shrink-0 text-ink/25" strokeWidth={1.8} />
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

export function CaseDetail() {
  const { caseId } = useParams<{ caseId: string }>();
  const [explain, setExplain] = useState<Explanation | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [resources, setResources] = useState<{ name: string; url: string; description: string }[] | null>(
    null,
  );
  const [outcome, setOutcome] = useState<"RESOLVED" | "STILL_UNCERTAIN">("RESOLVED");
  const [note, setNote] = useState("");

  const load = useCallback(async () => {
    if (!caseId) return;
    try {
      setExplain(await api.explainCase(caseId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load this case.");
    }
  }, [caseId]);

  useEffect(() => {
    void load();
  }, [load]);

  async function recordReason(code: string) {
    if (!caseId) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.recordReason(caseId, code);
      setResources(result.resources);
      setExplain(await api.explainCase(caseId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not record this reason.");
    } finally {
      setBusy(false);
    }
  }

  async function resolve() {
    if (!caseId) return;
    setBusy(true);
    setError(null);
    try {
      await api.resolveCase(caseId, outcome, note || undefined);
      setExplain(await api.explainCase(caseId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not resolve this case.");
    } finally {
      setBusy(false);
    }
  }

  if (!caseId) return null;

  return (
    <div className="mx-auto max-w-[720px]">
      <Link
        to="/app/cases"
        className="inline-flex items-center gap-1.5 font-inter text-[12.5px] text-ink/45 transition-colors hover:text-ink"
      >
        <ArrowLeft className="h-3.5 w-3.5" strokeWidth={1.8} />
        All cases
      </Link>

      {error && (
        <p className="mt-4 rounded-lg border border-red-300 bg-red-50 px-4 py-3 font-inter text-[13px] text-red-800">
          {error}
        </p>
      )}

      {!explain ? (
        <p className="mt-6 font-inter text-[13px] text-ink/40">Loading…</p>
      ) : (
        <>
          {/* What / why / source / status / action */}
          <div className="mt-4 rounded-xl border border-ink/10 bg-paper p-5 sm:p-6">
            <p className="font-inter text-[11.5px] uppercase tracking-wide text-ink/40">
              {explain.status.toLowerCase().replace("_", " ")}
            </p>
            <h1 className="mt-2 font-dm text-[24px] font-normal leading-tight tracking-[-0.03em] text-ink">
              {explain.what}
            </h1>

            <dl className="mt-4 space-y-2.5">
              <Row label="Why" value={explain.why} />
              <Row label="Source" value={explain.source} />
              <Row label="Next step" value={explain.action} />
              <Row
                label="Reason recorded"
                value={explain.reason_recorded ? pretty(explain.reason_recorded) : "Not yet recorded"}
              />
            </dl>

            <p className="mt-4 rounded-lg bg-ink/[0.04] px-3.5 py-2.5 font-inter text-[12px] leading-relaxed text-ink/55">
              Taalmel does not {explain.taalmel_does_not.replace(/^does not /, "")}. A person
              decides.
            </p>
          </div>

          {/* Reason */}
          {explain.status !== "RESOLVED" && (
            <div className="mt-5 rounded-xl border border-ink/10 bg-paper p-5 sm:p-6">
              <h2 className="font-dm text-[17px] font-medium tracking-[-0.03em] text-ink">
                Why did this happen?
              </h2>
              <p className="mt-1 font-inter text-[12.5px] leading-relaxed text-ink/50">
                Recorded once, so the pattern becomes visible instead of repeating.
              </p>

              <div className="mt-4 grid gap-2 sm:grid-cols-2">
                {REASONS.map((reason) => (
                  <button
                    key={reason.code}
                    type="button"
                    disabled={busy}
                    onClick={() => void recordReason(reason.code)}
                    className={`rounded-lg border px-3.5 py-2.5 text-left font-inter text-[13px] transition-colors disabled:opacity-60 ${
                      explain.reason_recorded === reason.code
                        ? "border-ink bg-ink text-white"
                        : "border-ink/12 bg-white text-ink hover:border-ink/30"
                    }`}
                  >
                    {reason.label}
                  </button>
                ))}
              </div>

              {resources && resources.length > 0 && (
                <div className="mt-4 rounded-lg border border-ink/12 bg-white p-3.5">
                  <p className="font-inter text-[12px] font-medium text-ink">Support programmes</p>
                  <ul className="mt-1.5 space-y-1.5">
                    {resources.map((resource) => (
                      <li key={resource.url}>
                        <a
                          href={resource.url}
                          target="_blank"
                          rel="noreferrer noopener"
                          className="font-inter text-[12.5px] text-ink underline underline-offset-2"
                        >
                          {resource.name}
                        </a>
                      </li>
                    ))}
                  </ul>
                  <p className="mt-2 font-inter text-[11.5px] leading-relaxed text-ink/45">
                    Taalmel never suggests a cheaper medicine. Discuss alternatives with a
                    doctor or pharmacist.
                  </p>
                </div>
              )}
            </div>
          )}

          {/* Resolve */}
          {explain.status !== "RESOLVED" && (
            <div className="mt-5 rounded-xl border border-ink/10 bg-paper p-5 sm:p-6">
              <h2 className="font-dm text-[17px] font-medium tracking-[-0.03em] text-ink">
                Close it
              </h2>
              <p className="mt-1 font-inter text-[12.5px] leading-relaxed text-ink/50">
                Only close this when you are satisfied it is actually settled.
              </p>

              <div className="mt-4 flex gap-2">
                {(
                  [
                    ["RESOLVED", "Resolved"],
                    ["STILL_UNCERTAIN", "Still uncertain"],
                  ] as const
                ).map(([value, label]) => (
                  <button
                    key={value}
                    type="button"
                    onClick={() => setOutcome(value)}
                    className={`flex-1 rounded-lg border px-3 py-2.5 font-inter text-[13px] transition-colors ${
                      outcome === value
                        ? "border-ink bg-ink text-white"
                        : "border-ink/12 bg-white text-ink hover:border-ink/30"
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>

              <textarea
                value={note}
                onChange={(event) => setNote(event.target.value)}
                rows={2}
                placeholder="What settled it? (optional)"
                className="mt-3 w-full resize-none rounded-lg border border-ink/15 bg-white px-3 py-2.5 font-inter text-[13px] text-ink outline-none focus:border-ink/35"
              />

              <button
                type="button"
                disabled={busy}
                onClick={() => void resolve()}
                className="mt-3 flex h-11 w-full items-center justify-center gap-2 rounded-md bg-ink font-inter text-[13px] font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-60"
              >
                {busy && <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={2} />}
                Record outcome
              </button>
            </div>
          )}

          {explain.status === "RESOLVED" && (
            <div className="mt-5 flex items-center gap-3 rounded-xl border border-emerald-300 bg-emerald-50 px-4 py-4">
              <CheckCircle2 className="h-5 w-5 text-emerald-700" strokeWidth={1.7} />
              <p className="font-inter text-[13px] text-emerald-900">
                This case is closed, and stays in the record.
              </p>
            </div>
          )}
        </>
      )}
    </div>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex flex-wrap gap-x-3">
      <dt className="w-[132px] shrink-0 font-inter text-[12.5px] text-ink/40">{label}</dt>
      <dd className="min-w-0 flex-1 font-inter text-[13px] leading-relaxed text-ink/85">{value}</dd>
    </div>
  );
}

function pretty(code: string): string {
  return code.toLowerCase().replace(/_/g, " ");
}

function formatDate(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "an unknown date";
  return date.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}
