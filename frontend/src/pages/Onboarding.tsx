import { useState } from "react";
import { Loader2, UserRoundPlus } from "lucide-react";
import { useHousehold } from "../lib/household";
import { useAuth } from "../lib/auth";

/**
 * First-run setup.
 *
 * One patient per household is the common case for this product (an adult child
 * caring for a parent), so setup asks for the minimum: a label for the household
 * and the name the caregiver uses for the person they care for.
 */
export default function Onboarding() {
  const { createHousehold, error } = useHousehold();
  const { user, signOut } = useAuth();
  const [householdName, setHouseholdName] = useState("My family");
  const [patientName, setPatientName] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    if (patientName.trim().length < 2) return;
    setBusy(true);
    try {
      await createHousehold(householdName.trim() || "My family", patientName.trim());
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-bone px-5 py-10">
      <div className="w-full max-w-[460px]">
        <div className="flex items-center justify-between">
          <span className="font-dm text-[22px] font-medium tracking-[-0.05em] text-ink">Taalmel</span>
          <button
            type="button"
            onClick={() => void signOut()}
            className="font-inter text-[12.5px] text-ink/40 underline underline-offset-2 hover:text-ink"
          >
            Sign out
          </button>
        </div>

        <div className="mt-8 rounded-2xl border border-ink/10 bg-paper p-6 sm:p-8">
          <div className="flex h-11 w-11 items-center justify-center rounded-full bg-ink">
            <UserRoundPlus className="h-5 w-5 text-white" strokeWidth={1.6} />
          </div>

          <h1 className="mt-5 font-dm text-[26px] font-normal leading-tight tracking-[-0.04em] text-ink">
            Who are you caring for?
          </h1>
          <p className="mt-2 font-inter text-[13.5px] leading-relaxed text-ink/55">
            Hi {user?.name?.split(" ")[0] ?? "there"}. Add the person whose medicines you
            keep track of. You can add more people later.
          </p>

          <form onSubmit={submit} className="mt-6 space-y-4">
            <label className="block">
              <span className="font-inter text-[12.5px] font-medium text-ink/60">Their name</span>
              <input
                value={patientName}
                onChange={(event) => setPatientName(event.target.value)}
                placeholder="Amma"
                autoFocus
                className="mt-1.5 h-12 w-full rounded-md border border-ink/15 bg-white px-3.5 font-inter text-[15px] text-ink outline-none transition-colors focus:border-ink/40"
              />
            </label>

            <label className="block">
              <span className="font-inter text-[12.5px] font-medium text-ink/60">Household label</span>
              <input
                value={householdName}
                onChange={(event) => setHouseholdName(event.target.value)}
                placeholder="Sharma family"
                className="mt-1.5 h-12 w-full rounded-md border border-ink/15 bg-white px-3.5 font-inter text-[15px] text-ink outline-none transition-colors focus:border-ink/40"
              />
            </label>

            {error && (
              <p role="alert" className="font-inter text-[12.5px] text-red-700">
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={busy || patientName.trim().length < 2}
              className="flex h-12 w-full items-center justify-center gap-2 rounded-md bg-ink font-inter text-[14px] font-medium tracking-[-0.02em] text-white transition-opacity hover:opacity-90 disabled:opacity-50"
            >
              {busy && <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2} />}
              Create household
            </button>
          </form>
        </div>

        <p className="mt-4 px-1 font-inter text-[11.5px] leading-relaxed text-ink/35">
          Creating a household records your consent to access this person's medication
          record. You can revoke it at any time.
        </p>
      </div>
    </div>
  );
}
