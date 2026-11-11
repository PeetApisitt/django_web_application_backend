
from django.contrib import admin

from .models import (
    BookingRequest,
    BookingRequestItem,
    EmployeeBookingReservation,
)

class BookingRequestItemInline(admin.TabularInline):

    model = BookingRequestItem

    extra = 1

    fields = (
        "personal_id",
        "employee_name_snapshot",
        "status",
        "reviewed_by",
        "reviewed_at",
        "review_note",
    )

    readonly_fields = (
        "status",
        "reviewed_by",
        "reviewed_at",
        "review_note",
    )

    def get_readonly_fields(self, request, obj=None):

        if obj and obj.status != BookingRequest.Status.DRAFT:
            return self.fields

        return self.readonly_fields

    def has_add_permission(self, request, obj=None):

        if obj and obj.status != BookingRequest.Status.DRAFT:
            return False

        return True

    def has_delete_permission(self, request, obj=None):

        if obj and obj.status != BookingRequest.Status.DRAFT:
            return False

        return True


@admin.register(BookingRequest)
class BookingRequestAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "requesting_division",
        "source_division",
        "booking_date",
        "end_date",
        "status",
        "requested_by",
        "created_at",
    )

    list_filter = (
        "booking_date",
        "status",
        "requesting_division",
        "source_division",
    )

    search_fields = (
        "requesting_division__code",
        "requesting_division__name",
        "source_division__code",
        "source_division__name",
        "requested_by__username",
        "purpose",
    )

    readonly_fields = (
        "status",
        "created_at",
        "updated_at",
    )

    inlines = [
        BookingRequestItemInline,
    ]

    def get_readonly_fields(self, request, obj=None):

        if obj and obj.status != BookingRequest.Status.DRAFT:

            return (
                "requesting_division",
                "source_division",
                "requested_by",
                "purpose",
                "booking_date",
                "end_date",
                "status",
                "created_at",
                "updated_at",
            )

        return self.readonly_fields


@admin.register(BookingRequestItem)
class BookingRequestItemAdmin(admin.ModelAdmin):

    list_display = (
        "id",
        "booking_request",
        "personal_id",
        "employee_name_snapshot",
        "status",
        "reviewed_by",
        "reviewed_at",
    )

    list_filter = (
        "status",
    )

    search_fields = (
        "personal_id",
        "employee_name_snapshot",
        "booking_request__purpose",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(EmployeeBookingReservation)
class EmployeeBookingReservationAdmin(admin.ModelAdmin):

    list_display = (
        "personal_id",
        "booking_date",
        "booking_request_item",
        "created_at",
    )

    list_filter = (
        "booking_date",
    )

    search_fields = (
        "personal_id",
        "booking_request_item__employee_name_snapshot",
    )

    readonly_fields = (
        "booking_request_item",
        "personal_id",
        "booking_date",
        "created_at",
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
