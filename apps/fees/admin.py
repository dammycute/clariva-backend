from django.contrib import admin
from .models import FeeItem, FeeInvoice, FeeInvoiceItem


@admin.register(FeeItem)
class FeeItemAdmin(admin.ModelAdmin):
    list_display = ('name', 'school', 'amount', 'class_group', 'year_group', 'term', 'academic_year', 'is_mandatory')
    search_fields = ('name', 'school__name')
    list_filter = ('is_mandatory', 'school', 'term', 'academic_year')


@admin.register(FeeInvoice)
class FeeInvoiceAdmin(admin.ModelAdmin):
    list_display = ('student', 'fee_item', 'amount_due', 'amount_paid', 'status', 'due_date', 'paid_at')
    search_fields = ('student__first_name', 'student__last_name', 'payment_ref')
    list_filter = ('status', 'school', 'due_date')


@admin.register(FeeInvoiceItem)
class FeeInvoiceItemAdmin(admin.ModelAdmin):
    list_display = ('invoice', 'fee_item', 'amount_due', 'amount_paid')
    search_fields = ('fee_item__name',)
