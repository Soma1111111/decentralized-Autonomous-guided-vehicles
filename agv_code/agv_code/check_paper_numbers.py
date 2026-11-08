"""
check_paper_numbers.py - fail if the paper hard-codes result numbers
====================================================================
Scans paper/main.tex and paper/sections/*.tex (the reproducibility appendix is
exempt: it documents commands and code line ranges, not results). Comments,
math, algorithmic pseudocode, \\texttt arguments, \\cite/\\ref/\\label/\\input
arguments and \\includegraphics options are stripped first; whatever numerals
remain are compared against paper/generated/whitelist.txt (experiment
parameters and layout constants). Any other numeral is a result that must come
from paper/generated/numbers.tex or a generated table body.

    python check_paper_numbers.py     # exit 0 = clean, 1 = findings

Also checks that every capitalized macro used in the scanned files is defined
by numbers.tex, so a typo cannot silently print a stale or missing value.
"""
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PAPER = os.path.normpath(os.path.join(HERE, "..", "..", "paper"))
WHITELIST = os.path.join(PAPER, "generated", "whitelist.txt")
NUMBERS = os.path.join(PAPER, "generated", "numbers.tex")
EXEMPT = {"reproducibility.tex"}   # command/path appendix, no result numbers

NUM_RE = re.compile(r"(?<![\w.])(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+\.\d+|\d+)(?![\w])")
ENV_RE = re.compile(r"\\begin\{(algorithmic?|equation\*?|align\*?|displaymath)\}"
                    r".*?\\end\{\1\}|\\\[.*?\\\]", re.S)


def strip_inline(text):
    """Remove constructs that may legitimately contain digits (single line)."""
    text = re.sub(r"(?<!\\)%[^\n]*", "", text)                       # comments
    text = re.sub(r"\\includegraphics(?:\[[^\]]*\])?\{[^{}]*\}", "", text)
    text = re.sub(r"\\texttt\{[^{}]*\}", "", text)
    text = re.sub(r"\\(?:cite|ref|eqref|label|input|include|bibliography"
                  r"|bibliographystyle|documentclass|usepackage|graphicspath)"
                  r"(?:\[[^\]]*\])?\{[^{}]*\}", "", text)
    text = re.sub(r"\$[^$]*\$", "", text)                            # inline math
    text = re.sub(r"\\\[.*?\\\]", "", text, flags=re.S)              # display math
    return text


def env_line_spans(text):
    """Line numbers occupied by multi-line pseudocode/equation environments."""
    lines = text.splitlines()
    starts = [0]
    for ln in lines:
        starts.append(starts[-1] + len(ln) + 1)
    spans = set()
    for m in ENV_RE.finditer(text):
        a = sum(1 for s in starts[1:] if s <= m.start())
        b = sum(1 for s in starts[1:] if s <= m.end())
        spans.update(range(a + 1, b + 1))
    return spans


def main():
    with open(WHITELIST, encoding="utf-8") as fh:
        allowed = {ln.strip() for ln in fh
                   if ln.strip() and not ln.strip().startswith("#")}
    with open(NUMBERS, encoding="utf-8") as fh:
        defined = set(re.findall(r"\\newcommand\{\\(\w+)\}", fh.read()))

    files = [os.path.join(PAPER, "full", "main.tex")] + sorted(
        p for p in glob.glob(os.path.join(PAPER, "full", "sections", "*.tex"))
        if os.path.basename(p) not in EXEMPT)
    short_paper = os.path.join(PAPER, "short")
    if os.path.isdir(short_paper):
        files.append(os.path.join(short_paper, "main.tex"))
        files += sorted(p for p in glob.glob(os.path.join(short_paper, "sections", "*.tex"))
                        if os.path.basename(p) not in EXEMPT)
    findings, used_macros = [], set()

    for path in files:
        with open(path, encoding="utf-8") as fh:
            raw = fh.read()
        raw = re.sub(r"\\begin\{thebibliography\}.*?\\end\{thebibliography\}", "", raw, flags=re.S)
        spans = env_line_spans(raw)
        outside = "\n".join("" if n in spans else ln
                            for n, ln in enumerate(raw.splitlines(), start=1))
        used_macros.update(re.findall(r"\\([A-Z][A-Za-z]+)", strip_inline(outside)))
        for lineno, line in enumerate(raw.splitlines(), start=1):
            if lineno in spans:
                continue
            for m in NUM_RE.finditer(strip_inline(line)):
                tok = m.group(1)
                if tok not in allowed:
                    findings.append(f"{os.path.relpath(path, PAPER)}:{lineno}: "
                                    f"hard-coded numeral {tok!r} in: {line.strip()[:90]}")

    # capitalized macros must be generated (guards against typos printing junk)
    known = {"IEEEauthorblockN", "IEEEauthorblockA", "IEEEkeywords"}
    for name in sorted(used_macros - defined - known):
        findings.append(f"macro \\{name} is used in the paper but not defined "
                        f"in generated/numbers.tex")

    if findings:
        print(f"check_paper_numbers: {len(findings)} problem(s)\n")
        print("\n".join(findings))
        return 1
    print(f"check_paper_numbers: OK - no hard-coded result numerals in "
          f"{len(files)} files; all capitalized macros defined "
          f"({len(defined)} generated macros, {len(allowed)} whitelisted parameters)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
