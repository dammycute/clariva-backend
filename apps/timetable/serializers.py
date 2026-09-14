from rest_framework import serializers
from apps.exams.models import TimeTable, TimeSlot


class TimeSlotSerializer(serializers.ModelSerializer):
    subject_name = serializers.SerializerMethodField()
    teacher_name = serializers.SerializerMethodField()

    class Meta:
        model = TimeSlot
        fields = '__all__'
        read_only_fields = ('timetable',)

    def get_subject_name(self, obj):
        return obj.subject.name if obj.subject else None

    def get_teacher_name(self, obj):
        return obj.teacher.get_full_name() if obj.teacher else None


class TimeTableSerializer(serializers.ModelSerializer):
    slots = TimeSlotSerializer(many=True, required=False)
    class_name = serializers.SerializerMethodField()

    class Meta:
        model = TimeTable
        fields = '__all__'
        read_only_fields = ('school',)

    def get_class_name(self, obj):
        return obj.class_group.name if obj.class_group else None

    def validate_slots(self, slots):
        if not slots:
            return slots
        teacher_periods = {}
        for slot in slots:
            teacher_id = slot.get('teacher')
            if not teacher_id:
                continue
            key = (slot['day'], slot['period'], teacher_id)
            if key in teacher_periods:
                raise serializers.ValidationError(
                    f'Teacher clashes on day {slot["day"]} period {slot["period"]}.'
                )
            teacher_periods[key] = True
        return slots

    def create(self, validated_data):
        slots_data = validated_data.pop('slots', [])
        tt = TimeTable.objects.create(**validated_data)
        for slot_data in slots_data:
            TimeSlot.objects.create(timetable=tt, **slot_data)
        return tt

    def update(self, instance, validated_data):
        slots_data = validated_data.pop('slots', None)
        for attr, val in validated_data.items():
            setattr(instance, attr, val)
        instance.save()
        if slots_data is not None:
            instance.slots.all().delete()
            for slot_data in slots_data:
                TimeSlot.objects.create(timetable=instance, **slot_data)
        return instance

    def to_representation(self, instance):
        rep = super().to_representation(instance)
        rep['slots'] = TimeSlotSerializer(instance.slots.all(), many=True).data
        return rep
