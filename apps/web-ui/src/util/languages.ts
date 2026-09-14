// File-extension → Monaco language id. Project detection supplies the primary
// mapping server-side; this covers editor rendering for common extensions.

const EXTENSION_TO_MONACO: Record<string, string> = {
  py: "python",
  pyw: "python",
  js: "javascript",
  jsx: "javascript",
  mjs: "javascript",
  cjs: "javascript",
  ts: "typescript",
  tsx: "typescript",
  go: "go",
  rs: "rust",
  cs: "csharp",
  java: "java",
  kt: "kotlin",
  swift: "swift",
  php: "php",
  rb: "ruby",
  dart: "dart",
  c: "c",
  h: "c",
  cpp: "cpp",
  cc: "cpp",
  cxx: "cpp",
  hpp: "cpp",
  json: "json",
  md: "markdown",
  css: "css",
  scss: "scss",
  less: "less",
  html: "html",
  htm: "html",
  xml: "xml",
  svg: "xml",
  yml: "yaml",
  yaml: "yaml",
  toml: "ini",
  ini: "ini",
  cfg: "ini",
  sql: "sql",
  sh: "shell",
  bat: "bat",
  ps1: "powershell",
};

export function monacoLanguageFor(path: string): string {
  const ext = path.includes(".") ? path.split(".").pop()!.toLowerCase() : "";
  return EXTENSION_TO_MONACO[ext] ?? "plaintext";
}
