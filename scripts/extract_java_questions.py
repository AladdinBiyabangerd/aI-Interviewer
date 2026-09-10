"""Extract structured, private review candidates from supported Java-question PDFs.

This script never publishes questions. It creates a bounded JSON artifact for the
operator-only staging tables. Source wording and explanations remain private until a
reviewer resolves correctness, currency, licensing, level, tags, and original wording.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pypdf import PdfReader

PARSER_RELEASE = "java-pdf-questions-v7"
QUESTION_START = re.compile(r"^\s*(\d{1,3})\.\s*(\S.*)$")
QUESTION_NUMBER_ONLY = re.compile(r"^\s*(\d{1,3})\.\s*$")
OPTION_START = re.compile(r"^\s*[^A-Za-z0-9]*([A-H])\.\s*(.*)$")
ANSWER_START = re.compile(r"^\s*(\d{1,3})\.\s*([A-H](?:\s*,\s*[A-H])*)\.\s*(.*)$")
ANSWER_NUMBER_ONLY = re.compile(r"^\s*(\d{1,3})\.\s*$")
ANSWER_CHOICE_ONLY = re.compile(r"^\s*([A-H](?:\s*,\s*[A-H])*)\.\s*(.*)$")
BOOK_CHAPTER_HEADER = re.compile(r"^\s*Chapter\s+(\d{1,2})\b", re.IGNORECASE)
ANSWER_CHAPTER = re.compile(r"^\s*Chapter\s+(\d{1,2})\s*:\s*(.*)$", re.IGNORECASE)
EXAM_STEM = re.compile(
    r"^(?:What|Which|For|Fill|On|How|A\s+bank|In\s+the|Given|Assuming|Consider)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SourceLine:
    text: str
    page: int


def normalize_text(value: str) -> str:
    value = value.replace("\x00", "").replace("\u00a0", " ")
    value = value.replace("\uf0a7", " ").replace("\uf0fc", " ")
    return "\n".join(line.rstrip() for line in value.splitlines())


def compact(lines: list[str]) -> str:
    result: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            if result and result[-1] != "":
                result.append("")
            continue
        if result and result[-1] and result[-1].endswith("-") and stripped[0].islower():
            result[-1] = result[-1][:-1] + stripped
        else:
            result.append(stripped)
    return "\n".join(result).strip()


def content_lines(text: str, page: int) -> list[SourceLine]:
    lines = normalize_text(text).splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and (
        re.match(r"^\s*\d+\s+Part\s+", lines[0])
        or re.match(r"^\s*Chapter\s+\d+.+\s\d+\s*$", lines[0])
        or re.match(r"^\s*\d+\s+Appendix\b", lines[0])
    ):
        lines.pop(0)
    return [SourceLine(line, page) for line in lines]


def chapter_from_page(text: str, current: int | None) -> int | None:
    lines = [line.strip() for line in normalize_text(text).splitlines() if line.strip()]
    if not lines:
        return current
    # Running headers put ``Chapter N`` first, while chapter title pages put
    # separate ``Chapter`` and number lines at the very end of extracted text.
    # Restrict the combined form to the first line so examples in questions do
    # not cause a false chapter transition.
    match = BOOK_CHAPTER_HEADER.match(lines[0])
    if match:
        return int(match.group(1))
    for index, line in enumerate(lines):
        if line.lower() == "chapter":
            for candidate in lines[index + 1 : index + 3]:
                if candidate.isdigit() and 1 <= int(candidate) <= 23:
                    return int(candidate)
    return current


def chapter_title(text: str, chapter: int, fallback: str) -> str:
    lines = [line.strip() for line in normalize_text(text).splitlines() if line.strip()]
    if lines:
        running_title = re.match(
            rf"^Chapter\s+{chapter}\s+[^A-Za-z0-9]*\s*(.*?)\s+\d+\s*$",
            lines[0],
            re.IGNORECASE,
        )
        if running_title and running_title.group(1).strip():
            return running_title.group(1).strip()
    for line in lines[:5]:
        match = ANSWER_CHAPTER.match(line)
        if match and int(match.group(1)) == chapter and match.group(2).strip():
            return re.sub(r"\s+\d+\s*$", "", match.group(2)).strip()

    def is_topics_heading(line: str) -> bool:
        letters = re.sub(r"[^a-z]", "", line.lower())
        return letters.startswith(("theocaexamtopics", "theocpexamtopics"))

    for index, line in enumerate(lines):
        if (
            line.lower() == "chapter"
            and index + 2 < len(lines)
            and lines[index + 1] == str(chapter)
        ):
            title_lines: list[str] = []
            for candidate in lines[index + 2 :]:
                if is_topics_heading(candidate):
                    break
                title_lines.append(candidate)
            if title_lines:
                return " ".join(title_lines[:2])
    # On title pages, the title precedes the trailing ``Chapter`` marker.
    chapter_index = next(
        (index for index, line in enumerate(lines) if line.lower() == "chapter"),
        None,
    )
    if chapter_index and lines[0]:
        title_end = next(
            (index for index, line in enumerate(lines[:chapter_index]) if is_topics_heading(line)),
            min(chapter_index, 2),
        )
        candidate = " ".join(lines[:title_end]).strip()
        if candidate:
            return candidate
    return fallback


def split_numbered_blocks(
    lines: list[SourceLine], *, require_exam_stem: bool = False
) -> tuple[list[dict[str, Any]], list[int]]:
    blocks: list[dict[str, Any]] = []
    gaps: list[int] = []
    current: dict[str, Any] | None = None
    expected = 1
    for line in lines:
        match = QUESTION_START.match(line.text)
        number_only = QUESTION_NUMBER_ONLY.match(line.text)
        candidate_number = (
            int(match.group(1)) if match else int(number_only.group(1)) if number_only else None
        )
        start = candidate_number == expected
        if start and current:
            # Exam PDFs often number code lines with the same "2." form as the
            # next question. A real transition occurs only after answer choices.
            start = (
                len({m.group(1) for item in current["lines"] if (m := OPTION_START.match(item))})
                >= 2
            )
            if require_exam_stem and start and match and not EXAM_STEM.match(match.group(2)):
                # Accept unusual stems (for example "And the commands") after a
                # complete option block, while still rejecting numbered code.
                start = True
        if start:
            if current:
                blocks.append(current)
            current = {
                "number": expected,
                "page_start": line.page,
                "lines": [match.group(2)] if match else [],
            }
            expected += 1
        elif current:
            current["lines"].append(line.text)
            current["page_end"] = line.page
    if current:
        blocks.append(current)
    if blocks:
        found = {block["number"] for block in blocks}
        gaps = [number for number in range(1, max(found) + 1) if number not in found]
    for block in blocks:
        block.setdefault("page_end", block["page_start"])
    return blocks, gaps


def parse_options(lines: list[str]) -> tuple[str, list[dict[str, str]]]:
    prompt: list[str] = []
    options: list[dict[str, str]] = []
    active: dict[str, str] | None = None
    for line in lines:
        match = OPTION_START.match(line)
        if match and (not options or ord(match.group(1)) == ord(options[-1]["id"]) + 1):
            active = {"id": match.group(1), "text": match.group(2).strip()}
            options.append(active)
        elif active:
            active["text"] = compact([active["text"], line])
        else:
            prompt.append(line)
    return compact(prompt), options


def parse_book_questions(
    pages: list[str], appendix_index: int
) -> tuple[list[dict[str, Any]], dict[int, str], list[str]]:
    by_chapter: dict[int, list[SourceLine]] = {}
    titles: dict[int, str] = {}
    current: int | None = None
    for page_number, text in enumerate(pages[:appendix_index], start=1):
        previous = current
        current = chapter_from_page(text, current)
        if current is None:
            continue
        if current != previous:
            titles[current] = chapter_title(text, current, f"Chapter {current}")
        elif BOOK_CHAPTER_HEADER.match(
            next(
                (line.strip() for line in normalize_text(text).splitlines() if line.strip()),
                "",
            )
        ):
            titles[current] = chapter_title(text, current, titles[current])
        by_chapter.setdefault(current, []).extend(content_lines(text, page_number))
    result: list[dict[str, Any]] = []
    issues: list[str] = []
    for chapter in sorted(by_chapter):
        blocks, gaps = split_numbered_blocks(by_chapter[chapter])
        if gaps:
            issues.append(f"chapter_{chapter}_question_gaps:{','.join(map(str, gaps))}")
        for block in blocks:
            prompt, options = parse_options(block.pop("lines"))
            result.append(
                {
                    **block,
                    "chapter": chapter,
                    "chapter_title": titles[chapter],
                    "prompt": prompt,
                    "options": options,
                }
            )
    return result, titles, issues


def parse_book_answers(
    pages: list[str], appendix_index: int, titles: dict[int, str]
) -> tuple[dict[tuple[int, int], dict[str, Any]], list[str]]:
    by_chapter: dict[int, list[SourceLine]] = {}
    current: int | None = None
    for page_number, text in enumerate(pages[appendix_index:], start=appendix_index + 1):
        first_line = next(
            (line.strip() for line in normalize_text(text).splitlines() if line.strip()),
            "",
        )
        if first_line == "Index":
            break
        lines = content_lines(text, page_number)
        for line in lines:
            match = ANSWER_CHAPTER.match(line.text)
            if match:
                current = int(match.group(1))
                continue
            if current is not None:
                by_chapter.setdefault(current, []).append(line)
    answers: dict[tuple[int, int], dict[str, Any]] = {}
    issues: list[str] = []
    for chapter in sorted(by_chapter):
        current_answer: dict[str, Any] | None = None
        pending_number: tuple[int, int] | None = None
        expected = 1
        for line in by_chapter[chapter]:
            match = ANSWER_START.match(line.text)
            if match and int(match.group(1)) == expected:
                if current_answer:
                    current_answer["explanation"] = compact(current_answer.pop("lines"))
                    answers[(chapter, current_answer["number"])] = current_answer
                current_answer = {
                    "number": expected,
                    "correct": [item.strip() for item in match.group(2).split(",")],
                    "page": line.page,
                    "lines": [match.group(3)],
                }
                expected += 1
                pending_number = None
                continue
            number_only = ANSWER_NUMBER_ONLY.match(line.text)
            if number_only and int(number_only.group(1)) == expected:
                pending_number = (expected, line.page)
                continue
            choice_only = ANSWER_CHOICE_ONLY.match(line.text) if pending_number else None
            if choice_only and pending_number:
                if current_answer:
                    current_answer["explanation"] = compact(current_answer.pop("lines"))
                    answers[(chapter, current_answer["number"])] = current_answer
                current_answer = {
                    "number": pending_number[0],
                    "correct": [item.strip() for item in choice_only.group(1).split(",")],
                    "page": pending_number[1],
                    "lines": [choice_only.group(2)],
                }
                expected += 1
                pending_number = None
            elif current_answer:
                current_answer["lines"].append(line.text)
        if current_answer:
            current_answer["explanation"] = compact(current_answer.pop("lines"))
            answers[(chapter, current_answer["number"])] = current_answer
        found = {number for answer_chapter, number in answers if answer_chapter == chapter}
        if found:
            gaps = [number for number in range(1, max(found) + 1) if number not in found]
            if gaps:
                issues.append(f"chapter_{chapter}_answer_gaps:{','.join(map(str, gaps))}")
        elif chapter in titles:
            issues.append(f"chapter_{chapter}_answers_missing")
    return answers, issues


def issue_codes(prompt: str, options: list[dict[str, str]], correct: list[str] | None) -> list[str]:
    issues: list[str] = []
    option_ids = [option["id"] for option in options]
    if not prompt:
        issues.append("empty_prompt")
    if len(options) < 2 or len(options) > 8:
        issues.append("option_count_outside_range")
    if len(option_ids) != len(set(option_ids)):
        issues.append("duplicate_option_id")
    if any(not option["text"].strip() for option in options):
        issues.append("empty_option")
    if correct is None:
        issues.append("missing_answer")
    elif any(answer not in option_ids for answer in correct):
        issues.append("answer_option_missing")
    if "�" in prompt or any("�" in option["text"] for option in options):
        issues.append("text_encoding_damage")
    if re.search(r"\b(diagram|figure|image|exhibit)\b", prompt, re.IGNORECASE):
        issues.append("visual_review_required")
    return issues


def build_candidates(
    questions: list[dict[str, Any]], answers: dict[tuple[int, int], dict[str, Any]]
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for question in questions:
        key = (question["chapter"], question["number"])
        answer = answers.get(key)
        correct = answer["correct"] if answer else None
        issues = issue_codes(question["prompt"], question["options"], correct)
        normalized = json.dumps(
            {
                "prompt": re.sub(r"\s+", " ", question["prompt"]).strip(),
                "options": [
                    re.sub(r"\s+", " ", option["text"]).strip() for option in question["options"]
                ],
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        status = (
            "needs_answer"
            if "missing_answer" in issues
            else "needs_review"
            if issues
            else "complete"
        )
        candidates.append(
            {
                "source_question_key": (
                    f"chapter-{question['chapter']}-question-{question['number']}"
                ),
                "chapter_number": question["chapter"],
                "chapter_title": question["chapter_title"],
                "question_number": question["number"],
                "page_start": question["page_start"],
                "page_end": question["page_end"],
                "prompt": question["prompt"],
                "options": question["options"],
                "correct": correct,
                "explanation": answer["explanation"] if answer else None,
                "answer_page": answer["page"] if answer else None,
                "normalized_hash": hashlib.sha256(normalized.encode()).hexdigest(),
                "parse_status": status,
                "issue_codes": issues,
            }
        )
    return candidates


def extract(args: argparse.Namespace) -> dict[str, Any]:
    source = Path(args.input).resolve(strict=True)
    reader = PdfReader(source)
    if reader.is_encrypted:
        raise ValueError("Encrypted PDFs are not supported")
    pages = [page.extract_text() or "" for page in reader.pages]
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    extraction_issues: list[str] = []
    answers: dict[tuple[int, int], dict[str, Any]] = {}
    if args.profile == "selikoff-java-8":
        appendix = next(
            (
                index
                for index, text in enumerate(pages)
                if normalize_text(text).lstrip().startswith("Appendix Answers to Review")
            ),
            None,
        )
        if appendix is None:
            raise ValueError("Answers appendix was not found")
        questions, titles, question_issues = parse_book_questions(pages, appendix)
        answers, answer_issues = parse_book_answers(pages, appendix, titles)
        extraction_issues.extend(question_issues + answer_issues)
    else:
        lines = [
            line
            for number, text in enumerate(pages, start=1)
            for line in content_lines(text, number)
        ]
        blocks, gaps = split_numbered_blocks(lines, require_exam_stem=True)
        if gaps:
            extraction_issues.append(f"exam_question_gaps:{','.join(map(str, gaps))}")
        questions = []
        for block in blocks:
            prompt, options = parse_options(block.pop("lines"))
            questions.append(
                {
                    **block,
                    "chapter": 1,
                    "chapter_title": args.source_title,
                    "prompt": prompt,
                    "options": options,
                }
            )
    candidates = build_candidates(questions, answers)
    status_counts = Counter(candidate["parse_status"] for candidate in candidates)
    issue_counts = Counter(issue for candidate in candidates for issue in candidate["issue_codes"])
    report = {
        "profile": args.profile,
        "status_counts": dict(sorted(status_counts.items())),
        "issue_counts": dict(sorted(issue_counts.items())),
        "extraction_issues": extraction_issues,
        "chapters": {
            str(chapter): len([q for q in candidates if q["chapter_number"] == chapter])
            for chapter in sorted({q["chapter_number"] for q in candidates})
        },
    }
    return {
        "schema_version": 1,
        "parser_release": PARSER_RELEASE,
        "source": {
            "file_name": args.source_file_name or source.name,
            "sha256": digest,
            "title": args.source_title,
            "authors": args.authors,
            "publisher": args.publisher,
            "publication_year": args.publication_year,
            "reference_url": args.reference_url,
            "page_count": len(pages),
        },
        "rights_status": "unverified",
        "status": "review_required"
        if extraction_issues
        or status_counts.get("needs_answer")
        or status_counts.get("needs_review")
        else "ready",
        "question_count": len(candidates),
        "answer_count": sum(candidate["correct"] is not None for candidate in candidates),
        "report": report,
        "candidates": candidates,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("selikoff-java-8", "ingress-exam"), required=True)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--source-title", required=True)
    parser.add_argument("--source-file-name")
    parser.add_argument("--authors")
    parser.add_argument("--publisher")
    parser.add_argument("--publication-year", type=int)
    parser.add_argument("--reference-url")
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite existing output: {output}")
    document = extract(args)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                key: document[key]
                for key in ("parser_release", "status", "question_count", "answer_count", "report")
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
