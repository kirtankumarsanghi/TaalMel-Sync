import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { ShieldAlert } from "lucide-react";

/**
 * Public doctor view.
 *
 * Reached by a time-limited token, with no login. It must therefore be readable by
 * someone who has never seen this product, so it leads with the patient and the
 * medications, and states plainly what this document is and is not.
 */
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
    timeline: { date: string; label: string; detail: string; source: string }[];
  }[];
  unresolved_case_count: number;
  questions_to_discuss: string[];
  note: string;
  lab_findings: {
    test_name: string;
    value: string;
    unit: string | null;
    captured_on: string | null;
    adherence_before: { medication_name: string; reported_adhered_percent: number | null }[];
  }[];
};

export default function DoctorView() {
  const { token } = useParams<{ token: string }>();
  const [data, setData] = useState<ExportData | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    fetch(`/api/public/doctor-export/${token}`)
      .then(async (response) => {
        if (!response.ok) throw new Error("This link is invalid or has expired.");
        return response.json();
      })
      .then((payload) => setData(payload as ExportData))
      .catch((err) => setError(err instanceof Error ? err.message : "Could not load."));
  }, [token]);

  if (error) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-bone px-5">
        <div className="max-w-[380px] text-center">
          <ShieldAlert className="mx-auto h-7 w-7 text-ink/30" strokeWidth={1.6} />
          <h1 className="mt-3 font-dm text-[20px] tracking-[-0.03em] text-ink">{error}</h1>
          <p className="mt-2 font-inter text-[13px] leading-relaxed text-ink/50">
            Ask the caregiver to create a new link. These links expire on purpose.
          </p>
        </div>
      </div>
    );
  }

  if (!data) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-bone">
        <p className="font-inter text-[13px] text-ink/40">Loading…</p>
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-bone px-5 py-8 sm:px-8 sm:py-12">
      <div className="mx-auto max-w-[760px]">
        <p className="font-dm text-[18px] font-medium tracking-[-0.04em] text-ink">Taalmel</p>

        <div className="mt-6 rounded-xl border border-ink/10 bg-white p-6 sm:p-8">
          <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-ink/10 pb-3">
            <h1 className="font-dm text-[24px] font-normal tracking-[-0.03em] text-ink">
              {data.patient_name}
            </h1>
            <p className="font-inter text-[11.5px] text-ink/40">
              {new Date(data.generated_at).toLocaleString()}
            </p>
          </div>

          <div className="mt-5 space-y-6">
            {data.medications.length === 0 && (
              <p className="font-inter text-[13px] text-ink/50">No medicines recorded yet.</p>
            )}

            {data.medications.map((med) => (
              <section key={med.name}>
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <h2 className="font-inter text-[15px] font-medium text-ink">{med.name}</h2>
                  {med.current_dose && (
                    <span className="font-inter text-[13px] text-ink/45">{med.current_dose}</span>
                  )}
                  {med.open_cases > 0 && (
                    <span className="rounded-full bg-amber-500/15 px-2 py-0.5 font-inter text-[10.5px] text-amber-800">
                      {med.open_cases} open issue
                    </span>
                  )}
                </div>

                {med.prescribed_by && (
                  <p className="mt-0.5 font-inter text-[12px] text-ink/45">
                    Prescribed by {med.prescribed_by}
                    {med.prescribed_on
                      ? ` on ${new Date(med.prescribed_on).toLocaleDateString()}`
                      : ""}
                  </p>
                )}

                <ol className="mt-2 space-y-1 border-l border-ink/12 pl-3">
                  {med.timeline.map((entry, index) => (
                    <li key={index} className="font-inter text-[12px] leading-relaxed text-ink/65">
                      <span className="text-ink/35">
                        {new Date(entry.date).toLocaleDateString()} ·
                      </span>{" "}
                      {entry.detail}
                      <span className="ml-1 text-ink/30">({entry.source})</span>
                    </li>
                  ))}
                </ol>

                <p className="mt-1.5 font-inter text-[11px] italic text-ink/40">{med.evidence_basis}</p>
              </section>
            ))}
          </div>

          {data.lab_findings.length > 0 && (
            <div className="mt-7 border-t border-ink/10 pt-4">
              <h2 className="font-inter text-[13px] font-medium text-ink">Lab results</h2>
              <ul className="mt-2 space-y-3">
                {data.lab_findings.map((finding, index) => (
                  <li key={index}>
                    <p className="font-inter text-[13px] text-ink">
                      {finding.test_name}: <strong className="font-medium">{finding.value}</strong>
                      {finding.unit ? ` ${finding.unit}` : ""}
                      {finding.captured_on && (
                        <span className="ml-1.5 text-ink/40">
                          ({new Date(finding.captured_on).toLocaleDateString()})
                        </span>
                      )}
                    </p>
                    {finding.adherence_before[0]?.reported_adhered_percent !== null && (
                      <p className="font-inter text-[11.5px] leading-relaxed text-ink/50">
                        Reported adherence to {finding.adherence_before[0]?.medication_name} in the
                        period before this test:{" "}
                        {finding.adherence_before[0]?.reported_adhered_percent}% of recorded days.
                        Results are shown as printed and are not interpreted.
                      </p>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {data.questions_to_discuss.length > 0 && (
            <div className="mt-6 border-t border-ink/10 pt-4">
              <h2 className="font-inter text-[13px] font-medium text-ink">Questions raised by the family</h2>
              <ul className="mt-1.5 list-disc space-y-1 pl-4">
                {data.questions_to_discuss.map((question) => (
                  <li key={question} className="font-inter text-[12.5px] text-ink/70">
                    {question}
                  </li>
                ))}
              </ul>
            </div>
          )}

          <p className="mt-6 border-t border-ink/10 pt-3 font-inter text-[10.5px] leading-relaxed text-ink/40">
            {data.note}
          </p>
        </div>
      </div>
    </div>
  );
}
