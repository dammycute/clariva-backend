"""The one set of marking rules for CBT. Pure functions: no database, no request.

Submit and auto-close both call these, so a score never depends on which path ran.
"""
import re
from fractions import Fraction

_CURRENCY = re.compile(r'[₦$£€]')          # naira, dollar, pound, euro signs
_LEADING_N = re.compile(r'^n(?=\s*\d)', re.IGNORECASE)    # "N5,000"
_SPACES = re.compile(r'\s+')


def normalise(text) -> str:
    """Lower case, trim, collapse spaces, drop one trailing full stop."""
    s = _SPACES.sub(' ', str(text if text is not None else '')).strip().lower()
    if s.endswith('.') and not re.search(r'\d\.$', s):
        s = s[:-1].rstrip()
    return s


def as_number(text):
    """Return an exact number for answers like '1,540', 'N1,500', '3/5' or '0.6'; otherwise None."""
    s = str(text if text is not None else '').strip()
    if not s:
        return None
    s = _CURRENCY.sub('', s)
    s = _LEADING_N.sub('', s.strip())
    s = s.replace(',', '').replace(' ', '').rstrip('%')
    if not s:
        return None
    try:
        return Fraction(s)
    except (ValueError, ZeroDivisionError):
        return None


def same_answer(given, expected) -> bool:
    """True when two answers match as text, or as the same number."""
    if normalise(given) == normalise(expected):
        return True
    a, b = as_number(given), as_number(expected)
    return a is not None and b is not None and a == b


def correct_option_text(question) -> str:
    """For multiple choice, the key may be a letter (A to D) or the option text. Return the text."""
    correct = str(question.correct_answer).strip()
    options = question.options or []
    if question.question_type == 'mcq' and len(correct) == 1 and correct.upper() in 'ABCD':
        idx = ord(correct.upper()) - ord('A')
        if 0 <= idx < len(options):
            return str(options[idx])
    return correct


def is_correct(question, answer) -> bool:
    if answer is None or str(answer).strip() == '':
        return False
    if question.question_type == 'short_answer':
        accepted = [str(question.correct_answer)] + [str(a) for a in (question.accepted_answers or [])]
        return any(same_answer(answer, key) for key in accepted)
    # mcq and true_false have exactly one right answer
    return same_answer(answer, correct_option_text(question))


def mark_answers(questions, answers) -> tuple:
    """Return (score, total_marks) for `answers` ({question id: answer text})."""
    score = total = 0
    for q in questions:
        total += q.mark
        if is_correct(q, answers.get(str(q.id))):
            score += q.mark
    return score, total
