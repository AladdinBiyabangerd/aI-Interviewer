export type JavaTokenKind =
  | "annotation"
  | "comment"
  | "function"
  | "keyword"
  | "literal"
  | "number"
  | "plain"
  | "string"
  | "type";

export type JavaToken = {
  kind: JavaTokenKind;
  text: string;
};

const javaTokenPatterns: Array<{ kind: Exclude<JavaTokenKind, "plain">; pattern: RegExp }> = [
  { kind: "comment", pattern: /\/\/[^\n]*|\/\*[\s\S]*?\*\//y },
  { kind: "string", pattern: /"(?:\\[\s\S]|[^"\\])*"|'(?:\\[\s\S]|[^'\\])*'/y },
  { kind: "annotation", pattern: /@[A-Za-z_$][\w$]*/y },
  { kind: "number", pattern: /\b(?:0[xX][\dA-Fa-f](?:_?[\dA-Fa-f])*|0[bB][01](?:_?[01])*|\d(?:_?\d)*(?:\.\d(?:_?\d)*)?(?:[eE][+-]?\d(?:_?\d)*)?[fFdDlL]?)\b/y },
  { kind: "keyword", pattern: /\b(?:abstract|assert|boolean|break|byte|case|catch|char|class|const|continue|default|do|double|else|enum|exports|extends|final|finally|float|for|goto|if|implements|import|instanceof|int|interface|long|module|native|new|non-sealed|open|opens|package|permits|private|protected|provides|public|record|requires|return|sealed|short|static|strictfp|super|switch|synchronized|this|throw|throws|to|transient|transitive|try|uses|var|void|volatile|when|while|with|yield)\b/y },
  { kind: "literal", pattern: /\b(?:false|null|true)\b/y },
  { kind: "type", pattern: /\b[A-Z][A-Za-z0-9_$]*\b/y },
  { kind: "function", pattern: /\b[A-Za-z_$][\w$]*(?=\s*\()/y },
];

export function highlightJava(source: string): JavaToken[] {
  const tokens: JavaToken[] = [];
  let offset = 0;
  let plainStart = 0;

  while (offset < source.length) {
    let token: JavaToken | null = null;
    for (const candidate of javaTokenPatterns) {
      candidate.pattern.lastIndex = offset;
      const match = candidate.pattern.exec(source);
      if (match) {
        token = { kind: candidate.kind, text: match[0] };
        break;
      }
    }
    if (!token) {
      offset += 1;
      continue;
    }
    if (offset > plainStart) tokens.push({ kind: "plain", text: source.slice(plainStart, offset) });
    tokens.push(token);
    offset += token.text.length;
    plainStart = offset;
  }

  if (plainStart < source.length) tokens.push({ kind: "plain", text: source.slice(plainStart) });
  return tokens;
}
