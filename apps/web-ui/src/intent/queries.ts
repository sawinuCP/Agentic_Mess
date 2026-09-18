// Search-query extraction (Wave 10): quoted strings plus code-like tokens
// for symbol/text lookup. Stopwords and length floors keep grep queries
// honest; bounded to a few terms per request.

const STOP = new Set([
  "the", "this", "that", "with", "from", "where", "what", "does",
  "and", "for", "are", "implement", "explain", "find", "review",
]);

/** Identifiers worth searching: quoted strings + code-like tokens. */
export function extractIdentifiers(text: string): string[] {
  const out: string[] = [];
  for (const match of text.matchAll(/"([^"]{2,80})"|'([^']{2,80})'|`([^`]{2,80})`/g)) {
    const hit = match[1] ?? match[2] ?? match[3];
    if (hit && !out.includes(hit)) out.push(hit);
  }
  for (const match of text.matchAll(/[A-Za-z_][\w.]*(?:\.[A-Za-z_]\w*)+|[A-Za-z_]{4,}\w*/g)) {
    const hit = match[0].replace(/\.+$/, "");
    if (hit.length >= 3 && !STOP.has(hit.toLowerCase()) && !out.includes(hit) && out.length < 6) {
      out.push(hit);
    }
  }
  return out.slice(0, 3);
}
