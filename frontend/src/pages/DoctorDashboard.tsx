import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, FileText, KeyRound, LogOut } from "lucide-react";
import { api } from "../lib/api";
import { useAuth } from "../lib/auth";

type DoctorPatient = {
  household_member_id: string;
  name: string;
  granted_at: string;
  expires_at: string | null;
};

type ExportData = {
  patient_name: string;
  unresolved_case_count: number;
  medications: { name: string; current_dose: string | null; open_cases: number; evidence_basis: string }[];
  questions_to_discuss: string[];
  note: string;
};

export default function DoctorDashboard() {
  const { user, signOut } = useAuth();
  const [patients, setPatients] = useState<DoctorPatient[]>([]);
  const [token, setToken] = useState("");
  const [selected, setSelected] = useState<ExportData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      setPatients(await api.doctorPatients());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load patients.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  async function redeem() {
    if (!token.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await api.doctorRedeem(token.trim());
      setToken("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not redeem the link.");
    } finally {
      setBusy(false);
    }
  }

  async function open(memberId: string) {
    setBusy(true);
    setError(null);
    try {
      setSelected((await api.doctorPatientExport(memberId)) as unknown as ExportData);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not open the export.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen bg-bone px-5 py-8 sm:px-8">
      <div className="mx-auto max-w-[900px]">
        <div className="flex items-center justify-between">
          <Link to="/" className="flex items-center gap-2 font-dm text-[22px] text-ink">
            <ArrowLeft className="h-4 w-4" /> Taalmel
          </Link>
          <button
            type="button"
            onClick={() => void signOut()}
            className="flex items-center gap-1.5 font-inter text-[12.5px] text-ink/50 hover:text-ink"
          >
            <LogOut className="h-4 w-4" /> Sign out
          </button>
        </div>

        <h1 className="mt-8 font-dm text-[30px] font-normal tracking-[-0.04em] text-ink">
          Doctor dashboard
        </h1>
        <p className="mt-1 font-inter text-[13px] text-ink/55">
          Signed in as {user?.name}. Public QR links still work without this account; this
          dashboard only saves the patients you have already opened.
        </p>

        {error && (
          <p className="mt-4 rounded-lg border border-red-300 bg-red-50 px-4 py-3 font-inter text-[13px] text-red-800">
            {error}
          </p>
        )}

        <div className="mt-6 rounded-xl border border-ink/10 bg-paper p-4">
          <h2 className="flex items-center gap-2 font-dm text-[16px] font-medium text-ink">
            <KeyRound className="h-4 w-4 text-ink/40" /> Add a patient from a link
          </h2>
          <p className="mt-1 font-inter text-[12px] text-ink/45">
            Paste the link token a caregiver shared. It is checked for expiry and scope.
          </p>
          <div className="mt-2 flex gap-2">
            <input
              value={token}
              onChange={(event) => setToken(event.target.value)}
              placeholder="Paste doctor-link token or full URL"
              className="h-10 min-w-0 flex-1 rounded-md border border-ink/15 bg-white px-3 font-inter text-[12.5px] text-ink outline-none"
            />
            <button
              type="button"
              disabled={busy || !token.trim()}
              onClick={() => void redeem()}
              className="rounded-md bg-ink px-3 py-2 font-inter text-[12.5px] font-medium text-white disabled:opacity-50"
            >
              Add
            </button>
          </div>
        </div>

        <div className="mt-5 grid gap-4 lg:grid-cols-[280px_1fr]">
          <ul className="space-y-2">
            {patients.length === 0 ? (
              <li className="rounded-lg border border-dashed border-ink/20 px-4 py-6 font-inter text-[12.5px] text-ink/45">
                No saved patients yet.
              </li>
            ) : (
              patients.map((patient) => (
                <li key={patient.household_member_id}>
                  <button
                    type="button"
                    onClick={() => void open(patient.household_member_id)}
                    className="w-full rounded-lg border border-ink/10 bg-paper px-4 py-3 text-left font-inter text-[13px] text-ink hover:border-ink/25"
                  >
                    {patient.name}
                  </button>
                </li>
              ))
            )}
          </ul>

          {selected ? (
            <div className="rounded-xl border border-ink/10 bg-white p-5">
              <div className="flex items-center justify-between border-b border-ink/10 pb-2">
                <h2 className="font-dm text-[18px] font-medium text-ink">{selected.patient_name}</h2>
                <span className="font-inter text-[11.5px] text-ink/45">
                  {selected.unresolved_case_count} unresolved
                </span>
              </div>
              <ul className="mt-3 space-y-3">
                {selected.medications.map((med) => (
                  <li key={med.name}>
                    <p className="font-inter text-[13.5px] font-medium text-ink">
                      {med.name} {med.current_dose ?? ""}
                    </p>
                    <p className="font-inter text-[11.5px] italic text-ink/45">{med.evidence_basis}</p>
                  </li>
                ))}
              </ul>
              {selected.questions_to_discuss.length > 0 && (
                <div className="mt-4 border-t border-ink/10 pt-3">
                  <p className="font-inter text-[12px] font-medium text-ink">Questions</p>
                  <ul className="mt-1 list-disc pl-4 font-inter text-[12px] text-ink/65">
                    {selected.questions_to_discuss.map((q) => (
                      <li key={q}>{q}</li>
                    ))}
                  </ul>
                </div>
              )}
              <p className="mt-4 border-t border-ink/10 pt-2 font-inter text-[10.5px] text-ink/40">
                {selected.note}
              </p>
            </div>
          ) : (
            <div className="flex items-center justify-center rounded-xl border border-dashed border-ink/20 p-8 font-inter text-[12.5px] text-ink/40">
              <FileText className="mr-2 h-4 w-4" /> Select a patient to read the export.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
