from django.db import models

class FeeItem(models.Model):
    school = models.ForeignKey('schools.School', on_delete=models.CASCADE)
    name = models.CharField(max_length=255)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    class_group = models.ForeignKey('classes.Class', on_delete=models.SET_NULL, null=True, blank=True)
    year_group = models.CharField(max_length=20, null=True, blank=True, help_text='e.g. JSS1 — applies to all students in this year group regardless of arm')
    term = models.CharField(max_length=50, null=True, blank=True)
    academic_year = models.CharField(max_length=20, null=True, blank=True)
    is_mandatory = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.name

class FeeInvoice(models.Model):
    school = models.ForeignKey('schools.School', on_delete=models.CASCADE)
    student = models.ForeignKey('students.Student', on_delete=models.CASCADE)
    fee_item = models.ForeignKey(FeeItem, null=True, blank=True, on_delete=models.SET_NULL)
    amount_due = models.DecimalField(max_digits=12, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    status = models.CharField(max_length=20, default='unpaid')
    due_date = models.DateField(null=True, blank=True)
    payment_method = models.CharField(max_length=50, null=True, blank=True)
    payment_ref = models.CharField(max_length=255, null=True, blank=True)
    paid_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.student.full_name} — Invoice #{self.pk}'

class FeeInvoiceItem(models.Model):
    invoice = models.ForeignKey(FeeInvoice, on_delete=models.CASCADE, related_name='items')
    fee_item = models.ForeignKey(FeeItem, null=True, blank=True, on_delete=models.SET_NULL)
    amount_due = models.DecimalField(max_digits=12, decimal_places=2)
    amount_paid = models.DecimalField(max_digits=12, decimal_places=2, default=0)

    def __str__(self):
        return f'{self.fee_item.name if self.fee_item else "Deleted"}'
