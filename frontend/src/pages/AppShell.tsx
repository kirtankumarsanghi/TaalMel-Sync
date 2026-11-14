import { NavLink, Navigate, Outlet, useNavigate } from "react-router-dom";
import { useEffect, useState } from "react";
import {
  Activity,
  FileText,
  HeartPulse,
  LayoutDashboard,
  LogOut,
  Menu,
  Pill,
  ShieldCheck,
  X,
} from "lucide-react";
import { useAuth } from "../lib/auth";
import { useHousehold } from "../lib/household";
import { useA11y } from "../lib/i18n";
import { api } from "../lib/api";
import type { NotificationRow } from "../lib/api";
import Onboarding from "./Onboarding";

const LINKS = [
  { to: "/app", key: "nav.today", fallback: "Today", icon: LayoutDashboard, end: true },
  { to: "/app/medicines", key: "nav.medicines", fallback: "Medicines", icon: Pill, end: false },
  { to: "/app/cases", key: "nav.cases", fallback: "Cases", icon: Activity, end: false },
  { to: "/app/wellness", key: "nav.wellness", fallback: "Wellness", icon: HeartPulse, end: false },
  { to: "/app/export", key: "nav.export", fallback: "Doctor export", icon: FileText, end: false },
  { to: "/app/safety", key: "nav.safety", fallback: "Safety", icon: ShieldCheck, end: false },
];

export default function AppShell() {
  const { user, signOut } = useAuth();
  const { patient, ready } = useHousehold();
  const {
    language,
    languages,
    setLanguage,
    t,
    largeText,
    setLargeText,
    highContrast,
    setHighContrast,
  } = useA11y();
  const navigate = useNavigate();
  const [menuOpen, setMenuOpen] = useState(false);
  const [notifications, setNotifications] = useState<NotificationRow[]>([]);

  useEffect(() => {
    if (!user) return;
    let cancelled = false;
    api
      .notifications()
      .then((rows) => {
        if (!cancelled) setNotifications(rows);
      })
      .catch(() => {
        // Notifications are supplementary; a failure must not block the app.
      });
    return () => {
      cancelled = true;
    };
  }, [user]);

  if (!ready) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-bone">
        <p className="font-inter text-sm text-ink/50">Loading…</p>
      </div>
    );
  }

  // A doctor account belongs in the dashboard, not the caregiver reconciliation shell.
  if (user?.role === "doctor") return <Navigate to="/doctor/dashboard" replace />;

  // A caregiver with no patient yet has nothing to reconcile, so onboarding comes
  // before the rest of the app rather than as an empty state.
  if (!patient) return <Onboarding />;

  const unread = notifications.filter((n) => !n.is_read).length;

  return (
    <div className="min-h-screen bg-bone">
      {/* Sidebar */}
      <aside
        className={`fixed inset-y-0 left-0 z-40 w-[248px] transform border-r border-ink/10 bg-paper transition-transform duration-300 lg:translate-x-0 ${
          menuOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        <div className="flex h-16 items-center justify-between px-5">
          <span className="font-dm text-[22px] font-medium tracking-[-0.05em] text-ink">Taalmel</span>
          <button
            type="button"
            aria-label="Close menu"
            onClick={() => setMenuOpen(false)}
            className="text-ink/50 lg:hidden"
          >
            <X className="h-5 w-5" strokeWidth={1.6} />
          </button>
        </div>

        <div className="px-4 pb-2">
          <div className="rounded-lg bg-ink/[0.04] px-3 py-2.5">
            <p className="font-inter text-[11px] uppercase tracking-wide text-ink/40">Caring for</p>
            <p className="mt-0.5 truncate font-dm text-[15px] font-medium tracking-[-0.02em] text-ink">
              {patient.display_name}
            </p>
          </div>
        </div>

        <nav className="mt-2 space-y-0.5 px-3">
          {LINKS.map(({ to, key, fallback, icon: Icon, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              onClick={() => setMenuOpen(false)}
              className={({ isActive }) =>
                `flex items-center gap-3 rounded-lg px-3 py-2.5 font-inter text-[14px] tracking-[-0.02em] transition-colors ${
                  isActive
                    ? "bg-ink text-white"
                    : "text-ink/70 hover:bg-ink/[0.05] hover:text-ink"
                }`
              }
            >
              <Icon className="h-4 w-4" strokeWidth={1.7} />
              {t(key, fallback)}
              {key === "nav.cases" && unread > 0 && (
                <span className="ml-auto rounded-full bg-amber-500/20 px-1.5 py-0.5 text-[10px] font-medium text-amber-700">
                  {unread}
                </span>
              )}
            </NavLink>
          ))}
        </nav>

        <div className="absolute inset-x-0 bottom-0 border-t border-ink/10 p-3 space-y-2.5">
          {/* Patient language & accessibility toggles */}
          <div className="space-y-1.5 px-2">
            <label className="block font-inter text-[11px] uppercase tracking-wide text-ink/40">
              Patient language
              <select
                value={language}
                onChange={(e) => setLanguage(e.target.value)}
                className="mt-1 w-full rounded-md border border-ink/15 bg-bone px-2 py-1 font-inter text-[12px] text-ink"
              >
                {languages.map((lang) => (
                  <option key={lang.code} value={lang.code}>
                    {lang.native} ({lang.name})
                  </option>
                ))}
              </select>
            </label>
            <div className="flex items-center gap-1.5 pt-0.5">
              <button
                type="button"
                onClick={() => setLargeText(!largeText)}
                aria-pressed={largeText}
                className={`flex-1 rounded-md border px-2 py-1 font-inter text-[11px] transition-colors ${
                  largeText
                    ? "border-ink bg-ink text-white"
                    : "border-ink/15 bg-bone text-ink/70 hover:text-ink"
                }`}
              >
                Large text
              </button>
              <button
                type="button"
                onClick={() => setHighContrast(!highContrast)}
                aria-pressed={highContrast}
                className={`flex-1 rounded-md border px-2 py-1 font-inter text-[11px] transition-colors ${
                  highContrast
                    ? "border-ink bg-ink text-white"
                    : "border-ink/15 bg-bone text-ink/70 hover:text-ink"
                }`}
              >
                High contrast
              </button>
            </div>
          </div>

          <div className="flex items-center gap-2.5 border-t border-ink/10 px-2 pt-2 pb-1">
            <div className="flex h-8 w-8 items-center justify-center rounded-full bg-ink/10 font-dm text-[13px] font-medium text-ink">
              {(user?.name ?? "?").slice(0, 1).toUpperCase()}
            </div>
            <div className="min-w-0 flex-1">
              <p className="truncate font-inter text-[13px] text-ink">{user?.name}</p>
              <p className="truncate font-inter text-[11px] text-ink/40">{user?.phone}</p>
            </div>
            <button
              type="button"
              aria-label="Sign out"
              onClick={async () => {
                await signOut();
                navigate("/", { replace: true });
              }}
              className="text-ink/40 transition-colors hover:text-ink"
            >
              <LogOut className="h-4 w-4" strokeWidth={1.7} />
            </button>
          </div>
        </div>
      </aside>

      {menuOpen && (
        <button
          type="button"
          aria-label="Close menu"
          onClick={() => setMenuOpen(false)}
          className="fixed inset-0 z-30 bg-black/40 lg:hidden"
        />
      )}

      {/* Content */}
      <div className="lg:pl-[248px]">
        <header className="sticky top-0 z-20 flex h-16 items-center gap-3 border-b border-ink/10 bg-bone/90 px-5 backdrop-blur sm:px-8">
          <button
            type="button"
            aria-label="Open menu"
            onClick={() => setMenuOpen(true)}
            className="text-ink/60 lg:hidden"
          >
            <Menu className="h-5 w-5" strokeWidth={1.7} />
          </button>
          <span className="font-inter text-[13px] text-ink/45">
            {unread > 0 ? `${unread} update${unread === 1 ? "" : "s"} need attention` : "Nothing needs attention right now"}
          </span>
        </header>

        <main className="px-5 py-6 sm:px-8 sm:py-8">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
