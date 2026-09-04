import fs from 'fs';
import path from 'path';
import { normalizeToGeneric } from './normalizationService';

const DATASET_PATH = path.join(__dirname, '..', 'data', 'safety-interactions.json');

export interface SafetyDataset {
  knownMedications: string[];
  interactions: Array<{ a: string; b: string; note: string; source: string }>;
  duplicateIngredientGroups: string[][];
}

export function loadDataset(): SafetyDataset {
  const raw = fs.readFileSync(DATASET_PATH, 'utf8');
  return JSON.parse(raw) as SafetyDataset;
}

/**
 * Check for drug interactions and duplicate ingredients.
 * Accepts either raw names or generic names — raw names are normalized first.
 * Only checks against the curated safety dataset; returns NOT_COVERED for unknown medications.
 */
export function checkInteractions(medicationNames: string[]) {
  const dataset = loadDataset();
  const known = new Set(dataset.knownMedications.map((m) => m.toLowerCase()));

  // Normalize all input names to generics before checking
  const genericNames = medicationNames.map((name) => {
    const normalized = normalizeToGeneric(name);
    return normalized || name;
  });

  const uncovered = genericNames.filter((n) => !known.has(n.toLowerCase()));

  const pairs: { a: string; b: string; result: string; detail?: string; source?: string }[] = [];
  for (let i = 0; i < genericNames.length; i++) {
    for (let j = i + 1; j < genericNames.length; j++) {
      const a = genericNames[i].toLowerCase();
      const b = genericNames[j].toLowerCase();

      const bothCovered = known.has(a) && known.has(b);
      if (!bothCovered) {
        pairs.push({ a: genericNames[i], b: genericNames[j], result: 'NOT_COVERED' });
        continue;
      }

      const match = dataset.interactions.find(
        (rule) =>
          (rule.a.toLowerCase() === a && rule.b.toLowerCase() === b) ||
          (rule.a.toLowerCase() === b && rule.b.toLowerCase() === a)
      );

      const duplicateIngredient = dataset.duplicateIngredientGroups.some(
        (group) => group.map((x) => x.toLowerCase()).includes(a) && group.map((x) => x.toLowerCase()).includes(b)
      );

      if (match) {
        pairs.push({ a: genericNames[i], b: genericNames[j], result: 'INTERACTION_FLAGGED', detail: match.note, source: match.source });
      } else if (duplicateIngredient) {
        pairs.push({ a: genericNames[i], b: genericNames[j], result: 'DUPLICATE_INGREDIENT_FLAGGED' });
      } else {
        pairs.push({ a: genericNames[i], b: genericNames[j], result: 'NO_KNOWN_ISSUE_IN_DATASET' });
      }
    }
  }

  return {
    normalizedNames: genericNames,
    pairs,
    uncovered,
    disclaimer:
      'This checks against a small, curated, referenced demonstration dataset only. ' +
      'It does not provide comprehensive clinical coverage. Medicines outside the dataset ' +
      'return NOT_COVERED and must never be read as "confirmed safe."',
  };
}
