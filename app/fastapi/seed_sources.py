"""합성 데이터 생성 — 명세서 S03/S04/S09/S11/S18 기반.

기획서 §14 합성 데이터 전략에 따라 5개 소스 테이블에 데이터를 생성한다.
기획서 시나리오 A("골드 회원 객실 매출")를 지원하는 일관된 데이터를 만든다.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database import engine, SessionLocal, Base
from app.models import PmsReservation, PmsStay, CrmMember, CrmMemberGradeHistory, CrmCustomerMap
from datetime import date, timedelta
import random

random.seed(20260727)

# 테이블 생성
Base.metadata.create_all(engine, tables=[
    PmsReservation.__table__, PmsStay.__table__,
    CrmMember.__table__, CrmMemberGradeHistory.__table__, CrmCustomerMap.__table__,
])

db = SessionLocal()

# 1. CRM 회원 20명
grades = ["BASIC", "SILVER", "GOLD", "VIP"]
grade_weights = [8, 6, 4, 2]
members = []
for i in range(1, 21):
    grade = random.choices(grades, weights=grade_weights)[0]
    member_no = f"MEM-{i:08d}"
    members.append({
        "member_no": member_no,
        "membership_grade": grade,
        "points_balance": random.randint(0, 50000),
        "member_status": "ACTIVE",
    })

for m in members:
    db.add(CrmMember(**m))

# 2. 등급 이력 (반개구간 [valid_from, valid_to))
for m in members:
    join_date = date(2025, random.randint(1, 12), random.randint(1, 28))
    # 초기 등급 BASIC
    db.add(CrmMemberGradeHistory(
        grade_history_id=f"GH-{m['member_no']}-1",
        member_no=m["member_no"],
        grade_code="BASIC",
        valid_from=join_date.isoformat(),
        valid_to=None if m["membership_grade"] == "BASIC" else (join_date + timedelta(days=180)).isoformat(),
        change_reason_code="JOIN",
    ))
    # 승급 이력 (BASIC이 아닌 경우)
    if m["membership_grade"] != "BASIC":
        upgrade_date = join_date + timedelta(days=180)
        db.add(CrmMemberGradeHistory(
            grade_history_id=f"GH-{m['member_no']}-2",
            member_no=m["member_no"],
            grade_code=m["membership_grade"],
            valid_from=upgrade_date.isoformat(),
            valid_to=None,
            change_reason_code="UPGRADE",
        ))

# 3. Customer Map (member_no ↔ guest_id)
guest_ids = []
for m in members:
    guest_id = f"GUEST-{m['member_no'][-4:]}"
    guest_ids.append((m["member_no"], guest_id))
    db.add(CrmCustomerMap(
        map_id=f"MAP-{m['member_no']}",
        member_no=m["member_no"],
        pms_guest_id=guest_id,
        pos_customer_ref=f"POS-{m['member_no'][-4:]}",
    ))

# 4. PMS 예약 50건 (2026-07 월)
room_types = ["Grand Deluxe", "Vista Deluxe", "Grand Suite", "Executive Twin"]
statuses = ["CHECKED_OUT", "CHECKED_OUT", "CHECKED_OUT", "CANCELLED"]
for i in range(50):
    member_no, guest_id = random.choice(guest_ids)
    stay_day = random.randint(1, 28)
    stay_date = date(2026, 7, stay_day)
    revenue = random.randint(150000, 800000)
    status = random.choice(statuses)
    res_id = f"RES-2026-{i+1:04d}"
    db.add(PmsReservation(
        reservation_id=res_id,
        guest_id=guest_id,
        stay_date=stay_date.isoformat(),
        room_revenue=revenue,
        room_type=random.choice(room_types),
        status=status,
    ))
    # 체크아웃된 예약은 투숙 기록
    if status == "CHECKED_OUT":
        nights = random.randint(1, 4)
        db.add(PmsStay(
            stay_id=f"STAY-{res_id}",
            reservation_id=res_id,
            guest_id=guest_id,
            check_in=stay_date.isoformat(),
            check_out=(stay_date + timedelta(days=nights)).isoformat(),
            room_number=f"{random.randint(10,25)}{random.choice('ABCDEFGH')}",
        ))

db.commit()

# 검증
for model in [PmsReservation, PmsStay, CrmMember, CrmMemberGradeHistory, CrmCustomerMap]:
    count = db.query(model).count()
    print(f"{model.__tablename__}: {count} rows")

db.close()
print("Done.")
