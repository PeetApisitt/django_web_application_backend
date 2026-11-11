from django.db import models
from django.contrib.auth.models import AbstractUser

class User(AbstractUser):
    ranks = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        verbose_name="RANKS",
    )
    personal_id = models.CharField(
        max_length=30,
        unique=True,
        null=True,
        blank=True,
        verbose_name="PERSONAL_ID",
    )
    position = models.CharField(
        max_length=150,
        blank=True,
        null=True,
        verbose_name="ตำแหน่ง",
    )
    military_id = models.CharField(
        max_length=50,
        null=True,
        blank=True,
        verbose_name="MILITARY_ID",
    )
    class Meta:
        ordering = ["ranks"]