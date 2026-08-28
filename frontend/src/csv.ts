/**
 * Minimal, dependency-free CSV encoding for client-side export buttons.
 *
 * RFC 4180 quoting: any field containing a comma, a double quote, or a
 * newline is wrapped in double quotes, with internal double quotes
 * doubled. `source_snippet` on a fundamentals row routinely contains
 * both commas and embedded newlines (see the "EXTRACTION FAILED
 * ARITHMETIC CHECK" warnings), so this is a real requirement here, not
 * defensive-only.
 */
function csvField(value: unknown): string {
  if (value === null || value === undefined) return "";
  const s = String(value);
  if (/[",\n\r]/.test(s)) {
    return `"${s.replace(/"/g, '""')}"`;
  }
  return s;
}

export function toCsv<T>(rows: T[], columns: { key: keyof T; header: string }[]): string {
  const lines = [columns.map((c) => csvField(c.header)).join(",")];
  for (const row of rows) {
    lines.push(columns.map((c) => csvField(row[c.key])).join(","));
  }
  // CRLF is the RFC 4180 line ending and what every spreadsheet app
  // expects; plain \n also works but this is the more compatible choice.
  return lines.join("\r\n");
}

/** Triggers a real browser file save via a temporary anchor — the
 * running app in the user's own browser, not a sandboxed preview, so
 * this is a normal client-side download, not the disabled-download
 * pattern that applies to published Artifacts. */
export function downloadCsv(filename: string, csv: string): void {
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
  downloadBlob(filename, blob);
}

/** Same real client-side save, for a binary response (R1 T3.1/T3.2's
 * .xlsx workbook and .zip backup) rather than text this module encodes
 * itself. */
export function downloadBlob(filename: string, blob: Blob): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
