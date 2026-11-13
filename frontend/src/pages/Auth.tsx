import { useState } from "react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { ArrowLeft, Loader2 } from "lucide-react";
import { useAuth } from "../lib/auth";

/**
 * Sign in / sign up.
 *
 * The backend identifies users by phone number, so that is the primary field.
 * Validation is deliberately minimal and local; the server is the authority and
 * its message is shown verbatim, because a generic "something went wrong" hides
 * the one thing the user needs to fix.
 */
export default function Auth({ mode }: { mode: "signin" | "signup" }) {
  const { user, signIn, signUp, ready } = useAuth();
  const navigate = useNavigate();

  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (ready && user) return <Navigate to="/app" replace />;

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);

    if (!/^\+?\d{6,15}$/.test(phone.replace(/[^\d+]/g, ""))) {
      setError("Enter a phone number with 6 to 15 digits.");
      return;
    }
    if (password.length < 8) {
      setError("Choose a password of at least 8 characters.");
      return;
    }
    if (mode === "signup" && name.trim().length < 2) {
      setError("Enter your name.");
      return;
    }

    setBusy(true);
    try {
      if (mode === "signup") await signUp(name, phone, password);
      else await signIn(phone, password);
      navigate("/app", { replace: true });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not sign in.");
    } finally {
      setBusy(false);
    }
  }

  const isSignup = mode === "signup";

  return (
    <div className="relative flex min-h-screen flex-col bg-ink">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0"
        style={{
          background:
            "radial-gradient(110% 80% at 20% 0%, #16302a 0%, #0d1a18 45%, #0c1110 75%)",
        }}
      />

      <div className="relative z-10 flex items-center justify-between px-5 py-5 sm:px-8 lg:px-10">
        <Link
          to="/"
          className="flex items-center gap-2 font-dm text-[24px] font-medium tracking-[-0.05em] text-white sm:text-[28px]"
        >
          <ArrowLeft className="h-4 w-4" strokeWidth={1.8} />
          Taalmel
        </Link>
        <Link
          to={isSignup ? "/signin" : "/signup"}
          className="font-inter text-sm tracking-[-0.03em] text-white/70 transition-colors hover:text-white"
        >
          {isSignup ? "Sign in" : "Create account"}
        </Link>
      </div>

      <div className="relative z-10 flex flex-1 items-center justify-center px-5 pb-16">
        <div className="w-full max-w-[420px]">
          <h1 className="font-dm text-[34px] font-normal leading-[1.05] tracking-[-0.05em] text-white sm:text-[40px]">
            {isSignup ? "Create your account" : "Welcome back"}
          </h1>
          <p className="mt-3 font-inter text-sm leading-relaxed tracking-[-0.03em] text-white/55">
            {isSignup
              ? "You will add the person you care for next."
              : "Sign in to see what needs attention today."}
          </p>

          <form onSubmit={submit} className="mt-8 space-y-4" noValidate>
            {isSignup && (
              <Field
                label="Your name"
                value={name}
                onChange={setName}
                autoComplete="name"
                placeholder="Asha Sharma"
              />
            )}
            <Field
              label="Phone number"
              value={phone}
              onChange={setPhone}
              autoComplete="tel"
              inputMode="tel"
              placeholder="9876543210"
              hint="This is how you sign in."
            />
            <Field
              label="Password"
              value={password}
              onChange={setPassword}
              type="password"
              autoComplete={isSignup ? "new-password" : "current-password"}
              placeholder="At least 8 characters"
            />

            {error && (
              <p
                role="alert"
                className="rounded-md border border-red-400/30 bg-red-500/10 px-3 py-2 font-inter text-[13px] leading-snug text-red-200"
              >
                {error}
              </p>
            )}

            <button
              type="submit"
              disabled={busy}
              className="flex h-14 w-full items-center justify-center gap-2 rounded-md bg-white font-inter text-base font-medium tracking-[-0.03em] text-ink transition-opacity hover:opacity-90 disabled:opacity-60"
            >
              {busy && <Loader2 className="h-4 w-4 animate-spin" strokeWidth={2} />}
              {isSignup ? "Create account" : "Sign in"}
            </button>
          </form>

          <p className="mt-6 font-inter text-[12.5px] leading-relaxed tracking-[-0.02em] text-white/40">
            Taalmel records what happened to a medicine. It does not diagnose, change a
            prescription, or give medical advice.
          </p>
        </div>
      </div>
    </div>
  );
}

function Field({
  label,
  value,
  onChange,
  type = "text",
  ...rest
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  type?: string;
  autoComplete?: string;
  inputMode?: "tel" | "text";
  placeholder?: string;
  hint?: string;
}) {
  return (
    <label className="block">
      <span className="font-inter text-[13px] font-medium tracking-[-0.02em] text-white/70">
        {label}
      </span>
      <input
        {...rest}
        type={type}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="mt-1.5 h-12 w-full rounded-md border border-white/15 bg-white/[0.06] px-3.5 font-inter text-[15px] text-white placeholder-white/30 outline-none transition-colors focus:border-white/40"
      />
      {rest.hint && <span className="mt-1 block font-inter text-[11.5px] text-white/35">{rest.hint}</span>}
    </label>
  );
}
