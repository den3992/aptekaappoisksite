// Existing truncated catalog slugs can end in '-' or contain '--2'. Their
// alphabet is still one strictly bounded URL segment without escapes or dots.
export const medicationSlugPattern = /^[a-z0-9][a-z0-9-]*$/;
export const instructionDocumentIdPattern = /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/;

export function isMedicationSlug(value) {
  return typeof value === 'string' && value.length <= 240 && medicationSlugPattern.test(value);
}

export function instructionOriginalPath(value) {
  if (typeof value !== 'string') return null;
  const match = value.match(/^\/api\/instructions\/originals\/([A-Za-z0-9][A-Za-z0-9_-]{0,127})\.pdf$/);
  return match ? `/instrukcii/originaly/${match[1]}` : null;
}
