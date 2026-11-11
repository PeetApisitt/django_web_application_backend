from typing import List, Optional
from ninja import NinjaAPI, ModelSchema, Schema
from ninja.security import django_auth
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError, PermissionDenied
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from datetime import date
from django.db import transaction
from organization.models import Divisions, DivisionRoleAssignment
from .models import BookingRequest, BookingRequestItem
from .services import (
    get_accessible_booking_requests,
    can_view_booking_request,
    submit_booking_request,
    review_booking_item,
    cancel_booking_request
)

User = get_user_model()

# ประกาศ API Instance และบังคับให้ต้อง Login (อิง Session จากระบบ Django)
api = NinjaAPI(title="Employee Booking API", version="1.0.0", auth=django_auth)


# ==========================================
# 1. Schemas (สำหรับกำหนดหน้าตาข้อมูล JSON)
# ==========================================
class DivisionSchema(ModelSchema):
    class Meta:
        model = Divisions
        fields = ['id', 'code', 'name']


class UserRoleSchema(Schema):
    division: DivisionSchema
    role: str


class UserOutSchema(ModelSchema):
    full_name: str

    class Meta:
        model = User
        fields = ['id', 'username', 'personal_id', 'first_name', 'position']

    @staticmethod
    def resolve_full_name(obj):
        return obj.get_full_name() or obj.first_name or obj.username


class CurrentUserSchema(ModelSchema):
    full_name: str
    roles: List[UserRoleSchema] = []

    class Meta:
        model = User
        fields = [
            'id',
            'username',
            'personal_id',
            'first_name',
            'email',
            'position',
            'is_superuser',
        ]

    @staticmethod
    def resolve_full_name(obj):
        return obj.get_full_name() or obj.first_name or obj.username

    @staticmethod
    def resolve_roles(obj):
        return [
            {"division": assignment.division, "role": assignment.role}
            for assignment in obj.division_role_assignments.all()
            if assignment.is_active
        ]


class EmployeeOutSchema(ModelSchema):
    full_name: str
    divisions: List[DivisionSchema] = []

    class Meta:
        model = User
        fields = ['id', 'username', 'personal_id', 'first_name', 'email', 'position']

    @staticmethod
    def resolve_full_name(obj):
        return obj.get_full_name() or obj.first_name or obj.username

    @staticmethod
    def resolve_divisions(obj):
        return [
            assignment.division
            for assignment in obj.division_role_assignments.all()
            if assignment.is_active
        ]


class BookingItemSchema(ModelSchema):
    class Meta:
        model = BookingRequestItem
        fields = ['id', 'personal_id', 'employee_name_snapshot', 'status', 'review_note']


class BookingRequestSchema(ModelSchema):
    requesting_division: DivisionSchema
    source_division: DivisionSchema
    requested_by: UserOutSchema
    items: List[BookingItemSchema] = []  # ฝังข้อมูลพนักงานเข้าไปในคำขอหลัก

    class Meta:
        model = BookingRequest
        fields = [
            'id',
            'requesting_division',
            'source_division',
            'requested_by',
            'purpose',
            'booking_date',
            'end_date',
            'status',
        ]


class ReviewActionSchema(Schema):
    action: str
    note: str = ""


class MessageSchema(Schema):
    message: str
    status: Optional[str] = None


class ErrorSchema(Schema):
    error: str


class CreateItemIn(Schema):
    personal_id: str
    employee_name_snapshot: str


class CreateBookingIn(Schema):
    requesting_division_id: int
    source_division_id: int
    purpose: str
    booking_date: date
    end_date: Optional[date] = None
    items: List[CreateItemIn]


# ==========================================
# 2. Auth & Master Data Endpoints (สำหรับ React UI)
# ==========================================
@api.get("/auth/me/", response=CurrentUserSchema)
def get_current_user(request):
    """ดึงข้อมูลผู้ใช้ที่กำลัง Login อยู่ พร้อมสิทธิ์ประจำกองงาน"""
    active_assignments = DivisionRoleAssignment.objects.filter(
        is_active=True
    ).select_related("division")
    user = (
        User.objects.prefetch_related(
            Prefetch("division_role_assignments", queryset=active_assignments)
        )
        .get(pk=request.user.pk)
    )
    return user


@api.get("/divisions/", response=List[DivisionSchema])
def list_divisions(request):
    """ดึงรายชื่อกองงาน/แผนกทั้งหมดที่เปิดใช้งาน (สำหรับ Dropdown)"""
    return Divisions.objects.filter(is_active=True).order_by("code")


@api.get("/employees/", response=List[EmployeeOutSchema])
def list_employees(request, division_id: Optional[int] = None):
    """ดึงรายชื่อพนักงานทั้งหมด (สามารถกรองตาม division_id ได้สำหรับ Dropdown)"""
    active_assignments = DivisionRoleAssignment.objects.filter(
        is_active=True
    ).select_related("division")

    qs = (
        User.objects.filter(is_active=True)
        .exclude(personal_id__isnull=True)
        .exclude(personal_id="")
        .prefetch_related(
            Prefetch("division_role_assignments", queryset=active_assignments)
        )
        .order_by("personal_id")
    )

    if division_id is not None:
        qs = qs.filter(
            division_role_assignments__division_id=division_id,
            division_role_assignments__is_active=True,
        ).distinct()

    return qs


# ==========================================
# 3. Booking Endpoints (เส้นทาง API สำหรับการจอง)
# ==========================================
@api.get("/bookings/", response=List[BookingRequestSchema])
def list_bookings(request):
    """ดึงรายการคำขอทั้งหมดที่ผู้ใช้มีสิทธิ์มองเห็น"""
    return get_accessible_booking_requests(request.user)


@api.get("/bookings/{request_id}/", response={200: BookingRequestSchema, 403: ErrorSchema, 404: ErrorSchema})
def get_booking_detail(request, request_id: int):
    """ดูรายละเอียดคำขอรายตัว"""
    if not can_view_booking_request(request.user, request_id):
        return 403, {"error": "คุณไม่มีสิทธิ์เข้าถึงคำขอนี้"}

    booking = get_object_or_404(
        BookingRequest.objects.select_related(
            "requesting_division",
            "source_division",
            "requested_by",
        ).prefetch_related("items"),
        pk=request_id,
    )
    return 200, booking


@api.post("/bookings/{request_id}/submit/", response={200: MessageSchema, 400: ErrorSchema})
def submit_booking(request, request_id: int):
    """ส่งคำขอยืมพนักงาน"""
    try:
        result = submit_booking_request(request_id)
        return 200, {"message": "ส่งคำขอสำเร็จ", "status": result.status}
    except ValidationError as e:
        return 400, {"error": str(e.message if hasattr(e, 'message') else e)}


@api.post("/bookings/items/{item_id}/review/", response={200: MessageSchema, 400: ErrorSchema, 403: ErrorSchema})
def review_item(request, item_id: int, payload: ReviewActionSchema):
    """แอดมินพิจารณารายชื่อพนักงาน (ระบุ action เป็น 'ACCEPT' หรือ 'REJECT')"""
    try:
        result = review_booking_item(item_id, request.user, payload.action, payload.note)
        return 200, {"message": f"ทำรายการ {payload.action} สำเร็จ", "status": result.status}
    except PermissionDenied as e:
        return 403, {"error": str(e)}
    except ValidationError as e:
        return 400, {"error": str(e.message if hasattr(e, 'message') else e)}


@api.delete("/bookings/{request_id}/cancel/", response={200: MessageSchema, 400: ErrorSchema, 403: ErrorSchema})
def cancel_booking(request, request_id: int):
    """ยกเลิกคำขอโดยผู้สร้าง"""
    try:
        result = cancel_booking_request(request_id, request.user)
        return 200, {"message": "ยกเลิกคำขอสำเร็จ", "status": result.status}
    except PermissionDenied as e:
        return 403, {"error": str(e)}
    except ValidationError as e:
        return 400, {"error": str(e.message if hasattr(e, 'message') else e)}


@api.post("/bookings/", response={201: MessageSchema, 400: ErrorSchema})
@transaction.atomic
def create_booking(request, payload: CreateBookingIn):
    """สร้างคำขอยืมพนักงานใหม่ (ระบบจะบันทึกเป็นฉบับร่าง DRAFT อัตโนมัติ)"""
    try:
        if payload.end_date and payload.end_date < payload.booking_date:
            return 400, {"error": "วันสิ้นสุดการใช้งานต้องไม่ก่อนวันเริ่มต้น"}
        booking = BookingRequest.objects.create(
            requesting_division_id=payload.requesting_division_id,
            source_division_id=payload.source_division_id,
            requested_by=request.user,
            purpose=payload.purpose,
            booking_date=payload.booking_date,
            end_date=payload.end_date,
            status=BookingRequest.Status.DRAFT
        )

        for item in payload.items:
            BookingRequestItem.objects.create(
                booking_request=booking,
                personal_id=item.personal_id,
                employee_name_snapshot=item.employee_name_snapshot,
                status=BookingRequestItem.Status.DRAFT
            )
        return 201, {"message": f"สร้างคำขอแบบร่างสำเร็จ (ID: {booking.id})", "status": booking.status}
    except Exception as e:
        return 400, {"error": str(e)}
