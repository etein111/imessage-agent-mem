# time_metadata_builder.py
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Tuple
import re

from dateutil.relativedelta import relativedelta


# =========================
# ISO helpers
# =========================

def _parse_iso_dt(iso_str: str) -> datetime:
    return datetime.fromisoformat(iso_str)

def _iso_seconds(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")

def _epoch_seconds(dt: datetime) -> int:
    # dt may be aware (recommended). datetime.timestamp() returns seconds since epoch in UTC.
    return int(dt.timestamp())


# =========================
# boundary helpers
# =========================

def _start_of_day(dt: datetime) -> datetime:
    return dt.replace(hour=0, minute=0, second=0, microsecond=0)

def _end_of_day(dt: datetime) -> datetime:
    return dt.replace(hour=23, minute=59, second=59, microsecond=0)

def _start_of_week(dt: datetime) -> datetime:
    return _start_of_day(dt - timedelta(days=dt.weekday()))  # Monday

def _end_of_week(dt: datetime) -> datetime:
    return _end_of_day(_start_of_week(dt) + timedelta(days=6))

def _start_of_month(dt: datetime) -> datetime:
    return dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

def _end_of_month(dt: datetime) -> datetime:
    nm = _start_of_month(dt) + relativedelta(months=1)
    return (nm - timedelta(seconds=1)).replace(microsecond=0)

def _start_of_year(dt: datetime) -> datetime:
    return dt.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)

def _end_of_year(dt: datetime) -> datetime:
    ny = dt.replace(year=dt.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    return (ny - timedelta(seconds=1)).replace(microsecond=0)

def _fallback_day(ref: datetime) -> Tuple[str, str]:
    return _iso_seconds(_start_of_day(ref)), _iso_seconds(_end_of_day(ref))


# =========================
# Chinese numeral parsing
# =========================

_CN_DIGIT = {
    "零": 0, "〇": 0,
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9,
}

def _cn_to_int(s: str) -> Optional[int]:
    """支持：阿拉伯数字、单字、一到九、十/十一/二十/二十三 等"""
    if not s:
        return None
    s = s.strip()
    if s.isdigit():
        return int(s)
    if s in _CN_DIGIT:
        return _CN_DIGIT[s]
    if "十" in s:
        left, *rest = s.split("十")
        right = rest[0] if rest else ""
        tens = 1 if left == "" else _CN_DIGIT.get(left)
        if tens is None:
            return None
        ones = 0
        if right:
            if right.isdigit():
                ones = int(right)
            else:
                ones = _CN_DIGIT.get(right)
                if ones is None:
                    return None
        return tens * 10 + ones
    return None

def _cn_month_to_int(m: str) -> Optional[int]:
    """三月/十一月/3月 -> 3/11/3"""
    m = m.strip()
    if m.endswith("月"):
        m = m[:-1]
    val = _cn_to_int(m)
    if val is None:
        return None
    if 1 <= val <= 12:
        return val
    return None


# =========================
# CN time expression -> absolute range
# =========================

WEEKDAY_MAP = {"一": 0, "二": 1, "三": 2, "四": 3, "五": 4, "六": 5, "日": 6, "天": 6}

def _parse_time_range_cn(time_expression: str, reference_time: datetime) -> Tuple[str, str]:
    """
    中文相对/绝对时间表达 -> 输出绝对时间区间(ts_start, ts_end)，ISO seconds
    解析不了就回退到 reference_time 当天范围（不炸）
    """
    if not time_expression or not time_expression.strip():
        return _fallback_day(reference_time)

    t = re.sub(r"\s+", "", time_expression.strip())
    ref = reference_time

    # A) 今年/去年/明年 + 月份（核心：去年三月）
    m = re.fullmatch(r"(去年|今年|明年)([0-9一二两三四五六七八九十]+)月", t)
    if m:
        which, mon_raw = m.group(1), m.group(2)
        mon = _cn_month_to_int(mon_raw)
        if mon is None:
            return _fallback_day(ref)
        year = ref.year + (-1 if which == "去年" else (1 if which == "明年" else 0))
        d = ref.replace(year=year, month=mon, day=1)
        return _iso_seconds(_start_of_month(d)), _iso_seconds(_end_of_month(d))

    # 2025年三月 / 2025年3月
    m = re.fullmatch(r"((19|20)\d{2})年([0-9一二两三四五六七八九十]+)月", t)
    if m:
        year = int(m.group(1))
        mon = _cn_month_to_int(m.group(3))
        if mon is None:
            return _fallback_day(ref)
        d = ref.replace(year=year, month=mon, day=1)
        return _iso_seconds(_start_of_month(d)), _iso_seconds(_end_of_month(d))

    # 仅月份：三月 / 3月（默认指最近一次该月份，偏过去）
    m = re.fullmatch(r"([0-9一二两三四五六七八九十]+)月", t)
    if m:
        mon = _cn_month_to_int(m.group(1))
        if mon is None:
            return _fallback_day(ref)
        d = ref.replace(year=ref.year, month=mon, day=1)
        if d > ref:
            d = d.replace(year=ref.year - 1)
        return _iso_seconds(_start_of_month(d)), _iso_seconds(_end_of_month(d))

    # B) 今天/昨天/前天/明天/后天（按日粒度）
    fixed_days = {
        "今天": 0,
        "昨日": -1, "昨天": -1, "昨晚": -1,
        "前天": -2,
        "明天": 1, "明晚": 1,
        "后天": 2,
    }
    if t in fixed_days:
        d = ref + timedelta(days=fixed_days[t])
        return _iso_seconds(_start_of_day(d)), _iso_seconds(_end_of_day(d))

    # C) 上上周/上周/本周/下周
    if t in ("上上周", "上上星期"):
        d = ref - timedelta(weeks=2)
        return _iso_seconds(_start_of_week(d)), _iso_seconds(_end_of_week(d))
    if t in ("上周", "上星期"):
        d = ref - timedelta(weeks=1)
        return _iso_seconds(_start_of_week(d)), _iso_seconds(_end_of_week(d))
    if t in ("本周", "这周", "这星期", "本星期"):
        return _iso_seconds(_start_of_week(ref)), _iso_seconds(_end_of_week(ref))
    if t in ("下周", "下星期"):
        d = ref + timedelta(weeks=1)
        return _iso_seconds(_start_of_week(d)), _iso_seconds(_end_of_week(d))

    # D) 上月/本月/下月
    if t in ("上月", "上个月"):
        d = ref + relativedelta(months=-1)
        return _iso_seconds(_start_of_month(d)), _iso_seconds(_end_of_month(d))
    if t in ("本月", "这个月", "这月"):
        return _iso_seconds(_start_of_month(ref)), _iso_seconds(_end_of_month(ref))
    if t in ("下月", "下个月"):
        d = ref + relativedelta(months=1)
        return _iso_seconds(_start_of_month(d)), _iso_seconds(_end_of_month(d))

    # E) 去年/今年/明年（按年粒度）
    if t == "去年":
        d = ref + relativedelta(years=-1)
        return _iso_seconds(_start_of_year(d)), _iso_seconds(_end_of_year(d))
    if t == "今年":
        return _iso_seconds(_start_of_year(ref)), _iso_seconds(_end_of_year(ref))
    if t == "明年":
        d = ref + relativedelta(years=1)
        return _iso_seconds(_start_of_year(d)), _iso_seconds(_end_of_year(d))

    # F) X天前/后, X周前/后, X个月前/后, X年前/后（支持中文数字 + 半）
    m = re.fullmatch(r"([0-9一二两三四五六七八九十半]+)天(前|后)", t)
    if m:
        num, direction = m.group(1), m.group(2)
        sign = -1 if direction == "前" else 1
        if num == "半":
            d = ref + timedelta(days=sign * 0.5)
        else:
            n = _cn_to_int(num)
            if n is None:
                return _fallback_day(ref)
            d = ref + timedelta(days=sign * n)
        return _iso_seconds(_start_of_day(d)), _iso_seconds(_end_of_day(d))

    m = re.fullmatch(r"([0-9一二两三四五六七八九十半]+)周(前|后)", t)
    if m:
        num, direction = m.group(1), m.group(2)
        sign = -1 if direction == "前" else 1
        if num == "半":
            d = ref + timedelta(weeks=sign * 0.5)
        else:
            n = _cn_to_int(num)
            if n is None:
                return _fallback_day(ref)
            d = ref + timedelta(weeks=sign * n)
        return _iso_seconds(_start_of_week(d)), _iso_seconds(_end_of_week(d))

    m = re.fullmatch(r"([0-9一二两三四五六七八九十半]+)个?月(前|后)", t)
    if m:
        num, direction = m.group(1), m.group(2)
        sign = -1 if direction == "前" else 1
        if num == "半":
            # 半个月：±15天近似
            d1 = ref - timedelta(days=15)
            d2 = ref + timedelta(days=15)
            s = _start_of_day(min(d1, d2))
            e = _end_of_day(max(d1, d2))
            return _iso_seconds(s), _iso_seconds(e)
        n = _cn_to_int(num)
        if n is None:
            return _fallback_day(ref)
        base = ref + relativedelta(months=sign * n)
        return _iso_seconds(_start_of_month(base)), _iso_seconds(_end_of_month(base))

    m = re.fullmatch(r"([0-9一二两三四五六七八九十半]+)年(前|后)", t)
    if m:
        num, direction = m.group(1), m.group(2)
        sign = -1 if direction == "前" else 1
        if num == "半":
            base = ref + relativedelta(months=sign * 6)
            return _iso_seconds(_start_of_month(base)), _iso_seconds(_end_of_month(base))
        n = _cn_to_int(num)
        if n is None:
            return _fallback_day(ref)
        base = ref + relativedelta(years=sign * n)
        return _iso_seconds(_start_of_year(base)), _iso_seconds(_end_of_year(base))

    # G) 上周五/上上周二/下周日/本周三
    m = re.fullmatch(r"(上上周|上上星期|上周|上星期|本周|这周|这星期|本星期|下周|下星期)(周|星期)([一二三四五六日天])", t)
    if m:
        which = m.group(1)
        wd = WEEKDAY_MAP[m.group(3)]
        if "上上" in which:
            base = ref - timedelta(weeks=2)
        elif "上" in which:
            base = ref - timedelta(weeks=1)
        elif "下" in which:
            base = ref + timedelta(weeks=1)
        else:
            base = ref
        d = _start_of_week(base) + timedelta(days=wd)
        return _iso_seconds(_start_of_day(d)), _iso_seconds(_end_of_day(d))

    # H) 周五/星期二：默认最近一次该周几（偏过去）
    m = re.fullmatch(r"(周|星期)([一二三四五六日天])", t)
    if m:
        wd = WEEKDAY_MAP[m.group(2)]
        d = _start_of_week(ref) + timedelta(days=wd)
        if d > ref:
            d = d - timedelta(days=7)
        return _iso_seconds(_start_of_day(d)), _iso_seconds(_end_of_day(d))

    # I) YYYY年MM月DD日 / YYYY年
    m = re.fullmatch(r"((19|20)\d{2})年(\d{1,2})月(\d{1,2})[日号]?", t)
    if m:
        y, mo, da = int(m.group(1)), int(m.group(3)), int(m.group(4))
        d = ref.replace(year=y, month=mo, day=da)
        return _iso_seconds(_start_of_day(d)), _iso_seconds(_end_of_day(d))

    m = re.fullmatch(r"((19|20)\d{2})年", t)
    if m:
        y = int(m.group(1))
        d = ref.replace(year=y)
        return _iso_seconds(_start_of_year(d)), _iso_seconds(_end_of_year(d))

    # J) MM月DD日（无年份：用 ref 年；若未来则回退一年）
    m = re.fullmatch(r"(\d{1,2})月(\d{1,2})[日号]?", t)
    if m:
        mo, da = int(m.group(1)), int(m.group(2))
        d = ref.replace(month=mo, day=da)
        if d > ref:
            d = d.replace(year=ref.year - 1)
        return _iso_seconds(_start_of_day(d)), _iso_seconds(_end_of_day(d))

    return _fallback_day(ref)


# =========================
# enrich mem0-style payload (ADD EPOCH)
# =========================

def enrich_mem0_payload_time(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Add:
      ts_start, ts_end, time_is_event, dialogue_ts
      ts_start_epoch, ts_end_epoch, dialogue_ts_epoch   (int seconds)

    Rules:
    - reference_time = created_at
    - if mem_type != episodic -> unchanged
    - if time.text exists -> parse event time range; time_is_event=1
    - else -> point time at created_at; time_is_event=0 (recency)
    """
    if "created_at" not in payload:
        raise ValueError("payload must include 'created_at'")

    mem_type = (payload.get("mem_type") or "").lower()
    if mem_type != "episodic":
        return payload

    ref_dt = _parse_iso_dt(payload["created_at"])
    dialogue_ts = _iso_seconds(ref_dt)
    dialogue_ts_epoch = _epoch_seconds(ref_dt)

    time_obj = payload.get("time") if isinstance(payload.get("time"), dict) else None
    time_text = time_obj.get("text") if time_obj else None

    # default: dialogue time point
    ts_start = dialogue_ts
    ts_end = dialogue_ts
    ts_start_epoch = dialogue_ts_epoch
    ts_end_epoch = dialogue_ts_epoch
    time_is_event = 0

    if time_text:
        ts_start, ts_end = _parse_time_range_cn(time_text, reference_time=ref_dt)
        # convert to epoch
        ts_start_dt = _parse_iso_dt(ts_start)
        ts_end_dt = _parse_iso_dt(ts_end)
        ts_start_epoch = _epoch_seconds(ts_start_dt)
        ts_end_epoch = _epoch_seconds(ts_end_dt)
        time_is_event = 1

    out = dict(payload)
    out.update({
        "ts_start": ts_start,
        "ts_end": ts_end,
        "time_is_event": time_is_event,
        "dialogue_ts": dialogue_ts,
        "ts_start_epoch": ts_start_epoch,
        "ts_end_epoch": ts_end_epoch,
        "dialogue_ts_epoch": dialogue_ts_epoch,
    })
    return out


# =========================
# demo
# =========================
if __name__ == "__main__":
    p = {
        "user_id":"default_user",
        "fact_schema_version":"structured",
        "mem_type":"episodic",
        "mem_category":"event",
        "time":{"text":"去年三月"},
        "data":"在去年三月，用户因内部晋升从波士顿办公室的数据分析岗位调任到西雅图总部，这次搬迁是用户职业上的重要转折点。",
        "hash":"73fde1c920f252d92c439558bb25a874",
        "created_at":"2026-01-13T01:14:30.361602-08:00"
    }
    import json
    out = enrich_mem0_payload_time(p)
    print(json.dumps(out, ensure_ascii=False, indent=2))
