from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models


class BookingRequest(models.Model):

    class Status(models.TextChoices):
        DRAFT = "draft", "แบบร่าง"
        PENDING_REVIEW = "pending_review", "รอแอดมินพิจารณา"
        PENDING_SIGNATURE = "pending_signature", "รอหัวหน้าแผนกลงนาม"
        APPROVED = "approved", "อนุมัติครบตามคำขอ"
        PARTIALLY_APPROVED = "partially_approved", "อนุมัติบางรายชื่อ"
        REJECTED = "rejected", "ปฏิเสธคำขอ"
        CANCELLED = "cancelled", "ยกเลิก"

    requesting_division = models.ForeignKey(
        "organization.Divisions",
        on_delete=models.PROTECT,
        related_name="outgoing_booking_requests",
        verbose_name="แผนกผู้ขอ",
    )

    source_division = models.ForeignKey(
        "organization.Divisions",
        on_delete=models.PROTECT,
        related_name="incoming_booking_requests",
        verbose_name="แผนกต้นสังกัดพนักงาน",
    )

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="created_booking_requests",
        verbose_name="ผู้สร้างคำขอ",
    )

    purpose = models.TextField(
        verbose_name="เหตุผลในการขอใช้พนักงาน",
    )

    booking_date = models.DateField(
        verbose_name="วันเริ่มต้นใช้งาน",
    )
    end_date = models.DateField(
        verbose_name="วันสิ้นสุดการใช้งาน",
        null=True,
        blank=True,
    )

    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.DRAFT,
        verbose_name="สถานะคำขอ",
    )

    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="approved_booking_requests",
        verbose_name="ผู้อนุมัติ (หัวหน้าแผนก)",
    )

    approved_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="วันที่อนุมัติ",
    )

    #approval_note = models.TextField(
    #    blank=True,
    #    verbose_name="หมายเหตุการอนุมัติ",
    #)

    #signature_text = models.CharField(
    #    max_length=255,
    #    blank=True,
    #    verbose_name="หลักฐานลายมือชื่ออิเล็กทรอนิกส์",
    #)

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="วันที่สร้างคำขอ",
    )

    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="วันที่แก้ไขล่าสุด",
    )

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "คำขอยืมพนักงาน"
        verbose_name_plural = "คำขอยืมพนักงาน"

    def clean(self):
        super().clean()
        if self.end_date and self.end_date < self.booking_date:
            raise ValidationError("วันสิ้นสุดการใช้งานต้องไม่ก่อนวันเริ่มต้น")
        # ปลดล็อกเงื่อนไขที่ห้าม requesting_division == source_division ออก เพื่อให้จองภายในแผนกได้

    def __str__(self):
        return (
            f"คำขอ #{self.pk} "
            f"{self.requesting_division} "
            f"ยืมจาก {self.source_division}"
        )


class BookingRequestItem(models.Model):

    class Status(models.TextChoices):
        DRAFT = "draft", "แบบร่าง"
        PENDING_REVIEW = "pending_review", "รอแอดมินพิจารณา"
        ACCEPTED = "accepted", "แอดมินยอมรับ"
        REJECTED = "rejected", "แอดมินปฏิเสธ"
        APPROVED = "approved", "อนุมัติแล้ว"
        CANCELLED = "cancelled", "ยกเลิก"

    booking_request = models.ForeignKey(
        BookingRequest,
        on_delete=models.CASCADE,
        related_name="items",
        verbose_name="คำขอ",
    )

    personal_id = models.CharField(
        max_length=30,
        db_index=True,
        verbose_name="รหัสพนักงาน",
    )

    employee_name_snapshot = models.CharField(
        max_length=150,
        verbose_name="ชื่อพนักงาน ณ เวลาที่ขอ",
    )

    status = models.CharField(
        max_length=30,
        choices=Status.choices,
        default=Status.DRAFT,
        verbose_name="สถานะรายชื่อ",
    )

    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reviewed_booking_items",
        verbose_name="ผู้พิจารณารายชื่อ",
    )

    reviewed_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name="วันที่พิจารณา",
    )

    review_note = models.TextField(
        blank=True,
        verbose_name="หมายเหตุการพิจารณา",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="วันที่เพิ่มรายชื่อ",
    )

    class Meta:
        ordering = ["personal_id"]
        verbose_name = "รายชื่อในคำขอ"
        verbose_name_plural = "รายชื่อในคำขอ"
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "booking_request",
                    "personal_id",
                ],
                name="uniq_employee_per_booking_request",
            ),
        ]

    def __str__(self):
        return f"{self.personal_id} - {self.employee_name_snapshot}"


class EmployeeBookingReservation(models.Model):

    booking_request_item = models.ForeignKey( # เปลี่ยนจาก OneToOneField
        BookingRequestItem,
        on_delete=models.CASCADE,
        related_name="reservations",
        verbose_name="รายการจอง",
    )   

    personal_id = models.CharField(
        max_length=30,
        verbose_name="รหัสพนักงาน",
    )

    booking_date = models.DateField(
        verbose_name="วันที่ถูกจอง",
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="วันที่สร้างรายการจอง",
    )

    class Meta:
        ordering = ["booking_date", "personal_id"]
        verbose_name = "รายการกันสิทธิ์การจอง"
        verbose_name_plural = "รายการกันสิทธิ์การจอง"
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "personal_id",
                    "booking_date",
                ],
                name="uniq_employee_booking_date",
            ),
        ]

    def __str__(self):
        return f"{self.personal_id} - {self.booking_date}"