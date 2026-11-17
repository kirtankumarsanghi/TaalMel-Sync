import { useCallback, useEffect, useState } from "react";
import {
  AlertCircle,
  Calendar,
  CheckCircle2,
  Clock,
  Loader2,
  Phone,
  Shield,
  ShieldAlert,
  UserCheck,
  UserMinus,
  UserPlus,
  Users,
} from "lucide-react";
import { api } from "../lib/api";
import type { CaregiverAccess, EmergencyContact } from "../lib/api";
import { useAuth } from "../lib/auth";
import { useHousehold } from "../lib/household";

const TODAY_ISO = new Date().toISOString().slice(0, 10);

export default function Caregivers() {
  const { user } = useAuth();
  const { patient, selectPatient } = useHousehold();

  const [patientGrants, setPatientGrants] = useState<CaregiverAccess[]>([]);
  const [myGrants, setMyGrants] = useState<CaregiverAccess[]>([]);
  const [emergencyContacts, setEmergencyContacts] = useState<EmergencyContact[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // Invite state
  const [phone, setPhone] = useState("");
  const [durationPreset, setDurationPreset] = useState<"permanent" | "7d" | "14d" | "30d" | "custom">("permanent");
  const [customExpiryDate, setCustomExpiryDate] = useState("");
  const [inviting, setInviting] = useState(false);

  // Consent modal / prompt state for incoming invitations
  const [acceptingId, setAcceptingId] = useState<string | null>(null);
  const [consentConfirmed, setConsentConfirmed] = useState(false);
  const [actionBusy, setActionBusy] = useState(false);

  // Emergency contact state
  const [emergencyUserId, setEmergencyUserId] = useState("");
  const [emergencyRelation, setEmergencyRelation] = useState("");
  const [addingEmergency, setAddingEmergency] = useState(false);

  const loadData = useCallback(async () => {
    if (!patient) return;
    setError(null);
    try {
      const [grants, mine, contacts] = await Promise.all([
        api.patientAccess(patient.patient_id).catch(() => []),
        api.myAccess().catch(() => []),
        api.emergencyContacts(patient.household_member_id).catch(() => []),
      ]);
      setPatientGrants(grants);
      setMyGrants(mine);
      setEmergencyContacts(contacts);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load access information.");
    } finally {
      setLoading(false);
    }
  }, [patient]);

  useEffect(() => {
    void loadData();
  }, [loadData]);

  // Compute ISO expiry based on preset
  function calculateExpiry(): string | null {
    if (durationPreset === "permanent") return null;
    const now = new Date();
    if (durationPreset === "7d") {
      now.setDate(now.getDate() + 7);
      return now.toISOString();
    }
    if (durationPreset === "14d") {
      now.setDate(now.getDate() + 14);
      return now.toISOString();
    }
    if (durationPreset === "30d") {
      now.setDate(now.getDate() + 30);
      return now.toISOString();
    }
    if (durationPreset === "custom" && customExpiryDate) {
      return new Date(customExpiryDate).toISOString();
    }
    return null;
  }

  async function handleInvite(event: React.FormEvent) {
    event.preventDefault();
    if (!patient || !phone.trim()) return;

    setInviting(true);
    setError(null);
    setNotice(null);

    try {
      const expiresAt = calculateExpiry();
      await api.grantAccess(patient.patient_id, phone.trim(), expiresAt);
      setNotice(`Access invitation sent to ${phone.trim()}. They will have access once they accept with consent.`);
      setPhone("");
      setDurationPreset("permanent");
      setCustomExpiryDate("");
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not invite caregiver.");
    } finally {
      setInviting(false);
    }
  }

  async function handleAcceptConsent(accessId: string) {
    if (!consentConfirmed) {
      setError("Please confirm patient consent before accepting.");
      return;
    }
    setActionBusy(true);
    setError(null);
    try {
      await api.consentAccess(accessId);
      setNotice("Invitation accepted. You now have active caregiver access.");
      setAcceptingId(null);
      setConsentConfirmed(false);
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not record consent.");
    } finally {
      setActionBusy(false);
    }
  }

  async function handleRevoke(accessId: string, nameOrPhone: string) {
    if (!confirm(`Are you sure you want to revoke access for ${nameOrPhone}? They will immediately lose access to all records.`)) {
      return;
    }
    setActionBusy(true);
    setError(null);
    try {
      await api.revokeAccess(accessId);
      setNotice(`Access revoked for ${nameOrPhone}.`);
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not revoke access.");
    } finally {
      setActionBusy(false);
    }
  }

  async function handleAddEmergencyContact(e: React.FormEvent) {
    e.preventDefault();
    if (!patient || !emergencyUserId) return;
    setAddingEmergency(true);
    setError(null);
    try {
      await api.addEmergencyContact(
        patient.household_member_id,
        emergencyUserId,
        emergencyRelation.trim() || null,
      );
      setNotice("Emergency contact added.");
      setEmergencyUserId("");
      setEmergencyRelation("");
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add emergency contact.");
    } finally {
      setAddingEmergency(false);
    }
  }

  async function handleRemoveEmergencyContact(contactId: string) {
    if (!patient) return;
    setActionBusy(true);
    setError(null);
    try {
      await api.removeEmergencyContact(patient.household_member_id, contactId);
      setNotice("Emergency contact removed.");
      await loadData();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not remove emergency contact.");
    } finally {
      setActionBusy(false);
    }
  }

  async function switchToPatient(patientId: string) {
    try {
      const p = await api.getPatient(patientId);
      selectPatient(p);
      setNotice(`Switched to caring for ${p.display_name}.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load patient profile.");
    }
  }

  if (!patient) return null;

  const pendingIncoming = myGrants.filter((g) => g.status === "PENDING");
  const acceptedShared = myGrants.filter(
    (g) => g.status === "ACTIVE" && g.patient_id && g.patient_id !== patient.patient_id,
  );

  return (
    <div className="mx-auto max-w-[880px] space-y-7">
      {/* Header */}
      <div>
        <p className="font-inter text-[12.5px] uppercase tracking-wide text-ink/40">Access & Handoff</p>
        <h1 className="mt-1 font-dm text-[28px] font-normal leading-tight tracking-[-0.04em] text-ink sm:text-[34px]">
          Caregiver circle
        </h1>
        <p className="mt-2 font-inter text-[13.5px] leading-relaxed text-ink/60">
          Manage family members and relief caregivers with access to {patient.display_name}&apos;s medical
          records. Temporary access expires automatically with no reminder needed.
        </p>
      </div>

      {notice && (
        <div className="flex items-center gap-2 rounded-xl border border-emerald-300 bg-emerald-50 px-4 py-3 text-[13px] text-emerald-900">
          <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600" />
          <span>{notice}</span>
        </div>
      )}

      {error && (
        <div className="flex items-center gap-2 rounded-xl border border-amber-300 bg-amber-50 px-4 py-3 text-[13px] text-amber-900">
          <AlertCircle className="h-4 w-4 shrink-0 text-amber-600" />
          <span>{error}</span>
        </div>
      )}

      {/* ── Section 1: Pending invitations to ME ─────────────────────── */}
      {pendingIncoming.length > 0 && (
        <section className="rounded-2xl border-2 border-amber-300 bg-amber-50/70 p-5 sm:p-6">
          <h2 className="flex items-center gap-2 font-dm text-[18px] font-medium tracking-[-0.03em] text-amber-950">
            <ShieldAlert className="h-5 w-5 text-amber-700" strokeWidth={1.8} />
            Invitations addressed to you
          </h2>
          <p className="mt-1 font-inter text-[13px] text-amber-900/80">
            Another family member has invited you to share caregiving responsibilities. To access their
            records, you must explicitly confirm that the patient agreed to this arrangement.
          </p>

          <div className="mt-4 space-y-3">
            {pendingIncoming.map((invite) => (
              <div
                key={invite.id}
                className="rounded-xl border border-amber-200 bg-white p-4 shadow-sm"
              >
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div>
                    <p className="font-dm text-[16px] font-medium text-ink">
                      Caring for: {invite.patient_name ?? "Family member"}
                    </p>
                    <p className="font-inter text-[12px] text-ink/50">
                      Granted: {new Date(invite.granted_at).toLocaleDateString()}
                      {invite.expires_at ? ` · Temporary until ${new Date(invite.expires_at).toLocaleDateString()}` : " · Permanent"}
                    </p>
                  </div>

                  {acceptingId === invite.id ? (
                    <div className="w-full mt-3 space-y-3 rounded-lg bg-amber-50/50 p-3.5 border border-amber-200">
                      <label className="flex items-start gap-2.5 text-[12.5px] font-inter text-ink/80">
                        <input
                          type="checkbox"
                          checked={consentConfirmed}
                          onChange={(e) => setConsentConfirmed(e.target.checked)}
                          className="mt-0.5 h-4 w-4 rounded"
                        />
                        <span>
                          I confirm that {invite.patient_name ?? "this patient"} has consented to me accessing
                          and maintaining their prescription and medical history.
                        </span>
                      </label>
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          disabled={!consentConfirmed || actionBusy}
                          onClick={() => handleAcceptConsent(invite.id)}
                          className="rounded-md bg-ink px-3.5 py-1.5 font-inter text-[12.5px] font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
                        >
                          {actionBusy ? "Accepting…" : "Accept & Record Consent"}
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            setAcceptingId(null);
                            setConsentConfirmed(false);
                          }}
                          className="rounded-md border border-ink/15 bg-white px-3 py-1.5 font-inter text-[12.5px] text-ink/60 hover:text-ink"
                        >
                          Cancel
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="flex items-center gap-2">
                      <button
                        type="button"
                        onClick={() => setAcceptingId(invite.id)}
                        className="rounded-md bg-ink px-3 py-1.5 font-inter text-[12.5px] font-medium text-white transition-opacity hover:opacity-90"
                      >
                        Accept invite
                      </button>
                      <button
                        type="button"
                        onClick={() => handleRevoke(invite.id, invite.patient_name ?? "this invitation")}
                        className="rounded-md border border-ink/15 bg-white px-3 py-1.5 font-inter text-[12.5px] text-ink/60 hover:text-red-700"
                      >
                        Decline
                      </button>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {/* ── Section 2: Shared patients you can switch to ─────────────── */}
      {acceptedShared.length > 0 && (
        <section className="rounded-xl border border-ink/10 bg-paper p-4">
          <p className="font-inter text-[12px] font-medium uppercase tracking-wide text-ink/40">
            Other people you care for
          </p>
          <div className="mt-2 flex flex-wrap gap-2">
            {acceptedShared.map((share) => (
              <button
                key={share.id}
                type="button"
                onClick={() => share.patient_id && switchToPatient(share.patient_id)}
                className="flex items-center gap-2 rounded-lg border border-ink/15 bg-white px-3 py-2 font-inter text-[13px] text-ink transition-colors hover:border-ink/40"
              >
                <Users className="h-4 w-4 text-ink/50" />
                <span>Switch to <strong>{share.patient_name}</strong></span>
              </button>
            ))}
          </div>
        </section>
      )}

      {/* ── Section 3: Invite new caregiver / Handoff ───────────────── */}
      <section className="rounded-2xl border border-ink/10 bg-paper p-6">
        <div className="flex items-center gap-2.5">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-ink/5">
            <UserPlus className="h-4 w-4 text-ink" strokeWidth={1.8} />
          </div>
          <div>
            <h2 className="font-dm text-[18px] font-medium tracking-[-0.03em] text-ink">
              Invite a caregiver or hand off care
            </h2>
            <p className="font-inter text-[12.5px] text-ink/50">
              Grant permanent or temporary access to {patient.display_name}&apos;s profile.
            </p>
          </div>
        </div>

        <form onSubmit={handleInvite} className="mt-5 space-y-4">
          <div>
            <label className="block font-inter text-[12px] font-medium text-ink/60">
              Caregiver&apos;s mobile number
            </label>
            <div className="relative mt-1">
              <Phone className="pointer-events-none absolute left-3 top-3 h-4 w-4 text-ink/30" />
              <input
                type="tel"
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                placeholder="e.g. 9876543210"
                required
                className="h-10 w-full rounded-lg border border-ink/15 bg-white pl-9 pr-3 font-inter text-[13.5px] text-ink outline-none transition-colors focus:border-ink/50"
              />
            </div>
            <p className="mt-1 font-inter text-[11.5px] text-ink/45">
              The caregiver must register for a Taalmel account with this phone number to sign in.
            </p>
          </div>

          <div>
            <label className="block font-inter text-[12px] font-medium text-ink/60">
              Handoff duration
            </label>
            <div className="mt-1.5 grid grid-cols-2 gap-2 sm:grid-cols-5">
              {[
                { id: "permanent", label: "Permanent", desc: "No expiry" },
                { id: "7d", label: "7 days", desc: "Weekly cover" },
                { id: "14d", label: "14 days", desc: "2-week trip" },
                { id: "30d", label: "30 days", desc: "1 month" },
                { id: "custom", label: "Custom", desc: "Pick date" },
              ].map((p) => (
                <button
                  key={p.id}
                  type="button"
                  onClick={() => setDurationPreset(p.id as typeof durationPreset)}
                  className={`rounded-xl border p-2.5 text-left transition-colors ${
                    durationPreset === p.id
                      ? "border-ink bg-ink text-white"
                      : "border-ink/12 bg-white text-ink hover:border-ink/30"
                  }`}
                >
                  <p className="font-dm text-[13.5px] font-medium leading-none">{p.label}</p>
                  <p className={`mt-1 font-inter text-[11px] ${durationPreset === p.id ? "text-white/70" : "text-ink/45"}`}>
                    {p.desc}
                  </p>
                </button>
              ))}
            </div>

            {durationPreset === "custom" && (
              <div className="mt-3">
                <label className="block font-inter text-[11.5px] font-medium text-ink/50">
                  Access closes on:
                </label>
                <input
                  type="date"
                  value={customExpiryDate}
                  min={TODAY_ISO}
                  onChange={(e) => setCustomExpiryDate(e.target.value)}
                  required
                  className="mt-1 h-9 rounded-md border border-ink/15 bg-white px-3 font-inter text-[12.5px] text-ink outline-none"
                />
              </div>
            )}
          </div>

          <div className="rounded-xl border border-ink/10 bg-bone p-3.5">
            <p className="flex items-center gap-2 font-inter text-[12px] font-medium text-ink/75">
              <Shield className="h-4 w-4 text-ink/50" />
              Temporary handoff rule
            </p>
            <p className="mt-0.5 font-inter text-[11.5px] leading-relaxed text-ink/55">
              If an expiry window is set, access shuts off automatically at that exact timestamp.
              No manual revocation is required when returning from travel.
            </p>
          </div>

          <button
            type="submit"
            disabled={inviting || !phone.trim() || (durationPreset === "custom" && !customExpiryDate)}
            className="flex items-center gap-2 rounded-lg bg-ink px-4 py-2.5 font-inter text-[13px] font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {inviting ? <Loader2 className="h-4 w-4 animate-spin" /> : <UserPlus className="h-4 w-4" />}
            {inviting ? "Sending invite…" : "Grant caregiver access"}
          </button>
        </form>
      </section>

      {/* ── Section 4: Current caregivers for patient ────────────────── */}
      <section className="rounded-2xl border border-ink/10 bg-paper p-6">
        <h2 className="font-dm text-[18px] font-medium tracking-[-0.03em] text-ink">
          Caregivers for {patient.display_name}
        </h2>
        <p className="mt-1 font-inter text-[12.5px] text-ink/50">
          Everyone authorized to view, verify, or report medicines for this patient.
        </p>

        {loading ? (
          <p className="mt-4 font-inter text-[13px] text-ink/40">Loading caregivers…</p>
        ) : patientGrants.length === 0 ? (
          <div className="mt-4 rounded-xl border border-dashed border-ink/15 p-6 text-center">
            <Users className="mx-auto h-6 w-6 text-ink/25" />
            <p className="mt-2 font-dm text-[15px] text-ink">Only you currently care for {patient.display_name}</p>
            <p className="mt-0.5 font-inter text-[12px] text-ink/45">
              Use the invite form above to add a spouse, sibling, or relief caregiver.
            </p>
          </div>
        ) : (
          <div className="mt-4 divide-y divide-ink/10 rounded-xl border border-ink/10 bg-white">
            {patientGrants.map((grant) => {
              const isMe = user?.id === grant.caregiver_user_id;
              const isExpired = grant.status === "EXPIRED";
              const isRevoked = grant.status === "REVOKED";
              const isPending = grant.status === "PENDING";
              const isActive = grant.status === "ACTIVE";

              return (
                <div key={grant.id} className="flex flex-wrap items-center justify-between gap-3 p-4">
                  <div className="flex items-center gap-3">
                    <div className="flex h-9 w-9 items-center justify-center rounded-full bg-ink/10 font-dm text-[14px] font-medium text-ink">
                      {(grant.caregiver_name ?? grant.caregiver_phone ?? "?").slice(0, 1).toUpperCase()}
                    </div>
                    <div>
                      <div className="flex items-center gap-2">
                        <span className="font-dm text-[15px] font-medium text-ink">
                          {grant.caregiver_name ?? grant.caregiver_phone}
                        </span>
                        {isMe && (
                          <span className="rounded bg-ink/5 px-1.5 py-0.5 font-inter text-[10.5px] font-medium text-ink/60">
                            You
                          </span>
                        )}
                      </div>
                      <div className="flex flex-wrap items-center gap-2 mt-0.5 font-inter text-[12px] text-ink/50">
                        {grant.caregiver_phone && <span>{grant.caregiver_phone}</span>}
                        <span>•</span>
                        {grant.expires_at ? (
                          <span className="flex items-center gap-1 text-ink/70">
                            <Clock className="h-3 w-3 text-ink/40" />
                            {isExpired ? "Expired" : "Expires"}: {new Date(grant.expires_at).toLocaleDateString()}
                          </span>
                        ) : (
                          <span className="flex items-center gap-1">
                            <Calendar className="h-3 w-3 text-ink/40" /> Permanent
                          </span>
                        )}
                      </div>
                    </div>
                  </div>

                  <div className="flex items-center gap-3">
                    {/* Status Pill */}
                    <span
                      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 font-inter text-[11px] font-medium ${
                        isActive
                          ? "bg-emerald-100 text-emerald-800"
                          : isPending
                          ? "bg-amber-100 text-amber-800"
                          : isExpired
                          ? "bg-rose-100 text-rose-800"
                          : "bg-ink/10 text-ink/60"
                      }`}
                    >
                      {isActive && <UserCheck className="h-3 w-3" />}
                      {grant.status}
                    </span>

                    {/* Revoke button */}
                    {!isRevoked && !isExpired && (
                      <button
                        type="button"
                        disabled={actionBusy}
                        onClick={() =>
                          handleRevoke(
                            grant.id,
                            grant.caregiver_name ?? grant.caregiver_phone ?? "caregiver",
                          )
                        }
                        className="flex items-center gap-1 rounded-md border border-ink/12 px-2.5 py-1.5 font-inter text-[12px] text-ink/60 transition-colors hover:border-red-300 hover:text-red-700"
                      >
                        <UserMinus className="h-3.5 w-3.5" />
                        Revoke
                      </button>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* ── Section 5: Emergency Contacts ──────────────────────────── */}
      <section className="rounded-2xl border border-ink/10 bg-paper p-6">
        <div className="flex items-center gap-2">
          <ShieldAlert className="h-5 w-5 text-ink/70" strokeWidth={1.8} />
          <div>
            <h2 className="font-dm text-[18px] font-medium tracking-[-0.03em] text-ink">
              Emergency contacts
            </h2>
            <p className="mt-0.5 font-inter text-[12.5px] text-ink/50">
              In addition to the primary caregiver, these contacts are notified immediately if a CRITICAL
              alert or drug-safety trigger is detected.
            </p>
          </div>
        </div>

        {emergencyContacts.length > 0 && (
          <div className="mt-4 space-y-2">
            {emergencyContacts.map((contact) => (
              <div
                key={contact.id}
                className="flex items-center justify-between rounded-xl border border-ink/10 bg-white px-4 py-3"
              >
                <div>
                  <p className="font-dm text-[14px] font-medium text-ink">
                    User ID: {contact.user_id.slice(0, 8)}…
                  </p>
                  <p className="font-inter text-[12px] text-ink/50">
                    Relationship: {contact.relationship ?? "Caregiver contact"}
                  </p>
                </div>
                <button
                  type="button"
                  disabled={actionBusy}
                  onClick={() => handleRemoveEmergencyContact(contact.id)}
                  className="rounded px-2.5 py-1 font-inter text-[11.5px] text-ink/40 hover:text-red-700"
                >
                  Remove
                </button>
              </div>
            ))}
          </div>
        )}

        <form onSubmit={handleAddEmergencyContact} className="mt-4 flex flex-wrap items-center gap-2">
          <select
            value={emergencyUserId}
            onChange={(e) => setEmergencyUserId(e.target.value)}
            className="h-9 min-w-[200px] flex-1 rounded-md border border-ink/15 bg-white px-2.5 font-inter text-[12.5px] text-ink outline-none"
          >
            <option value="">Select an active caregiver</option>
            {patientGrants
              .filter((g) => g.status === "ACTIVE")
              .map((g) => (
                <option key={g.caregiver_user_id} value={g.caregiver_user_id}>
                  {g.caregiver_name ?? g.caregiver_phone} {g.caregiver_user_id === user?.id ? "(You)" : ""}
                </option>
              ))}
          </select>
          <input
            value={emergencyRelation}
            onChange={(e) => setEmergencyRelation(e.target.value)}
            placeholder="Relationship (e.g. Sister, Doctor)"
            className="h-9 min-w-[180px] flex-1 rounded-md border border-ink/15 bg-white px-2.5 font-inter text-[12.5px] text-ink outline-none"
          />
          <button
            type="submit"
            disabled={addingEmergency || !emergencyUserId}
            className="rounded-md bg-ink px-3.5 py-2 font-inter text-[12.5px] font-medium text-white transition-opacity hover:opacity-90 disabled:opacity-50"
          >
            {addingEmergency ? "Adding…" : "Add contact"}
          </button>
        </form>
      </section>
    </div>
  );
}
