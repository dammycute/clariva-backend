from rest_framework import serializers
from .models import State, LGA

class StateSerializer(serializers.ModelSerializer):
    class Meta:
        model = State
        fields = ('id', 'name', 'code')

class LGASerializer(serializers.ModelSerializer):
    class Meta:
        model = LGA
        fields = ('id', 'name', 'state')
