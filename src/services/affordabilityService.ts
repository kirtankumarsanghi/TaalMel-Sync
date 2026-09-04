import fs from 'fs';
import path from 'path';

const RESOURCES_PATH = path.join(__dirname, '..', '..', 'data', 'affordability-resources.json');

export function getAffordabilityResponse() {
  const raw = fs.readFileSync(RESOURCES_PATH, 'utf8');
  const { resources } = JSON.parse(raw);
  return {
    resources,
    followUpPrompt:
      'Please also discuss alternatives with your doctor or pharmacist \u2014 this list is a starting ' +
      'point, not a substitute for their guidance.',
  };
}

export {};
