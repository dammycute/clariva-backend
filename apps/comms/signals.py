from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone

from apps.attendance.models import Attendance
from apps.exams.models import ExamSession
from apps.fees.models import FeeInvoice
from .models import Notification


@receiver(post_save, sender=Attendance)
def attendance_notification(sender, instance, created, **kwargs):
    if not created or not instance.student or not instance.student.user:
        return
    Notification.objects.create(
        school=instance.school,
        recipient=instance.student.user,
        notif_type='attendance',
        title='Attendance Recorded',
        message=f'Your attendance for {instance.date} was marked as {instance.status}.',
    )


@receiver(post_save, sender=ExamSession)
def exam_notification(sender, instance, **kwargs):
    if not instance.student or not instance.student.user:
        return
    if instance.status == 'submitted':
        Notification.objects.create(
            school=instance.school,
            recipient=instance.student.user,
            notif_type='exam',
            title='Exam Submitted',
            message=f'Your exam "{instance.exam.title}" has been submitted. Score: {instance.score}/{instance.total_marks}',
            link=f'/student/exams',
        )


@receiver(post_save, sender=FeeInvoice)
def fee_notification(sender, instance, **kwargs):
    if not instance.student or not instance.student.user:
        return
    action = 'created' if kwargs.get('created') else 'updated'
    Notification.objects.create(
        school=instance.school,
        recipient=instance.student.user,
        notif_type='fee',
        title=f'Fee Invoice {action.title()}',
        message=f'Invoice for {instance.fee_item.name if instance.fee_item else "fee"} — ₦{instance.amount_due:,.2f}',
        link=f'/student/fees',
    )
