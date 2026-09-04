import { test } from 'vitest';
import { normalizeMedication } from '../src/services/normalizationService';

test('Audit Scenarios', () => {
  const scenarios = [
    {
      nameRaw: 'Tab Glucophage 500mg',
      dosage: null,
      frequency: 'bd',
      instructions: 'After meals',
    },
    {
      nameRaw: 'Metformin 1000mg',
      dosage: '1000mg',
      frequency: 'od',
      instructions: null,
    },
    {
      nameRaw: 'UnknownMeds 50mg',
      dosage: null,
      frequency: null,
      instructions: null,
    },
    {
      nameRaw: 'Dolo 650',
      dosage: null,
      frequency: 'sos',
      instructions: 'When fever > 100',
    },
    {
      nameRaw: 'Thyronorm',
      dosage: '50mcg',
      frequency: 'od',
      instructions: 'Empty stomach',
    }
  ];

  console.log('\n\n--- AUDIT RESULTS START ---\n');
  for (const s of scenarios) {
    const norm = normalizeMedication(s);
    console.log(`INPUT: ${JSON.stringify(s, null, 2)}`);
    console.log(`NORMALIZATION: ${JSON.stringify(norm, null, 2)}`);
    console.log('--------------------------------------------------');
  }
  console.log('\n--- AUDIT RESULTS END ---\n\n');
});
