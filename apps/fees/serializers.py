from rest_framework import serializers
from .models import FeeItem, FeeInvoice, FeeInvoiceItem


class FeeItemSerializer(serializers.ModelSerializer):
    class_name = serializers.SerializerMethodField()

    class Meta:
        model = FeeItem
        fields = '__all__'
        read_only_fields = ('school',)

    def validate(self, attrs):
        if attrs.get('class_group') and attrs.get('year_group'):
            raise serializers.ValidationError('Cannot set both a specific class and a year group.')
        return attrs

    def get_class_name(self, obj):
        if obj.year_group:
            return f'{obj.year_group} (All Arms)'
        if obj.class_group:
            return obj.class_group.name if obj.class_group else 'All Classes'
        return 'All Classes'


class FeeInvoiceItemSerializer(serializers.ModelSerializer):
    fee_name = serializers.SerializerMethodField()

    class Meta:
        model = FeeInvoiceItem
        fields = ['id', 'fee_item', 'fee_name', 'amount_due', 'amount_paid']

    def get_fee_name(self, obj):
        return obj.fee_item.name if obj.fee_item else None


class FeeInvoiceSerializer(serializers.ModelSerializer):
    student_name = serializers.SerializerMethodField()
    fee_name = serializers.SerializerMethodField()
    items = FeeInvoiceItemSerializer(many=True, required=False)

    class Meta:
        model = FeeInvoice
        fields = '__all__'
        read_only_fields = ('school',)

    def validate(self, attrs):
        fee_item = attrs.get('fee_item')
        if fee_item and fee_item.term:
            term = attrs.get('term')
            if term and term != fee_item.term:
                raise serializers.ValidationError(
                    f'Term "{term}" does not match fee item\'s term "{fee_item.term}".'
                )
        return attrs

    def get_student_name(self, obj):
        return obj.student.full_name if obj.student else None

    def get_fee_name(self, obj):
        return obj.fee_item.name if obj.fee_item else None

    def create(self, validated_data):
        items_data = validated_data.pop('items', [])
        invoice = FeeInvoice.objects.create(**validated_data)
        for item_data in items_data:
            FeeInvoiceItem.objects.create(invoice=invoice, **item_data)
        return invoice

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        # Always include items in output
        items = instance.items.all()
        rep['items'] = FeeInvoiceItemSerializer(items, many=True).data
        return rep
