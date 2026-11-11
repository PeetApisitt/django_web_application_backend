from django.contrib import admin
from .models import Divisions, DivisionRoleAssignment

@admin.register(Divisions)
class DivisionsAdmin(admin.ModelAdmin):
    list_display = ("code", "name", "is_active")
    search_fields = ("code", "name")
    list_filter = ("is_active",)

@admin.register(DivisionRoleAssignment)
class DivisionRoleAssignmentAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "division",
        "role",
        "is_active",
        "created_at",
    )

    list_filter = ("division", "role", "is_active")

    search_fields = (
        "user__username",
        "user__personal_id",
        "division__code",
        "division__name",
    )