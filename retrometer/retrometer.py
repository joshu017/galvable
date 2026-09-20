#!/usr/bin/env python3
"""Mercury retrograde cycle tracker for GalvoCtrl.

Computes a 0.0–1.0 galvo reading based on where Mercury is in its
retrograde cycle right now.  Station dates (retrograde/direct) are from
the Astrodienst "Planetary Phenomena of Mercury 2000–2100" ephemeris.

Shadow (pre-retrograde and post-retrograde) periods are approximated
from the retrograde duration — see SHADOW_RATIO below.

Gauge mapping (left-to-right sweep then back):

    0%   mid-direct
    ↓    direct motion
    65%  pre-shadow begins
    ↓    pre-shadow
    80%  retrograde station (Rx)
    ↓    retrograde motion
    100% mid-retrograde
    ↓    retrograde motion
    80%  direct station (D)
    ↓    post-shadow
    65%  post-shadow ends
    ↓    direct motion
    0%   next mid-direct

The 65 % and 80 % transition points are adjustable (DIRECT_LIMIT,
SHADOW_LIMIT).
"""

import asyncio
import sys
import struct
import time
from datetime import datetime, timezone

# ── Gauge mapping parameters ────────────────────────────────────────────────
# These set the galvo value at each phase boundary.
# The gauge sweeps 0 → DIRECT_LIMIT → SHADOW_LIMIT → 1.0 → SHADOW_LIMIT
# → DIRECT_LIMIT → 0 over one full cycle.

DIRECT_LIMIT = 0.65   # boundary between direct motion and shadow
SHADOW_LIMIT = 0.80   # boundary between shadow and retrograde
SHADOW_RATIO = 1.0    # shadow duration as a fraction of retrograde duration


# ── Mercury station data ────────────────────────────────────────────────────
# (retrograde_station, direct_station) pairs from Astrodienst ephemeris.
# Dates are UTC.  Covers 2000-01 through 2100-02 (316 retrograde periods).

_STATIONS_RAW = """\
2000-02-21 12:46,2000-03-14 20:39
2000-06-23 08:31,2000-07-17 13:20
2000-10-18 13:41,2000-11-08 02:28
2001-02-04 01:58,2001-02-25 15:41
2001-06-04 05:21,2001-06-28 05:49
2001-10-01 19:23,2001-10-23 00:22
2002-01-18 20:49,2002-02-08 17:27
2002-05-15 18:49,2002-06-08 15:11
2002-09-14 19:38,2002-10-06 19:25
2003-01-02 18:19,2003-01-23 01:08
2003-04-26 11:58,2003-05-20 07:32
2003-08-28 13:41,2003-09-20 08:52
2003-12-17 16:00,2004-01-06 13:43
2004-04-06 20:27,2004-04-30 13:05
2004-08-10 00:32,2004-09-02 13:09
2004-11-30 12:17,2004-12-20 06:29
2005-03-20 00:14,2005-04-12 07:45
2005-07-23 03:00,2005-08-16 03:50
2005-11-14 05:42,2005-12-04 02:23
2006-03-02 20:29,2006-03-25 13:42
2006-07-04 19:33,2006-07-29 00:39
2006-10-28 19:16,2006-11-18 00:25
2007-02-14 04:37,2007-03-08 04:44
2007-06-15 23:40,2007-07-10 02:15
2007-10-12 03:59,2007-11-01 22:58
2008-01-28 20:30,2008-02-19 02:57
2008-05-26 15:47,2008-06-19 14:31
2008-09-24 07:16,2008-10-15 20:05
2009-01-11 16:43,2009-02-01 07:10
2009-05-07 05:00,2009-05-31 01:21
2009-09-07 04:44,2009-09-29 13:13
2009-12-26 14:38,2010-01-15 16:51
2010-04-18 04:06,2010-05-11 22:26
2010-08-20 19:58,2010-09-12 23:08
2010-12-10 12:04,2010-12-30 07:20
2011-03-30 20:47,2011-04-23 10:03
2011-08-03 03:50,2011-08-26 22:02
2011-11-24 07:19,2011-12-14 01:42
2012-03-12 07:48,2012-04-04 10:11
2012-07-15 02:15,2012-08-08 05:40
2012-11-06 23:03,2012-11-26 22:47
2013-02-23 09:41,2013-03-17 20:02
2013-06-26 13:07,2013-07-20 18:22
2013-10-21 10:28,2013-11-10 21:11
2014-02-06 21:43,2014-02-28 14:00
2014-06-07 11:56,2014-07-01 12:49
2014-10-04 17:02,2014-10-25 19:16
2015-01-21 15:54,2015-02-11 14:56
2015-05-19 01:49,2015-06-11 22:32
2015-09-17 18:09,2015-10-09 14:57
2016-01-05 13:05,2016-01-25 21:49
2016-04-28 17:19,2016-05-22 13:19
2016-08-30 13:03,2016-09-22 05:30
2016-12-19 10:55,2017-01-08 09:42
2017-04-09 23:14,2017-05-03 16:32
2017-08-13 01:00,2017-09-05 11:29
2017-12-03 07:34,2017-12-23 01:50
2018-03-23 00:18,2018-04-15 09:20
2018-07-26 05:02,2018-08-19 04:24
2018-11-17 01:33,2018-12-06 21:22
2019-03-05 18:18,2019-03-28 13:58
2019-07-07 23:14,2019-08-01 03:57
2019-10-31 15:41,2019-11-20 19:11
2020-02-17 00:54,2020-03-10 03:48
2020-06-18 04:58,2020-07-12 08:26
2020-10-14 01:05,2020-11-03 17:49
2021-01-30 15:51,2021-02-21 00:52
2021-05-29 22:34,2021-06-22 22:00
2021-09-27 05:10,2021-10-18 15:16
2022-01-14 11:41,2022-02-04 04:12
2022-05-10 11:47,2022-06-03 08:00
2022-09-10 03:38,2022-10-02 09:07
2022-12-29 09:31,2023-01-18 13:11
2023-04-21 08:34,2023-05-15 03:16
2023-08-23 19:59,2023-09-15 20:21
2023-12-13 07:09,2024-01-02 03:07
2024-04-01 22:14,2024-04-25 12:54
2024-08-05 04:56,2024-08-28 21:13
2024-11-26 02:42,2024-12-15 20:56
2025-03-15 06:46,2025-04-07 11:07
2025-07-18 04:45,2025-08-11 07:29
2025-11-09 19:01,2025-11-29 17:38
2026-02-26 06:48,2026-03-20 19:32
2026-06-29 17:35,2026-07-23 22:57
2026-10-24 07:12,2026-11-13 15:53
2027-02-09 17:36,2027-03-03 12:32
2027-06-10 18:15,2027-07-04 19:39
2027-10-07 14:37,2027-10-28 14:10
2028-01-24 11:02,2028-02-14 12:37
2028-05-21 08:43,2028-06-14 06:05
2028-09-19 16:33,2028-10-11 10:27
2029-01-07 07:56,2029-01-27 18:40
2029-05-01 23:05,2029-05-25 19:20
2029-09-02 12:18,2029-09-25 02:01
2029-12-22 05:50,2030-01-11 05:45
2030-04-13 02:33,2030-05-06 20:14
2030-08-16 01:20,2030-09-08 09:27
2030-12-06 02:47,2030-12-25 21:14
2031-03-26 00:43,2031-04-18 11:15
2031-07-29 06:47,2031-08-22 04:28
2031-11-19 21:15,2031-12-09 16:23
2032-03-07 16:21,2032-03-30 14:29
2032-07-10 02:33,2032-08-03 06:52
2032-11-02 11:56,2032-11-22 14:00
2033-02-18 21:20,2033-03-13 02:57
2033-06-21 10:05,2033-07-15 14:19
2033-10-16 22:03,2033-11-06 12:39
2034-02-02 11:21,2034-02-23 22:54
2034-06-02 05:23,2034-06-26 05:23
2034-09-30 02:59,2034-10-21 10:22
2035-01-17 06:44,2035-02-07 01:24
2035-05-13 18:40,2035-06-06 14:52
2035-09-13 02:28,2035-10-05 04:53
2036-01-01 04:24,2036-01-21 09:41
2036-04-23 13:17,2036-05-17 08:29
2036-08-25 19:47,2036-09-17 17:20
2036-12-15 02:06,2037-01-03 22:57
2037-04-05 00:05,2037-04-28 15:55
2037-08-08 05:45,2037-08-31 20:07
2037-11-28 22:00,2037-12-18 16:12
2038-03-18 06:07,2038-04-10 12:11
2038-07-21 06:58,2038-08-14 08:49
2038-11-12 14:56,2038-12-02 12:30
2039-03-01 04:11,2039-03-23 19:19
2039-07-02 21:47,2039-07-27 03:06
2039-10-27 03:54,2039-11-16 10:38
2040-02-12 13:38,2040-03-05 11:19
2040-06-13 00:19,2040-07-07 02:21
2040-10-09 12:05,2040-10-30 09:05
2041-01-26 06:14,2041-02-16 10:27
2041-05-24 15:37,2041-06-17 13:41
2041-09-22 14:43,2041-10-14 05:51
2042-01-10 02:47,2042-01-30 15:31
2042-05-05 05:13,2042-05-29 01:31
2042-09-05 11:20,2042-09-27 22:18
2042-12-25 00:43,2043-01-14 01:49
2043-04-16 06:17,2043-05-10 00:19
2043-08-19 01:33,2043-09-11 07:04
2043-12-08 21:57,2043-12-28 16:45
2044-03-28 01:30,2044-04-20 13:34
2044-07-31 08:21,2044-08-24 04:12
2044-11-21 16:51,2044-12-11 11:31
2045-03-10 14:41,2045-04-02 15:09
2045-07-13 05:37,2045-08-06 09:27
2045-11-05 08:07,2045-11-25 08:54
2046-02-21 18:00,2046-03-16 02:11
2046-06-24 14:57,2046-07-18 19:50
2046-10-19 18:56,2046-11-09 07:26
2047-02-05 07:01,2047-02-26 21:04
2047-06-05 12:04,2047-06-29 12:35
2047-10-03 00:45,2047-10-24 05:20
2048-01-20 01:47,2048-02-09 22:44
2048-05-16 01:31,2048-06-08 21:56
2048-09-15 01:08,2048-10-07 00:29
2049-01-02 23:14,2049-01-23 06:19
2049-04-26 18:19,2049-05-20 13:57
2049-08-28 19:21,2049-09-20 14:09
2049-12-17 20:59,2050-01-06 18:51
2050-04-08 02:27,2050-05-01 19:09
2050-08-11 06:22,2050-09-03 18:42
2050-12-01 17:19,2050-12-21 11:32
2051-03-21 05:56,2051-04-13 13:37
2051-07-24 09:02,2051-08-17 09:41
2051-11-15 10:50,2051-12-05 07:24
2052-03-03 01:51,2052-03-25 19:24
2052-07-05 01:44,2052-07-29 06:48
2052-10-29 00:29,2052-11-18 05:24
2053-02-14 09:45,2053-03-08 10:16
2053-06-16 06:04,2053-07-10 08:48
2053-10-12 09:18,2053-11-02 03:57
2054-01-29 01:29,2054-02-19 08:18
2054-05-27 22:30,2054-06-20 21:18
2054-09-25 12:41,2054-10-17 01:07
2055-01-12 21:41,2055-02-02 12:25
2055-05-08 11:40,2055-06-01 07:57
2055-09-08 10:17,2055-09-30 18:20
2055-12-27 19:36,2056-01-16 22:00
2056-04-18 10:25,2056-05-12 04:50
2056-08-21 01:41,2056-09-13 04:27
2056-12-10 17:04,2056-12-30 12:26
2057-03-31 02:39,2057-04-23 16:08
2057-08-03 09:45,2057-08-27 03:41
2057-11-24 12:21,2057-12-14 06:45
2058-03-13 13:19,2058-04-05 15:56
2058-07-16 08:23,2058-08-09 11:42
2058-11-08 04:11,2058-11-28 03:46
2059-02-24 14:55,2059-03-19 01:35
2059-06-27 19:31,2059-07-22 00:49
2059-10-22 15:43,2059-11-12 02:08
2060-02-08 02:47,2060-02-29 19:24
2060-06-07 18:31,2060-07-01 19:29
2060-10-04 22:26,2060-10-26 00:16
2061-01-21 20:53,2061-02-11 20:17
2061-05-19 08:27,2061-06-12 05:15
2061-09-17 23:40,2061-10-09 20:03
2062-01-05 18:03,2062-01-26 03:04
2062-04-29 23:50,2062-05-23 19:49
2062-08-31 18:43,2062-09-23 10:48
2062-12-20 15:53,2063-01-09 14:50
2063-04-11 05:22,2063-05-04 22:41
2063-08-14 06:45,2063-09-06 16:54
2063-12-04 12:35,2063-12-24 06:53
2064-03-23 06:03,2064-04-15 15:17
2064-07-26 10:57,2064-08-19 10:05
2064-11-17 06:37,2064-12-07 02:20
2065-03-05 23:40,2065-03-28 19:39
2065-07-08 05:27,2065-08-01 10:05
2065-10-31 20:53,2065-11-21 00:10
2066-02-17 06:00,2066-03-11 09:19
2066-06-19 11:27,2066-07-13 15:00
2066-10-15 06:21,2066-11-04 22:47
2067-01-31 20:53,2067-02-22 06:15
2067-05-31 05:17,2067-06-24 04:48
2067-09-28 10:34,2067-10-19 20:18
2068-01-15 16:41,2068-02-05 09:29
2068-05-10 18:24,2068-06-03 14:39
2068-09-10 09:13,2068-10-02 14:15
2068-12-29 14:31,2069-01-18 18:24
2069-04-21 14:55,2069-05-15 09:42
2069-08-24 01:43,2069-09-16 01:39
2069-12-13 12:06,2070-01-02 08:13
2070-04-03 04:11,2070-04-26 18:58
2070-08-06 10:48,2070-08-30 02:50
2070-11-27 07:43,2070-12-17 01:58
2071-03-16 12:19,2071-04-08 16:52
2071-07-19 10:44,2071-08-12 13:25
2071-11-06 13:17,2071-11-26 13:54
2072-02-27 12:06,2072-03-21 01:10
2072-06-29 23:53,2072-07-24 05:17
2072-10-24 12:27,2072-11-13 20:51
2073-02-09 22:42,2073-03-03 18:00
2073-06-11 00:52,2073-07-05 02:17
2073-10-07 20:00,2073-10-28 19:12
2074-01-24 16:03,2074-02-14 18:00
2074-05-22 15:24,2074-06-15 12:49
2074-09-20 22:01,2074-10-12 15:33
2075-01-08 12:53,2075-01-28 23:53
2075-05-03 05:40,2075-05-27 01:56
2075-09-03 17:53,2075-09-26 07:14
2075-12-23 10:47,2076-01-12 10:52
2076-04-13 08:44,2076-05-07 02:29
2076-08-16 07:04,2076-09-08 14:48
2076-12-06 07:47,2076-12-26 02:17
2077-03-26 06:28,2077-04-18 17:12
2077-07-29 12:44,2077-08-22 10:08
2077-11-20 02:20,2077-12-09 21:24
2078-03-08 21:44,2078-03-31 20:11
2078-07-11 08:47,2078-08-04 13:00
2078-11-03 17:07,2078-11-23 19:00
2079-02-20 02:31,2079-03-14 08:30
2079-06-22 16:28,2079-07-16 20:52
2079-10-18 03:20,2079-11-07 17:38
2080-02-03 16:28,2080-02-25 04:19
2080-06-02 12:00,2080-06-26 12:07
2080-09-30 08:24,2080-10-21 15:23
2081-01-17 11:43,2081-02-07 06:41
2081-05-14 01:19,2081-06-06 21:31
2081-09-13 08:01,2081-10-05 09:59
2082-01-01 09:21,2082-01-21 14:54
2082-04-24 19:42,2082-05-18 14:54
2082-08-27 01:27,2082-09-18 22:36
2082-12-16 07:03,2083-01-05 04:03
2083-04-06 06:08,2083-04-29 22:04
2083-08-09 11:32,2083-09-02 01:39
2083-11-30 03:02,2083-12-19 21:13
2084-03-18 11:46,2084-04-10 18:03
2084-07-21 12:58,2084-08-14 14:41
2084-11-12 20:04,2084-12-02 17:29
2085-03-01 09:32,2085-03-24 00:59
2085-07-03 04:06,2085-07-27 09:21
2085-10-27 09:08,2085-11-16 15:36
2086-02-12 18:45,2086-03-06 16:49
2086-06-14 06:56,2086-07-08 09:01
2086-10-10 17:24,2086-10-31 14:06
2087-01-27 11:13,2087-02-17 15:47
2087-05-25 22:18,2087-06-18 20:30
2087-09-23 20:09,2087-10-15 10:54
2088-01-11 07:43,2088-01-31 20:44
2088-05-05 11:48,2088-05-29 08:08
2088-09-05 16:54,2088-09-28 03:26
2088-12-25 05:40,2089-01-14 06:57
2089-04-16 12:30,2089-05-10 06:32
2089-08-19 07:20,2089-09-11 12:27
2089-12-09 02:58,2089-12-28 21:51
2090-03-29 07:16,2090-04-21 19:31
2090-08-01 14:19,2090-08-25 09:53
2090-11-22 21:57,2090-12-12 16:34
2091-03-11 20:10,2091-04-03 20:57
2091-07-14 11:44,2091-08-07 15:33
2091-11-06 13:17,2091-11-26 13:54
2092-02-22 23:16,2092-03-16 07:47
2092-06-24 21:16,2092-07-19 02:14
2092-10-20 00:12,2092-11-09 12:25
2093-02-05 12:07,2093-02-27 02:31
2093-06-05 18:39,2093-06-29 19:12
2093-10-03 06:08,2093-10-24 10:20
2094-01-20 06:46,2094-02-10 04:03
2094-05-17 08:18,2094-06-10 04:43
2094-09-16 06:40,2094-10-08 05:35
2095-01-04 04:09,2095-01-24 11:31
2095-04-28 00:50,2095-05-21 20:30
2095-08-30 00:57,2095-09-21 19:22
2095-12-19 01:57,2096-01-07 23:58
2096-04-08 08:33,2096-05-02 01:20
2096-08-11 12:07,2096-09-04 00:11
2096-12-01 22:20,2096-12-21 16:33
2097-03-21 11:35,2097-04-13 19:27
2097-07-24 15:06,2097-08-17 15:31
2097-11-15 15:57,2097-12-05 12:24
2098-03-04 07:10,2098-03-27 01:03
2098-07-06 08:03,2098-07-30 13:01
2098-10-30 05:41,2098-11-19 10:22
2099-02-15 14:53,2099-03-09 15:46
2099-06-17 12:33,2099-07-11 15:27
2099-10-13 14:37,2099-11-03 08:57
2100-01-30 06:29,2100-02-20 13:39"""


def _parse_stations():
    """Parse the embedded station data into a list of (rx_dt, d_dt) tuples."""
    pairs = []
    for line in _STATIONS_RAW.strip().splitlines():
        rx_s, d_s = line.split(",")
        rx = datetime.strptime(rx_s, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        d = datetime.strptime(d_s, "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc)
        pairs.append((rx, d))
    return pairs


STATIONS = _parse_stations()


# ── Cycle computation ────────────────────────────────────────────────────────

def _ts(dt):
    """datetime → POSIX timestamp (float seconds)."""
    return dt.timestamp()


def _lerp(t, a, b):
    """Linear interpolation: returns a when t=0, b when t=1."""
    return a + t * (b - a)


def compute_cycle_dates(idx, shadow_ratio=SHADOW_RATIO):
    """Compute the 6 key dates for retrograde cycle `idx`.

    Returns a dict with:
        mid_direct_before  – centre of direct motion before this Rx
        pre_shadow_start   – estimated start of pre-retrograde shadow
        rx                 – retrograde station
        mid_retro          – centre of retrograde period
        d                  – direct station
        post_shadow_end    – estimated end of post-retrograde shadow
        mid_direct_after   – centre of direct motion after this D
    """
    rx, d = STATIONS[idx]
    retro_secs = _ts(d) - _ts(rx)
    shadow_secs = retro_secs * shadow_ratio

    # Previous direct station (end of last retrograde)
    if idx > 0:
        prev_d = STATIONS[idx - 1][1]
    else:
        # Before first record — extrapolate backwards
        prev_d = datetime.fromtimestamp(
            _ts(rx) - 93 * 86400, tz=timezone.utc  # avg direct gap ≈ 93 days
        )

    # Next retrograde station (start of next retrograde)
    if idx + 1 < len(STATIONS):
        next_rx = STATIONS[idx + 1][0]
    else:
        next_rx = datetime.fromtimestamp(
            _ts(d) + 93 * 86400, tz=timezone.utc
        )

    pre_shadow = datetime.fromtimestamp(_ts(rx) - shadow_secs, tz=timezone.utc)
    post_shadow = datetime.fromtimestamp(_ts(d) + shadow_secs, tz=timezone.utc)

    # Clamp shadow dates so they don't overlap adjacent retrogrades
    mid_before = datetime.fromtimestamp(
        (_ts(prev_d) + _ts(rx)) / 2, tz=timezone.utc
    )
    mid_after = datetime.fromtimestamp(
        (_ts(d) + _ts(next_rx)) / 2, tz=timezone.utc
    )
    if _ts(pre_shadow) < _ts(mid_before):
        pre_shadow = mid_before
    if _ts(post_shadow) > _ts(mid_after):
        post_shadow = mid_after

    mid_retro = datetime.fromtimestamp(
        (_ts(rx) + _ts(d)) / 2, tz=timezone.utc
    )

    return {
        "mid_direct_before": mid_before,
        "pre_shadow_start": pre_shadow,
        "rx": rx,
        "mid_retro": mid_retro,
        "d": d,
        "post_shadow_end": post_shadow,
        "mid_direct_after": mid_after,
    }


def get_mercury_phase(dt=None, shadow_ratio=SHADOW_RATIO,
                      direct_limit=DIRECT_LIMIT, shadow_limit=SHADOW_LIMIT):
    """Determine Mercury's retrograde-cycle phase and galvo value.

    Returns (phase_name, galvo_value, cycle_info) where:
        phase_name  – one of "direct", "pre_shadow", "retrograde",
                      "post_shadow"
        galvo_value – 0.0 to 1.0
        cycle_info  – dict with all the cycle dates and progress
    """
    if dt is None:
        dt = datetime.now(timezone.utc)
    t = _ts(dt)

    # Find which retrograde cycle we're nearest
    # We check each cycle's full span (mid_direct_before → mid_direct_after)
    for idx in range(len(STATIONS)):
        cyc = compute_cycle_dates(idx, shadow_ratio)
        t_start = _ts(cyc["mid_direct_before"])
        t_end = _ts(cyc["mid_direct_after"])

        if t_start <= t <= t_end:
            t_md1 = _ts(cyc["mid_direct_before"])
            t_ps = _ts(cyc["pre_shadow_start"])
            t_rx = _ts(cyc["rx"])
            t_mr = _ts(cyc["mid_retro"])
            t_d = _ts(cyc["d"])
            t_pe = _ts(cyc["post_shadow_end"])
            t_md2 = _ts(cyc["mid_direct_after"])

            if t <= t_ps:
                # Direct motion (ascending)
                frac = (t - t_md1) / (t_ps - t_md1) if t_ps > t_md1 else 0
                phase = "direct"
                galvo = _lerp(frac, 0.0, direct_limit)
            elif t <= t_rx:
                # Pre-shadow
                frac = (t - t_ps) / (t_rx - t_ps) if t_rx > t_ps else 0
                phase = "pre_shadow"
                galvo = _lerp(frac, direct_limit, shadow_limit)
            elif t <= t_mr:
                # Retrograde first half (ascending to peak)
                frac = (t - t_rx) / (t_mr - t_rx) if t_mr > t_rx else 0
                phase = "retrograde"
                galvo = _lerp(frac, shadow_limit, 1.0)
            elif t <= t_d:
                # Retrograde second half (descending from peak)
                frac = (t - t_mr) / (t_d - t_mr) if t_d > t_mr else 0
                phase = "retrograde"
                galvo = _lerp(frac, 1.0, shadow_limit)
            elif t <= t_pe:
                # Post-shadow
                frac = (t - t_d) / (t_pe - t_d) if t_pe > t_d else 0
                phase = "post_shadow"
                galvo = _lerp(frac, shadow_limit, direct_limit)
            else:
                # Direct motion (descending)
                frac = (t - t_pe) / (t_md2 - t_pe) if t_md2 > t_pe else 0
                phase = "direct"
                galvo = _lerp(frac, direct_limit, 0.0)

            cyc["phase_frac"] = frac
            return phase, max(0.0, min(1.0, galvo)), cyc

    return "unknown", 0.0, {}


# ── Display helpers ──────────────────────────────────────────────────────────

_PHASE_LABELS = {
    "direct": "Direct",
    "pre_shadow": "Pre-shadow",
    "retrograde": "RETROGRADE",
    "post_shadow": "Post-shadow",
    "unknown": "Unknown",
}

_PHASE_COLORS = {
    "direct": "\033[32m",       # green
    "pre_shadow": "\033[33m",   # yellow
    "retrograde": "\033[31m",   # red
    "post_shadow": "\033[33m",  # yellow
    "unknown": "\033[0m",
}


def format_status(dt=None, **kwargs):
    """Return a formatted status string for the given datetime."""
    phase, galvo, cyc = get_mercury_phase(dt, **kwargs)
    rst = "\033[0m"
    c = _PHASE_COLORS.get(phase, rst)
    label = _PHASE_LABELS.get(phase, phase)

    bar_w = 30
    filled = round(galvo * bar_w)
    bar = "█" * filled + "░" * (bar_w - filled)

    lines = [f"  {c}{bar}{rst} {galvo:.4f}  {c}{label}{rst}"]

    if cyc:
        now = dt or datetime.now(timezone.utc)
        fmt = "%b %d %Y %H:%M"

        if phase == "direct" and now > cyc["d"]:
            # Direct motion AFTER the retrograde — show last Rx→D, next Rx
            lines.append(f"  Last Rx  {cyc['rx'].strftime(fmt)}")
            lines.append(f"  Last D   {cyc['d'].strftime(fmt)}")
            for idx in range(len(STATIONS)):
                if STATIONS[idx][0] == cyc["rx"]:
                    if idx + 1 < len(STATIONS):
                        next_rx = STATIONS[idx + 1][0]
                        lines.append(f"  Next Rx  {next_rx.strftime(fmt)}")
                        delta = next_rx - now
                        lines.append(f"  Rx in {delta.total_seconds() / 86400:.1f} days")
                    break
        elif phase in ("direct", "pre_shadow"):
            # Direct motion or pre-shadow BEFORE retrograde — show upcoming Rx→D
            lines.append(f"  Next Rx  {cyc['rx'].strftime(fmt)}")
            lines.append(f"  Next D   {cyc['d'].strftime(fmt)}")
            delta = cyc["rx"] - now
            lines.append(f"  Rx in {delta.total_seconds() / 86400:.1f} days")
        elif phase == "retrograde":
            # In retrograde — show current Rx→D
            lines.append(f"  Rx  {cyc['rx'].strftime(fmt)}")
            lines.append(f"  D   {cyc['d'].strftime(fmt)}")
            delta = cyc["d"] - now
            lines.append(f"  D in {delta.total_seconds() / 86400:.1f} days")
        elif phase == "post_shadow":
            # After retrograde — show last Rx→D, next Rx
            lines.append(f"  Last Rx  {cyc['rx'].strftime(fmt)}")
            lines.append(f"  Last D   {cyc['d'].strftime(fmt)}")
            delta = cyc["post_shadow_end"] - now
            lines.append(f"  Shadow clears in {delta.total_seconds() / 86400:.1f} days")
            # Find next retrograde
            for idx in range(len(STATIONS)):
                if STATIONS[idx][0] == cyc["rx"]:
                    if idx + 1 < len(STATIONS):
                        lines.append(f"  Next Rx  {STATIONS[idx + 1][0].strftime(fmt)}")
                    break

        lines.append(f"  Pre-shadow  {cyc['pre_shadow_start'].strftime(fmt)}")
        lines.append(f"  Post-shadow {cyc['post_shadow_end'].strftime(fmt)}")

    return "\n".join(lines)


# ── Main ─────────────────────────────────────────────────────────────────────

async def main():
    args = sys.argv[1:]

    # Parse optional date argument for testing (m-d-y, e.g. 4-13-2026)
    dt = None
    if args and not args[0].startswith("--"):
        try:
            dt = datetime.strptime(args[0], "%m-%d-%Y").replace(
                tzinfo=timezone.utc)
            args = args[1:]
        except ValueError:
            pass

    # Parse --name, --id, --channel
    target_name = None
    if "--name" in args:
        idx = args.index("--name")
        target_name = args[idx + 1]
        args = args[:idx] + args[idx + 2:]

    target_id = None
    if "--id" in args:
        idx = args.index("--id")
        target_id = args[idx + 1]
        args = args[:idx] + args[idx + 2:]

    channel = None
    if "--channel" in args:
        idx = args.index("--channel")
        channel = int(args[idx + 1])
        args = args[:idx] + args[idx + 2:]

    watch_mode = "--watch" in args
    interval = 3600  # default: once per hour
    if watch_mode:
        idx = args.index("--watch")
        if idx + 1 < len(args):
            try:
                interval = int(args[idx + 1])
            except ValueError:
                pass

    # Send to galvo if --name or --id specified
    want_ble = target_name is not None or target_id is not None

    phase, galvo, cyc = get_mercury_phase(dt)
    now_label = (dt or datetime.now(timezone.utc)).strftime("%Y-%m-%d %H:%M UTC")
    print(f"\n  Mercury Retrograde Tracker  ({now_label})")
    print(format_status(dt))

    if want_ble:
        from bleak import BleakClient, BleakScanner

        service_uuid = "e0f3a8b1-4c6d-4e9f-8b2a-7d1c5f3e9a0b"
        value_uuid = "a1b2c3d4-5e6f-7890-abcd-ef1234567890"
        name_uuid = "a1b2c3d4-5e6f-7890-abcd-ef1234567891"

        try:
            discovered = await BleakScanner.discover(timeout=5.0, return_adv=True)
            device = None
            for candidate, adv in discovered.values():
                if service_uuid not in adv.service_uuids and adv.local_name != "GalvoCtrl":
                    continue
                if target_id:
                    if candidate.address.upper() == target_id.upper():
                        device = candidate
                        break
                else:
                    # Preserve selection by the device's stored name.
                    try:
                        async with BleakClient(candidate) as probe:
                            raw = await probe.read_gatt_char(name_uuid)
                        if bytes(raw).decode("utf-8") == target_name:
                            device = candidate
                            break
                    except Exception:
                        continue
            if device is None:
                raise RuntimeError(f"No matching galvo: {target_id or target_name}")

            async with BleakClient(device) as g:
                async def write_galvo(value):
                    data = struct.pack("<f", value) if channel is None else struct.pack("<fB", value, channel)
                    await g.write_gatt_char(value_uuid, data, response=True)

                if watch_mode:
                    print(f"  Connected to {g.address}")
                    print(f"  Updating every {interval}s (Ctrl+C to stop)\n")
                    try:
                        while True:
                            now = datetime.now(timezone.utc)
                            phase, galvo, _ = get_mercury_phase(now)
                            c = _PHASE_COLORS.get(phase, "\033[0m")
                            rst = "\033[0m"
                            bar_w = 30
                            filled = round(galvo * bar_w)
                            bar = "█" * filled + "░" * (bar_w - filled)
                            label = _PHASE_LABELS.get(phase, phase)
                            ts = now.strftime("%H:%M")
                            await write_galvo(galvo)
                            print(f"  [{ts}]  {c}{bar}{rst} {galvo:.4f}  {c}{label}{rst}  → galvo")
                            await asyncio.sleep(interval)
                    except KeyboardInterrupt:
                        pass
                else:
                    await write_galvo(galvo)
                    ch_label = f" ch{channel}" if channel is not None else ""
                    print(f"  → galvo{ch_label} {galvo:.4f}")
        except Exception as e:
            print(f"  Device not found: {e}")
            sys.exit(1)
    elif watch_mode:
        print(f"\n  Watching every {interval}s (Ctrl+C to stop)\n")
        try:
            while True:
                time.sleep(interval)
                now = datetime.now(timezone.utc)
                phase, galvo, _ = get_mercury_phase(now)
                c = _PHASE_COLORS.get(phase, "\033[0m")
                rst = "\033[0m"
                bar_w = 30
                filled = round(galvo * bar_w)
                bar = "█" * filled + "░" * (bar_w - filled)
                label = _PHASE_LABELS.get(phase, phase)
                ts = now.strftime("%H:%M")
                print(f"  [{ts}]  {c}{bar}{rst} {galvo:.4f}  {c}{label}{rst}")
        except KeyboardInterrupt:
            pass
    print()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print()
