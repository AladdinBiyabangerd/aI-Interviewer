from scripts.extract_java_questions import (
    SourceLine,
    build_candidates,
    parse_book_answers,
    parse_book_questions,
    split_numbered_blocks,
)


def test_number_only_question_lines_do_not_break_numbered_code() -> None:
    lines = [
        SourceLine("1. What is printed?", 1),
        SourceLine("1. int value = 2;", 1),
        SourceLine("A. one", 1),
        SourceLine("B. two", 1),
        SourceLine("C. compile error", 1),
        SourceLine("2.", 2),
        SourceLine("Which declaration compiles?", 2),
        SourceLine("A. first", 2),
        SourceLine("B. second", 2),
        SourceLine("C. third", 2),
    ]

    blocks, gaps = split_numbered_blocks(lines)

    assert gaps == []
    assert [block["number"] for block in blocks] == [1, 2]
    assert "int value = 2" in "\n".join(blocks[0]["lines"])
    assert blocks[1]["page_start"] == 2


def test_book_questions_pair_with_inline_and_wrapped_answers() -> None:
    pages = [
        "Chapter\n1\nJava Basics\nThe OCA exam topics covered",
        (
            "1. First question?\nA. alpha\nB. beta\nC. gamma\n"
            "2.\nSecond question?\nA. one\nB. two\nC. three"
        ),
        (
            "Appendix Answers to Review Questions\n"
            "Chapter 1: Java Basics\n"
            "1. B. First explanation.\n"
            "2.\nC. Second explanation."
        ),
        "Index\nJava, 1-20\nThis must not enter the final explanation.",
    ]

    questions, titles, question_issues = parse_book_questions(pages, 2)
    answers, answer_issues = parse_book_answers(pages, 2, titles)
    candidates = build_candidates(questions, answers)

    assert question_issues == []
    assert answer_issues == []
    assert titles == {1: "Java Basics"}
    assert [candidate["correct"] for candidate in candidates] == [["B"], ["C"]]
    assert [candidate["parse_status"] for candidate in candidates] == ["complete", "complete"]
    assert candidates[1]["explanation"] == "Second explanation."


def test_normalized_hash_preserves_java_case() -> None:
    questions = [
        {
            "chapter": 1,
            "chapter_title": "Date/time",
            "number": number,
            "page_start": 1,
            "page_end": 1,
            "prompt": f'DateTimeFormatter.ofPattern("{pattern}")',
            "options": [
                {"id": "A", "text": "Compiles"},
                {"id": "B", "text": "Does not compile"},
                {"id": "C", "text": "Throws"},
            ],
        }
        for number, pattern in ((1, "MM-dd-yyyy"), (2, "mm-dd-yyyy"))
    ]
    answers = {
        (1, number): {
            "correct": ["A"],
            "page": 2,
            "explanation": "Case changes the pattern.",
        }
        for number in (1, 2)
    }

    candidates = build_candidates(questions, answers)

    assert candidates[0]["normalized_hash"] != candidates[1]["normalized_hash"]
