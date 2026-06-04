from django.db import models
from apps.base.models import BaseUUIDModel

class State(BaseUUIDModel):
    name = models.CharField(max_length=100, unique=True)
    code = models.CharField(max_length=10, unique=True)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']

class LGA(BaseUUIDModel):
    name = models.CharField(max_length=100)
    state = models.ForeignKey(State, on_delete=models.CASCADE, related_name='lgas')

    def __str__(self):
        return f'{self.name}, {self.state.name}'

    class Meta:
        ordering = ['name']
        unique_together = ('name', 'state')
