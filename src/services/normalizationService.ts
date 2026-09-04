import fs from 'fs';
import path from 'path';
import { prisma } from '../db/client';

// ── Types ────────────────────────────────────────────────────────────────────

export interface MedicationDictionaryEntry {
  genericName: string;
  brandNames: string[];
  strengths: string[];
  dosageForms: string[];
  activeIngredient: string;
  category: string;
}

export interface MedicationDictionary {
  _disclaimer: string;
  medications: MedicationDictionaryEntry[];
  dosageFormAliases: Record<string, string>;
  strengthUnits: string[];
  strengthPattern: string;
  frequencyAliases: Record<string, string>;
}

export interface ParsedMedication {
  name: string;
  strength: string | null;
  strengthUnit: string | null;
  dosageForm: string | null;
  remainder: string | null;
}

export interface NormalizationInput {
  nameRaw: string;
  dosage?: string | null;
  frequency?: string | null;
  instructions?: string | null;
  duration?: string | null;
}

export type NormalizationMethod =
  | 'EXACT_GENERIC_MATCH'
  | 'BRAND_LOOKUP'
  | 'FUZZY_MATCH'
  | 'MANUAL'
  | 'UNRESOLVED';

export type NormalizationStatus =
  | 'NORMALIZED'
  | 'NEEDS_REVIEW'
  | 'AMBIGUOUS'
  | 'MANUALLY_VERIFIED'
  | 'PENDING';

export interface NormalizationResult {
  nameGeneric: string | null;
  nameBrand: string | null;
  strength: string | null;
  strengthRaw: string | null;
  strengthUnit: string | null;
  dosageForm: string | null;
  dosageFormRaw: string | null;
  frequency: string | null;
  frequencyRaw: string | null;
  activeIngredient: string | null;
  category: string | null;
  method: NormalizationMethod;
  confidence: number;
  status: NormalizationStatus;
  matchedEntry: MedicationDictionaryEntry | null;
}

// ── Dictionary Loading ───────────────────────────────────────────────────────

const DICT_PATH = path.join(__dirname, '..', 'data', 'medicationDictionary.json');

let _cachedDictionary: MedicationDictionary | null = null;
let _brandIndex: Map<string, MedicationDictionaryEntry> | null = null;
let _genericIndex: Map<string, MedicationDictionaryEntry> | null = null;

export function loadDictionary(): MedicationDictionary {
  if (_cachedDictionary) return _cachedDictionary;
  const raw = fs.readFileSync(DICT_PATH, 'utf8');
  _cachedDictionary = JSON.parse(raw) as MedicationDictionary;
  return _cachedDictionary;
}

/** Build a case-insensitive brand→entry index */
function getBrandIndex(): Map<string, MedicationDictionaryEntry> {
  if (_brandIndex) return _brandIndex;
  const dict = loadDictionary();
  _brandIndex = new Map();
  for (const entry of dict.medications) {
    for (const brand of entry.brandNames) {
      _brandIndex.set(brand.toLowerCase(), entry);
    }
  }
  return _brandIndex;
}

/** Build a case-insensitive generic→entry index */
function getGenericIndex(): Map<string, MedicationDictionaryEntry> {
  if (_genericIndex) return _genericIndex;
  const dict = loadDictionary();
  _genericIndex = new Map();
  for (const entry of dict.medications) {
    _genericIndex.set(entry.genericName.toLowerCase(), entry);
  }
  return _genericIndex;
}

/** Reset caches — useful for testing */
export function resetDictionaryCache(): void {
  _cachedDictionary = null;
  _brandIndex = null;
  _genericIndex = null;
}

// ── Parsing ──────────────────────────────────────────────────────────────────

/**
 * Parse a raw medication string into structured components.
 * Handles formats like:
 *   "Metformin 500mg"
 *   "Tab Glucophage XR 1000 mg"
 *   "Ecosprin 75mg tablet"
 *   "Dolo 650"
 */
export function parseRawMedication(raw: string): ParsedMedication {
  if (!raw || !raw.trim()) {
    return { name: '', strength: null, strengthUnit: null, dosageForm: null, remainder: null };
  }

  let input = raw.trim();
  const dict = loadDictionary();

  // 1. Extract dosage form if it appears as a prefix (e.g., "Tab Ecosprin 75mg")
  let dosageForm: string | null = null;
  let dosageFormRaw: string | null = null;

  const aliasKeys = Object.keys(dict.dosageFormAliases).sort((a, b) => b.length - a.length);
  const prefixFormPattern = new RegExp(`^(${aliasKeys.join('|')})\\.?\\s+`, 'i');
  const prefixMatch = input.match(prefixFormPattern);
  if (prefixMatch) {
    dosageFormRaw = prefixMatch[1];
    dosageForm = dict.dosageFormAliases[prefixMatch[1].toLowerCase()] || null;
    input = input.slice(prefixMatch[0].length).trim();
  }

  // 2. Extract strength (e.g., "500mg", "1000 mg", "650", "100iu/ml")
  let strength: string | null = null;
  let strengthUnit: string | null = null;

  const strengthRegex = new RegExp(dict.strengthPattern, 'i');
  const strengthMatch = input.match(strengthRegex);

  if (strengthMatch) {
    const numVal = strengthMatch[1];
    const unit = strengthMatch[2].toLowerCase();
    strength = `${numVal}${unit}`;
    strengthUnit = unit;
    // If there's a compound form like "100mg/5ml" (groups 3+4)
    if (strengthMatch[3] && strengthMatch[4]) {
      strength = `${numVal}${unit}/${strengthMatch[3]}${strengthMatch[4].toLowerCase()}`;
    }
    // Alternate compound form like "100iu/ml" (group 5 = "/ml")
    else if (strengthMatch[5]) {
      strength = `${numVal}${unit}${strengthMatch[5].toLowerCase()}`;
    }
    input = input.replace(strengthMatch[0], ' ').trim();
  } else {
    // Try bare number at end (e.g., "Dolo 650" — assume mg)
    const bareNumberMatch = input.match(/\s+(\d+(?:\.\d+)?)\s*$/);
    if (bareNumberMatch) {
      strength = `${bareNumberMatch[1]}mg`;
      strengthUnit = 'mg';
      input = input.slice(0, -bareNumberMatch[0].length).trim();
    }
  }

  // 3. Extract trailing dosage form (e.g., "... tablet", "... capsule")
  if (!dosageForm) {
    const suffixFormPattern = new RegExp(`\\s+(${aliasKeys.join('|')})\\.?\\s*$`, 'i');
    const suffixMatch = input.match(suffixFormPattern);
    if (suffixMatch) {
      dosageFormRaw = suffixMatch[1];
      dosageForm = dict.dosageFormAliases[suffixMatch[1].toLowerCase()] || null;
      input = input.slice(0, -suffixMatch[0].length).trim();
    }
  }

  // 4. What remains is the medication name
  const name = input.replace(/\s+/g, ' ').trim();

  return {
    name,
    strength,
    strengthUnit,
    dosageForm,
    remainder: dosageFormRaw,
  };
}

// ── Name Resolution ──────────────────────────────────────────────────────────

interface NameResolution {
  genericName: string | null;
  brandName: string | null;
  method: NormalizationMethod;
  confidence: number;
  matchedEntry: MedicationDictionaryEntry | null;
}

/**
 * Multi-strategy name resolution:
 *  1. Exact generic match
 *  2. Brand-to-generic lookup
 *  3. Simple fuzzy matching (prefix/substring)
 *  4. Unresolved
 */
export function normalizeMedicationName(name: string): NameResolution {
  if (!name || !name.trim()) {
    return { genericName: null, brandName: null, method: 'UNRESOLVED', confidence: 0, matchedEntry: null };
  }

  const cleanName = name.trim().toLowerCase();
  const genericIndex = getGenericIndex();
  const brandIndex = getBrandIndex();

  // Strategy 1: Exact generic match
  const genericMatch = genericIndex.get(cleanName);
  if (genericMatch) {
    return {
      genericName: genericMatch.genericName,
      brandName: null,
      method: 'EXACT_GENERIC_MATCH',
      confidence: 1.0,
      matchedEntry: genericMatch,
    };
  }

  // Strategy 2: Exact brand match
  const brandMatch = brandIndex.get(cleanName);
  if (brandMatch) {
    return {
      genericName: brandMatch.genericName,
      brandName: name.trim(),
      method: 'BRAND_LOOKUP',
      confidence: 0.95,
      matchedEntry: brandMatch,
    };
  }

  // Strategy 3: Fuzzy matching — prefix match on generics and brands
  // First word of multi-word input matches a generic
  const firstWord = cleanName.split(/\s+/)[0];
  const genericPrefixMatch = genericIndex.get(firstWord);
  if (genericPrefixMatch) {
    return {
      genericName: genericPrefixMatch.genericName,
      brandName: null,
      method: 'EXACT_GENERIC_MATCH',
      confidence: 0.9,
      matchedEntry: genericPrefixMatch,
    };
  }

  const brandPrefixMatch = brandIndex.get(firstWord);
  if (brandPrefixMatch) {
    return {
      genericName: brandPrefixMatch.genericName,
      brandName: firstWord,
      method: 'BRAND_LOOKUP',
      confidence: 0.85,
      matchedEntry: brandPrefixMatch,
    };
  }

  // Strategy 3b: Substring/prefix fuzzy — does any generic name start with the input?
  const fuzzyMatches: { entry: MedicationDictionaryEntry; type: 'generic' | 'brand'; similarity: number }[] = [];

  for (const [gName, entry] of genericIndex) {
    if (gName.startsWith(cleanName) && cleanName.length >= 4) {
      fuzzyMatches.push({ entry, type: 'generic', similarity: cleanName.length / gName.length });
    }
  }
  for (const [bName, entry] of brandIndex) {
    if (bName.startsWith(cleanName) && cleanName.length >= 4) {
      fuzzyMatches.push({ entry, type: 'brand', similarity: cleanName.length / bName.length });
    }
  }

  if (fuzzyMatches.length === 1) {
    const m = fuzzyMatches[0];
    const conf = Math.min(0.75, 0.5 + m.similarity * 0.3);
    return {
      genericName: m.entry.genericName,
      brandName: m.type === 'brand' ? name.trim() : null,
      method: 'FUZZY_MATCH',
      confidence: conf,
      matchedEntry: m.entry,
    };
  }

  if (fuzzyMatches.length > 1) {
    // Ambiguous — multiple possible matches
    // Pick the best one but mark as ambiguous
    fuzzyMatches.sort((a, b) => b.similarity - a.similarity);
    const best = fuzzyMatches[0];
    return {
      genericName: best.entry.genericName,
      brandName: best.type === 'brand' ? name.trim() : null,
      method: 'FUZZY_MATCH',
      confidence: 0.4,
      matchedEntry: best.entry,
    };
  }

  // Strategy 4: Unresolved — return the input as-is, no invented generic name
  return {
    genericName: null,
    brandName: null,
    method: 'UNRESOLVED',
    confidence: 0,
    matchedEntry: null,
  };
}

// ── Strength Normalization ───────────────────────────────────────────────────

/**
 * Standardize strength values:
 *  "500 mg" → "500mg"
 *  "0.5g"   → "0.5g" (preserved, not converted)
 *  null     → null
 */
export function normalizeStrength(raw: string | null | undefined): string | null {
  if (!raw || !raw.trim()) return null;

  const dict = loadDictionary();
  const regex = new RegExp(dict.strengthPattern, 'i');
  const match = raw.trim().match(regex);
  if (!match) return raw.trim(); // Return as-is if can't parse

  const numVal = match[1];
  const unit = match[2].toLowerCase();

  if (match[3] && match[4]) {
    return `${numVal}${unit}/${match[3]}${match[4].toLowerCase()}`;
  }
  if (match[5]) {
    return `${numVal}${unit}${match[5].toLowerCase()}`;
  }

  return `${numVal}${unit}`;
}

// ── Dosage Form Normalization ────────────────────────────────────────────────

/**
 * Resolve dosage form aliases:
 *  "tab" → "tablet"
 *  "cap" → "capsule"
 *  "SR"  → "sustained-release tablet"
 */
export function normalizeDosageForm(raw: string | null | undefined): string | null {
  if (!raw || !raw.trim()) return null;
  const dict = loadDictionary();
  const key = raw.trim().toLowerCase();
  return dict.dosageFormAliases[key] || raw.trim();
}

// ── Frequency Normalization ──────────────────────────────────────────────────

export function normalizeFrequency(raw: string | null | undefined): string | null {
  if (!raw || !raw.trim()) return null;
  const dict = loadDictionary();
  const key = raw.trim().toLowerCase();
  return dict.frequencyAliases[key] || raw.trim();
}

// ── Full Pipeline ────────────────────────────────────────────────────────────

const CONFIDENCE_THRESHOLD_NORMALIZED = 0.7;
const CONFIDENCE_THRESHOLD_AMBIGUOUS = 0.5;

/**
 * Full normalization pipeline:
 *  1. Parse raw input into components
 *  2. Resolve medication name (generic/brand)
 *  3. Normalize strength
 *  4. Normalize dosage form
 *  5. Score confidence
 *  6. Determine status
 */
export function normalizeMedication(input: NormalizationInput): NormalizationResult {
  if (!input.nameRaw || !input.nameRaw.trim()) {
    return {
      nameGeneric: null,
      nameBrand: null,
      strength: null,
      strengthRaw: null,
      strengthUnit: null,
      dosageForm: null,
      dosageFormRaw: null,
      frequency: null,
      frequencyRaw: input.frequency || null,
      activeIngredient: null,
      category: null,
      method: 'UNRESOLVED',
      confidence: 0,
      status: 'NEEDS_REVIEW',
      matchedEntry: null,
    };
  }

  // Step 1: Parse the raw name
  const parsed = parseRawMedication(input.nameRaw);

  // Step 2: Resolve name
  const nameResult = normalizeMedicationName(parsed.name);

  // Step 3: Normalize strength — from parsed value or dosage field
  const strengthRaw = parsed.strength || input.dosage || null;
  const strength = normalizeStrength(strengthRaw);

  // Step 4: Normalize dosage form
  const dosageFormRaw = parsed.dosageForm || null;
  const dosageForm = parsed.dosageForm || null; // Already normalized during parsing

  // Step 5: Normalize frequency
  const frequencyRaw = input.frequency || null;
  const frequency = normalizeFrequency(frequencyRaw);

  // Step 6: Compute overall confidence
  let confidence = nameResult.confidence;

  // Boost confidence if strength matches known strengths
  if (nameResult.matchedEntry && strength) {
    const knownStrengths = nameResult.matchedEntry.strengths.map(s => s.toLowerCase());
    if (knownStrengths.includes(strength.toLowerCase())) {
      confidence = Math.min(1.0, confidence + 0.05);
    }
  }

  // Step 7: Determine status
  let status: NormalizationStatus;
  if (nameResult.method === 'UNRESOLVED') {
    status = 'NEEDS_REVIEW';
  } else if (confidence >= CONFIDENCE_THRESHOLD_NORMALIZED) {
    status = 'NORMALIZED';
  } else if (confidence >= CONFIDENCE_THRESHOLD_AMBIGUOUS) {
    status = 'AMBIGUOUS';
  } else {
    status = 'NEEDS_REVIEW';
  }

  return {
    nameGeneric: nameResult.genericName,
    nameBrand: nameResult.brandName,
    strength,
    strengthRaw,
    strengthUnit: parsed.strengthUnit,
    dosageForm,
    dosageFormRaw: dosageFormRaw !== dosageForm ? (parsed.remainder || null) : null,
    frequency,
    frequencyRaw,
    activeIngredient: nameResult.matchedEntry?.activeIngredient || null,
    category: nameResult.matchedEntry?.category || null,
    method: nameResult.method,
    confidence,
    status,
    matchedEntry: nameResult.matchedEntry,
  };
}

// ── Canonical Record Management ──────────────────────────────────────────────

/**
 * Find or create a MedicationCanonical record.
 * Uses the unique constraint [genericName, strength, dosageForm].
 */
export async function findOrCreateCanonical(
  genericName: string,
  strength: string | null,
  dosageForm: string | null,
  matchedEntry: MedicationDictionaryEntry | null,
) {
  // Try to find existing (SQLite doesn't support mode: 'insensitive', so we query broadly and filter)
  const candidates = await prisma.medicationCanonical.findMany({
    where: {
      strength: strength || undefined,
      dosageForm: dosageForm || undefined,
    },
  });
  const existing = candidates.find(
    (c) => c.genericName.toLowerCase() === genericName.toLowerCase()
  );

  if (existing) return existing;

  // Create new
  return prisma.medicationCanonical.create({
    data: {
      genericName,
      brandNames: matchedEntry ? JSON.stringify(matchedEntry.brandNames) : '[]',
      strength,
      dosageForm,
      activeIngredient: matchedEntry?.activeIngredient || null,
      category: matchedEntry?.category || null,
    },
  });
}

// ── Normalization Log ────────────────────────────────────────────────────────

export async function logNormalization(
  medicationId: string,
  inputRaw: string,
  result: NormalizationResult,
  reviewNote?: string | null,
) {
  return prisma.normalizationLog.create({
    data: {
      medicationId,
      inputRaw,
      outputGeneric: result.nameGeneric,
      outputStrength: result.strength,
      outputForm: result.dosageForm,
      method: result.method,
      confidence: result.confidence,
      status: result.status,
      reviewNote: reviewNote || null,
    },
  });
}

// ── Backward Compatibility ───────────────────────────────────────────────────

/**
 * Legacy brand-to-generic map — preserved for backward compatibility.
 * Internally delegates to the new dictionary.
 */
export const BRAND_TO_GENERIC: Record<string, string> = (() => {
  try {
    const dict = loadDictionary();
    const map: Record<string, string> = {};
    for (const entry of dict.medications) {
      for (const brand of entry.brandNames) {
        map[brand.toLowerCase()] = entry.genericName;
      }
    }
    return map;
  } catch {
    // Fallback if dictionary fails to load
    return {
      glucophage: 'Metformin',
      amaryl: 'Glimepiride',
      norvasc: 'Amlodipine',
      cozaar: 'Losartan',
      lipitor: 'Atorvastatin',
      ecosprin: 'Aspirin',
      crocin: 'Paracetamol',
      dolo: 'Paracetamol',
      brufen: 'Ibuprofen',
      omez: 'Omeprazole',
    };
  }
})();

/**
 * Legacy normalizeToGeneric — backward-compatible.
 * Now uses the full pipeline internally.
 */
export function normalizeToGeneric(nameRaw: string | null | undefined): string | null {
  if (!nameRaw) return null;
  const result = normalizeMedicationName(nameRaw.trim());
  return result.genericName || nameRaw.trim();
}
