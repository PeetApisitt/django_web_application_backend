import logging
from django.core.exceptions import ValidationError, PermissionDenied
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from datetime import timedelta

from organization.models import DivisionRoleAssignment
from .models import (
    BookingRequest,
    BookingRequestItem,
    EmployeeBookingReservation,
)

logger = logging.getLogger(__name__)


@transaction.atomic
def submit_booking_request(request_id):
    try:
        booking_request = (
            BookingRequest.objects
            .select_for_update()
            .get(pk=request_id)
        )
    except BookingRequest.DoesNotExist:
        raise ValidationError("ไม่พบคำขอจองที่ระบุ")

    if booking_request.status != BookingRequest.Status.DRAFT:
        raise ValidationError("สามารถส่งคำขอได้เฉพาะรายการแบบร่าง")

    if not booking_request.booking_date:
        raise ValidationError("กรุณาระบุวันที่ต้องการใช้พนักงาน")

    # ปลดล็อกเงื่อนไขที่ห้ามแผนกเดียวกันออก เพื่อรองรับการจองใช้ภายใน
    is_internal_booking = (booking_request.requesting_division_id == booking_request.source_division_id)

    items = list(
        BookingRequestItem.objects
        .select_for_update()
        .filter(booking_request=booking_request)
        .order_by("personal_id")
    )

    if not items:
        raise ValidationError("กรุณาเพิ่มรายชื่อพนักงานก่อนส่งคำขอ")

    personal_ids = []
    for item in items:
        code = item.personal_id.strip()
        if not code:
            raise ValidationError("พบรายการที่ไม่ได้ระบุรหัสพนักงาน")
        personal_ids.append(code)

    if len(personal_ids) != len(set(personal_ids)):
        raise ValidationError("พบรหัสพนักงานซ้ำภายในคำขอเดียวกัน")

    start_date = booking_request.booking_date
    end_date = booking_request.end_date or start_date

    if end_date < start_date:
        raise ValidationError("วันสิ้นสุดการใช้งานต้องไม่ก่อนวันเริ่มต้น")

    delta = end_date - start_date
    booking_dates = [start_date + timedelta(days=i) for i in range(delta.days + 1)]

    for item, code in zip(items, personal_ids):
        for b_date in booking_dates:
            reservation, created = (
                EmployeeBookingReservation.objects.get_or_create(
                    personal_id=code,
                    booking_date=b_date,
                    defaults={"booking_request_item": item},
                )
            )

            if not created and reservation.booking_request_item_id != item.pk:
                raise ValidationError(
                    f"พนักงาน {code} ถูกจองแล้วในวันที่ {b_date}"
                )

        item.personal_id = code
        
        # หากเป็นการจองภายในแผนก ให้อนุมัติอัตโนมัติทันที
        if is_internal_booking:
            item.status = BookingRequestItem.Status.APPROVED
            item.reviewed_by = booking_request.requested_by
            item.reviewed_at = timezone.now()
            item.review_note = "จองใช้ภายในแผนก (อนุมัติอัตโนมัติ)"
        else:
            item.status = BookingRequestItem.Status.PENDING_REVIEW
            item.reviewed_by = None
            item.reviewed_at = None
            item.review_note = ""

        item.save(
            update_fields=[
                "personal_id",
                "status",
                "reviewed_by",
                "reviewed_at",
                "review_note",
            ]
        )

    # เปลี่ยนสถานะคำขอหลักตามประเภทการจอง
    if is_internal_booking:
        booking_request.status = BookingRequest.Status.APPROVED
        logger.info(f"BookingRequest [{booking_request.pk}] AUTO-APPROVED (Internal Booking by User [{booking_request.requested_by_id}])")
    else:
        booking_request.status = BookingRequest.Status.PENDING_REVIEW
        logger.info(f"BookingRequest [{booking_request.pk}] SUBMITTED by User [{booking_request.requested_by_id}]")

    booking_request.save(update_fields=["status", "updated_at"])

    return booking_request


@transaction.atomic
def evaluate_booking_request_status(request_id):
    try:
        booking_request = BookingRequest.objects.select_for_update().get(pk=request_id)
    except BookingRequest.DoesNotExist:
        return None

    if booking_request.status != BookingRequest.Status.PENDING_REVIEW:
        return booking_request

    items = list(booking_request.items.all())
    
    has_pending = False
    approved_count = 0
    rejected_count = 0

    for item in items:
        if item.status == BookingRequestItem.Status.PENDING_REVIEW:
            has_pending = True
            break
        elif item.status == BookingRequestItem.Status.ACCEPTED:
            approved_count += 1
        elif item.status == BookingRequestItem.Status.REJECTED:
            rejected_count += 1

    if has_pending:
        return booking_request

    if approved_count > 0 and rejected_count == 0:
        booking_request.status = BookingRequest.Status.APPROVED
    elif approved_count > 0 and rejected_count > 0:
        booking_request.status = BookingRequest.Status.PARTIALLY_APPROVED
    else:
        booking_request.status = BookingRequest.Status.REJECTED

    if approved_count > 0:
        booking_request.items.filter(
            status=BookingRequestItem.Status.ACCEPTED
        ).update(status=BookingRequestItem.Status.APPROVED)

    booking_request.save(update_fields=['status', 'updated_at'])
    logger.info(f"BookingRequest [{booking_request.pk}] AUTO-EVALUATED to status: {booking_request.status}")
    
    return booking_request


@transaction.atomic
def review_booking_item(item_id, reviewer, action, note=""):
    try:
        item = (
            BookingRequestItem.objects
            .select_for_update()
            .select_related("booking_request", "booking_request__source_division")
            .get(pk=item_id)
        )
    except BookingRequestItem.DoesNotExist:
        raise ValidationError("ไม่พบรายการพนักงานที่ต้องการพิจารณา")

    if item.status != BookingRequestItem.Status.PENDING_REVIEW:
        raise ValidationError("ไม่สามารถพิจารณารายการนี้ได้ (สถานะปัจจุบันไม่ถูกต้อง)")

    source_division = item.booking_request.source_division
    is_admin = DivisionRoleAssignment.objects.filter(
        user=reviewer,
        division=source_division,
        role=DivisionRoleAssignment.Role.ADMIN,
        is_active=True
    ).exists()

    if not is_admin:
        logger.warning(f"UNAUTHORIZED REVIEW ATTEMPT on Item [{item.pk}] by User [{reviewer.pk}]")
        raise PermissionDenied("คุณไม่มีสิทธิ์ในการพิจารณาคำขอของแผนกต้นสังกัดนี้")

    if action not in ["ACCEPT", "REJECT"]:
        raise ValidationError("การกระทำไม่ถูกต้อง (ต้องเป็น ACCEPT หรือ REJECT)")

    if action == "REJECT":
        if not note or not note.strip():
            raise ValidationError("กรุณาระบุหมายเหตุเมื่อทำการปฏิเสธพนักงาน")
        
        item.status = BookingRequestItem.Status.REJECTED
        EmployeeBookingReservation.objects.filter(booking_request_item=item).delete()
        
    elif action == "ACCEPT":
        item.status = BookingRequestItem.Status.ACCEPTED

    item.reviewed_by = reviewer
    item.reviewed_at = timezone.now()
    item.review_note = note.strip() if note else ""

    item.save(
        update_fields=[
            "status",
            "reviewed_by",
            "reviewed_at",
            "review_note",
        ]
    )

    logger.info(f"BookingItem [{item.pk}] {action} by Admin [{reviewer.pk}]")
    evaluate_booking_request_status(item.booking_request_id)
    return item


@transaction.atomic
def cancel_booking_request(request_id, requested_user):
    try:
        booking_request = BookingRequest.objects.select_for_update().get(pk=request_id)
    except BookingRequest.DoesNotExist:
        raise ValidationError("ไม่พบคำขอจองที่ระบุ")

    if booking_request.requested_by != requested_user:
        logger.warning(f"UNAUTHORIZED CANCEL ATTEMPT on Request [{booking_request.pk}] by User [{requested_user.pk}]")
        raise PermissionDenied("คุณไม่มีสิทธิ์ยกเลิกคำขอนี้ (ต้องเป็นผู้สร้างคำขอเท่านั้น)")

    if booking_request.status in [
        BookingRequest.Status.CANCELLED, 
        BookingRequest.Status.REJECTED
    ]:
        raise ValidationError(f"ไม่สามารถยกเลิกคำขอที่อยู่ในสถานะ '{booking_request.get_status_display()}' ได้")

    items = BookingRequestItem.objects.select_for_update().filter(booking_request=booking_request)

    # ลบรายการจองทั้งหมดของคำขอนี้ และอัปเดตสถานะรายชื่อพนักงานแบบรวดเดียว (Bulk Query)
    EmployeeBookingReservation.objects.filter(
        booking_request_item__booking_request=booking_request
    ).delete()
    items.update(status=BookingRequestItem.Status.CANCELLED)

    booking_request.status = BookingRequest.Status.CANCELLED
    booking_request.save(update_fields=['status', 'updated_at'])

    logger.info(f"BookingRequest [{booking_request.pk}] CANCELLED by User [{requested_user.pk}]")
    return booking_request


def get_accessible_booking_requests(user):
    base_qs = BookingRequest.objects.select_related(
        "requesting_division",
        "source_division",
        "requested_by",
    ).prefetch_related("items")

    if user.is_superuser:
        return base_qs.all()

    q_requested_by = Q(requested_by=user)
    user_managed_divisions = DivisionRoleAssignment.objects.filter(
        user=user,
        is_active=True,
        role__in=[DivisionRoleAssignment.Role.ADMIN, DivisionRoleAssignment.Role.DIRECTOR]
    ).values_list('division_id', flat=True)

    q_source_division = Q(source_division_id__in=user_managed_divisions)
    return base_qs.filter(q_requested_by | q_source_division).distinct()


def can_view_booking_request(user, request_id):
    try:
        booking_request = BookingRequest.objects.get(pk=request_id)
    except BookingRequest.DoesNotExist:
        return False

    if user.is_superuser:
        return True

    if booking_request.requested_by == user:
        return True

    is_manager = DivisionRoleAssignment.objects.filter(
        user=user,
        division=booking_request.source_division,
        role__in=[DivisionRoleAssignment.Role.ADMIN, DivisionRoleAssignment.Role.DIRECTOR],
        is_active=True
    ).exists()

    return is_manager
