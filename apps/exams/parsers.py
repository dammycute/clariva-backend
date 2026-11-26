"""Reading an exam paper out of a Word document, whatever shape the teacher wrote it in.

A real paper is not a form. One teacher numbers questions "1." and letters options
"A."; another writes "(a)" and puts the answers in a key at the bottom; another pastes
a table. This module guesses the structure from the text instead of demanding one
exact template. The old `---` template still reads exactly as it did before.

Nothing here needs a third-party package: a .docx is a zip with XML inside.
"""
import re
import zipfile
from xml.etree import ElementTree

NS = {
    'w': 'http://schemas.openxmlformats.org/wordprocessingml/2006/main',
}

LETTERS = 'ABCDEFGH'


def _extract_text_from_docx(file) -> str:
    """Every paragraph in the document, one per line, including text inside tables.

    Accepts a path, a file-like object, or an already-opened python-docx Document.
    """
    if _is_docx_document(file):
        return '\n'.join(p.text for p in file.paragraphs)

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


# ---------------------------------------------------------------------------
# The shape of the document
# ---------------------------------------------------------------------------

_Q_START = re.compile(r'^(?:q(?:uestion)?\s*)?(\d{1,3})\s*[.):\]\-]\s*(.*)$', re.I)
_OPT = re.compile(r'^\(?([a-hA-H])\)\s*(.*)$|^([a-hA-H])\s*[.):]\s*(.*)$')
_ANSWER = re.compile(
    r'^(?:the\s+)?(?:correct\s+)?(?:answer|ans)\s*[:\-.=\u2013\u2014]\s*(.+)$', re.I)
_ACCEPT = re.compile(r'^(?:accept|also\s+accept|accepted\s+answers?)\s*[:\-.=]\s*(.+)$', re.I)
_DIFFICULTY = re.compile(r'^difficulty\s*[:\-.=]\s*(.+)$', re.I)
_MARK = re.compile(r'^(?:marks?|score)\s*[:\-.=]\s*(.+)$', re.I)
_TOPIC = re.compile(r'^(?:topic|sub-?topic|theme)\s*[:\-.=]\s*(.+)$', re.I)
_SECTION = re.compile(
    r'^(?:section|part)\s+([a-z0-9]+)\s*(?:[:\-\u2013]\s*(.*))?$', re.I)
_SEPARATOR = re.compile(r'^[-_=*~]{3,}$')
_NOISE = re.compile(
    r'^(?:page\s*\d+|\d+\s*\|\s*page|©|copyright|powered\s+by|www\.|https?://)', re.I)
_ANSWER_KEY_HEAD = re.compile(
    r'^(?:answer\s*key|answers?|marking\s*(?:scheme|guide)|key\s+to\s+answers?)\s*[:\-]?$',
    re.I)

# Header lines a paper usually opens with. Both "EXAM: x" and "EXAM x" are accepted.
_HEADER_KEYS = (
    (re.compile(r'^(?:exam(?:ination)?|paper|title)\s*[:\-]', re.I), 'title'),
    (re.compile(r'^subject\s*[:\-]', re.I), 'subject'),
    (re.compile(r'^(?:class|level|grade)\s*[:\-]', re.I), 'class_group'),
    (re.compile(r'^(?:duration|time[_\s]*allowed|time[_\s]*limit|time)\s*[:\-]', re.I), 'duration'),
    (re.compile(r'^pass[_\s]*mark\s*[:\-]', re.I), 'pass_mark'),
    (re.compile(r'^(?:instructions?|directions?)\s*[:\-]', re.I), 'instructions'),
)

_MARK_IN_INSTRUCTIONS = re.compile(
    r'each\s+question\s+carries?\s+(\d+)|(\d+)\s*marks?\s+each|each\s+question\s+is\s+(\d+)',
    re.I)


def _clean(line: str) -> str:
    """Tidy one line without changing what it says."""
    line = (line or '').replace('\u00a0', ' ').replace('\u200b', '')
    line = line.replace('\u2018', "'").replace('\u2019', "'")
    line = line.replace('\u201c', '"').replace('\u201d', '"')
    return re.sub(r'[ \t]+', ' ', line).strip()


def _is_separator(line: str) -> bool:
    return bool(_SEPARATOR.match(line))


def _is_noise(line: str) -> bool:
    return bool(_NOISE.match(line))


def _int(value, field_name):
    try:
        return int(str(value).strip().split()[0])
    except (ValueError, TypeError, IndexError):
        raise ValueError(f'{field_name} must be a number. Got: {value!r}')


def _duration_minutes(value: str):
    """'60', '1 hour', '1hr 30 mins' and '1:30' all mean a number of minutes."""
    text = (value or '').strip().lower()
    clock = re.search(r'(\d{1,2})\s*[:.]\s*(\d{2})', text)
    if clock:
        return int(clock.group(1)) * 60 + int(clock.group(2))
    hours = re.search(r'(\d+)\s*(?:hours?|hrs?|h)\b', text)
    mins = re.search(r'(\d+)\s*(?:minutes?|mins?|m)\b', text)
    if hours or mins:
        total = (int(hours.group(1)) * 60 if hours else 0) + (int(mins.group(1)) if mins else 0)
        return total or None
    digits = re.search(r'\d+', text)
    return int(digits.group()) if digits else None


def _read_header(lines):
    """The paper's own details, and the line where the questions begin."""
    meta = {
        'title': None, 'subject': None, 'class_group': None,
        'duration_mins': None, 'pass_mark': None, 'instructions': None,
    }
    body_start = 0
    for i, line in enumerate(lines[:60]):
        if _Q_START.match(line) or _looks_like_option(line) or _SECTION.match(line):
            body_start = i
            break
        if _is_separator(line) or _is_noise(line):
            continue
        key = value = None
        for pattern, name in _HEADER_KEYS:
            if pattern.match(line):
                key = name
                value = line[pattern.match(line).end():].strip()
                break
        if key == 'duration':
            meta['duration_mins'] = _duration_minutes(value)
            continue
        if key == 'pass_mark':
            digits = re.search(r'\d+', value or '')
            meta['pass_mark'] = int(digits.group()) if digits else None
            continue
        if key:
            if value:
                meta[key] = value
            continue
        # The first plain line is usually the title: "SS1 Mathematics First Term Exam".
        if meta['title'] is None and len(line) <= 160:
            meta['title'] = line
    return meta, body_start


def _looks_like_option(line: str):
    return _OPT.match(line)


def _opt_parts(match):
    """The letter and the text out of either shape of the option regex."""
    letter = (match.group(1) or match.group(3) or '').upper()
    text = (match.group(2) if match.group(1) else match.group(4)) or ''
    return letter, text.strip()


def _inline_options(line: str):
    """'A. 9   B. 10   C. 11   D. 13' on one line, or None."""
    marks = list(re.finditer(r'(?:^|(?<=\s))\(?([a-hA-H])\)?[.):]\s+', line))
    if len(marks) < 2:
        return None
    letters = [m.group(1).upper() for m in marks]
    if letters != list(LETTERS[:len(letters)]):
        return None
    found = []
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(line)
        found.append((m.group(1).upper(), line[m.end():end].strip()))
    return found or None


def _section_topic(line: str):
    m = _SECTION.match(line)
    if not m:
        return None
    title = (m.group(2) or '').strip()
    if title.isupper():
        title = title.title()
    return title or f'Section {m.group(1).upper()}'


def _split_answer_key(lines):
    """Separate an 'ANSWER KEY' section at the end from the questions."""
    for i, line in enumerate(lines):
        if _ANSWER_KEY_HEAD.match(line):
            return lines[:i], _read_key(lines[i + 1:])
    return lines, {}


def _read_key(lines):
    """A key of the form '1. B', '1 B', '1-B', '1 | B' or '1. Abuja', several per line."""
    key = {}
    for line in lines:
        if _is_noise(line) or _is_separator(line) or _is_header_noise(line):
            continue
        pairs = re.findall(
            r'(\d{1,3})\s*[.):\-|]?\s*([A-Ha-h])(?=\s|$|[,;.])', line)
        if pairs:
            for number, letter in pairs:
                key[int(number)] = letter.upper()
            continue
        single = re.match(r'^(\d{1,3})\s*[.):\-|]\s*(.+)$', line)
        if single:
            key[int(single.group(1))] = single.group(2).strip()
    return key


def _is_header_noise(line: str) -> bool:
    return any(pattern.match(line) for pattern, _ in _HEADER_KEYS)


def _clean_answer(value: str) -> str:
    """'Option B' and 'B.' both mean B."""
    text = (value or '').strip()
    text = re.sub(r'^(?:option|choice|ans(?:wer)?)\s*', '', text, flags=re.I).strip()
    return text.rstrip('.').strip()


def _mark_from_instructions(meta):
    text = meta.get('instructions') or ''
    m = _MARK_IN_INSTRUCTIONS.search(text)
    if not m:
        return None
    for group in m.groups():
        if group:
            return int(group)
    return None


# ---------------------------------------------------------------------------
# The public entry point
# ---------------------------------------------------------------------------

def parse_question_docx(file):
    """Read a paper and return its details and its questions.

    Returns
    -------
    dict with keys:
        metadata        : {title, subject, class_group, duration_mins, pass_mark, instructions}
        questions       : [{body, question_type, options, correct_answer,
                            accepted_answers, difficulty, mark, topic}, ...]
        warnings        : things the teacher should look at, in plain words
        answer_key_found: whether the answers came from a key at the end

    Raises
    ------
    ValueError
        If no question can be found, or a question contradicts itself in a way
        that cannot be guessed (an invalid DIFFICULTY, a missing answer on a
        multiple-choice question, and so on).
    """
    text = _extract_text_from_docx(file)
    lines = [_clean(line) for line in text.splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        raise ValueError('The document is empty.')

    metadata, body_start = _read_header(lines)
    body, key = _split_answer_key(lines[body_start:])
    questions, warnings = _read_questions(body, metadata, key)

    if not questions:
        raise ValueError(
            'No questions found in the document. Number the questions (1., 2., 3. …) '
            'and put each answer on its own line such as "Answer: B", or add an '
            '"ANSWER KEY" section at the end.'
        )

    return {
        'metadata': metadata,
        'questions': questions,
        'warnings': warnings,
        'answer_key_found': bool(key),
    }


def _read_questions(lines, metadata, key):
    """Group the lines into questions, then read each one."""
    blocks = []
    current = None
    topic = None

    for line in lines:
        if _is_separator(line) or _is_noise(line):
            continue
        if _is_header_noise(line):
            continue

        section = _section_topic(line)
        if section:
            if current:
                blocks.append((current, topic))
                current = None
            topic = section
            continue

        start = _Q_START.match(line)
        if start:
            if current:
                blocks.append((current, topic))
            current = [line]
            continue

        if current is None:
            # Text before the first numbered question is a heading or a note.
            continue
        current.append(line)

    if current:
        blocks.append((current, topic))

    questions, warnings = [], []
    for block, section in blocks:
        question = _parse_block(block, metadata, key, section, warnings)
        if question is not None:
            questions.append(question)
    return questions, warnings


def _parse_block(lines, metadata, key, section, warnings):
    body_parts, options, accepted = [], [], []
    answer = difficulty = mark = topic = None
    number = None

    first = _Q_START.match(lines[0])
    if first:
        number = int(first.group(1))
        if (first.group(2) or '').strip():
            body_parts.append(first.group(2).strip())

    for line in lines[1:]:
        if _is_noise(line) or _is_separator(line) or _is_header_noise(line):
            continue
        if _section_topic(line):
            continue

        m = _ANSWER.match(line)
        if m:
            answer = _clean_answer(m.group(1))
            continue
        m = _ACCEPT.match(line)
        if m:
            accepted = [a.strip() for a in m.group(1).split('|') if a.strip()]
            continue
        m = _DIFFICULTY.match(line)
        if m:
            value = m.group(1).strip().lower().rstrip('.')
            if value not in ('easy', 'medium', 'hard'):
                raise ValueError(
                    f'DIFFICULTY must be easy, medium, or hard. Got: {value}'
                )
            difficulty = value
            continue
        m = _MARK.match(line)
        if m:
            mark = _int(m.group(1), 'MARK')
            continue
        m = _TOPIC.match(line)
        if m:
            topic = m.group(1).strip() or None
            continue

        inline = _inline_options(line)
        if inline:
            options.extend(text for _, text in inline)
            continue
        m = _OPT.match(line)
        if m:
            _, text = _opt_parts(m)
            if options and not text:
                options[-1] = options[-1]
                continue
            options.append(text)
            continue

        if options:
            # A wrapped option line: "B. Abuja, the Federal" / "Capital Territory".
            options[-1] = f'{options[-1]} {line}'.strip()
        else:
            body_parts.append(line)

    body = ' '.join(part for part in body_parts if part).strip()
    if not body:
        return None

    if answer is None and number is not None and number in key:
        answer = key[number]
    if not accepted and number is not None and isinstance(key.get(number), str) \
            and '|' in str(key.get(number)):
        accepted = [a.strip() for a in str(key[number]).split('|') if a.strip()]

    if options:
        question_type = 'mcq'
        if answer is None:
            raise ValueError(
                f'Question "{body[:60]}" has options but no ANSWER line. '
                f'Add "ANSWER: A" under it, or an ANSWER KEY at the end.'
            )
        letter = answer.strip().upper()
        if len(letter) == 1 and letter in LETTERS and LETTERS.index(letter) < len(options):
            correct_answer = options[LETTERS.index(letter)]
        elif answer in options:
            correct_answer = answer
        else:
            expected = ', '.join(LETTERS[:len(options)])
            raise ValueError(
                f'MCQ answer must be one of {expected}. Got: {answer} '
                f'for question "{body[:60]}..."'
            )
        if len(options) < 2:
            warnings.append(f'Question "{body[:40]}" has only one option.')
    else:
        word = (answer or '').strip().lower().rstrip('.')
        if word in ('true', 'false', 't', 'f', 'yes', 'no'):
            question_type = 'true_false'
            correct_answer = 'True' if word in ('true', 't', 'yes') else 'False'
        else:
            question_type = 'short_answer'
            correct_answer = answer
        if correct_answer is None:
            warnings.append(
                f'Question "{body[:40]}" has no answer. Set it in the editor before publishing.'
            )

    return {
        'body': body,
        'question_type': question_type,
        'options': options if options else None,
        'correct_answer': correct_answer,
        'accepted_answers': accepted if (accepted and question_type == 'short_answer') else None,
        'difficulty': difficulty or 'medium',
        'mark': mark or _mark_from_instructions(metadata) or 1,
        'topic': topic or section,
    }


# ---------------------------------------------------------------------------
# Kept for older callers
# ---------------------------------------------------------------------------

def _strip_q_prefix(line: str) -> str:
    """Remove a leading Q[number]. from a question body line."""
    return re.sub(r'^Q\d+\.\s*', '', line).strip()


def _after_colon(line: str) -> str:
    """Everything after the first colon, stripped."""
    idx = line.find(':')
    return line[idx + 1:].strip() if idx != -1 else ''
