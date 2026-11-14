import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import {
  ArrowUpRight,
  Check,
  Clock,
  FileText,
  Menu,
  Package,
  Pill,
  Search,
  ShieldAlert,
  UserRound,
  X,
} from "lucide-react";

/**
 * Landing page.
 *
 * Structure follows the reference design: full-height hero, nav, word-by-word
 * headline, CTA row, and a three-panel strip. The content is rewritten for
 * medication reconciliation, and the "product image" is replaced with live-looking
 * evidence UI, because a stock photo would say less about this product than the
 * actual artifact does.
 */

const NAV_LINKS = [
  { label: "How it works", href: "#how" },
  { label: "Evidence", href: "#evidence" },
  { label: "Doctors", href: "#doctors" },
  { label: "Safety", href: "#safety" },
];

function Word({ children, delay, dim }: { children: string; delay: number; dim?: boolean }) {
  return (
    <span className="inline-block overflow-hidden align-bottom">
      <span
        className={dim ? "inline-block text-white/40" : "inline-block text-white"}
        style={{ animation: `wordReveal 0.7s cubic-bezier(0.16,1,0.3,1) ${delay}s both` }}
      >
        {children}
      </span>
    </span>
  );
}

function EvidenceCard() {
  return (
    <div className="w-full max-w-[420px] rounded-2xl border border-white/15 bg-white/[0.07] p-5 backdrop-blur-md">
      <div className="flex items-center justify-between">
        <span className="font-dm text-[15px] font-medium tracking-tight text-white">
          Metformin 500mg
        </span>
        <span className="rounded-full bg-amber-400/15 px-2.5 py-1 text-[11px] font-medium text-amber-200">
          Discrepancy
        </span>
      </div>

      <div className="mt-4 space-y-2.5">
        {[
          { icon: FileText, label: "Prescribed", value: "Active", tone: "text-white/70", ok: true },
          { icon: UserRound, label: "Patient reports", value: "Stopped", tone: "text-white/70", ok: false },
          { icon: Package, label: "Stock at home", value: "Present", tone: "text-white/70", ok: true },
        ].map(({ icon: Icon, label, value }) => (
          <div key={label} className="flex items-center gap-2.5 text-[13px]">
            <Icon className="h-3.5 w-3.5 shrink-0 text-white/40" strokeWidth={1.5} />
            <span className="text-white/50">{label}</span>
            <span className={`ml-auto ${value === "Stopped" ? "text-amber-200" : "text-white/85"}`}>
              {value}
            </span>
          </div>
        ))}
      </div>

      <div className="mt-4 border-t border-white/10 pt-3.5">
        <p className="text-[12.5px] leading-snug text-white/60">
          <span className="text-white/85">Why?</span> Ran out — case opened, caregiver notified.
        </p>
      </div>
    </div>
  );
}

function BreachCard() {
  return (
    <div className="w-full max-w-[360px] rounded-2xl border border-white/15 bg-white/[0.07] p-5 backdrop-blur-md">
      <div className="flex items-start gap-3">
        <div className="rounded-full bg-red-500/20 p-2">
          <ShieldAlert className="h-4 w-4 text-red-300" strokeWidth={1.5} />
        </div>
        <div className="flex-1">
          <p className="font-dm text-[14px] font-medium leading-tight tracking-tight text-white">
            Expired stock still in the cabinet
          </p>
          <p className="mt-1.5 text-[12.5px] leading-snug text-white/55">
            Amlodipine 5mg expired 3 months ago. Case opened, emergency contact notified.
          </p>
        </div>
      </div>
    </div>
  );
}

export default function Landing() {
  const [menuOpen, setMenuOpen] = useState(false);
  const [card, setCard] = useState(0);

  // The rotating panel is paused while the menu is open so two motions never
  // compete for attention.
  useEffect(() => {
    if (menuOpen) return;
    const id = window.setInterval(() => setCard((current) => (current + 1) % 4), 3500);
    return () => window.clearInterval(id);
  }, [menuOpen]);

  useEffect(() => {
    document.body.style.overflow = menuOpen ? "hidden" : "";
    return () => {
      document.body.style.overflow = "";
    };
  }, [menuOpen]);

  const panels = [
    {
      icon: Pill,
      bg: "bg-black",
      text: "Three sources — prescription, patient report, stock at home — reconciled into one clear status.",
    },
    {
      icon: Check,
      bg: "bg-emerald-800",
      text: "Every fact carries its source and its age, so an old check is never mistaken for a current one.",
    },
    {
      icon: Clock,
      bg: "bg-cyan-800",
      text: "Cases stay open until a person resolves them. Nothing disappears quietly between visits.",
    },
    {
      icon: FileText,
      bg: "bg-amber-700",
      text: "A doctor scans a QR code and reads a sourced history. No login, no app, no email.",
    },
  ];

  return (
    <div className="relative flex min-h-screen flex-col overflow-hidden bg-ink">
      {/* Background: layered gradient stands in for a photograph, which keeps the page
          fast and avoids shipping an image that has nothing to do with the product. */}
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 z-0"
        style={{
          background:
            "radial-gradient(120% 90% at 15% 10%, #16302a 0%, #0d1a18 38%, #0c1110 72%), radial-gradient(80% 70% at 85% 85%, #1d3a2f 0%, transparent 60%)",
        }}
      />
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 z-0 opacity-[0.05]"
        style={{
          backgroundImage:
            "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='120' height='120'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.85' numOctaves='3'/%3E%3C/filter%3E%3Crect width='120' height='120' filter='url(%23n)'/%3E%3C/svg%3E\")",
        }}
      />

      {/* Navbar */}
      <nav className="animate-fade-in relative z-20 flex items-center justify-between px-5 py-4 sm:px-8 lg:px-10 lg:py-5">
        <Link
          to="/"
          className="animate-slide-left delay-200 font-dm text-[24px] font-medium tracking-[-0.05em] text-white sm:text-[30px]"
        >
          Taalmel
        </Link>

        <div className="animate-fade-in delay-400 hidden items-center gap-10 lg:flex">
          {NAV_LINKS.map((link) => (
            <a
              key={link.label}
              href={link.href}
              className="font-dm text-[16px] font-medium text-white/90 transition-colors hover:text-white xl:text-[18px]"
            >
              {link.label}
            </a>
          ))}
        </div>

        <div className="animate-slide-right delay-300 flex items-center gap-3 sm:gap-4">
          <button
            type="button"
            aria-label="Search"
            className="hidden text-white/85 transition-colors hover:text-white sm:block"
          >
            <Search size={20} strokeWidth={1.5} />
          </button>
          <button
            type="button"
            aria-label="Medicines"
            className="hidden text-white/85 transition-colors hover:text-white sm:block"
          >
            <Pill size={20} strokeWidth={1.5} />
          </button>
          <Link
            to="/app"
            className="hidden rounded-full bg-white px-4 py-2 font-inter text-[13px] font-medium tracking-[-0.03em] text-ink transition-opacity hover:opacity-90 sm:block"
          >
            Open app
          </Link>
          <button
            type="button"
            aria-label={menuOpen ? "Close menu" : "Open menu"}
            onClick={() => setMenuOpen((open) => !open)}
            className="text-white lg:hidden"
          >
            {menuOpen ? <X size={22} strokeWidth={1.5} /> : <Menu size={22} strokeWidth={1.5} />}
          </button>
        </div>
      </nav>

      {/* Mobile menu */}
      <div
        className={`fixed inset-0 z-30 flex flex-col items-center justify-center gap-8 bg-black/95 transition-opacity duration-300 lg:hidden ${
          menuOpen ? "pointer-events-auto opacity-100" : "pointer-events-none opacity-0"
        }`}
      >
        <button
          type="button"
          aria-label="Close menu"
          onClick={() => setMenuOpen(false)}
          className="absolute right-5 top-5 text-white"
        >
          <X size={26} strokeWidth={1.5} />
        </button>
        {NAV_LINKS.map((link) => (
          <a
            key={link.label}
            href={link.href}
            onClick={() => setMenuOpen(false)}
            className="font-dm text-2xl font-medium tracking-tight text-white"
          >
            {link.label}
          </a>
        ))}
        <Link
          to="/app"
          onClick={() => setMenuOpen(false)}
          className="mt-4 rounded-full bg-white px-6 py-3 font-inter text-sm font-medium text-ink"
        >
          Open the app
        </Link>
      </div>

      {/* Hero */}
      <section className="relative z-10 flex flex-1 flex-col justify-center px-5 pb-8 pt-4 sm:px-8 lg:px-10 lg:pb-12">
        <div className="max-w-[min(100%,58rem)]">
          <h1 className="font-dm font-normal tracking-[-0.05em] text-[48px] leading-[50px] sm:text-[68px] sm:leading-[64px] md:text-[84px] md:leading-[78px] lg:text-[100px] lg:leading-[92px] xl:text-[112px] xl:leading-[102px]">
            <span className="block">
              <Word delay={0.3}>Every</Word> <Word delay={0.4}>dose,</Word>{" "}
              <Word delay={0.5} dim>
                finally
              </Word>
            </span>
            <span className="block">
              <Word delay={0.6} dim>
                accounted
              </Word>{" "}
              <Word delay={0.7} dim>
                for
              </Word>{" "}
              <Word delay={0.8}>—</Word>
            </span>
            <span className="block">
              <Word delay={0.9}>not</Word> <Word delay={1.0}>assumed.</Word>
            </span>
          </h1>

          {/* CTA row */}
          <div className="animate-fade-up delay-600 mt-8 flex flex-col items-stretch gap-5 sm:mt-12 sm:flex-row sm:items-center sm:gap-8 lg:mt-[60px] lg:gap-[50px]">
            <Link
              to="/app"
              className="group flex h-14 w-full items-center justify-center gap-2.5 rounded-md bg-black px-6 font-inter text-base font-medium tracking-[-0.03em] text-white ring-1 ring-white/15 transition-transform hover:-translate-y-0.5 sm:h-16 sm:w-[240px] md:w-[280px] lg:h-[72px] lg:w-[310px] lg:text-xl"
            >
              Open the app
              <ArrowUpRight size={20} strokeWidth={1.8} className="transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
            </Link>

            <p className="max-w-[310px] font-inter text-sm font-normal leading-[1.45] tracking-[-0.03em] text-white/75 sm:text-base lg:text-lg">
              Taalmel reconciles the prescription, what the patient reports, and what is
              actually in the cabinet — then tracks every gap until someone closes it.
            </p>
          </div>
        </div>

        {/* Mobile / tablet visual */}
        <div className="animate-scale-in delay-800 mt-8 flex items-center justify-center lg:hidden">
          <EvidenceCard />
        </div>
      </section>

      {/* Desktop floating visual.
          z-20 puts it above the hero section, which is z-10 and spans the full height.
          pointer-events-none keeps it from intercepting the headline or CTA. */}
      <div className="animate-scale-in delay-700 pointer-events-none absolute bottom-[30%] right-6 z-20 hidden w-[420px] lg:block xl:right-12">
        <EvidenceCard />
      </div>

      {/* Three-panel strip. Stacks until lg: at md width a 2:1:2 grid squeezes the middle
          column until text wraps one word per line. */}
      <div id="how" className="relative z-10 mt-auto grid grid-cols-1 md:grid-cols-2 lg:grid-cols-[2fr_1fr_2fr]">
        {/* Panel 1 */}
        <div className="animate-fade-up delay-900 relative overflow-hidden bg-bone px-6 py-8 sm:px-8 sm:py-10 lg:px-10 lg:py-12">
          <p className="font-dm text-2xl font-normal leading-[1.1] tracking-[-0.05em] text-ink sm:text-[26px] lg:text-[32px]">
            Start with a prescription. We will build the record from there.
          </p>
          <Link
            to="/app"
            className="mt-6 inline-block font-inter text-base font-normal tracking-[-0.03em] text-ink underline underline-offset-4 transition-opacity hover:opacity-70 lg:text-lg"
          >
            Set up a household
          </Link>
        </div>

        {/* Panel 2 — rotating */}
        <div id="evidence" className="animate-fade-up delay-1000 flex flex-col justify-between gap-5 bg-paper px-6 py-8 sm:px-8 sm:py-10">
          <div className="relative flex-1">
            {panels.map((panel, index) => {
              const Icon = panel.icon;
              const active = index === card;
              return (
                <div
                  key={panel.text}
                  className={`flex items-start gap-3.5 transition-all duration-500 ${
                    active
                      ? "translate-y-0 opacity-100"
                      : "pointer-events-none absolute inset-x-0 top-0 translate-y-4 opacity-0"
                  }`}
                >
                  <div
                    className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full sm:h-12 sm:w-12 ${panel.bg}`}
                  >
                    <Icon className="h-4 w-4 text-white sm:h-5 sm:w-5" strokeWidth={1.6} />
                  </div>
                  <p className="font-inter text-sm font-normal leading-[1.25] tracking-[-0.03em] text-black/80 sm:text-base lg:text-[17px]">
                    {panel.text}
                  </p>
                </div>
              );
            })}
          </div>

          <div className="flex gap-1.5">
            {panels.map((panel, index) => (
              <button
                key={panel.text}
                type="button"
                aria-label={`Show panel ${index + 1}`}
                onClick={() => setCard(index)}
                className={`h-0.5 flex-1 rounded-full transition-colors ${
                  index === card ? "bg-black" : "bg-black/20"
                }`}
              />
            ))}
          </div>
        </div>

        {/* Panel 3 */}
        <div id="doctors" className="animate-fade-up delay-1100 flex flex-col justify-center gap-5 bg-black px-6 py-8 sm:px-8 sm:py-10 md:col-span-2 lg:col-span-1 lg:px-10">
          <BreachCard />
          <div className="flex items-baseline gap-2.5">
            <p className="font-inter text-2xl font-normal leading-none tracking-[-0.05em] text-white sm:text-3xl lg:text-[34px]">
              6
            </p>
            <p className="font-inter text-[12.5px] font-normal leading-[1.2] tracking-[-0.03em] text-white/60 sm:text-[13.5px]">
              sources — every fact dated, sourced and traceable
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
