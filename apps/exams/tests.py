import io
import zipfile
from xml.etree import ElementTree
import json
from django.test import TestCase, override_settings
from django.urls import reverse
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient
from apps.schools.models import School

from .parsers import parse_question_docx
from .models import Exam, Question

W_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'


def _make_docx(paragraph_texts: list[str]) -> bytes:
    """
    Build a minimal in-memory DOCX (ZIP) file whose only content is a series
    of <w:p> paragraphs containing the supplied text.
    """
    # Build word/document.xml
    root = ElementTree.Element(f'{{{W_NS}}}document')
    body = ElementTree.SubElement(root, f'{{{W_NS}}}body')

    for text in paragraph_texts:
        p = ElementTree.SubElement(body, f'{{{W_NS}}}p')
        r = ElementTree.SubElement(p, f'{{{W_NS}}}r')
        t = ElementTree.SubElement(r, f'{{{W_NS}}}t')
        t.text = text

    xml_bytes = ElementTree.tostring(root, xml_declaration=True, encoding='UTF-8')

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, 'w', zipfile.ZIP_DEFLATED) as zf:
        zf.writestr('[Content_Types].xml', _CONTENT_TYPES)
        zf.writestr('_rels/.rels', _RELS)
        zf.writestr('word/_rels/document.xml.rels', _DOC_RELS)
        zf.writestr('word/document.xml', xml_bytes)

    return buf.getvalue()


_CONTENT_TYPES = b"""\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""

_RELS = b"""\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

_DOC_RELS = b"""\
<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""


class ParseQuestionDocxTest(TestCase):

    def _parse(self, lines: list[str]):
        data = _make_docx(lines)
        return parse_question_docx(io.BytesIO(data))

    # ------------------------------------------------------------------
    # MCQ
    # ------------------------------------------------------------------
    def test_mcq(self):
        lines = [
            'Q1. What is the capital of Nigeria?',
            'A. Lagos',
            'B. Abuja',
            'C. Port Harcourt',
            'D. Kano',
            'ANSWER: B',
            'DIFFICULTY: easy',
            'MARK: 2',
            'TOPIC: Geography',
        ]
        result = self._parse(lines)
        self.assertEqual(len(result['questions']), 1)
        q = result['questions'][0]
        self.assertEqual(q['body'], 'What is the capital of Nigeria?')
        self.assertEqual(q['question_type'], 'mcq')
        self.assertEqual(q['options'], ['Lagos', 'Abuja', 'Port Harcourt', 'Kano'])
        self.assertEqual(q['correct_answer'], 'Abuja')
        self.assertEqual(q['difficulty'], 'easy')
        self.assertEqual(q['mark'], 2)
        self.assertEqual(q['topic'], 'Geography')

    # ------------------------------------------------------------------
    # True / False
    # ------------------------------------------------------------------
    def test_true_false(self):
        lines = [
            'Q1. The earth is flat.',
            'ANSWER: False',
        ]
        result = self._parse(lines)
        q = result['questions'][0]
        self.assertEqual(q['body'], 'The earth is flat.')
        self.assertEqual(q['question_type'], 'true_false')
        self.assertIsNone(q['options'])
        self.assertEqual(q['correct_answer'], 'False')
        self.assertEqual(q['difficulty'], 'medium')
        self.assertEqual(q['mark'], 1)

    # ------------------------------------------------------------------
    # Short answer
    # ------------------------------------------------------------------
    def test_short_answer(self):
        lines = [
            'Q1. Name the largest planet in our solar system.',
            'ANSWER: Jupiter',
            'DIFFICULTY: hard',
            'MARK: 3',
        ]
        result = self._parse(lines)
        q = result['questions'][0]
        self.assertEqual(q['body'], 'Name the largest planet in our solar system.')
        self.assertEqual(q['question_type'], 'short_answer')
        self.assertIsNone(q['options'])
        self.assertEqual(q['correct_answer'], 'Jupiter')
        self.assertEqual(q['difficulty'], 'hard')
        self.assertEqual(q['mark'], 3)

    # ------------------------------------------------------------------
    # Header metadata
    # ------------------------------------------------------------------
    def test_header_metadata(self):
        lines = [
            'EXAM: Mid-Term Test',
            'SUBJECT: Mathematics',
            'CLASS: SS1',
            'DURATION: 45',
            'PASS_MARK: 50',
            'INSTRUCTIONS: Answer all questions.',
            '---',
            'Q1. What is 2 + 2?',
            'A. 3',
            'B. 4',
            'C. 5',
            'D. 6',
            'ANSWER: B',
        ]
        result = self._parse(lines)
        meta = result['metadata']
        self.assertEqual(meta['title'], 'Mid-Term Test')
        self.assertEqual(meta['subject'], 'Mathematics')
        self.assertEqual(meta['duration_mins'], 45)
        self.assertEqual(meta['pass_mark'], 50)
        self.assertEqual(meta['instructions'], 'Answer all questions.')

    # ------------------------------------------------------------------
    # Multi-question with separator
    # ------------------------------------------------------------------
    def test_multiple_questions(self):
        lines = [
            'Q1. First question?',
            'ANSWER: Yes',
            '---',
            'Q2. Second question?',
            'ANSWER: No',
            '---',
            'Q3. Third question?',
            'ANSWER: Maybe',
        ]
        result = self._parse(lines)
        self.assertEqual(len(result['questions']), 3)

    # ------------------------------------------------------------------
    # No questions
    # ------------------------------------------------------------------
    def test_no_questions_raises(self):
        lines = ['Just some text', 'without any questions']
        with self.assertRaises(ValueError) as ctx:
            self._parse(lines)
        self.assertIn('No questions', str(ctx.exception))

    # ------------------------------------------------------------------
    # MCQ without ANSWER
    # ------------------------------------------------------------------
    def test_mcq_missing_answer_raises(self):
        lines = [
            'Q1. Which colour is the sky?',
            'A. Red',
            'B. Blue',
            'C. Green',
            'D. Yellow',
        ]
        with self.assertRaises(ValueError) as ctx:
            self._parse(lines)
        self.assertIn('ANSWER', str(ctx.exception))

    # ------------------------------------------------------------------
    # Invalid difficulty
    # ------------------------------------------------------------------
    def test_invalid_difficulty_raises(self):
        lines = [
            'Q1. A question.',
            'ANSWER: True',
            'DIFFICULTY: extreme',
        ]
        with self.assertRaises(ValueError) as ctx:
            self._parse(lines)
        self.assertIn('DIFFICULTY', str(ctx.exception))

    # ------------------------------------------------------------------
    # Invalid MARK
    # ------------------------------------------------------------------
    def test_invalid_mark_raises(self):
        lines = [
            'Q1. A question.',
            'ANSWER: 42',
            'MARK: notanumber',
        ]
        with self.assertRaises(ValueError) as ctx:
            self._parse(lines)
        self.assertIn('MARK', str(ctx.exception))

    # ------------------------------------------------------------------
    # MCQ answer not in A B C D
    # ------------------------------------------------------------------
    def test_mcq_invalid_answer_raises(self):
        lines = [
            'Q1. Pick one.',
            'A. Opt 1',
            'B. Opt 2',
            'C. Opt 3',
            'D. Opt 4',
            'ANSWER: E',
        ]
        with self.assertRaises(ValueError) as ctx:
            self._parse(lines)
        self.assertIn('A, B, C, D', str(ctx.exception))

    # ------------------------------------------------------------------
    # Metadata defaults
    # ------------------------------------------------------------------
    def test_metadata_defaults(self):
        lines = ['Q1. A question?', 'ANSWER: True']
        result = self._parse(lines)
        meta = result['metadata']
        self.assertIsNone(meta['title'])
        self.assertIsNone(meta['subject'])
        self.assertIsNone(meta['duration_mins'])
        self.assertIsNone(meta['pass_mark'])
        self.assertIsNone(meta['instructions'])


class UploadQuestionsAPITest(TestCase):

    def setUp(self):
        from django.contrib.auth import get_user_model
        from apps.schools.models import School

        self.client = APIClient()
        self.school = School.objects.create(name='Test School', subdomain='test')
        user_model = get_user_model()
        self.user = user_model.objects.create_user(
            username='admin', email='admin@test.com', password='pass1234',
            school=self.school, role='school_admin',
        )
        self.client.force_authenticate(user=self.user)

        self.exam = Exam.objects.create(
            school=self.school, title='Test Exam',
            duration_mins=30, pass_mark=40,
        )

    def _make_docx_bytes(self, lines):
        return _make_docx(lines)

    def test_upload_questions(self):
        lines = [
            'Q1. What is 2+2?',
            'A. 3',
            'B. 4',
            'C. 5',
            'D. 6',
            'ANSWER: B',
            '---',
            'Q2. The sky is blue.',
            'ANSWER: True',
        ]
        docx_bytes = self._make_docx_bytes(lines)
        url = reverse('exam-upload-questions', kwargs={'pk': self.exam.pk})
        uploaded = SimpleUploadedFile('questions.docx', docx_bytes, content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        resp = self.client.post(url, {'questions_file': uploaded}, format='multipart')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['created'], 2)
        self.assertFalse(data['replaced'])
        self.assertEqual(data['errors'], [])
        self.assertEqual(self.exam.question_set.count(), 2)

    def test_upload_questions_replace(self):
        # Pre-populate one existing question
        Question.objects.create(
            school=self.school, exam=self.exam,
            body='Old question', question_type='short_answer',
            correct_answer='yes',
        )
        lines = [
            'Q1. New question?',
            'ANSWER: Yes',
        ]
        docx_bytes = self._make_docx_bytes(lines)
        url = reverse('exam-upload-questions', kwargs={'pk': self.exam.pk})
        uploaded = SimpleUploadedFile('questions.docx', docx_bytes, content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        resp = self.client.post(
            url + '?replace=true',
            {'questions_file': uploaded},
            format='multipart',
        )
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['created'], 1)
        self.assertTrue(data['replaced'])
        self.assertEqual(self.exam.question_set.count(), 1)
        self.assertEqual(self.exam.question_set.first().body, 'New question?')

    def test_upload_invalid_file_type(self):
        url = reverse('exam-upload-questions', kwargs={'pk': self.exam.pk})
        uploaded = SimpleUploadedFile('not_a_docx.txt', b'not a docx', content_type='text/plain')
        resp = self.client.post(url, {'questions_file': uploaded}, format='multipart')
        self.assertEqual(resp.status_code, 400)
        self.assertIn('.docx', resp.json()['error'])

    def test_upload_no_file(self):
        url = reverse('exam-upload-questions', kwargs={'pk': self.exam.pk})
        resp = self.client.post(url, {}, format='multipart')
        self.assertEqual(resp.status_code, 400)

    def test_template_download(self):
        url = reverse('exam-question-template')
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(
            resp['Content-Type'],
            'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        )
        self.assertIn('cbt_question_template', resp['Content-Disposition'])


class CBTStartSubmitTest(TestCase):

    def setUp(self):
        from django.contrib.auth import get_user_model
        from apps.schools.models import School
        from apps.students.models import Student
        from apps.classes.models import Class

        self.client = APIClient()
        self.school = School.objects.create(name='Test School', subdomain='cbt-test')
        user_model = get_user_model()

        # Student user
        self.student_user = user_model.objects.create_user(
            username='student1', email='student@test.com', password='pass1234',
            school=self.school, role='student',
        )
        cls = Class.objects.create(school=self.school, name='SS1A', year_group='SS1', arm='A')
        self.student = Student.objects.create(
            school=self.school, user=self.student_user,
            admission_no='STU001', full_name='Student One',
            class_group=cls, status='active',
        )

        # Admin user for setup
        self.admin_user = user_model.objects.create_user(
            username='admin2', email='admin2@test.com', password='pass1234',
            school=self.school, role='school_admin',
        )

        self.exam = Exam.objects.create(
            school=self.school, title='CBT Test',
            duration_mins=30, pass_mark=40, status='published',
            shuffle_questions=True, shuffle_options=True,
        )

        # Create questions via admin client
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(user=self.admin_user)

        self.q1 = Question.objects.create(
            school=self.school, exam=self.exam,
            body='What is 2+2?', question_type='mcq',
            options=['3', '4', '5', '6'], correct_answer='B',
            mark=2, difficulty='easy',
        )
        self.q2 = Question.objects.create(
            school=self.school, exam=self.exam,
            body='The sky is green.', question_type='true_false',
            correct_answer='False', mark=1,
        )
        self.q3 = Question.objects.create(
            school=self.school, exam=self.exam,
            body='Name the capital of France.', question_type='short_answer',
            correct_answer='Paris', mark=3,
        )
        self.all_q_ids = [str(self.q1.id), str(self.q2.id), str(self.q3.id)]

    # ── Start ────────────────────────────────────────────────────

    def test_start_exam(self):
        self.client.force_authenticate(user=self.student_user)
        url = reverse('exam-start', kwargs={'pk': self.exam.pk})
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn('session_id', data)
        self.assertEqual(data['time_remaining'], 1800)  # 30 min
        self.assertEqual(len(data['questions']), 3)
        # No correct_answer in response
        for q in data['questions']:
            self.assertNotIn('correct_answer', q)

    def test_start_exam_not_published(self):
        self.exam.status = 'draft'
        self.exam.save()
        self.client.force_authenticate(user=self.student_user)
        url = reverse('exam-start', kwargs={'pk': self.exam.pk})
        resp = self.client.post(url)
        self.assertEqual(resp.status_code, 403)

    def test_start_exam_double_submit_blocked(self):
        self.client.force_authenticate(user=self.student_user)
        url = reverse('exam-start', kwargs={'pk': self.exam.pk})
        resp1 = self.client.post(url)
        self.assertEqual(resp1.status_code, 200)
        session_id = resp1.json()['session_id']

        # Submit
        submit_url = reverse('examsession-submit', kwargs={'pk': session_id})
        resp_submit = self.client.post(submit_url, {'answers': {}}, format='json')
        self.assertEqual(resp_submit.status_code, 200)

        # Try start again
        resp2 = self.client.post(url)
        self.assertEqual(resp2.status_code, 403)
        self.assertIn('already submitted', resp2.json()['error'])

    # ── Questions ─────────────────────────────────────────────────

    def test_questions_endpoint(self):
        self.client.force_authenticate(user=self.student_user)
        # First start
        start_url = reverse('exam-start', kwargs={'pk': self.exam.pk})
        self.client.post(start_url)
        # Then fetch questions
        q_url = reverse('exam-questions', kwargs={'pk': self.exam.pk})
        resp = self.client.get(q_url)
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data['questions']), 3)
        for q in data['questions']:
            self.assertNotIn('correct_answer', q)

    def test_questions_without_start(self):
        self.client.force_authenticate(user=self.student_user)
        url = reverse('exam-questions', kwargs={'pk': self.exam.pk})
        resp = self.client.get(url)
        self.assertEqual(resp.status_code, 403)

    # ── Submit ────────────────────────────────────────────────────

    def test_submit_exam(self):
        self.client.force_authenticate(user=self.student_user)
        start_url = reverse('exam-start', kwargs={'pk': self.exam.pk})
        start_resp = self.client.post(start_url)
        session_id = start_resp.json()['session_id']

        answers = {
            str(self.q1.id): '4',  # option text matching correct_answer 'B' → resolved to '4'
            str(self.q2.id): 'False',
            str(self.q3.id): 'paris',  # lowercase should still match
        }
        submit_url = reverse('examsession-submit', kwargs={'pk': session_id})
        resp = self.client.post(submit_url, {'answers': answers}, format='json')
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data['score'], 6.0)  # 2 + 1 + 3
        self.assertEqual(data['total_marks'], 6.0)
        self.assertTrue(data['passed'])
        self.assertFalse(data['late_submission'])

    def test_submit_wrong_answers(self):
        self.client.force_authenticate(user=self.student_user)
        start_url = reverse('exam-start', kwargs={'pk': self.exam.pk})
        start_resp = self.client.post(start_url)
        session_id = start_resp.json()['session_id']

        answers = {
            str(self.q1.id): '3',  # wrong (option text, correct is '4')
            str(self.q2.id): 'True',  # wrong
            str(self.q3.id): 'London',  # wrong
        }
        submit_url = reverse('examsession-submit', kwargs={'pk': session_id})
        resp = self.client.post(submit_url, {'answers': answers}, format='json')
        data = resp.json()
        self.assertEqual(data['score'], 0.0)
        self.assertFalse(data['passed'])

    def test_submit_double_submission_blocked(self):
        self.client.force_authenticate(user=self.student_user)
        start_url = reverse('exam-start', kwargs={'pk': self.exam.pk})
        start_resp = self.client.post(start_url)
        session_id = start_resp.json()['session_id']

        submit_url = reverse('examsession-submit', kwargs={'pk': session_id})
        self.client.post(submit_url, {'answers': {}}, format='json')
        # Second submit
        resp = self.client.post(submit_url, {'answers': {}}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_submit_wrong_user(self):
        # Another student tries to submit someone else's session
        from django.contrib.auth import get_user_model
        from apps.students.models import Student
        from apps.classes.models import Class

        other_user = get_user_model().objects.create_user(
            username='student2', email='student2@test.com', password='pass1234',
            school=self.school, role='student',
        )
        cls = Class.objects.get(school=self.school)
        Student.objects.create(
            school=self.school, user=other_user,
            admission_no='STU002', full_name='Student Two',
            class_group=cls, status='active',
        )

        self.client.force_authenticate(user=self.student_user)
        start_url = reverse('exam-start', kwargs={'pk': self.exam.pk})
        start_resp = self.client.post(start_url)
        session_id = start_resp.json()['session_id']

        self.client.force_authenticate(user=other_user)
        submit_url = reverse('examsession-submit', kwargs={'pk': session_id})
        resp = self.client.post(submit_url, {'answers': {}}, format='json')
        self.assertEqual(resp.status_code, 404)

    # ── Perform create ────────────────────────────────────────────

    def test_direct_session_create_returns_405(self):
        self.client.force_authenticate(user=self.student_user)
        url = reverse('examsession-list')
        resp = self.client.post(url, {'exam': self.exam.pk}, format='json')
        self.assertEqual(resp.status_code, 405)
