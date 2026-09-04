export const CONFIDENCE_THRESHOLD = 0.75;

export interface MedicationCandidate {
  medicationName: string;
  dosage: string | null;
  frequency: string | null;
  instructions: string | null;
  confidence: number;
}

export interface OcrRawResult {
  rawText: string;
  candidates: MedicationCandidate[];
}

export interface IOcrProvider {
  extractText(buffer: Buffer, mimeType: string): Promise<OcrRawResult>;
}

export class StubOcrProvider implements IOcrProvider {
  async extractText(buffer: Buffer, mimeType: string): Promise<OcrRawResult> {
    // Return mock results. In a real app this would call Textract/Vision API.
    return {
      rawText: "Rx\nPatient: John Doe\nLisinopril 10mg\nTake 1 tablet daily",
      candidates: [
        {
          medicationName: "Lisinopril",
          dosage: "10mg",
          frequency: "daily",
          instructions: "Take 1 tablet",
          confidence: 0.85
        }
      ]
    };
  }
}

export function getOcrProvider(): IOcrProvider {
  return new StubOcrProvider();
}

export function processOcrResult(result: OcrRawResult) {
  const items = result.candidates.map((c) => ({
    medicationName: c.medicationName,
    dosage: c.dosage,
    frequency: c.frequency,
    instructions: c.instructions,
    confidence: c.confidence,
    ocrRawValue: JSON.stringify(c), // Store what OCR originally saw
    verified: false // ALL OCR data must start as unverified
  }));

  const requiresManualReview = items.some(i => i.confidence < CONFIDENCE_THRESHOLD);
  const status = items.length === 0 ? 'FAILED' : (requiresManualReview ? 'NEEDS_REVIEW' : 'COMPLETED');

  return { items, status };
}
