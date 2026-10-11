import datetime as dt
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

import daily_brief as brief


SGT = ZoneInfo("Asia/Singapore")


class DailyBriefTests(unittest.TestCase):
    def setUp(self):
        self.start = dt.datetime(2026, 10, 10, 8, 0, tzinfo=SGT)
        self.end = self.start + dt.timedelta(hours=24)

    def test_first_publication_date_blocks_old_online_paper(self):
        work = {
            "published-online": {"date-parts": [[2026, 9, 1]]},
            "published-print": {"date-parts": [[2026, 10, 11]]},
        }
        first = brief.first_publication_date(work)
        self.assertEqual(first, dt.date(2026, 9, 1))
        self.assertFalse(brief.in_window_calendar_day(first, self.start, self.end))

    def test_dedup_excludes_delivered_doi_and_preprint_version(self):
        work = {
            "DOI": "10.1234/abc",
            "title": ["Fusion-driven sarcoma cell states"],
            "container-title": ["Communications Biology"],
            "published-online": {"date-parts": [[2026, 10, 11]]},
            "type": "journal-article",
        }
        with patch.object(brief, "get_json", return_value={"message": {"items": [work]}}):
            journals, errors = brief.collect_journals(self.start, self.end, {"10.1234/abc"})
        self.assertEqual(journals, [])
        self.assertEqual(errors, [])

        biorxiv = {
            "doi": "10.1101/2026.10.11.123456", "version": "2",
            "date": "2026-10-11", "title": "Fusion-driven sarcoma model",
            "abstract": "", "authors": "A. Author",
        }
        with patch.object(brief, "get_json", return_value={"collection": [biorxiv]}):
            preprints, errors = brief.collect_preprints(
                self.start, self.end, {"10.1101/2026.10.11.123456:v2"}
            )
        self.assertEqual(preprints, [])
        self.assertEqual(errors, [])

    def test_zero_paper_report_does_not_fill_quotas(self):
        report, journal_dois, preprint_versions = brief.render(
            self.start, self.end,
            {"journals": [], "preprints": [], "search_notes": "No qualified papers."},
            [], [], [],
        )
        self.assertIn("journal papers 0 篇", report)
        self.assertIn("bioRxiv preprints 0 篇", report)
        self.assertIn("没有用旧论文补数", report)
        self.assertEqual(journal_dois, [])
        self.assertEqual(preprint_versions, [])

    def test_duplicate_selection_fails_instead_of_emailing(self):
        with self.assertRaisesRegex(RuntimeError, "duplicate"):
            brief.selection([{"index": 0}, {"index": 0}], [{"doi": "10.1234/abc"}], 4)

    def test_unverified_publisher_fields_are_not_reported(self):
        article = {"primary_evidence": "citation_title: Fusion-driven sarcoma cell states"}
        model = {"impact_factor": "99.9", "received": "1 January 2026"}
        self.assertEqual(brief.primary_field(model, "impact_factor", article, "impact factor"),
                         "not publicly reported")
        self.assertEqual(brief.primary_field(model, "received", article, "received"),
                         "not publicly reported")


if __name__ == "__main__":
    unittest.main()
