from pathlib import Path
import pandas as pd
from django.core.management.base import BaseCommand
from django.db import transaction
from django.contrib.auth import get_user_model
from organization.models import Divisions, DivisionRoleAssignment

User = get_user_model()


class Command(BaseCommand):
    help = "นำเข้าข้อมูลกองงานและรายชื่อพนักงานจากไฟล์ data.xlsx (Sheet1)"

    def handle(self, *args, **options):
        base_dir = Path(__file__).resolve().parent.parent.parent.parent
        file_path = base_dir / "data" / "data.xlsx"

        if not file_path.exists():
            self.stdout.write(self.style.ERROR(f"ไม่พบไฟล์ที่: {file_path}"))
            return

        self.stdout.write(f"กำลังอ่านข้อมูลจาก {file_path} (Sheet1)...")

        # อ่านข้อมูลจาก Sheet1 และแปลงค่า NaN ทั้งหมดเป็น String ว่าง "" ทันที
        df = pd.read_excel(file_path, sheet_name="Sheet1", dtype=str).fillna("")

        with transaction.atomic():
            # ---------------------------------------------------------
            # ขั้นที่ 1: สร้าง Divisions จาก division_code และ division_name ที่ไม่ซ้ำกัน
            # ---------------------------------------------------------
            self.stdout.write("กำลังนำเข้าข้อมูลกองงาน (Divisions)...")
            df_divisions = df[["division_code", "division_name"]].drop_duplicates(
                subset=["division_code"]
            )
            division_map = {}

            for _, row in df_divisions.iterrows():
                div_code = str(row.get("division_code", "")).strip()
                div_name = str(row.get("division_name", "")).strip()

                if not div_code or div_code.lower() == "nan":
                    continue

                if div_name.lower() == "nan":
                    div_name = ""

                division_obj, _ = Divisions.objects.update_or_create(
                    code=div_code,
                    defaults={"name": div_name, "is_active": True},
                )
                division_map[div_code] = division_obj

            self.stdout.write(
                self.style.SUCCESS(f"บันทึกกองงานเรียบร้อย: {len(division_map)} รายการ")
            )

            # ---------------------------------------------------------
            # ขั้นที่ 2 & 3: สร้าง User และผูกสิทธิ์เข้ากับ Division (Role = USERS)
            # ---------------------------------------------------------
            self.stdout.write("กำลังนำเข้าข้อมูลพนักงานและผูกสิทธิ์ (Users & Role Assignments)...")
            imported_count = 0

            # ตรวจสอบว่าโมเดล User มีฟิลด์ position รองรับหรือไม่
            has_position_field = hasattr(User, "position")

            for _, row in df.iterrows():
                personal_id = str(row.get("personal_id", "")).strip()
                full_name = str(row.get("full_name", "")).strip()
                div_code = str(row.get("division_code", "")).strip()
                pos = str(row.get("position", "")).strip()
                ranks = str(row.get("ranks", "")).strip()
                military_id = str(row.get("military_id", "")).strip()
                raw_email = row.get("email", "") or row.get("e-mail", "")
                email = str(raw_email).strip()

                # ข้ามแถวที่ไม่มีรหัสพนักงาน
                if not personal_id or personal_id.lower() == "nan":
                    continue

                # ป้องกันกรณีค่ากลายเป็นคำว่า "nan" และต่อท้ายโดเมน @rtarf.mi.th สำหรับ email ที่มีค่า
                full_name = "" if full_name.lower() == "nan" else full_name
                user_email = "" if (not email or email.lower() == "nan") else f"{email}@rtarf.mi.th"
                user_position = "" if pos.lower() == "nan" else pos
                user_ranks = "" if ranks.lower() == "nan" else ranks
                user_military_id = "" if military_id.lower() == "nan" else military_id

                user_defaults = {
                    "username": personal_id,
                    "first_name": full_name,
                    "email": user_email,
                    "ranks": user_ranks,
                    "military_id": user_military_id,
                    "is_active": True,
                }

                # เพิ่ม position เข้า dict เฉพาะเมื่อ Model มีฟิลด์นี้รองรับ
                if has_position_field:
                    user_defaults["position"] = user_position

                # ขั้นที่ 2: บันทึกหรืออัปเดตข้อมูลผู้ใช้งาน (User)
                user, _ = User.objects.update_or_create(
                    personal_id=personal_id,
                    defaults=user_defaults,
                )

                # ขั้นที่ 3: ผูกสิทธิ์เข้ากับกองงานด้วย Role = USERS
                if div_code in division_map:
                    DivisionRoleAssignment.objects.update_or_create(
                        user=user,
                        division=division_map[div_code],
                        role=DivisionRoleAssignment.Role.USERS,
                        defaults={"is_active": True},
                    )

                imported_count += 1

            self.stdout.write(
                self.style.SUCCESS(f"นำเข้าข้อมูลพนักงานสำเร็จทั้งหมด {imported_count} รายการ")
            )
