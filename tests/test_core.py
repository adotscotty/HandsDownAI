"""Quick checks for the parts that decide which picks get tracked. Run: python -m unittest -q"""
import datetime as dt, json, os, shutil, tempfile, unittest
from unittest import mock

from sportsai import bestbets, lock, nbainjury, parlays, props

START = dt.datetime(2026, 10, 27, 23, 0, tzinfo=dt.timezone.utc)
PRED = dict(sport="nba", event_id="9", date="2026-10-27T23:00Z", name="A @ B")


def prop(name):
    return dict(pid="1", name=name, stat="pts", label="points", side="over", line=10.5, price=-110,
                projection=12.0, prob=0.6, ev=0.1)


class InjuryReport(unittest.TestCase):
    def test_names(self):
        self.assertEqual(nbainjury.norm("Udeh, Jr., Ernest"), "ernest udeh")
        self.assertEqual(nbainjury.norm("Ernest Udeh Jr."), "ernest udeh")
        self.assertEqual(nbainjury.norm("Dončić, Luka"), "luka doncic")

    def test_line(self):
        line = ("10/27/2026 07:00 (ET) MIN@CLE   Minnesota Timberwolves   Edwards, Anthony   Questionable"
                "   Injury/Illness - Right Hamstring; Strain")
        m = nbainjury.LINE.match(line)
        self.assertIsNotNone(m)
        self.assertEqual(m.group("name"), "Edwards, Anthony")
        self.assertEqual(m.group("status"), "Questionable")
        self.assertIn("Minnesota Timberwolves", m.group("pre"))


def at(now):
    """Pretend the clock reads `now`."""
    p = mock.patch.object(dt, "datetime", wraps=dt.datetime)
    fake = p.start()
    fake.now.return_value = now
    fake.fromisoformat = dt.datetime.fromisoformat
    return p


class Locking(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.patches = [mock.patch.object(lock, "PATH", os.path.join(self.dir, "drafts.json")),
                        mock.patch.object(props, "DATA", self.dir),
                        mock.patch.object(bestbets, "DATA", self.dir),
                        mock.patch.object(bestbets, "LOG", os.path.join(self.dir, "bestbets_log.csv")),
                        mock.patch.object(bestbets, "results", lambda: {}),
                        mock.patch.object(bestbets, "box_scores", lambda rows: {}),
                        mock.patch.object(parlays, "DATA", self.dir),
                        mock.patch.object(parlays, "LOG", os.path.join(self.dir, "parlays_log.csv")),
                        mock.patch.object(parlays, "results", lambda: {})]
        for p in self.patches:
            p.start()

    def tearDown(self):
        for p in self.patches:
            p.stop()
        shutil.rmtree(self.dir)

    # --- props ---
    def run_at(self, minutes_before, name, in_preds=True):
        p = at(START - dt.timedelta(minutes=minutes_before))
        try:
            preds = [dict(PRED, best_prop=prop(name) if name else None)] if in_preds else []
            return props.lock_and_grade(preds, {})
        finally:
            p.stop()

    def test_window(self):
        self.assertTrue(lock.in_window("2026-10-27T23:00Z", START - dt.timedelta(minutes=25)))
        self.assertFalse(lock.in_window("2026-10-27T23:00Z", START - dt.timedelta(minutes=26)))

    def test_locks_inside_window(self):
        self.assertEqual(self.run_at(40, "early"), [])
        self.assertEqual([r["name"] for r in self.run_at(20, "inside")], ["inside"])
        self.assertEqual([r["name"] for r in self.run_at(5, "later change")], ["inside"])  # locked stays locked

    def test_missed_window_locks_last_draft(self):
        self.run_at(65, "early")
        self.run_at(40, "last shown")
        log = self.run_at(-5, None, in_preds=False)   # started games drop out of the predictions
        self.assertEqual([r["name"] for r in log], ["last shown"])
        self.assertEqual(log[0]["logged_at"], "2026-10-27T22:20+00:00")
        self.assertEqual(lock.load(), {})

    def test_prop_that_disappeared_is_not_locked(self):
        self.run_at(65, "early")
        self.run_at(40, None)                          # no prop shown any more
        self.assertEqual(self.run_at(-5, None, in_preds=False), [])

    # --- best bets ---
    def best_at(self, now, picks):
        p = at(now)
        try:
            with mock.patch.object(bestbets, "candidates", lambda preds, day, n: dict(picks)):
                bestbets.update([], {})
            return bestbets.load_log()
        finally:
            p.stop()

    def winner(self, start):
        return dict(kind="winner", start=start, legs=[dict(type="ml", event_id="1", start=start)])

    def test_late_game_missed_after_midnight_still_locks(self):
        late = "2026-10-28T03:00Z"                      # 11 PM Eastern on Oct 27
        self.best_at(dt.datetime(2026, 10, 28, 2, 30, tzinfo=dt.timezone.utc), {"winner": self.winner(late)})
        log = self.best_at(dt.datetime(2026, 10, 28, 4, 10, tzinfo=dt.timezone.utc), {})   # 12:10 AM Oct 28
        self.assertEqual(list(log), ["2026-10-27|winner"])

    def test_dropped_best_bet_is_not_locked(self):
        game = "2026-10-27T23:00Z"
        self.best_at(START - dt.timedelta(minutes=120), {"winner": self.winner(game)})
        self.best_at(START - dt.timedelta(minutes=30), {})        # no winner shown any more
        self.assertEqual(self.best_at(START + dt.timedelta(minutes=5), {}), {})

    # --- parlays page ---
    def test_parlay_card_missed_after_midnight_still_locks(self):
        legs = [dict(event_id=str(i), sport="nba", side="home", team="T", game="A @ B", line=-2.5,
                     start="2026-10-28T03:00Z", odds=-110, chance=0.55) for i in range(2)]
        card = dict(legs=legs, chance=0.3, payout=52.0, projected_profit=-4.0)
        with mock.patch.object(parlays, "best_parlays", lambda pool, size, n=1: [dict(card)] if size == 2 else []), \
             mock.patch.object(parlays, "legs_for", lambda preds, now: legs * 2):
            p = at(dt.datetime(2026, 10, 28, 2, 30, tzinfo=dt.timezone.utc)); parlays.update_parlays([]); p.stop()
        with mock.patch.object(parlays, "legs_for", lambda preds, now: []):
            p = at(dt.datetime(2026, 10, 28, 4, 10, tzinfo=dt.timezone.utc)); parlays.update_parlays([]); p.stop()
        self.assertEqual(sorted(parlays.load_log()), ["2026-10-27|nba|two"])


class PropPick(unittest.TestCase):
    """Per-game prop: DraftKings' most likely side, only when it is at least 65% likely (tested 2026-10-28)."""
    class Proj:
        names = {"1": "A", "2": "B"}
        def project(self, pid, stat): return 10.0
        def sd(self, proj, stat): return 4.0

    def test_skips_weak_favorites(self):
        # -150 / +125 is about 58% likely after removing the book's cut: no pick
        self.assertIsNone(props.best_prop(self.Proj(), [("1", "pts", 10.5, -150, 125)]))

    def test_keeps_strong_favorite(self):
        # -250 / +200 is about 69% likely: pick it
        b = props.best_prop(self.Proj(), [("1", "pts", 10.5, -150, 125), ("2", "reb", 4.5, -250, 200)])
        self.assertEqual((b["pid"], b["side"]), ("2", "over"))


class SameGameParlayProp(unittest.TestCase):
    """The same-game parlay keeps its original prop rule (no 65% minimum), so it still shows most days."""
    def test_sgp_rule_allows_weaker_favorite(self):
        b = props.best_prop(PropPick.Proj(), [("1", "pts", 10.5, -150, 125)], min_fair=0.5)
        self.assertEqual((b["pid"], b["side"]), ("1", "over"))

    def test_sgp_uses_its_own_prop(self):
        leg = bestbets.prop_leg(dict(PRED, home="B", away="A", best_prop=None, sgp_prop=dict(
            pid="1", name="A", stat="pts", label="points", side="over", line=10.5, price="-150", prob=0.6,
            market_prob=0.58, projection=12.0)), for_sgp=True)
        self.assertEqual(leg["pid"], "1")


class SiteBuild(unittest.TestCase):
    def test_build_runs_on_saved_data(self):
        """The site build must finish on today's saved data (a crash here once froze the site)."""
        import subprocess, sys
        root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        tmp = tempfile.mkdtemp()
        try:
            for d in ("sportsai", "site"):
                shutil.copytree(os.path.join(root, d), os.path.join(tmp, d))
            os.symlink(os.path.join(root, "data"), os.path.join(tmp, "data"))  # read only; the build writes to site/
            r = subprocess.run([sys.executable, "-m", "sportsai.build_site"], cwd=tmp, capture_output=True, text=True, timeout=300)
            self.assertEqual(r.returncode, 0, r.stderr[-2000:])
            for f in ("predictions.json", "track_record.json", "daily.json", "bestbets.json"):
                with open(os.path.join(tmp, "site", "data", f)) as fh:
                    json.load(fh)
        finally:
            shutil.rmtree(tmp)


if __name__ == "__main__":
    unittest.main()
