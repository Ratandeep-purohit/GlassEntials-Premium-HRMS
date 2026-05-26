import calendar
import csv
import io
from datetime import datetime

from django.db import transaction
from django.db.models import Q

from leaves.models import Holiday, HolidayCalendar, Location


class HolidayCalendarService:
    DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y")
    HOLIDAY_TYPES = {"NATIONAL", "REGIONAL", "COMPANY", "OPTIONAL"}

    @classmethod
    def holiday_dates_for_period(
        cls,
        *,
        organization,
        start_date,
        end_date,
        employee=None,
        include_optional=False,
        paid_only=False,
    ):
        holidays = Holiday.objects.filter(
            organization=organization,
            calendar__isnull=False,
            date__range=(start_date, end_date),
        )
        if not include_optional:
            holidays = holidays.filter(is_optional=False)
        if paid_only:
            holidays = holidays.filter(is_paid=True)

        work_location = (getattr(employee, "work_location", "") or "").strip()
        if work_location:
            holidays = holidays.filter(
                Q(calendar__is_default=True)
                | Q(calendar__branch="")
                | Q(calendar__branch__iexact=work_location)
            )
        else:
            holidays = holidays.filter(
                Q(calendar__is_default=True)
                | Q(calendar__branch="")
                | Q(calendar__branch__isnull=True)
            )

        return set(holidays.values_list("date", flat=True))

    @classmethod
    @transaction.atomic
    def create_calendar(cls, *, organization, user, name, year, branch="", location_id=None, is_default=False):
        name = (name or "").strip()
        year = cls._parse_year(year)
        if not name:
            raise ValueError("Calendar name is required.")

        if HolidayCalendar.objects.filter(organization=organization, name=name, year=year).exists():
            raise ValueError("A holiday calendar with this name already exists for the selected year.")

        location = cls._get_location(organization, location_id)
        if is_default:
            cls._clear_default(organization, year)

        return HolidayCalendar.objects.create(
            organization=organization,
            name=name,
            year=year,
            branch=(branch or "").strip(),
            location_fk=location,
            is_default=is_default,
            created_by=user,
        )

    @classmethod
    @transaction.atomic
    def copy_calendar(cls, *, organization, user, source_calendar_id, target_year, target_name="", make_default=False):
        target_year = cls._parse_year(target_year)
        source = HolidayCalendar.objects.get(id=source_calendar_id, organization=organization)
        target_name = (target_name or f"{source.name} {target_year}").strip()

        if HolidayCalendar.objects.filter(organization=organization, name=target_name, year=target_year).exists():
            raise ValueError("Target calendar already exists. Choose a different name.")

        if make_default:
            cls._clear_default(organization, target_year)

        target = HolidayCalendar.objects.create(
            organization=organization,
            name=target_name,
            year=target_year,
            branch=source.branch,
            location_fk=source.location_fk,
            is_default=make_default,
            created_by=user,
        )

        copied_count = 0
        for holiday in source.holidays.all().order_by("date", "name"):
            Holiday.objects.create(
                organization=organization,
                calendar=target,
                name=holiday.name,
                date=cls._same_month_day(holiday.date, target_year),
                location_fk=holiday.location_fk,
                holiday_type=holiday.holiday_type,
                is_paid=holiday.is_paid,
                is_optional=holiday.is_optional,
                created_by=user,
            )
            copied_count += 1

        return target, copied_count

    @classmethod
    @transaction.atomic
    def import_csv(cls, *, organization, user, calendar_id, uploaded_file):
        calendar_obj = HolidayCalendar.objects.get(id=calendar_id, organization=organization)
        if not uploaded_file:
            raise ValueError("Select a CSV file to import.")

        content = uploaded_file.read().decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(content))
        required = {"name", "date"}
        headers = {header.strip().lower() for header in (reader.fieldnames or [])}
        if not required.issubset(headers):
            raise ValueError("CSV must include name and date columns.")

        imported = 0
        errors = []
        for row_number, raw_row in enumerate(reader, start=2):
            row = {str(key).strip().lower(): (value or "").strip() for key, value in raw_row.items()}
            try:
                name = row.get("name", "")
                holiday_date = cls._parse_date(row.get("date"))
                if holiday_date.year != calendar_obj.year:
                    raise ValueError("date year must match the calendar year")

                holiday_type = cls._normalize_type(row.get("holiday_type") or row.get("type"))
                is_optional = cls._parse_bool(row.get("is_optional") or row.get("optional"))
                is_paid = cls._parse_bool(row.get("is_paid") or row.get("paid"), default=True)
                if holiday_type == "OPTIONAL":
                    is_optional = True

                cls.save_holiday(
                    organization=organization,
                    user=user,
                    calendar_id=calendar_obj.id,
                    holiday_id=None,
                    name=name,
                    holiday_date=holiday_date,
                    holiday_type=holiday_type,
                    is_paid=is_paid,
                    is_optional=is_optional,
                    location_id=row.get("location_id") or None,
                )
                imported += 1
            except Exception as exc:
                errors.append(f"Row {row_number}: {exc}")

        if errors:
            raise ValueError(" ".join(errors[:3]))

        return imported

    @classmethod
    @transaction.atomic
    def save_holiday(
        cls,
        *,
        organization,
        user,
        calendar_id,
        holiday_id,
        name,
        holiday_date,
        holiday_type,
        is_paid,
        is_optional,
        location_id=None,
    ):
        calendar_obj = HolidayCalendar.objects.get(id=calendar_id, organization=organization)
        name = (name or "").strip()
        if not name:
            raise ValueError("Holiday name is required.")

        holiday_date = cls._parse_date(holiday_date)
        if holiday_date.year != calendar_obj.year:
            raise ValueError("Holiday date must be inside the calendar year.")

        holiday_type = cls._normalize_type(holiday_type)
        if holiday_type == "OPTIONAL":
            is_optional = True

        location = cls._get_location(organization, location_id)

        if holiday_id:
            holiday = Holiday.objects.get(id=holiday_id, organization=organization, calendar=calendar_obj)
            holiday.name = name
            holiday.date = holiday_date
            holiday.holiday_type = holiday_type
            holiday.is_paid = bool(is_paid)
            holiday.is_optional = bool(is_optional)
            holiday.location_fk = location
            holiday.updated_by = user
            holiday.save()
            return holiday, False

        holiday, created = Holiday.objects.update_or_create(
            organization=organization,
            calendar=calendar_obj,
            name=name,
            date=holiday_date,
            defaults={
                "holiday_type": holiday_type,
                "is_paid": bool(is_paid),
                "is_optional": bool(is_optional),
                "location_fk": location,
                "updated_by": user,
            },
        )
        if created:
            holiday.created_by = user
            holiday.save(update_fields=["created_by"])
        return holiday, created

    @classmethod
    def _clear_default(cls, organization, year):
        HolidayCalendar.objects.filter(organization=organization, year=year, is_default=True).update(is_default=False)

    @classmethod
    def _get_location(cls, organization, location_id):
        if not location_id:
            return None
        return Location.objects.get(id=location_id, organization=organization)

    @classmethod
    def _parse_year(cls, year):
        try:
            parsed = int(year)
        except (TypeError, ValueError):
            raise ValueError("Enter a valid calendar year.")
        if parsed < 2000 or parsed > 2100:
            raise ValueError("Enter a valid calendar year.")
        return parsed

    @classmethod
    def _parse_date(cls, value):
        if hasattr(value, "year") and hasattr(value, "month") and hasattr(value, "day"):
            return value
        value = (value or "").strip()
        for date_format in cls.DATE_FORMATS:
            try:
                return datetime.strptime(value, date_format).date()
            except ValueError:
                continue
        raise ValueError("date must be YYYY-MM-DD, DD-MM-YYYY, DD/MM/YYYY, or MM/DD/YYYY")

    @classmethod
    def _normalize_type(cls, value):
        normalized = (value or "COMPANY").strip().upper().replace(" ", "_")
        if normalized in {"PUBLIC", "GENERAL"}:
            normalized = "COMPANY"
        if normalized not in cls.HOLIDAY_TYPES:
            raise ValueError("holiday type must be NATIONAL, REGIONAL, COMPANY, or OPTIONAL")
        return normalized

    @staticmethod
    def _parse_bool(value, default=False):
        if value in (None, ""):
            return default
        return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}

    @staticmethod
    def _same_month_day(source_date, target_year):
        try:
            return source_date.replace(year=target_year)
        except ValueError:
            last_day = calendar.monthrange(target_year, source_date.month)[1]
            return source_date.replace(year=target_year, day=last_day)
