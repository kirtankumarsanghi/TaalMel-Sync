import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import type { ReactNode } from "react";
import { AuthProvider, useAuth } from "./lib/auth";
import { HouseholdProvider } from "./lib/household";
import { A11yProvider } from "./lib/i18n";
import Landing from "./pages/Landing";
import Auth from "./pages/Auth";
import AppShell from "./pages/AppShell";
import Dashboard from "./pages/Dashboard";
import Medicines from "./pages/Medicines";
import { CaseDetail, Cases } from "./pages/Cases";
import DoctorExport, { Safety } from "./pages/DoctorExport";
import DoctorView from "./pages/DoctorView";
import DoctorDashboard from "./pages/DoctorDashboard";
import Wellness from "./pages/Wellness";

function RequireAuth({ children }: { children: ReactNode }) {
  const { user, ready } = useAuth();
  if (!ready) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-bone">
        <p className="font-inter text-sm text-ink/40">Loading…</p>
      </div>
    );
  }
  if (!user) return <Navigate to="/signin" replace />;
  return <>{children}</>;
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <A11yProvider>
          <HouseholdProvider>
          <Routes>
            <Route path="/" element={<Landing />} />
            <Route path="/signin" element={<Auth mode="signin" />} />
            <Route path="/signup" element={<Auth mode="signup" />} />

            {/* Public, token-gated: the doctor's entire interface. */}
            <Route path="/doctor/:token" element={<DoctorView />} />

            {/* Optional doctor account dashboard. Public links remain the default. */}
            <Route
              path="/doctor/dashboard"
              element={
                <RequireAuth>
                  <DoctorDashboard />
                </RequireAuth>
              }
            />

            <Route
              path="/app"
              element={
                <RequireAuth>
                  <AppShell />
                </RequireAuth>
              }
            >
              <Route index element={<Dashboard />} />
              <Route path="medicines" element={<Medicines />} />
              <Route path="cases" element={<Cases />} />
              <Route path="cases/:caseId" element={<CaseDetail />} />
              <Route path="export" element={<DoctorExport />} />
              <Route path="safety" element={<Safety />} />
              <Route path="wellness" element={<Wellness />} />
            </Route>

            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
          </HouseholdProvider>
        </A11yProvider>
      </AuthProvider>
    </BrowserRouter>
  );
}
