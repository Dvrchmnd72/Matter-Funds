import datetime

from django.utils import timezone


def _as_local_date(date_value):
    if isinstance(date_value, datetime.datetime):
        if timezone.is_aware(date_value):
            return timezone.localdate(date_value)
        return date_value.date()
    return date_value


def _easter_sunday(year):
    """Return Gregorian Easter Sunday for the given year."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return datetime.date(year, month, day)


def _first_monday(year, month):
    current = datetime.date(year, month, 1)
    return current + datetime.timedelta(days=(7 - current.weekday()) % 7)


def _second_monday(year, month):
    return _first_monday(year, month) + datetime.timedelta(days=7)


def _observed_fixed_holiday(year, month, day):
    actual = datetime.date(year, month, day)
    if actual.weekday() == 5:
        return actual + datetime.timedelta(days=2)
    if actual.weekday() == 6:
        return actual + datetime.timedelta(days=1)
    return actual


def _christmas_boxing_holidays(year):
    christmas = datetime.date(year, 12, 25)
    boxing = datetime.date(year, 12, 26)
    holidays = {christmas, boxing}
    if christmas.weekday() == 5:  # Saturday: Christmas Monday, Boxing Tuesday
        holidays.update({datetime.date(year, 12, 27), datetime.date(year, 12, 28)})
    elif christmas.weekday() == 6:  # Sunday: Christmas Tuesday, Boxing Monday
        holidays.update({datetime.date(year, 12, 27), datetime.date(year, 12, 28)})
    elif boxing.weekday() == 5:  # Saturday: Boxing Monday
        holidays.add(datetime.date(year, 12, 28))
    elif boxing.weekday() == 6:  # Sunday: Boxing Tuesday
        holidays.add(datetime.date(year, 12, 28))
    return holidays


def nsw_public_holidays(year):
    easter = _easter_sunday(year)
    holidays = {
        datetime.date(year, 1, 1),
        _observed_fixed_holiday(year, 1, 1),
        datetime.date(year, 1, 26),
        _observed_fixed_holiday(year, 1, 26),
        easter - datetime.timedelta(days=2),  # Good Friday
        easter - datetime.timedelta(days=1),  # Easter Saturday
        easter,  # Easter Sunday
        easter + datetime.timedelta(days=1),  # Easter Monday
        datetime.date(year, 4, 25),  # Anzac Day (NSW does not generally add a weekday substitute)
        _second_monday(year, 6),  # King's Birthday
        _first_monday(year, 10),  # Labour Day
    }
    holidays.update(_christmas_boxing_holidays(year))
    return holidays


def nsw_bank_holidays(year):
    return {_first_monday(year, 8)}


def is_nsw_public_or_bank_holiday(date_value):
    date_value = _as_local_date(date_value)
    return date_value in nsw_public_holidays(date_value.year) or date_value in nsw_bank_holidays(date_value.year)


def is_nsw_working_day(date_value):
    date_value = _as_local_date(date_value)
    return date_value.weekday() < 5 and not is_nsw_public_or_bank_holiday(date_value)


def add_nsw_working_days(start_date, number_of_days):
    current = _as_local_date(start_date)
    added = 0
    while added < number_of_days:
        current += datetime.timedelta(days=1)
        if is_nsw_working_day(current):
            added += 1
    return current


def nsw_working_days_after(start_date, end_date):
    start_date = _as_local_date(start_date)
    end_date = _as_local_date(end_date) if end_date else None
    if not end_date or end_date <= start_date:
        return 0
    current = start_date
    days = 0
    while current < end_date:
        current += datetime.timedelta(days=1)
        if is_nsw_working_day(current):
            days += 1
    return days
