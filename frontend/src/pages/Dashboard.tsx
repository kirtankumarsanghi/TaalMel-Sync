import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Clock3,
  PackageX,
  Pill,
  RefreshCw,
} from "lucide-react";
import { api } from "../lib/api";
import type { CaseRow, Summary, TodayItem } from "../lib/api";
import { useHousehold } from "../lib/household";

/**
 * Today.
 *
 * The question this screen answers is "what needs me right now", so open cases come
 * first. Counts are secondary detail, not the headline, because a caregiver who sees
 * only "3/5 confirmed" learns nothing actionable.
 */
export default function Dashboard() {
  const { patient } = useHousehold();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [today, setToday] = useState<TodayItem[]>([]);
  const [cases, setCases] = useState<CaseRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    if (!patient) return;
    setLoading(true);
    setError(null);
    try {
      const [summaryData, todayData, caseData] = await Promise.all([
        api.summary(patient.household_member_id),
        api.today(patient.household_member_id),
        api.openCases(patient.household_member_id),
      ]);
      setSummary(summaryData);
      setToday(todayData);
      setCases(caseData);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load today's status.");
    } finally {
      setLoading(false);
    }
  }, [patient]);

  useEffect(() => {
    void load();
  }, [load]);

  if (!patient) return null;

  return (
    <div className="mx-auto max-w-[1080px]">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <p className="font-inter text-[12.5px] uppercase tracking-wide text-ink/40">Today</p>
          <h1 className="mt-1 font-dm text-[28px] font-normal leading-tight tracking-[-0.04em] text-ink sm:text-[34px]">
            {patient.display_name}
          </h1>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => void load()}
            className="flex items-center gap-2 rounded-md border border-ink/15 bg-paper px-3 py-2 font-inter text-[13px] text-ink/70 transition-colors hover:text-ink"
          >
            <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} strokeWidth={1.8} />
            Refresh
          </button>
          <Link
            to="/app/medicines"
            className="flex items-center gap-2 rounded-md bg-ink px-3.5 py-2 font-inter text-[13px] font-medium text-white transition-opacity hover:opacity-90"
          >
            Record evidence
            <ArrowRight className="h-3.5 w-3.5" strokeWidth={1.8} />
          </Link>
        </div>
      </div>

      {error && (
        <p className="mt-4 rounded-lg border border-red-300 bg-red-50 px-4 py-3 font-inter text-[13px] text-red-800">
          {error}
        </p>
      )}

      {/* Counts */}
      <div className="mt-6 grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Medicines" value={summary?.medicines_total ?? 0} icon={Pill} />
        <Stat label="Open cases" value={summary?.open_cases ?? 0} icon={AlertTriangle} tone="amber" />
        <Stat label="Need checking" value={summary?.needs_checking ?? 0} icon={Clock3} />
        <Stat label="Expired" value={summary?.expired ?? 0} icon={PackageX} tone="red" />
      </div>

      {/* Open cases first */}
      <section className="mt-8">
        <h2 className="font-dm text-[18px] font-medium tracking-[-0.03em] text-ink">
          Needs a decision
        </h2>

        {cases.length === 0 ? (
          <div className="mt-3 flex items-center gap-3 rounded-xl border border-ink/10 bg-paper px-4 py-5">
            <CheckCircle2 className="h-5 w-5 text-emerald-700" strokeWidth={1.7} />
            <p className="font-inter text-[13.5px] text-ink/60">
              Nothing is open. Every record is consistent with what was last recorded.
            </p>
          </div>
        ) : (
          <ul className="mt-3 space-y-2.5">
            {cases.map((row) => (
              <li key={row.id}>
                <Link
                  to={`/app/cases/${row.id}`}
                  className="flex items-center gap-3 rounded-xl border border-ink/10 bg-paper px-4 py-3.5 transition-colors hover:border-ink/25"
                >
                  <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-amber-500/15">
                    <AlertTriangle className="h-4 w-4 text-amber-700" strokeWidth={1.7} />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block font-inter text-[14px] font-medium text-ink">
                      {row.reason_code ? `Reason recorded: ${pretty(row.reason_code)}` : "Discrepancy needs a reason"}
                    </span>
                    <span className="block font-inter text-[12px] text-ink/45">
                      Opened {formatDate(row.opened_at)} · {row.status.toLowerCase().replace("_", " ")}
                    </span>
                  </span>
                  <ArrowRight className="h-4 w-4 shrink-0 text-ink/25" strokeWidth={1.8} />
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>

      {/* Today's medicines */}
      <section className="mt-8">
        <h2 className="font-dm text-[18px] font-medium tracking-[-0.03em] text-ink">
          Today's medicines
        </h2>

        {today.length === 0 ? (
          <div className="mt-3 rounded-xl border border-dashed border-ink/20 bg-paper px-4 py-8 text-center">
            <p className="font-inter text-[13.5px] text-ink/50">
              No medicines yet. Add a prescription to start the record.
            </p>
            <Link
              to="/app/medicines"
              className="mt-3 inline-block font-inter text-[13px] font-medium text-ink underline underline-offset-4"
            >
              Add a prescription
            </Link>
          </div>
        ) : (
          <ul className="mt-3 divide-y divide-ink/10 overflow-hidden rounded-xl border border-ink/10 bg-paper">
            {today.map((item) => (
              <li key={item.medication_id} className="flex items-start gap-3 px-4 py-3.5">
                <div className="min-w-0 flex-1">
                  <p className="font-inter text-[14px] font-medium text-ink">
                    {item.name}
                    {item.dose ? <span className="ml-1.5 text-ink/45">{item.dose}</span> : null}
                  </p>
                  {item.instruction && (
                    <p className="mt-0.5 font-inter text-[12px] italic text-ink/45">
                      Doctor's note: {item.instruction}
                    </p>
                  )}
                </div>
                <StatusPill status={item.reported_taking} />
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

function Stat({
  label,
  value,
  icon: Icon,
  tone = "ink",
}: {
  label: string;
  value: number;
  icon: typeof Pill;
  tone?: "ink" | "amber" | "red";
}) {
  const toneClass =
    tone === "amber" && value > 0
      ? "text-amber-700"
      : tone === "red" && value > 0
        ? "text-red-700"
        : "text-ink";
  return (
    <div className="rounded-xl border border-ink/10 bg-paper px-4 py-3.5">
      <Icon className="h-4 w-4 text-ink/30" strokeWidth={1.7} />
      <p className={`mt-2 font-dm text-[26px] font-normal leading-none tracking-[-0.04em] ${toneClass}`}>
        {value}
      </p>
      <p className="mt-1 font-inter text-[11.5px] text-ink/45">{label}</p>
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  const map: Record<string, { label: string; className: string }> = {
    TAKING: { label: "Reported taking", className: "bg-emerald-500/12 text-emerald-800" },
    STOPPED: { label: "Reported stopped", className: "bg-amber-500/15 text-amber-800" },
    UNKNOWN: { label: "Not reported", className: "bg-ink/[0.06] text-ink/50" },
  };
  const entry = map[status] ?? map.UNKNOWN;
  return (
    <span className={`shrink-0 rounded-full px-2.5 py-1 font-inter text-[11px] font-medium ${entry.className}`}>
      {entry.label}
    </span>
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
