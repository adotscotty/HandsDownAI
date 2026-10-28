# Can three bets a day make 10%+ profit? (tested Oct 2026)

**No rule we tested got there.** `strategies.py` tried 124 betting rules on past NFL, NBA and college games,
graded against the closing spread or total at -110. 10% profit needs about 57.6% wins; breaking even needs 52.4%.

How it was tested: each rule was judged on 2023-2024 first, and only rules that cleared 10% there would
count, if they also cleared 10% on 2025 (a season that played no part in choosing them).

- **Cleared 10% on 2023-24: none.** The best was NFL underdogs of 7+ points at +5.7% (130 bets), which then lost 2.1% in 2025.
- **Three biggest model-vs-Vegas disagreements each day (any sport):** -4.2% on 2023-24 and -8.2% on 2025 (686 bets, 48% wins).
- **Betting our model's side whenever it disagrees with Vegas:** -2.5% on 2023-24, -0.7% on 2025 (2,410 bets).
- **A trap to avoid:** our model's side when it disagrees by 8+ points made +12.5% in 2025 (112 bets) but lost 11.3% in 2023-24.
  Results that flip from season to season like this are noise, not an edge.

Limits: only spreads and totals have enough history here (no past moneyline or player-prop prices), and the
closing line is harder to beat than the earlier lines the site actually bets. Full numbers: `results.json`.
Run again: `python -m research.strategies`.
