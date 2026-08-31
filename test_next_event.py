import json
import os
import runpy
import stat
import types
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from zoneinfo import ZoneInfo

from icalendar import Event


SCRIPT = runpy.run_path(Path(__file__).with_name("next-event"), run_name="next_event")


class FixedDateTime(datetime):
    current = datetime(2026, 8, 27, 12, 0, tzinfo=timezone.utc)
    local_timezone = timezone(timedelta(hours=-4))

    @classmethod
    def now(cls, tz=None):
        if tz is None:
            local = cls.fromtimestamp(cls.current.timestamp(), cls.local_timezone)
            return local.replace(tzinfo=None)
        return cls.fromtimestamp(cls.current.timestamp(), tz)

    def astimezone(self, tz=None):
        if self.tzinfo is None:
            localized = self.replace(tzinfo=self.local_timezone)
            if tz is None:
                tz = timezone(localized.utcoffset())
            return datetime.astimezone(localized, tz)
        return datetime.astimezone(self, tz)


class DstDateTime(FixedDateTime):
    local_timezone = ZoneInfo("America/New_York")


def event(start, end):
    return {
        "dtstart": types.SimpleNamespace(dt=start),
        "dtend": types.SimpleNamespace(dt=end),
    }


def empty_calendar(prodid="Example"):
    return "\r\n".join(
        [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            f"PRODID:-//{prodid}//Calendar//EN",
            "END:VCALENDAR",
            "",
        ]
    )


class NextEventTests(unittest.TestCase):
    def load_events_from_ics(self, ics_content, current=None):
        with TemporaryDirectory() as directory:
            home = Path(directory)
            config_dir = home / ".config" / "next-event"
            config_dir.mkdir(parents=True)
            (config_dir / "calendars.txt").write_text(
                "https://calendar.example/feed.ics\n"
            )
            previous_current = FixedDateTime.current
            if current is not None:
                FixedDateTime.current = current

            try:
                with (
                    patch.object(SCRIPT["Path"], "home", return_value=home),
                    patch.dict(
                        SCRIPT["load_events"].__globals__,
                        {
                            "datetime": FixedDateTime,
                            "fetch_ics": lambda *args, **kwargs: ics_content,
                        },
                    ),
                ):
                    return SCRIPT["load_events"]()
            finally:
                FixedDateTime.current = previous_current

    def test_extracts_supported_meeting_links_without_html_delimiters(self):
        cases = [
            (
                "Join https://zoom.us/j/123456789?x=1&copy=2",
                "https://zoom.us/j/123456789?x=1&copy=2",
            ),
            (
                '<a href="https://meet.google.com/abc-defg-hij">Join</a>',
                "https://meet.google.com/abc-defg-hij",
            ),
            (
                (
                    '<a href="https://teams.microsoft.com/l/meetup-join/'
                    'abc?x=1&amp;y=2">Join</a>'
                ),
                "https://teams.microsoft.com/l/meetup-join/abc?x=1&y=2",
            ),
            (
                '<a href="https://acme.webex.com/acme/j.php?MTID=abc">Join</a>',
                "https://acme.webex.com/acme/j.php?MTID=abc",
            ),
            (
                '<a href="https://acme.gotomeeting.com/join/123456789">Join</a>',
                "https://acme.gotomeeting.com/join/123456789",
            ),
            (
                '<a href="https://meet.goto.com/123456789">Join</a>',
                "https://meet.goto.com/123456789",
            ),
        ]

        for description, expected in cases:
            with self.subTest(expected=expected):
                meeting = Event()
                meeting.add("description", description)
                self.assertEqual(SCRIPT["extract_link"](meeting), expected)

    def test_selects_upcoming_floating_event_in_local_timezone(self):
        meeting = event(
            FixedDateTime(2026, 8, 27, 9, 0),
            FixedDateTime(2026, 8, 27, 10, 0),
        )

        with patch.dict(
            SCRIPT["pick_next_event"].__globals__, {"datetime": FixedDateTime}
        ):
            selected = SCRIPT["pick_next_event"]([meeting])

        self.assertIs(selected, meeting)

    def test_all_day_event_ends_at_start_of_exclusive_end_date(self):
        all_day_event = Event()
        all_day_event.add("dtstart", date(2026, 8, 27))
        all_day_event.add("dtend", date(2026, 8, 28))
        FixedDateTime.current = datetime(2026, 8, 28, 12, 0, tzinfo=timezone.utc)

        try:
            with patch.dict(
                SCRIPT["pick_next_event"].__globals__, {"datetime": FixedDateTime}
            ):
                selected = SCRIPT["pick_next_event"]([all_day_event])
        finally:
            FixedDateTime.current = datetime(
                2026, 8, 27, 12, 0, tzinfo=timezone.utc
            )

        self.assertIsNone(selected)

    def test_all_day_event_without_end_ends_at_next_local_midnight(self):
        all_day_event = Event()
        all_day_event.add("dtstart", date(2026, 3, 8))

        with patch.dict(
            SCRIPT["event_bounds"].__globals__, {"datetime": DstDateTime}
        ):
            start, end = SCRIPT["event_bounds"](all_day_event)

        self.assertEqual(start.date(), date(2026, 3, 8))
        self.assertEqual(start.hour, 0)
        self.assertEqual(start.utcoffset(), timedelta(hours=-5))
        self.assertEqual(end.date(), date(2026, 3, 9))
        self.assertEqual(end.hour, 0)
        self.assertEqual(end.utcoffset(), timedelta(hours=-4))
        self.assertEqual(
            end.astimezone(timezone.utc) - start.astimezone(timezone.utc),
            timedelta(hours=23),
        )

    def test_uses_cached_calendar_after_retryable_http_error(self):
        cached_calendar = empty_calendar("Cached")
        for status_code in (408, 429, 503):
            with (
                self.subTest(status_code=status_code),
                TemporaryDirectory() as directory,
            ):
                cache_file = Path(directory) / "calendar.json"
                cache_file.write_text(
                    json.dumps(
                        {
                            "content": cached_calendar,
                            "timestamp": (
                                datetime.now(timezone.utc) - timedelta(minutes=10)
                            ).isoformat(),
                            "etag": "cached-etag",
                        }
                    )
                )
                response = types.SimpleNamespace(status_code=status_code)

                with patch.object(SCRIPT["requests"], "get", return_value=response):
                    content = SCRIPT["fetch_ics"](
                        "https://calendar.example/feed.ics", cache_file
                    )

                self.assertEqual(content, cached_calendar)

    def test_invalid_http_response_does_not_replace_cached_calendar(self):
        valid_calendar = empty_calendar()
        invalid_responses = [
            "<html>Sign in</html>",
            "\r\n".join(
                [
                    "BEGIN:VCALENDAR",
                    "VERSION:2.0",
                    "BEGIN:VEVENT",
                    "UID:invalid-recurrence@example.com",
                    "DTSTART:20260827T140000Z",
                    "DTEND:20260827T150000Z",
                    "RRULE:FREQ=BOGUS",
                    "END:VEVENT",
                    "END:VCALENDAR",
                    "",
                ]
            ),
        ]

        for invalid_response in invalid_responses:
            with (
                self.subTest(invalid_response=invalid_response),
                TemporaryDirectory() as directory,
            ):
                cache_file = Path(directory) / "calendar.json"
                cache_file.write_text(
                    json.dumps(
                        {
                            "content": valid_calendar,
                            "timestamp": (
                                datetime.now(timezone.utc) - timedelta(minutes=10)
                            ).isoformat(),
                        }
                    )
                )
                response = types.SimpleNamespace(
                    status_code=200,
                    text=invalid_response,
                    headers={},
                )

                with patch.object(
                    SCRIPT["requests"], "get", return_value=response
                ):
                    content = SCRIPT["fetch_ics"](
                        "https://calendar.example/feed.ics", cache_file
                    )

                persisted_content = json.loads(cache_file.read_text())["content"]

                self.assertEqual(content, valid_calendar)
                self.assertEqual(persisted_content, valid_calendar)

    def test_omits_null_cache_validators_from_request_headers(self):
        cached_calendar = empty_calendar("Cached")
        validator_cases = [
            {"etag": None},
            {"last_modified": None},
            {"etag": None, "last_modified": None},
        ]

        for validators in validator_cases:
            with (
                self.subTest(validators=validators),
                TemporaryDirectory() as directory,
            ):
                cache_file = Path(directory) / "calendar.json"
                cache_file.write_text(
                    json.dumps(
                        {
                            "content": cached_calendar,
                            "timestamp": (
                                datetime.now(timezone.utc) - timedelta(minutes=10)
                            ).isoformat(),
                            **validators,
                        }
                    )
                )
                response = types.SimpleNamespace(status_code=503)

                with patch.object(
                    SCRIPT["requests"], "get", return_value=response
                ) as request:
                    SCRIPT["fetch_ics"](
                        "https://calendar.example/feed.ics", cache_file
                    )

                request.assert_called_once_with(
                    "https://calendar.example/feed.ics",
                    headers={},
                    timeout=10,
                )

    def test_omits_cache_validators_without_usable_cached_content(self):
        with TemporaryDirectory() as directory:
            cache_file = Path(directory) / "calendar.json"
            cache_file.write_text(
                json.dumps(
                    {
                        "content": "<html>Expired login</html>",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                        "etag": "cached-etag",
                    }
                )
            )
            response = types.SimpleNamespace(status_code=503)

            with patch.object(
                SCRIPT["requests"], "get", return_value=response
            ) as request:
                SCRIPT["fetch_ics"](
                    "https://calendar.example/feed.ics", cache_file
                )

            request.assert_called_once_with(
                "https://calendar.example/feed.ics",
                headers={},
                timeout=10,
            )

    def test_force_refresh_bypasses_fresh_cache(self):
        old_calendar = empty_calendar("Old")
        new_calendar = empty_calendar("New")
        with TemporaryDirectory() as directory:
            cache_file = Path(directory) / "calendar.json"
            cache_file.write_text(
                json.dumps(
                    {
                        "content": old_calendar,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
            )
            response = types.SimpleNamespace(
                status_code=200,
                text=new_calendar,
                headers={},
            )

            with patch.object(SCRIPT["requests"], "get", return_value=response):
                content = SCRIPT["fetch_ics"](
                    "https://calendar.example/feed.ics",
                    cache_file,
                    force_refresh=True,
                )

        self.assertEqual(content, new_calendar)

    def test_different_feed_urls_use_different_cache_files(self):
        cache_dir = Path("cache")

        first = SCRIPT["calendar_cache_file"](
            cache_dir, "https://calendar.example/first.ics"
        )
        second = SCRIPT["calendar_cache_file"](
            cache_dir, "https://calendar.example/second.ics"
        )

        self.assertNotEqual(first, second)

    def test_existing_cache_permissions_are_restricted(self):
        cached_calendar = empty_calendar("Cached")
        with TemporaryDirectory() as directory:
            cache_dir = Path(directory) / "cache"
            cache_dir.mkdir(mode=0o777)
            os.chmod(cache_dir, 0o777)
            cache_file = cache_dir / "calendar.json"
            cache_file.write_text(
                json.dumps(
                    {
                        "content": cached_calendar,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                )
            )
            os.chmod(cache_file, 0o666)

            SCRIPT["fetch_ics"]("https://calendar.example/feed.ics", cache_file)

            directory_mode = stat.S_IMODE(cache_dir.stat().st_mode)
            file_mode = stat.S_IMODE(cache_file.stat().st_mode)

        self.assertEqual(directory_mode, 0o700)
        self.assertEqual(file_mode, 0o600)

    def test_cache_write_failure_preserves_existing_content(self):
        with TemporaryDirectory() as directory:
            cache_file = Path(directory) / "calendar.json"
            cache_file.write_text("existing cache")

            with (
                patch.object(
                    SCRIPT["json"], "dump", side_effect=OSError("disk full")
                ),
                self.assertRaises(OSError),
            ):
                SCRIPT["write_cache"](cache_file, {"content": "new cache"})

            content = cache_file.read_text()

        self.assertEqual(content, "existing cache")

    def test_unwritable_cache_does_not_discard_fetched_calendar(self):
        valid_calendar = empty_calendar()
        with TemporaryDirectory() as directory:
            blocked_parent = Path(directory) / "not-a-directory"
            blocked_parent.write_text("blocked")
            cache_file = blocked_parent / "calendar.json"
            response = types.SimpleNamespace(
                status_code=200,
                text=valid_calendar,
                headers={},
            )

            with patch.object(SCRIPT["requests"], "get", return_value=response):
                content = SCRIPT["fetch_ics"](
                    "https://calendar.example/feed.ics", cache_file
                )

        self.assertEqual(content, valid_calendar)

    def test_load_events_omits_cancelled_event(self):
        ics_content = "\r\n".join(
            [
                "BEGIN:VCALENDAR",
                "VERSION:2.0",
                "BEGIN:VEVENT",
                "UID:cancelled@example.com",
                "DTSTART:20260827T140000Z",
                "DTEND:20260827T150000Z",
                "STATUS:CANCELLED",
                "SUMMARY:Cancelled meeting",
                "END:VEVENT",
                "END:VCALENDAR",
                "",
            ]
        )

        events = self.load_events_from_ics(ics_content)

        self.assertEqual(events, [])

    def test_load_events_omits_cancelled_recurring_occurrence(self):
        ics_content = "\r\n".join(
            [
                "BEGIN:VCALENDAR",
                "VERSION:2.0",
                "BEGIN:VEVENT",
                "UID:recurring@example.com",
                "DTSTART:20260827T140000Z",
                "DTEND:20260827T150000Z",
                "RRULE:FREQ=DAILY;COUNT=2",
                "SUMMARY:Recurring meeting",
                "END:VEVENT",
                "BEGIN:VEVENT",
                "UID:recurring@example.com",
                "RECURRENCE-ID:20260828T140000Z",
                "DTSTART:20260828T140000Z",
                "DTEND:20260828T150000Z",
                "STATUS:CANCELLED",
                "SUMMARY:Recurring meeting",
                "END:VEVENT",
                "END:VCALENDAR",
                "",
            ]
        )

        events = self.load_events_from_ics(ics_content)

        self.assertEqual(len(events), 1)
        self.assertEqual(
            events[0]["DTSTART"].dt,
            datetime(2026, 8, 27, 14, 0, tzinfo=timezone.utc),
        )

    def test_load_events_includes_recent_event_crossing_midnight(self):
        ics_content = "\r\n".join(
            [
                "BEGIN:VCALENDAR",
                "VERSION:2.0",
                "BEGIN:VEVENT",
                "UID:midnight@example.com",
                "DTSTART;TZID=America/New_York:20260827T235900",
                "DTEND;TZID=America/New_York:20260828T003000",
                "SUMMARY:Midnight meeting",
                "END:VEVENT",
                "END:VCALENDAR",
                "",
            ]
        )

        events = self.load_events_from_ics(
            ics_content,
            current=datetime(2026, 8, 28, 4, 1, tzinfo=timezone.utc),
        )

        self.assertEqual(len(events), 1)
        self.assertEqual(str(events[0]["SUMMARY"]), "Midnight meeting")


if __name__ == "__main__":
    unittest.main()
