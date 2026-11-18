"""Tests for the CBT flow: marking rules, who may sit an exam, autosave and resume,
closing by the clock, holding and releasing results, and who may change what."""
import io
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.classes.models import Class
from apps.grades.models import Grade
from apps.schools.models import School, GradingConfig
from apps.students.models import StudentProfile

from .marking import as_number, is_correct, mark_answers, normalise, same_answer
from .models import Exam, ExamAnswer, ExamSession, Question, Subject

User = get_user_model()


def _q(qtype, correct, options=None, accepted=None, mark=1):
    return SimpleNamespace(id='q', question_type=qtype, correct_answer=correct, options=options,
                           accepted_answers=accepted, mark=mark)


class MarkingRulesTest(SimpleTestCase):

    def test_text_ignores_case_spaces_and_a_final_full_stop(self):
        self.assertTrue(same_answer('  jupiter. ', 'Jupiter'))
        self.assertTrue(same_answer('new   york', 'New York'))

    def test_numbers_match_as_numbers(self):
        self.assertTrue(same_answer('1540', '1,540'))
        self.assertTrue(same_answer('₦1,500', '1500'))
        self.assertTrue(same_answer('N5,000', '5000'))
        self.assertTrue(same_answer('0.6', '3/5'))
        self.assertFalse(same_answer('1540', '1,541'))

    def test_non_numbers_are_not_numbers(self):
        self.assertIsNone(as_number('Jupiter'))
        self.assertIsNone(as_number(''))
        self.assertEqual(normalise(None), '')

    def test_short_answer_accepts_listed_alternatives(self):
        q = _q('short_answer', '3', accepted=['x = 3', 'x=3'])
        self.assertTrue(is_correct(q, '3'))
        self.assertTrue(is_correct(q, 'X = 3'))
        self.assertFalse(is_correct(q, '4'))

    def test_mcq_key_can_be_a_letter_or_the_option_text(self):
        by_letter = _q('mcq', 'B', options=['3', '4', '5', '6'])
        by_text = _q('mcq', '4', options=['3', '4', '5', '6'])
        for q in (by_letter, by_text):
            self.assertTrue(is_correct(q, '4'))
            self.assertFalse(is_correct(q, '3'))

    def test_true_false_and_blank_answers(self):
        q = _q('true_false', 'True')
        self.assertTrue(is_correct(q, 'true'))
        self.assertFalse(is_correct(q, 'False'))
        self.assertFalse(is_correct(q, ''))
        self.assertFalse(is_correct(q, None))

    def test_mark_answers_adds_up_marks(self):
        qs = [SimpleNamespace(id='1', question_type='short_answer', correct_answer='a', options=None, accepted_answers=None, mark=2),
              SimpleNamespace(id='2', question_type='short_answer', correct_answer='b', options=None, accepted_answers=None, mark=3)]
        self.assertEqual(mark_answers(qs, {'1': 'a', '2': 'x'}), (2, 5))


class CBTBase(TestCase):
    """A school with two classes, a teacher, a student in each class, and a published CA exam."""

    def setUp(self):
        self.school = School.objects.create(name='Queens', subdomain='queens-cbt')
        self.cls_a = Class.objects.create(school=self.school, name='SS1A', year_group='SS1', arm='A')
        self.cls_b = Class.objects.create(school=self.school, name='SS2A', year_group='SS2', arm='A')

        self.admin = self._user('admin', 'school_admin')
        self.teacher = self._user('teacher1', 'teacher')
        self.other_teacher = self._user('teacher2', 'teacher')
        self.bursar = self._user('bursar', 'bursary')
        self.student = self._student('stu1', self.cls_a, 'STU001')
        self.other_student = self._student('stu2', self.cls_b, 'STU002')

        # manual grading mode, so creating the subject does not create draft exams
        self.subject = Subject.objects.create(school=self.school, name='CBT Maths', year_group='SS1',
                                              teacher=self.teacher, grading_mode='manual')
        self.other_subject = Subject.objects.create(school=self.school, name='CBT English', year_group='SS1',
                                                    teacher=self.other_teacher, grading_mode='manual')
        self.exam = Exam.objects.create(
            school=self.school, title='Maths CA 1', subject=self.subject, duration_mins=30, pass_mark=40,
            status='published', component='ca1', term='First term', academic_year='2025/2026',
            release_mode='immediate')
        self.exam.classes.add(self.cls_a)

        self.q1 = Question.objects.create(school=self.school, exam=self.exam, body='2 + 2?', question_type='mcq',
                                          options=['3', '4', '5', '6'], correct_answer='B', mark=2)
        self.q2 = Question.objects.create(school=self.school, exam=self.exam, body='Sky is green.',
                                          question_type='true_false', correct_answer='False', mark=1)
        self.q3 = Question.objects.create(school=self.school, exam=self.exam, body='Cube of 3?',
                                          question_type='short_answer', correct_answer='27',
                                          accepted_answers=['twenty seven'], mark=3)
        self.right = {str(self.q1.id): '4', str(self.q2.id): 'False', str(self.q3.id): '27'}

    def _user(self, username, role):
        return User.objects.create_user(username=username, email=f'{username}@test.com', password='pass1234',
                                        school=self.school, role=role)

    def _student(self, username, cls, adm):
        user = self._user(username, 'student')
        StudentProfile.objects.create(school=self.school, user=user, admission_no=adm, class_group=cls,
                                      student_status='active')
        return user

    def client_for(self, user):
        c = APIClient()
        c.force_authenticate(user=user)
        return c

    def start(self, user=None, exam=None):
        return self.client_for(user or self.student).post(reverse('exam-start', kwargs={'pk': (exam or self.exam).pk}))


class WhoMaySitTest(CBTBase):

    def test_student_sees_only_exams_for_their_class(self):
        mine = self.client_for(self.student).get(reverse('exam-list')).json()
        theirs = self.client_for(self.other_student).get(reverse('exam-list')).json()
        mine = mine['results'] if isinstance(mine, dict) else mine
        theirs = theirs['results'] if isinstance(theirs, dict) else theirs
        self.assertEqual([e['id'] for e in mine], [str(self.exam.id)])
        self.assertEqual(theirs, [])

    def test_student_in_another_class_cannot_start(self):
        self.assertEqual(self.start(self.other_student).status_code, 404)

    def test_draft_exams_are_hidden_from_students(self):
        self.exam.status = 'draft'
        self.exam.save()
        self.assertEqual(self.start().status_code, 404)

    def test_list_shows_the_students_own_progress(self):
        self.start()
        body = self.client_for(self.student).get(reverse('exam-list')).json()
        rows = body['results'] if isinstance(body, dict) else body
        self.assertEqual(rows[0]['my_status'], 'in_progress')
        self.assertEqual(rows[0]['question_count'], 3)
        self.assertEqual(rows[0]['subject_name'], 'CBT Maths')

    def test_exam_without_classes_is_open_only_to_its_subjects_year_group(self):
        self.exam.classes.clear()
        self.assertEqual(self.start().status_code, 200)               # SS1 student, SS1 subject
        self.assertEqual(self.start(self.other_student).status_code, 404)

    def test_exam_with_no_class_and_no_subject_is_open_to_nobody(self):
        self.exam.classes.clear()
        self.exam.subject = None
        self.exam.save()
        self.assertEqual(self.start().status_code, 404)

    def test_double_click_on_start_makes_one_attempt(self):
        first = self.start().json()['session_id']
        second = self.start().json()['session_id']
        self.assertEqual(first, second)
        self.assertEqual(ExamSession.objects.filter(exam=self.exam, student=self.student).count(), 1)


class AutosaveAndResumeTest(CBTBase):

    def test_saved_answers_come_back_when_the_student_returns(self):
        data = self.start().json()
        sid = data['session_id']
        save = self.client_for(self.student).post(reverse('examsession-save', kwargs={'pk': sid}),
                                                  {'answers': {str(self.q1.id): '4'}}, format='json')
        self.assertEqual(save.status_code, 200)
        self.assertEqual(save.json()['saved'], 1)
        self.assertFalse(save.json()['closed'])

        again = self.start().json()                                   # power cut, open again
        self.assertEqual(again['session_id'], sid)
        self.assertEqual(again['saved_answers'], {str(self.q1.id): '4'})

    def test_saving_again_replaces_the_answer(self):
        sid = self.start().json()['session_id']
        url = reverse('examsession-save', kwargs={'pk': sid})
        c = self.client_for(self.student)
        c.post(url, {'answers': {str(self.q1.id): '3'}}, format='json')
        c.post(url, {'answers': {str(self.q1.id): '4'}}, format='json')
        self.assertEqual(ExamAnswer.objects.filter(session_id=sid).count(), 1)
        self.assertEqual(ExamAnswer.objects.get(session_id=sid).answer, '4')

    def test_unknown_question_ids_are_ignored(self):
        sid = self.start().json()['session_id']
        resp = self.client_for(self.student).post(reverse('examsession-save', kwargs={'pk': sid}),
                                                  {'answers': {'11111111-1111-1111-1111-111111111111': 'x'}}, format='json')
        self.assertEqual(resp.json()['saved'], 0)

    def test_submit_uses_saved_answers_when_none_are_sent(self):
        sid = self.start().json()['session_id']
        c = self.client_for(self.student)
        c.post(reverse('examsession-save', kwargs={'pk': sid}), {'answers': self.right}, format='json')
        resp = c.post(reverse('examsession-submit', kwargs={'pk': sid}), {}, format='json')
        self.assertEqual(resp.json()['score'], 6.0)

    def test_someone_elses_attempt_cannot_be_saved(self):
        sid = self.start().json()['session_id']
        resp = self.client_for(self.other_student).post(reverse('examsession-save', kwargs={'pk': sid}),
                                                        {'answers': {}}, format='json')
        self.assertEqual(resp.status_code, 404)

    def test_sending_submit_twice_returns_the_same_result(self):
        sid = self.start().json()['session_id']
        c = self.client_for(self.student)
        url = reverse('examsession-submit', kwargs={'pk': sid})
        first = c.post(url, {'answers': self.right}, format='json')
        second = c.post(url, {'answers': {}}, format='json')
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()['score'], second.json()['score'])


class CloseByTheClockTest(CBTBase):

    def _run_out_of_time(self, sid):
        ExamSession.objects.filter(pk=sid).update(deadline=timezone.now() - timedelta(minutes=10))

    def test_attempt_has_a_server_deadline(self):
        sid = self.start().json()['session_id']
        session = ExamSession.objects.get(pk=sid)
        self.assertAlmostEqual((session.deadline - session.started_at).total_seconds(), 1800, delta=1)

    def test_exam_end_time_shortens_the_deadline(self):
        self.exam.end_time = timezone.now() + timedelta(minutes=10)
        self.exam.save()
        sid = self.start().json()['session_id']
        remaining = (ExamSession.objects.get(pk=sid).deadline - timezone.now()).total_seconds()
        self.assertLess(remaining, 601)

    def test_overdue_attempt_is_submitted_with_its_saved_answers(self):
        sid = self.start().json()['session_id']
        self.client_for(self.student).post(reverse('examsession-save', kwargs={'pk': sid}),
                                           {'answers': self.right}, format='json')
        self._run_out_of_time(sid)
        resp = self.start()                                            # student comes back too late
        self.assertEqual(resp.status_code, 403)
        self.assertIn('ran out', resp.json()['error'])
        session = ExamSession.objects.get(pk=sid)
        self.assertEqual(session.status, 'submitted')
        self.assertTrue(session.auto_submitted)
        self.assertEqual(session.score, 6)

    def test_save_after_the_deadline_closes_the_attempt(self):
        sid = self.start().json()['session_id']
        self._run_out_of_time(sid)
        resp = self.client_for(self.student).post(reverse('examsession-save', kwargs={'pk': sid}),
                                                  {'answers': self.right}, format='json')
        self.assertTrue(resp.json()['closed'])
        self.assertEqual(ExamSession.objects.get(pk=sid).status, 'submitted')

    def test_opening_results_closes_overdue_attempts(self):
        sid = self.start().json()['session_id']
        self._run_out_of_time(sid)
        resp = self.client_for(self.teacher).get(reverse('examsession-list'), {'exam': str(self.exam.id)})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(ExamSession.objects.get(pk=sid).status, 'submitted')

    def test_close_exam_submits_everyone_still_sitting(self):
        sid = self.start().json()['session_id']
        resp = self.client_for(self.teacher).post(reverse('exam-close', kwargs={'pk': self.exam.pk}))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['attempts_submitted'], 1)
        self.exam.refresh_from_db()
        self.assertEqual(self.exam.status, 'closed')
        self.assertEqual(ExamSession.objects.get(pk=sid).status, 'submitted')

    def test_finalising_twice_changes_nothing(self):
        from . import cbt
        sid = self.start().json()['session_id']
        _, first = cbt.finalize_session(sid, answers=self.right)
        _, second = cbt.finalize_session(sid, answers={})
        self.assertTrue(first)
        self.assertFalse(second)
        self.assertEqual(ExamSession.objects.get(pk=sid).score, 6)


class HoldAndReleaseTest(CBTBase):

    def setUp(self):
        super().setUp()
        self.exam.release_mode = 'on_release'
        self.exam.save()
        # the school gives CA 1 a maximum of 20 marks
        GradingConfig.objects.create(school=self.school, components=[
            {'key': 'ca1', 'label': 'CA 1', 'max': 20, 'enabled': True},
            {'key': 'exam', 'label': 'Exam', 'max': 60, 'enabled': True}], grade_boundaries=[])

    def _submit(self, answers):
        sid = self.start().json()['session_id']
        return sid, self.client_for(self.student).post(reverse('examsession-submit', kwargs={'pk': sid}),
                                                       {'answers': answers}, format='json')

    def test_held_result_shows_no_score_and_writes_no_grade(self):
        _, resp = self._submit(self.right)
        body = resp.json()
        self.assertTrue(body['held'])
        self.assertNotIn('score', body)
        self.assertFalse(Grade.objects.filter(student=self.student).exists())

    def test_student_cannot_read_the_score_while_held(self):
        sid, _ = self._submit(self.right)
        row = self.client_for(self.student).get(reverse('examsession-detail', kwargs={'pk': sid})).json()
        self.assertIsNone(row['score'])
        self.assertFalse(row['result_visible'])

    def test_release_shows_scores_and_posts_grades_using_the_schools_maximum(self):
        sid, _ = self._submit(self.right)                              # full marks
        resp = self.client_for(self.teacher).post(reverse('exam-release', kwargs={'pk': self.exam.pk}))
        self.assertEqual(resp.json()['grades_posted'], 1)
        grade = Grade.objects.get(student=self.student, subject=self.subject)
        self.assertEqual(grade.ca1, Decimal('20.00'))                  # 6 of 6 marks, scaled to the school's 20
        row = self.client_for(self.student).get(reverse('examsession-detail', kwargs={'pk': sid})).json()
        self.assertEqual(row['score'], 6)

    def test_partial_score_is_scaled_to_the_maximum(self):
        self._submit({str(self.q1.id): '4'})                           # 2 of 6 marks
        self.client_for(self.teacher).post(reverse('exam-release', kwargs={'pk': self.exam.pk}))
        self.assertEqual(Grade.objects.get(student=self.student).ca1, Decimal('6.67'))

    def test_without_a_grading_setup_the_old_defaults_apply(self):
        GradingConfig.objects.all().delete()
        self._submit(self.right)
        self.client_for(self.teacher).post(reverse('exam-release', kwargs={'pk': self.exam.pk}))
        self.assertEqual(Grade.objects.get(student=self.student).ca1, Decimal('30.00'))

    def test_approved_grade_is_never_overwritten(self):
        Grade.objects.create(school=self.school, student=self.student, subject=self.subject,
                             term='First term', academic_year='2025/2026', ca1=Decimal('11'),
                             results_status='approved')
        self._submit(self.right)
        self.client_for(self.teacher).post(reverse('exam-release', kwargs={'pk': self.exam.pk}))
        self.assertEqual(Grade.objects.get(student=self.student).ca1, Decimal('11.00'))

    def test_late_submission_after_release_is_visible_at_once(self):
        self.client_for(self.teacher).post(reverse('exam-release', kwargs={'pk': self.exam.pk}))
        _, resp = self._submit(self.right)
        self.assertFalse(resp.json()['held'])
        self.assertEqual(resp.json()['score'], 6.0)


class WhoMayChangeWhatTest(CBTBase):

    def _new_exam_body(self, subject):
        return {'title': 'New exam', 'subject': str(subject.id), 'duration_mins': 20, 'pass_mark': 40,
                'component': 'ca2'}

    def test_teacher_can_create_an_exam_for_their_own_subject(self):
        resp = self.client_for(self.teacher).post(reverse('exam-list'), self._new_exam_body(self.subject), format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        self.assertEqual(resp.json()['status'], 'draft')
        self.assertEqual(resp.json()['release_mode'], 'on_release')   # CAs wait for release by default

    def test_teacher_cannot_create_an_exam_for_someone_elses_subject(self):
        resp = self.client_for(self.teacher).post(reverse('exam-list'), self._new_exam_body(self.other_subject), format='json')
        self.assertEqual(resp.status_code, 403)

    def test_bursar_cannot_create_exams(self):
        resp = self.client_for(self.bursar).post(reverse('exam-list'), self._new_exam_body(self.subject), format='json')
        self.assertEqual(resp.status_code, 403)

    def test_student_cannot_duplicate_an_exam(self):
        resp = self.client_for(self.student).post(reverse('exam-duplicate', kwargs={'pk': self.exam.pk}))
        self.assertEqual(resp.status_code, 403)

    def test_teacher_cannot_touch_another_teachers_questions(self):
        theirs = Exam.objects.create(school=self.school, title='English CA', subject=self.other_subject,
                                     duration_mins=20, status='draft')
        q = Question.objects.create(school=self.school, exam=theirs, body='?', question_type='short_answer',
                                    correct_answer='x')
        resp = self.client_for(self.teacher).patch(reverse('question-detail', kwargs={'pk': q.pk}),
                                                   {'correct_answer': 'y'}, format='json')
        self.assertIn(resp.status_code, (403, 404))
        q.refresh_from_db()
        self.assertEqual(q.correct_answer, 'x')

    def test_students_cannot_list_questions(self):
        resp = self.client_for(self.student).get(reverse('question-list'))
        self.assertEqual(resp.json()['results'] if isinstance(resp.json(), dict) else resp.json(), [])

    def test_questions_cannot_be_added_once_students_have_started(self):
        self.start()
        resp = self.client_for(self.teacher).post(reverse('question-list'), {
            'exam': str(self.exam.id), 'body': 'Late question', 'question_type': 'short_answer',
            'correct_answer': 'a', 'mark': 1}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_exam_with_attempts_cannot_be_deleted(self):
        self.start()
        resp = self.client_for(self.teacher).delete(reverse('exam-detail', kwargs={'pk': self.exam.pk}))
        self.assertEqual(resp.status_code, 400)
        self.assertTrue(Exam.objects.filter(pk=self.exam.pk).exists())

    def test_deleting_an_exam_removes_its_questions(self):
        draft = Exam.objects.create(school=self.school, title='Draft', subject=self.subject, duration_mins=10)
        Question.objects.create(school=self.school, exam=draft, body='?', question_type='short_answer', correct_answer='x')
        self.client_for(self.admin).delete(reverse('exam-detail', kwargs={'pk': draft.pk}))
        self.assertFalse(Question.objects.filter(body='?').exists())

    def test_mcq_needs_two_options(self):
        resp = self.client_for(self.teacher).post(reverse('question-list'), {
            'exam': str(Exam.objects.create(school=self.school, title='D', subject=self.subject, duration_mins=5).id),
            'body': 'Pick', 'question_type': 'mcq', 'options': ['only one'], 'correct_answer': 'A'}, format='json')
        self.assertEqual(resp.status_code, 400)


class PublishChecksTest(CBTBase):

    def setUp(self):
        super().setUp()
        self.draft = Exam.objects.create(school=self.school, title='Draft', subject=self.subject, duration_mins=20)

    def _publish(self):
        return self.client_for(self.teacher).patch(reverse('exam-detail', kwargs={'pk': self.draft.pk}),
                                                   {'status': 'published'}, format='json')

    def test_cannot_publish_without_questions(self):
        self.draft.classes.add(self.cls_a)
        self.assertEqual(self._publish().status_code, 400)

    def test_cannot_publish_without_classes(self):
        Question.objects.create(school=self.school, exam=self.draft, body='?', question_type='short_answer', correct_answer='x')
        resp = self._publish()
        self.assertEqual(resp.status_code, 400)
        self.assertIn('classes', str(resp.json()))

    def test_cannot_publish_with_end_before_start(self):
        Question.objects.create(school=self.school, exam=self.draft, body='?', question_type='short_answer', correct_answer='x')
        self.draft.classes.add(self.cls_a)
        now = timezone.now()
        resp = self.client_for(self.teacher).patch(reverse('exam-detail', kwargs={'pk': self.draft.pk}), {
            'status': 'published', 'start_time': (now + timedelta(hours=2)).isoformat(),
            'end_time': (now + timedelta(hours=1)).isoformat()}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_can_publish_when_ready(self):
        Question.objects.create(school=self.school, exam=self.draft, body='?', question_type='short_answer', correct_answer='x')
        self.draft.classes.add(self.cls_a)
        self.assertEqual(self._publish().status_code, 200)

    def test_old_status_words_are_translated(self):
        resp = self.client_for(self.admin).patch(reverse('exam-detail', kwargs={'pk': self.exam.pk}),
                                                 {'status': 'completed'}, format='json')
        self.assertEqual(resp.json()['status'], 'closed')

    def test_classes_must_belong_to_the_school(self):
        other = School.objects.create(name='Other', subdomain='other-cbt')
        foreign = Class.objects.create(school=other, name='SS1A', year_group='SS1', arm='A')
        resp = self.client_for(self.admin).patch(reverse('exam-detail', kwargs={'pk': self.draft.pk}),
                                                 {'classes': [str(foreign.id)]}, format='json')
        self.assertEqual(resp.status_code, 400)

    def test_choosing_classes_sets_the_first_as_the_older_single_class(self):
        self.client_for(self.admin).patch(reverse('exam-detail', kwargs={'pk': self.draft.pk}),
                                          {'classes': [str(self.cls_a.id)]}, format='json')
        self.draft.refresh_from_db()
        self.assertEqual(self.draft.class_group_id, self.cls_a.id)


class CopyAndResetTest(CBTBase):

    def test_copy_questions_from_another_exam(self):
        target = Exam.objects.create(school=self.school, title='Copy here', subject=self.subject, duration_mins=10)
        resp = self.client_for(self.teacher).post(reverse('exam-copy-questions', kwargs={'pk': target.pk}),
                                                  {'source_exam': str(self.exam.id)}, format='json')
        self.assertEqual(resp.json()['created'], 3)
        copied = Question.objects.filter(exam=target).get(body='Cube of 3?')
        self.assertEqual(copied.accepted_answers, ['twenty seven'])

    def test_duplicate_keeps_classes_and_accepted_answers(self):
        resp = self.client_for(self.teacher).post(reverse('exam-duplicate', kwargs={'pk': self.exam.pk}))
        self.assertEqual(resp.status_code, 201)
        new = Exam.objects.get(pk=resp.json()['id'])
        self.assertEqual(new.status, 'draft')
        self.assertEqual(list(new.classes.all()), [self.cls_a])
        self.assertEqual(Question.objects.filter(exam=new).count(), 3)

    def test_reset_lets_a_student_sit_again(self):
        sid = self.start().json()['session_id']
        self.client_for(self.student).post(reverse('examsession-submit', kwargs={'pk': sid}), {'answers': {}}, format='json')
        self.assertEqual(self.start().status_code, 403)
        resp = self.client_for(self.teacher).post(reverse('examsession-reset', kwargs={'pk': sid}))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.start().status_code, 200)

    def test_student_cannot_reset(self):
        sid = self.start().json()['session_id']
        resp = self.client_for(self.student).post(reverse('examsession-reset', kwargs={'pk': sid}))
        self.assertEqual(resp.status_code, 403)

    def test_results_list_only_shows_the_chosen_exam(self):
        other = Exam.objects.create(school=self.school, title='Other', subject=self.subject, duration_mins=10,
                                    status='published')
        other.classes.add(self.cls_a)
        Question.objects.create(school=self.school, exam=other, body='?', question_type='short_answer', correct_answer='x')
        self.start()
        self.start(exam=other)
        body = self.client_for(self.teacher).get(reverse('examsession-list'), {'exam': str(self.exam.id)}).json()
        rows = body['results'] if isinstance(body, dict) else body
        self.assertEqual({r['exam'] for r in rows}, {str(self.exam.id)})


class TemplateFileTest(CBTBase):

    def test_template_download_opens_in_word_tools(self):
        from docx import Document
        resp = self.client_for(self.admin).get(reverse('exam-question-template'))
        self.assertEqual(resp.status_code, 200)
        doc = Document(io.BytesIO(b''.join(resp.streaming_content)))      # python-docx rejected the old file
        self.assertTrue(any('ACCEPT' in p.text for p in doc.paragraphs))
        self.assertTrue(any(p.text.startswith('Q1.') for p in doc.paragraphs))

    def test_accept_line_is_read_for_short_answers(self):
        from .parsers import parse_question_docx
        from .tests import _make_docx
        data = _make_docx(['Q1. Name the planet.', 'ANSWER: Jupiter', 'ACCEPT: The planet Jupiter | Jupiter planet', 'MARK: 2'])
        q = parse_question_docx(io.BytesIO(data))['questions'][0]
        self.assertEqual(q['accepted_answers'], ['The planet Jupiter', 'Jupiter planet'])
