from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from .models import User

@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("ข้อมูลบริษัท", {
            "fields": ( "personal_id", "military_id","ranks", "position"),
        }),
    )

    add_fieldsets = UserAdmin.add_fieldsets + (
        ("ข้อมูลบริษัท", {
            "fields": ( "personal_id", "military_id","ranks", "position"),
        }),
    )

    list_display = ("personal_id", "military_id","ranks", "first_name",  "email", "is_staff")
    list_display_links = ("personal_id", "military_id",)
    search_fields = UserAdmin.search_fields + ( "personal_id", "military_id","ranks")