import { useCallback, useEffect, useState } from "react";
import { Check, Copy, ExternalLink, Loader2, RefreshCw, ShieldQuestion } from "lucide-react";
import { api } from "../lib/api";
import type { SafetyResult } from "../lib/api";
import { useHousehold } from "../lib/household";

type ExportData = {
  generated_at: string;
  patient_name: string;
  medications: {
    name: string;
    current_dose: string | null;
    prescribed_by: string | null;
    prescribed_on: string | null;
    open_cases: number;
    evidence_basis: string;
    timeline: { date: string; label: string; detail: string; source: string; age_days: number }[];
  }[];
  unresolved_case_count: number;
  questions_to_discuss: string[];
  note: string;
  lab_findings: {
    test_name: string;
    value: string;
    unit: string | null;
    captured_on: string | null;
    adherence_before: { medication_name: string; reported_adhered_percent: number | null; basis: string }[];
  }[];
};

/**
 * Doctor export.
 *
 * The doctor never logs in. A caregiver issues a short-lived link, shows it as a QR
 * code, and the doctor opens it. This screen therefore does two things: preview what
 * the doctor will see, and hand over the link.
 */
export default function DoctorExport() {
  const { patient } = useHousehold();
  const [data, setData] = useState<ExportData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [link, setLink] = useState<{ url: string; expires_at: string } | null>(null);
  const [issuing, setIssuing] = useState(false);
  const [copied, setCopied] = useState(false);

  const load = useCallback(async () => {
    if (!patient) return;
    setLoading(true);
    setError(null);
    try {
      setData((await api.doctorExport(patient.household_member_id)) as unknown as ExportData);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not build the export.");
    } finally {
      setLoading(false);
    }
  }, [patient]);

  useEffect(() => {
    void load();
  }, [load]);

  async function issue() {
    if (!patient) return;
    setIssuing(true);
    setError(null);
    try {
      const created = await api.doctorLink(patient.household_member_id);
      setLink({
        url: `${window.location.origin}${created.url_path}`,
        expires_at: created.expires_at,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create a link.");
    } finally {
      setIssuing(false);
    }
  }

  if (!patient) return null;

  return (
    <div className="mx-auto max-w-[900px]">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="font-inter text-[12.5px] uppercase tracking-wide text-ink/40">
            Doctor export
          </p>
          <h1 className="mt-1 font-dm text-[28px] font-normal leading-tight tracking-[-0.04em] text-ink sm:text-[34px]">
            What the doctor will read
          </h1>
        </div>
        <button
          type="button"
          onClick={() => void load()}
          className="flex items-center gap-2 rounded-md border border-ink/15 bg-paper px-3 py-2 font-inter text-[13px] text-ink/70 hover:text-ink"
        >
          <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} strokeWidth={1.8} />
          Rebuild
        </button>
      </div>

      {error && (
        <p className="mt-4 rounded-lg border border-red-300 bg-red-50 px-4 py-3 font-inter text-[13px] text-red-800">
          {error}
        </p>
      )}

      {/* Handover */}
      <div className="mt-6 rounded-xl border border-ink/10 bg-paper p-5 sm:p-6">
        <h2 className="font-dm text-[17px] font-medium tracking-[-0.03em] text-ink">
          Give this to the doctor
        </h2>
        <p className="mt-1 max-w-[560px] font-inter text-[12.5px] leading-relaxed text-ink/50">
          Creates a link that expires in two hours. The doctor opens it in any browser —
          no account, no app. Share the link, or turn it into a QR code on the phone.
        </p>

        {link ? (
          <div className="mt-4">
            <div className="flex items-center gap-2 rounded-lg border border-ink/12 bg-white px-3 py-2.5">
              <code className="min-w-0 flex-1 truncate font-inter text-[11.5px] text-ink/70">
                {link.url}
              </code>
              <button
                type="button"
                onClick={() => {
                  void navigator.clipboard.writeText(link.url);
                  setCopied(true);
                  window.setTimeout(() => setCopied(false), 1800);
                }}
                className="flex shrink-0 items-center gap-1.5 rounded px-2 py-1 font-inter text-[11.5px] text-ink/60 hover:text-ink"
              >
                {copied ? <Check className="h-3.5 w-3.5" strokeWidth={2} /> : <Copy className="h-3.5 w-3.5" strokeWidth={1.8} />}
                {copied ? "Copied" : "Copy"}
              </button>
              <a
                href={link.url}
                target="_blank"
                rel="noreferrer noopener"
                className="shrink-0 text-ink/45 hover:text-ink"
                aria-label="Open the doctor view"
              >
                <ExternalLink className="h-3.5 w-3.5" strokeWidth={1.8} />
              </a>
            </div>
            <p className="mt-2 font-inter text-[11.5px] text-ink/40">
              Expires {new Date(link.expires_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}.
              The link is read-only and covers this one patient.
            </p>
          </div>
        ) : (
          <button
            type="button"
            disabled={issuing}
            onClick={() => void issue()}
            className="mt-4 flex items-center gap-2 rounded-md bg-ink px-3.5 py-2 font-inter text-[13px] font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-60"
          >
            {issuing ? <Loader2 className="h-3.5 w-3.5 animate-spin" strokeWidth={2} /> : null}
            Create link
          </button>
        )}
      </div>

      {/* Preview */}
      {loading ? (
        <p className="mt-6 font-inter text-[13px] text-ink/40">Building…</p>
      ) : data ? (
        <div className="mt-5 rounded-xl border border-ink/10 bg-white p-5 sm:p-7">
          <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-ink/10 pb-3">
            <div>
              <p className="font-dm text-[18px] font-medium tracking-[-0.03em] text-ink">
                {data.patient_name}
              </p>
              <p className="font-inter text-[11.5px] text-ink/40">
                Generated {new Date(data.generated_at).toLocaleString()}
              </p>
            </div>
            <p className="font-inter text-[11.5px] text-ink/45">
              {data.unresolved_case_count} unresolved
            </p>
          </div>

          <div className="mt-4 space-y-5">
            {data.medications.map((med) => (
              <div key={med.name}>
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <p className="font-inter text-[14px] font-medium text-ink">{med.name}</p>
                  {med.current_dose && (
                    <span className="font-inter text-[12.5px] text-ink/45">{med.current_dose}</span>
                  )}
                  {med.open_cases > 0 && (
                    <span className="rounded-full bg-amber-500/15 px-2 py-0.5 font-inter text-[10.5px] text-amber-800">
                      {med.open_cases} open
                    </span>
                  )}
                </div>

                {med.prescribed_by && (
                  <p className="mt-0.5 font-inter text-[11.5px] text-ink/40">
                    Prescribed by {med.prescribed_by}
                    {med.prescribed_on ? ` on ${new Date(med.prescribed_on).toLocaleDateString()}` : ""}
                  </p>
                )}

                <ol className="mt-2 space-y-1 border-l border-ink/12 pl-3">
                  {med.timeline.slice(-6).map((entry, index) => (
                    <li key={index} className="font-inter text-[11.5px] leading-relaxed text-ink/60">
                      <span className="text-ink/35">
                        {new Date(entry.date).toLocaleDateString()} ·
                      </span>{" "}
                      {entry.detail}
                      <span className="ml-1 text-ink/30">({entry.source})</span>
                    </li>
                  ))}
                </ol>

                <p className="mt-1.5 font-inter text-[11px] italic text-ink/40">
                  {med.evidence_basis}
                </p>
              </div>
            ))}
          </div>

          {data.lab_findings.length > 0 && (
            <div className="mt-6 border-t border-ink/10 pt-4">
              <p className="font-inter text-[12px] font-medium text-ink">Lab results</p>
              <ul className="mt-2 space-y-2.5">
                {data.lab_findings.map((finding, index) => (
                  <li key={index}>
                    <p className="font-inter text-[12.5px] text-ink">
                      {finding.test_name}: <span className="font-medium">{finding.value}</span>
                      {finding.unit ? ` ${finding.unit}` : ""}
                      {finding.captured_on && (
                        <span className="ml-1.5 text-ink/40">
                          ({new Date(finding.captured_on).toLocaleDateString()})
                        </span>
                      )}
                    </p>
                    {finding.adherence_before[0]?.reported_adhered_percent !== null && (
                      <p className="font-inter text-[11px] leading-relaxed text-ink/45">
                        {finding.adherence_before[0]?.medication_name} was reported taken on{" "}
                        {finding.adherence_before[0]?.reported_adhered_percent}% of recorded days
                        before this test. Values are shown as printed and are not interpreted.
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {data.questions_to_discuss.length > 0 && (
            <div className="mt-5 border-t border-ink/10 pt-4">
              <p className="font-inter text-[12px] font-medium text-ink">Questions to discuss</p>
              <ul className="mt-1.5 list-disc space-y-1 pl-4">
                {data.questions_to_discuss.map((question) => (
                  <li key={question} className="font-inter text-[12px] text-ink/70">
                    {question}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <p className="mt-5 border-t border-ink/10 pt-3 font-inter text-[10.5px] leading-relaxed text-ink/40">
            {data.note}
          </p>
        </div>
      ) : null}
    </div>
  );
}

export function Safety() {
  const { patient } = useHousehold();
  const [result, setResult] = useState<SafetyResult | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!patient) return;
    api
      .safetyCheck(patient.household_member_id)
      .then(setResult)
      .catch(() => setResult(null))
      .finally(() => setLoading(false));
  }, [patient]);

  if (!patient) return null;

  return (
    <div className="mx-auto max-w-[820px]">
      <p className="font-inter text-[12.5px] uppercase tracking-wide text-ink/40">Safety</p>
      <h1 className="mt-1 font-dm text-[28px] font-normal leading-tight tracking-[-0.04em] text-ink sm:text-[34px]">
        Checked, or honestly not checked
      </h1>

      <div className="mt-3 flex items-start gap-2.5 rounded-xl border border-ink/12 bg-paper px-4 py-3.5">
        <ShieldQuestion className="mt-0.5 h-4 w-4 shrink-0 text-ink/40" strokeWidth={1.7} />
        <p className="font-inter text-[12.5px] leading-relaxed text-ink/55">
          {result?.disclaimer ??
            "This checks a small curated dataset only. Anything outside it is reported as not covered — never as safe."}
        </p>
      </div>

      {loading ? (
        <p className="mt-6 font-inter text-[13px] text-ink/40">Loading…</p>
      ) : result ? (
        <>
          {result.pairs.length > 0 && (
            <ul className="mt-5 space-y-2">
              {result.pairs.map((pair, index) => {
                const tone =
                  pair.result === "INTERACTION_FLAGGED"
                    ? "border-red-300 bg-red-50"
                    : pair.result === "DUPLICATE_INGREDIENT_FLAGGED"
                      ? "border-amber-300 bg-amber-50"
                      : pair.result === "NOT_COVERED"
                        ? "border-ink/15 bg-paper"
                        : "border-emerald-200 bg-emerald-50";
                return (
                  <li key={index} className={`rounded-lg border px-4 py-3 ${tone}`}>
                    <p className="font-inter text-[13px] font-medium text-ink">
                      {pair.a} + {pair.b}
                    </p>
                    <p className="mt-0.5 font-inter text-[12px] text-ink/60">
                      {pair.result === "INTERACTION_FLAGGED"
                        ? pair.detail ?? "Known interaction in the dataset."
                        : pair.result === "DUPLICATE_INGREDIENT_FLAGGED"
                          ? "These contain the same active ingredient."
                          : pair.result === "NOT_COVERED"
                            ? "Not in the checked dataset. This is not a statement that it is safe."
                            : "No known issue in this dataset."}
                    </p>
                    {pair.source && (
                      <p className="mt-1 font-inter text-[10.5px] text-ink/35">{pair.source}</p>
                    )}
                  </li>
                );
              })}
            </ul>
          )}

          {result.uncovered.length > 0 && (
            <p className="mt-4 font-inter text-[11.5px] leading-relaxed text-ink/45">
              Not covered by the dataset: {result.uncovered.join(", ")}.
            </p>
          )}
        </>
      ) : (
        <p className="mt-6 font-inter text-[13px] text-ink/45">
          Could not run the check. This does not mean the medicines are safe.
        </p>
      )}
    </div>
  );
}
