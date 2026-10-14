#!/usr/bin/env python3
"""Measure whether two sibling cover letters actually say different things.

Two applications at one company, landing together, read as spray unless each letter is
visibly written for its own role. This measures that instead of asserting it.

    check-distinct.py letter_a.html letter_b.html [n]
    check-distinct.py --help

WHY PARAGRAPHS ONLY. It compares the text inside <p> tags and nothing else. The letterhead,
contact block and date are identical across every document by design, so comparing whole
document bodies reports dozens of "shared phrases" that are pure boilerplate -- that exact
mistake has produced a false double-digit "collision" reading between two otherwise-distinct
letters before; the paragraph-only count was zero and the paragraph-only count was the true
one.

WHY THE CONTROL. The script also compares each file against ITSELF (a positive control) and
refuses to report a clean result unless that self-comparison is large. A tokenizer that
matches nothing returns "0 shared" for two identical files just as happily as for two
different ones, so a zero without a positive control is not evidence of distinctness -- it is
equally consistent with a broken measure.

Exit 0 = distinct. Exit 1 = shared phrases found. Exit 2 = the measure itself is broken, or
a usage error.

No config file is needed -- this tool takes its inputs as plain CLI arguments.
"""
import sys, re, html


def paragraph_words(path):
    with open(path, encoding="utf-8") as f:
        src = f.read()
    paras = re.findall(r"<p[^>]*>(.*?)</p>", src, re.S)
    if not paras:
        print(f"BROKEN: no <p> elements in {path}; this is not a letter, or the markup changed",
              file=sys.stderr)
        sys.exit(2)
    text = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", p)) for p in paras).lower()
    return re.findall(r"[a-z0-9']+", text)


def grams(words, n):
    return {tuple(words[i:i + n]) for i in range(len(words) - n + 1)}


def main():
    if len(sys.argv) > 1 and sys.argv[1] in ("-h", "--help"):
        print(__doc__)
        sys.exit(0)
    if len(sys.argv) < 3:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    a_path, b_path = sys.argv[1], sys.argv[2]
    n = int(sys.argv[3]) if len(sys.argv) > 3 else 6
    A, B = paragraph_words(a_path), paragraph_words(b_path)
    ga, gb = grams(A, n), grams(B, n)

    if not ga or not gb:
        print(f"BROKEN: one letter has fewer than {n} paragraph words", file=sys.stderr)
        sys.exit(2)
    if len(ga & grams(A, n)) == 0:
        print("BROKEN: a file does not match itself; the tokenizer is not working", file=sys.stderr)
        sys.exit(2)

    shared = sorted(ga & gb)
    print(f"{a_path.split('/')[-1]}: {len(A)} paragraph words, {len(ga)} {n}-grams")
    print(f"{b_path.split('/')[-1]}: {len(B)} paragraph words, {len(gb)} {n}-grams")
    print(f"control (self-overlap): {len(ga)} -- the measure fires")
    print(f"\nshared {n}-grams: {len(shared)}")
    for g in shared[:20]:
        print("   ", " ".join(g))
    if len(shared) > 20:
        print(f"    ... and {len(shared) - 20} more")
    sys.exit(1 if shared else 0)


if __name__ == "__main__":
    main()
