from rest_framework import serializers
from .models import School, GradingConfig, DEFAULT_GRADE_BOUNDARIES


class GradingConfigSerializer(serializers.ModelSerializer):
    class Meta:
        model = GradingConfig
        fields = '__all__'
        read_only_fields = ('school',)


class SchoolSerializer(serializers.ModelSerializer):
    grading_config = GradingConfigSerializer(read_only=True)

    class Meta:
        model = School
        fields = '__all__'
