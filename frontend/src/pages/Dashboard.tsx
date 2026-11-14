import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Clock3,
  Mic,
  PackageX,
  Pill,
  RefreshCw,
} from "lucide-react";
import { api } from "../lib/api";
import type { CaseRow, Summary, TodayItem } from "../lib/api";
import { useHousehold } from "../lib/household";
import { useA11y } from "../lib/i18n";

/**
 * Today.
 *
 * The question this screen answers is "what needs me right now", so open cases come
 * first. Counts are secondary detail, not the headline, because a caregiver who sees
 * only "3/5 confirmed" learns nothing actionable.
 */
export default function Dashboard() {
  const { patient } = useHousehold();
  const { language, t } = useA11y();
  const [summary, setSummary] = useState<Summary | null>(null);
  const [today, setToday] = useState<TodayItem[]>([]);
  const [cases, setCases] = useState<CaseRow[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [voiceNote, setVoiceNote] = useState<string | null>(null);
  const [voiceBusy, setVoiceBusy] = useState(false);

  async function onVoiceUpload(file: File | undefined) {
    if (!patient || !file) return;
    setVoiceBusy(true);
    setVoiceNote(null);
    try {
      const res = await api.voiceReport(patient.household_member_id, file, language);
      handleVoiceResult(res);
    } catch (err) {
      setVoiceNote(err instanceof Error ? err.message : "Voice upload failed.");
    } finally {
      setVoiceBusy(false);
    }
  }

  async function onVoiceTranscript(transcript: string) {
    if (!patient || !transcript.trim()) return;
    setVoiceBusy(true);
    setVoiceNote(null);
    try {
      const res = await api.voiceReportText(patient.household_member_id, transcript, language);
      handleVoiceResult(res);
    } catch (err) {
      setVoiceNote(err instanceof Error ? err.message : "Voice report failed.");
    } finally {
      setVoiceBusy(false);
    }
  }

  function handleVoiceResult(res: {
    recorded: boolean;
    medication_name: string | null;
    transcript: string;
    clarification: string | null;
  }) {
    if (res.recorded) {
      setVoiceNote(`Recorded (${res.medication_name}): "${res.transcript}"`);
      void load();
    } else {
      setVoiceNote(res.clarification || "Could not match voice report.");
    }
  }

  function startListening() {
    const SpeechRecognitionCtor =
      (window as any).SpeechRecognition || (window as any).webkitSpeechRecognition;
    if (!SpeechRecognitionCtor) {
      setVoiceNote("This browser does not support speech recognition. Attach an audio file instead.");
      return;
    }
    const locales: Record<string, string> = {
      en: "en-IN", hi: "hi-IN", ta: "ta-IN", te: "te-IN", bn: "bn-IN", mr: "mr-IN",
    };
    const recognition = new SpeechRecognitionCtor();
    recognition.lang = locales[language] ?? "en-IN";
    recognition.interimResults = false;
    recognition.maxAlternatives = 1;
    setVoiceBusy(true);
    setVoiceNote(null);
    recognition.onresult = (event: any) => {
      const text = event.results?.[0]?.[0]?.transcript ?? "";
      void onVoiceTranscript(text);
    };
    recognition.onerror = () => {
      setVoiceBusy(false);
      setVoiceNote("I could not hear that. Please try again or attach an audio file.");
    };
    recognition.onend = () => setVoiceBusy(false);
    recognition.start();
  }

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
      <div className="flex flex-col gap-3 sm:flex-row sm:flex-wrap sm:items-end sm:justify-between">
        <div className="min-w-0">
          <p className="font-inter text-[12.5px] uppercase tracking-wide text-ink/40">Today</p>
          <h1 className="mt-1 truncate font-dm text-[28px] font-normal leading-tight tracking-[-0.04em] text-ink sm:text-[34px]">
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
            className="flex flex-1 items-center justify-center gap-2 rounded-md bg-ink px-3.5 py-2 font-inter text-[13px] font-medium text-white transition-opacity hover:opacity-90 sm:flex-none"
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
                      {row.medication_name ?? "Medicine"}
                    </span>
                    <span className="mt-0.5 block font-inter text-[12px] leading-snug text-ink/50">
                      {row.issue ?? "Needs a reason"}
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
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-dm text-[18px] font-medium tracking-[-0.03em] text-ink">
            {t("today.title", "Today's medicines")}
          </h2>
          <div className="flex flex-wrap items-center gap-1.5">
            <button
              type="button"
              disabled={voiceBusy}
              onClick={startListening}
              className="inline-flex items-center gap-1.5 rounded-lg border border-ink/15 bg-paper px-3 py-1.5 font-inter text-[12px] text-ink/80 transition-colors hover:border-ink/30 hover:text-ink disabled:opacity-50"
            >
              <Mic className="h-3.5 w-3.5" strokeWidth={1.7} />
              {voiceBusy ? t("report.listening", "Listening…") : t("report.speak", "Speak your answer")}
            </button>
            <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-lg border border-ink/15 bg-paper px-3 py-1.5 font-inter text-[12px] text-ink/80 transition-colors hover:border-ink/30 hover:text-ink">
              <Mic className="h-3.5 w-3.5" strokeWidth={1.7} />
              Attach audio
              <input
                type="file"
                accept="audio/*"
                disabled={voiceBusy}
                className="hidden"
                onChange={(e) => {
                  void onVoiceUpload(e.target.files?.[0]);
                  e.target.value = "";
                }}
              />
            </label>
          </div>
        </div>

        {voiceNote && (
          <p className="mt-2 rounded-lg border border-ink/10 bg-paper px-3 py-2 font-inter text-[12.5px] text-ink/80">
            {voiceNote}
          </p>
        )}

        {today.length === 0 ? (
          <div className="mt-3 rounded-xl border border-dashed border-ink/20 bg-paper px-4 py-8 text-center">
            <p className="font-inter text-[13.5px] text-ink/50">
              {t("today.empty", "No medicines yet. Add a prescription to start the record.")}
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
                  {item.plain_explanation && (
                    <p className="mt-0.5 font-inter text-[12px] text-ink/65">
                      Plain guide ({item.explanation_source}): {item.plain_explanation}
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
