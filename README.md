# Sports AI: game predictions (step 1: data + model)

Predicts the margin of victory and win probability for NFL, NBA and college football (FBS) games,
using only free ESPN data. It runs on its own; nobody needs to touch the code.

## What it does
1. **Team ratings.** Every team has a rating in points. After each game the ratings move toward
   what the score says. Between seasons they are pulled back partway toward average.
2. **Prediction** = home-field edge + home rating - away rating - injury penalty.
   Win probability comes from how big the predicted margin is.
3. **Injuries** (from ESPN's injury report, refreshed every run):
   - NBA: the value of regular rotation players listed Out (full), Doubtful (75%) or Questionable/Day-to-day (30%).
   - NFL and college: whether the team's usual starting quarterback is listed out or doubtful.
4. **Betting line**: ESPN's spread and over/under (ESPN BET) are shown next to our number.

## Last season's backtest (graded on 2025, each game predicted only from earlier games; NFL tuned on 2021-2024, NBA and college on 2024)

| | NFL | NBA | College (FBS v FBS) |
|---|---|---|---|
| Games graded | 285 | 1,316 | 809 |
| Our average miss (points) | 10.0 | 11.3 | 12.7 |
| Betting spread's average miss | 9.6 | 11.0 | 11.8 |
| Picked the winner, us | 64% | 70% | 73% |
| Picked the winner, spread | 66% | 69% | 73% |
| Against the spread, every game | 48% | 50% | 53% |
| Against the spread, when we disagree by 4+ pts | 32% (31 games) | 51% (309 games) | 54% (361 games) |

Breaking even against the spread needs about 52.4%. So the model is about as good as the betting
line at picking winners, slightly worse at the exact margin, and is not yet a proven betting edge.
Win chances are fitted to who actually won, and in the NBA they line up well (games we called 75% were won about 79% of the time).
The injury adjustment improved accuracy in all three sports (NBA most).

NFL extras (added Oct 2026): rest days (bye weeks, short weeks) and quarterback quality (a QB's adjusted
net yards per dropback, so losing a star costs more than losing an average starter). Tested on 2023-2025
(854 games), these took NFL from 63.5% to 64.6% winners and 47.5% to 49.6% against the spread. The NFL
betting line is very hard to beat with scores alone.

Play-by-play test (Oct 2026): we also tried learning team ratings from nflverse play-by-play efficiency
(EPA: all plays, competitive plays only, and without turnovers). On 2023-2025 none of these beat the
current model (best: 49.9% vs 49.6% against the spread, same average miss), and the model doesn't beat
opening lines either (50.3%). So it is not switched on. The code is kept in `sportsai/nflverse.py` and the
model setting `epa_w` (0 = off), with the efficiency numbers saved in `data/games_nfl.csv`.

Caveat: in the backtest, "injured" means the player didn't play (taken from box scores), which is a
bit more than what was known before kickoff. Live predictions use the real pre-game injury report.

## Files
- `sportsai/fetch_history.py` downloads past seasons (scores, closing spreads, who played).
- `sportsai/backtest.py` tunes the settings and grades last season. Results: `data/backtest_summary.json`, `data/backtest_<sport>.csv`.
- `sportsai/predict.py` makes predictions for upcoming games: `data/predictions.json`
  (built to run every 15 minutes) and `data/season_<sport>.csv` (this season's track record so far).

Commands: `python -m sportsai.fetch_history`, `python -m sportsai.backtest`, `python -m sportsai.predict`.
No extra packages needed (plain Python 3).

## When to consider paid data
- **The Odds API (~$30/mo)**: if ESPN stops showing lines, or you want lines from several sportsbooks.
- **SportsDataIO or similar**: if injury news on ESPN lags (e.g. late scratches in the NBA).
- **Licensed data**: before charging money or running ads, since ESPN's API is unofficial and not licensed for commercial use.

## Website and automatic updates
- `site/` is the website (plain HTML/CSS/JS). It reads `site/data/predictions.json` and `site/data/track_record.json`,
  which `python -m sportsai.build_site` writes.
- `.github/workflows/update.yml` runs every 15 minutes on GitHub: fetches the latest scores, injuries and odds,
  makes predictions, rebuilds the site data and publishes it to GitHub Pages. Finished games and the last
  pre-game prediction for each game (`data/pregame_log.csv`) are saved back to the repository.
- `.github/workflows/retune.yml` re-picks the model's settings every quarter (Jan 1, Apr 1, Jul 1, Oct 1)
  using every finished game so far (`python -m sportsai.retune`). New settings are only kept if they
  predicted recent games at least as well as the old ones; each retune is logged under `retunes` in
  `data/backtest_summary.json`.
