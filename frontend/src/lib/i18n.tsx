import { createContext, useContext, useEffect, useState } from "react";
import type { ReactNode } from "react";
import { api } from "./api";

type LanguageInfo = { code: string; name: string; native: string };

type A11yContextValue = {
  language: string;
  languages: LanguageInfo[];
  strings: Record<string, string>;
  setLanguage: (code: string) => void;
  t: (key: string, fallback: string) => string;
  largeText: boolean;
  setLargeText: (on: boolean) => void;
  highContrast: boolean;
  setHighContrast: (on: boolean) => void;
};

const A11yContext = createContext<A11yContextValue | null>(null);

export function A11yProvider({ children }: { children: ReactNode }) {
  const [language, setLanguageState] = useState<string>(
    () => localStorage.getItem("taalmel.lang") || "en",
  );
  const [languages, setLanguages] = useState<LanguageInfo[]>([
    { code: "en", name: "English", native: "English" },
  ]);
  const [strings, setStrings] = useState<Record<string, string>>({});
  const [largeText, setLargeTextState] = useState<boolean>(
    () => localStorage.getItem("taalmel.largeText") === "1",
  );
  const [highContrast, setHighContrastState] = useState<boolean>(
    () => localStorage.getItem("taalmel.highContrast") === "1",
  );

  useEffect(() => {
    api
      .languages()
      .then(setLanguages)
      .catch(() => {
        // Keep English fallback if offline.
      });
  }, []);

  useEffect(() => {
    api
      .catalogue(language)
      .then((res) => setStrings(res.strings))
      .catch(() => setStrings({}));
  }, [language]);

  useEffect(() => {
    document.documentElement.classList.toggle("taalmel-large-text", largeText);
    localStorage.setItem("taalmel.largeText", largeText ? "1" : "0");
  }, [largeText]);

  useEffect(() => {
    document.documentElement.classList.toggle("taalmel-high-contrast", highContrast);
    localStorage.setItem("taalmel.highContrast", highContrast ? "1" : "0");
  }, [highContrast]);

  function setLanguage(code: string) {
    localStorage.setItem("taalmel.lang", code);
    setLanguageState(code);
  }

  function t(key: string, fallback: string): string {
    return strings[key] || fallback;
  }

  return (
    <A11yContext.Provider
      value={{
        language,
        languages,
        strings,
        setLanguage,
        t,
        largeText,
        setLargeText: setLargeTextState,
        highContrast,
        setHighContrast: setHighContrastState,
      }}
    >
      {children}
    </A11yContext.Provider>
  );
}

export function useA11y() {
  const ctx = useContext(A11yContext);
  if (!ctx) throw new Error("useA11y must be used inside A11yProvider");
  return ctx;
}
