import zipfile
import re
from xml.etree import ElementTree

NS = {
    'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
}


def _extract_text_from_docx(file) -> str:
    """
    Read a DOCX file and return all paragraph text joined by newlines.

    Uses stdlib xml.etree.ElementTree + zipfile so no external dependency
    is required.  The caller may also pass a ``python-docx`` ``Document``
    object instead of a file path / file-like object.
    """
    # If the caller already opened the docx via python-docx, read paragraphs directly.
    if _is_docx_document(file):
        return '\n'.join(p.text for p in file.paragraphs)

    # Otherwise treat it as a file path or file-like object.
    with zipfile.ZipFile(file) as z:
        xml_bytes = z.read('word/document.xml')
    root = ElementTree.fromstring(xml_bytes)
    paragraphs = []
    for p_elem in root.iter(f'{{{NS["w"]}}}p'):
        texts = []
        for t_elem in p_elem.iter(f'{{{NS["w"]}}}t'):
            if t_elem.text:
                texts.append(t_elem.text)
        paragraphs.append(''.join(texts))
    return '\n'.join(paragraphs)


def _is_docx_document(obj):
    return hasattr(obj, 'paragraphs')


def _strip_q_prefix(line: str) -> str:
    """Remove leading Q[number]. from a question body line."""
    return re.sub(r'^Q\d+\.\s*', '', line).strip()


def parse_question_docx(file):
    """
    Parse a DOCX exam file and return structured question data.

    Returns
    -------
    dict with keys:
        metadata : dict with keys {title, subject, duration_mins, pass_mark, instructions}
                   (all None if not found)
        questions : list of dicts each with {body, question_type, options,
                    correct_answer, difficulty, mark, topic}

    Raises
    ------
    ValueError
        If the document has no questions, or a question is malformed.
    """
    text = _extract_text_from_docx(file)

    lines = text.splitlines()
    # Strip and remove empty lines from the ends but keep internal blanks
    lines = [l.strip() for l in lines]

    metadata = {
        'title': None,
        'subject': None,
        'duration_mins': None,
        'pass_mark': None,
        'instructions': None,
    }

    # -------- Header block (only lines matching known header fields) --------
    # Scan lines until we find a non-header, non-empty, non-separator line
    # that does NOT match any known header prefix.
    header_lines = []
    header_done = False
    body_start = 0
    for i, line in enumerate(lines):
        if not line.strip():
            continue
        if line.startswith('---'):
            header_done = True
            body_start = i + 1
            break
        if _is_header_line(line):
            header_lines.append(line)
        else:
            # A non-header line encountered before any --- means no header block
            body_start = 0
            break

    metadata = {
        'title': None,
        'subject': None,
        'duration_mins': None,
        'pass_mark': None,
        'instructions': None,
    }

    for line in header_lines:
        if line.upper().startswith('EXAM:'):
            metadata['title'] = _after_colon(line)
        elif line.upper().startswith('SUBJECT:'):
            metadata['subject'] = _after_colon(line)
        elif line.upper().startswith('DURATION:'):
            metadata['duration_mins'] = _parse_int(_after_colon(line), 'DURATION')
        elif line.upper().startswith('PASS_MARK:'):
            metadata['pass_mark'] = _parse_int(_after_colon(line), 'PASS_MARK')
        elif line.upper().startswith('INSTRUCTIONS:'):
            metadata['instructions'] = _after_colon(line)

    body_lines = lines[body_start:] if body_start > 0 else lines

    # -------- Split questions by --- --------
    question_texts = _split_by_separator(body_lines)

    if not question_texts:
        raise ValueError('No questions found in the document.')

    # Filter to blocks that contain a Q[number]. line
    question_texts = [b for b in question_texts if any(re.match(r'^Q\d+\.', l) for l in b)]
    if not question_texts:
        raise ValueError('No questions found in the document.')

    questions = []
    for qlines in question_texts:
        qlines = [l for l in qlines if l.strip()]
        if not qlines:
            continue

        question = _parse_single_question(qlines)
        questions.append(question)

    if not questions:
        raise ValueError('No questions found in the document.')

    return {
        'metadata': metadata,
        'questions': questions,
    }


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_HEADER_PREFIXES = ('EXAM:', 'SUBJECT:', 'CLASS:', 'DURATION:', 'PASS_MARK:', 'INSTRUCTIONS:')


def _is_header_line(line: str) -> bool:
    return line.upper().startswith(_HEADER_PREFIXES)


def _split_by_separator(lines):
    """Split a list of lines into blocks separated by lines starting with ---."""
    blocks = []
    current = []
    for line in lines:
        if line.startswith('---'):
            if current:
                blocks.append(current)
                current = []
            continue
        current.append(line)
    if current:
        blocks.append(current)
    return blocks


def _parse_single_question(qlines):
    body = None
    options = []
    correct_answer = None
    difficulty = 'medium'
    mark = 1
    topic = None

    for line in qlines:
        line = line.strip()
        if not line:
            continue

        upper = line.upper()

        # Question body
        if re.match(r'^Q\d+\.', line):
            body = _strip_q_prefix(line)
            continue

        # Option lines: A. B. C. D.
        opt_match = re.match(r'^([A-D])\.\s*(.+)$', line)
        if opt_match:
            options.append(opt_match.group(2))
            continue

        # ANSWER
        if upper.startswith('ANSWER:'):
            correct_answer = _after_colon(line)
            continue

        # DIFFICULTY
        if upper.startswith('DIFFICULTY:'):
            val = _after_colon(line).lower()
            if val not in ('easy', 'medium', 'hard'):
                raise ValueError(
                    f'DIFFICULTY must be easy, medium, or hard. Got: {val}'
                )
            difficulty = val
            continue

        # MARK
        if upper.startswith('MARK:'):
            mark = _parse_int(_after_colon(line), 'MARK')
            continue

        # TOPIC
        if upper.startswith('TOPIC:'):
            topic = _after_colon(line)
            continue

    if not body:
        raise ValueError(f'Question block has no Q[number]. line:\n' + '\n'.join(qlines))

    # -------- Infer question type --------
    if options:
        question_type = 'mcq'
    else:
        tf = correct_answer.strip().lower() if correct_answer else ''
        if tf in ('true', 'false'):
            question_type = 'true_false'
        else:
            question_type = 'short_answer'

    # -------- Validation --------
    if options and correct_answer is None:
        raise ValueError(
            f'Question "{body[:60]}..." has options but no ANSWER line.'
        )

    if options:
        expected = ['A', 'B', 'C', 'D'][:len(options)]
        if correct_answer.upper() not in expected:
            raise ValueError(
                f'MCQ answer must be one of {", ".join(expected)}. '
                f'Got: {correct_answer} for question "{body[:60]}..."'
            )
        # Resolve MCQ letter to option text
        idx = ord(correct_answer.upper()) - ord('A')
        correct_answer = options[idx]

    return {
        'body': body,
        'question_type': question_type,
        'options': options if options else None,
        'correct_answer': correct_answer,
        'difficulty': difficulty,
        'mark': mark,
        'topic': topic,
    }


def _after_colon(line: str) -> str:
    """Return everything after the first colon, stripped."""
    idx = line.find(':')
    if idx == -1:
        return ''
    return line[idx + 1:].strip()


def _parse_int(value: str, field_name: str) -> int:
    try:
        return int(value)
    except (ValueError, TypeError):
        raise ValueError(
            f'{field_name} must be a number. Got: {value!r}'
        )
