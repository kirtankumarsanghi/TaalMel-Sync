/**
 * Household context.
 *
 * The backend is built around a "household member" (the patient), not around the
 * caregiver's account. A caregiver's first useful screen therefore depends on
 * knowing which patient they are looking at, so it is resolved once here.
 */

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { api } from "./api";
import type { Patient } from "./api";
import { useAuth } from "./auth";

const STORAGE_KEY = "taalmel.member";

type HouseholdState = {
  patient: Patient | null;
  ready: boolean;
  error: string | null;
  createHousehold: (householdName: string, patientName: string) => Promise<void>;
  selectPatient: (patient: Patient) => void;
  refresh: () => Promise<void>;
};

const HouseholdContext = createContext<HouseholdState | null>(null);

export function HouseholdProvider({ children }: { children: ReactNode }) {
  const { user, ready: authReady } = useAuth();
  const [patient, setPatient] = useState<Patient | null>(null);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const stored = sessionStorage.getItem(STORAGE_KEY);
    if (!stored) {
      setReady(true);
      return;
    }
    try {
      const parsed = JSON.parse(stored) as Patient;
      const fresh = await api.getPatient(parsed.patient_id);
      setPatient(fresh);
    } catch {
      sessionStorage.removeItem(STORAGE_KEY);
      setPatient(null);
    } finally {
      setReady(true);
    }
  }, []);

  useEffect(() => {
    if (!authReady) return;
    if (!user) {
      setPatient(null);
      setReady(true);
      return;
    }
    void load();
  }, [authReady, user, load]);

  const selectPatient = useCallback((next: Patient) => {
    sessionStorage.setItem(STORAGE_KEY, JSON.stringify(next));
    setPatient(next);
  }, []);

  const createHousehold = useCallback(
    async (householdName: string, patientName: string) => {
      setError(null);
      try {
        const created = await api.createHousehold(householdName, patientName);
        selectPatient(created.patient);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not create the household.");
        throw err;
      }
    },
    [selectPatient],
  );

  return (
    <HouseholdContext.Provider
      value={{ patient, ready, error, createHousehold, selectPatient, refresh: load }}
    >
      {children}
    </HouseholdContext.Provider>
  );
}

export function useHousehold(): HouseholdState {
  const context = useContext(HouseholdContext);
  if (!context) throw new Error("useHousehold must be used inside HouseholdProvider");
  return context;
}
