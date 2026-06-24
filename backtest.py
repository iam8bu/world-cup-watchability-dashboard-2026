#!/usr/bin/env python3
"""backtest.py — Empirical validation suite for the SPI Poisson match model.

Five analyses, each selectable via CLI flag:

  (default)  Walk-forward backtest against completed WC2026 results.
             Refits GLM once per matchday (no look-ahead leakage) and
             reports log loss / Brier score by confederation pairing.
             Note: no checkpointing — an interrupted run must restart from scratch.

  --decay    Recency decay rate sensitivity (tested: /3, /5, /7, /10 years).
             Uses held-out last-10% of historical_matches as validation set.

  --weights  Tournament importance weight scheme sensitivity (4 schemes tested).
             Same held-out split as --decay.

  --schedule Confederation schedule-strength bias check for all 48 WC2026 teams.

  --rho      Dixon-Coles rho grid search (-0.20 to 0.00) against observed
             low-score frequencies and overall log loss.
             Finding: production rho=-0.13 is slightly conservative vs. this
             dataset; best-fit -0.08 (LL) / -0.03 (SSD). Gap negligible (<0.001 LL).

All constants (DIXON_COLES_RHO, RECENCY_DECAY_YEARS) imported from spi_model.py
so this script's baselines automatically track any production changes.
"""

import math
import sqlite3
import sys
from collections import defaultdict

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from scipy.stats import poisson, ttest_ind

from spi_model import (
    normalize,
    tournament_weight,
    load_historical_from_db,
    score_matrix,
    dixon_coles_correction,
    match_probs,
    DIXON_COLES_RHO,
    RECENCY_DECAY_YEARS,
)

ODDS_DB_PATH = "odds.db"

# ── Confederation lookup (all 48 WC2026 teams) ───────────────────────────────
CONFEDERATION: dict[str, str] = {
    # CONCACAF
    "Mexico":            "CONCACAF",
    "United States":     "CONCACAF",
    "Canada":            "CONCACAF",
    "Haiti":             "CONCACAF",
    "Panama":            "CONCACAF",
    "Curacao":           "CONCACAF",
    # CONMEBOL
    "Brazil":            "CONMEBOL",
    "Argentina":         "CONMEBOL",
    "Colombia":          "CONMEBOL",
    "Uruguay":           "CONMEBOL",
    "Paraguay":          "CONMEBOL",
    "Ecuador":           "CONMEBOL",
    # UEFA
    "Spain":             "UEFA",
    "France":            "UEFA",
    "Germany":           "UEFA",
    "England":           "UEFA",
    "Netherlands":       "UEFA",
    "Portugal":          "UEFA",
    "Belgium":           "UEFA",
    "Czechia":           "UEFA",
    "Croatia":           "UEFA",
    "Sweden":            "UEFA",
    "Scotland":          "UEFA",
    "Norway":            "UEFA",
    "Austria":           "UEFA",
    "Switzerland":       "UEFA",
    "Bosnia-Herzegovina":"UEFA",
    "Turkiye":           "UEFA",
    # CAF
    "Morocco":           "CAF",
    "Senegal":           "CAF",
    "Ghana":             "CAF",
    "DR Congo":          "CAF",
    "Algeria":           "CAF",
    "Egypt":             "CAF",
    "Tunisia":           "CAF",
    "Cape Verde":        "CAF",
    "Ivory Coast":       "CAF",
    "South Africa":      "CAF",
    # AFC
    "South Korea":       "AFC",
    "Japan":             "AFC",
    "Saudi Arabia":      "AFC",
    "Iran":              "AFC",
    "Australia":         "AFC",
    "Qatar":             "AFC",
    "Uzbekistan":        "AFC",
    "Jordan":            "AFC",
    "Iraq":              "AFC",
    # OFC
    "New Zealand":       "OFC",
}


def load_wc2026_results() -> list[dict]:
    """Load all completed WC2026 results from odds.db, sorted by fetch date."""
    conn = sqlite3.connect(ODDS_DB_PATH)
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(match_results)").fetchall()]
        where = "WHERE completed = 1" if "completed" in cols else ""
        rows = conn.execute(
            f"SELECT home_team, away_team, home_score, away_score, fetched_at "
            f"FROM match_results {where} ORDER BY fetched_at"
        ).fetchall()
    finally:
        conn.close()

    results = []
    for home, away, hs, aws, fetched_at in rows:
        results.append({
            "home_team":  normalize(home),
            "away_team":  normalize(away),
            "home_score": int(hs),
            "away_score": int(aws),
            "date":       pd.to_datetime(fetched_at).date(),
        })
    return results


def fit_glm_in_memory(historical_df, wc_prior):
    """
    Fit Poisson GLM on historical_df + wc_prior completed WC matches.
    Returns (ratings, home_adv_coef, intercept) with
    ratings = {team: (attack_rating, defense_rating)}, or None on failure.
    Replicates the fitting logic from spi_model.main() without writing to DB.
    """
    rows_to_add = []
    for r in wc_prior:
        rows_to_add.append({
            "date":       r["date"],
            "home_team":  r["home_team"],
            "away_team":  r["away_team"],
            "home_score": r["home_score"],
            "away_score": r["away_score"],
            "tournament": "FIFA World Cup",
            "neutral":    "True",
        })

    if rows_to_add:
        df = pd.concat([historical_df, pd.DataFrame(rows_to_add)], ignore_index=True)
    else:
        df = historical_df.copy()

    reference_date = df["date"].max()

    obs = []
    for row in df.itertuples(index=False):
        try:
            hs  = int(row.home_score)
            aws = int(row.away_score)
        except (ValueError, TypeError):
            continue
        years_ago = (reference_date - row.date).days / 365.25
        recency   = math.exp(-years_ago / RECENCY_DECAY_YEARS)
        imp       = tournament_weight(str(row.tournament))
        w         = imp * recency
        neutral   = str(getattr(row, "neutral", "False")).strip().lower() == "true"
        obs.append({"goals": hs,  "attack": row.home_team, "defense": row.away_team,
                    "home_adv": 0.0 if neutral else 1.0, "weight": w})
        obs.append({"goals": aws, "attack": row.away_team, "defense": row.home_team,
                    "home_adv": 0.0, "weight": w})

    model_df = pd.DataFrame(obs)
    wvals = model_df["weight"].values.astype(float)
    bad   = ~np.isfinite(wvals) | (wvals <= 0)
    if bad.any():
        model_df = model_df[~bad].copy()
        wvals    = model_df["weight"].values.astype(float)
    model_df = model_df.copy()
    model_df["weight"] = wvals / wvals.mean()

    try:
        result = smf.glm(
            "goals ~ home_adv + C(attack) + C(defense)",
            data=model_df,
            family=sm.families.Poisson(),
            freq_weights=model_df["weight"],
        ).fit_regularized(alpha=1e-4, L1_wt=0, disp=False)
    except Exception as e:
        print(f" GLM fit error: {e}")
        return None

    params        = result.params
    intercept     = float(params["Intercept"])
    home_adv_coef = float(params.get("home_adv", 0.0))

    ratings: dict[str, tuple[float, float]] = {}
    for team in set(model_df["attack"].unique()):
        ac = float(params.get(f"C(attack)[T.{team}]", 0.0))
        dc = float(params.get(f"C(defense)[T.{team}]", 0.0))
        ratings[team] = (math.exp(intercept + ac), math.exp(intercept + dc))

    return ratings, home_adv_coef, intercept


def predict(home, away, ratings, home_adv_coef, intercept, neutral=True):
    """Return (p_home_win, p_draw, p_away_win) using in-memory ratings."""
    if home not in ratings or away not in ratings:
        return None
    baseline     = math.exp(intercept)
    ar_h, dr_h   = ratings[home]
    ar_a, dr_a   = ratings[away]
    mu_h = ar_h * dr_a / baseline
    mu_a = ar_a * dr_h / baseline
    if not neutral:
        mu_h *= math.exp(home_adv_coef)
    mat = dixon_coles_correction(score_matrix(mu_h, mu_a), mu_h, mu_a)
    return match_probs(mat)


def log_loss_single(probs: tuple, outcome_idx: int) -> float:
    return -math.log(max(probs[outcome_idx], 1e-10))


def brier_score_single(probs: tuple, outcome_idx: int) -> float:
    actuals = [0.0, 0.0, 0.0]
    actuals[outcome_idx] = 1.0
    return sum((p - a) ** 2 for p, a in zip(probs, actuals))


def conf_pairing(home: str, away: str) -> str:
    hc = CONFEDERATION.get(home, "UNK")
    ac = CONFEDERATION.get(away, "UNK")
    if hc == ac:
        return f"{hc} vs {hc}"
    return " vs ".join(sorted([hc, ac]))


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    W = 72
    print("=" * W)
    print("  WC2026 SPI Model Backtest")
    print("=" * W)

    historical_df = load_historical_from_db()
    print(f"  Historical:  {len(historical_df):,} matches  "
          f"({historical_df['date'].min()} → {historical_df['date'].max()})")

    all_wc = load_wc2026_results()
    if not all_wc:
        print("No completed WC2026 results found in odds.db.")
        sys.exit(0)

    # Group by fetch date → matchday
    by_day: dict = defaultdict(list)
    for r in all_wc:
        by_day[r["date"]].append(r)
    matchdays = sorted(by_day.keys())

    print(f"  WC2026:      {len(all_wc)} results across {len(matchdays)} matchday(s)\n")

    records: list[dict] = []

    # Walk-forward: refit GLM once per matchday using only data available before
    # that date (no look-ahead leakage). No checkpointing — if interrupted,
    # restart from scratch. Fits are not cached between runs.
    for day in matchdays:
        matches_today = by_day[day]
        wc_prior      = [r for r in all_wc if r["date"] < day]

        print(f"  [{day}]  {len(matches_today)} match(es)  —  "
              f"training on hist + {len(wc_prior)} prior WC result(s) … ", end="", flush=True)

        fit = fit_glm_in_memory(historical_df, wc_prior)
        if fit is None:
            print("FAILED — skipping")
            continue
        ratings, home_adv_coef, intercept = fit
        print("done")

        for r in matches_today:
            home, away = r["home_team"], r["away_team"]
            hs,   aws  = r["home_score"], r["away_score"]
            probs = predict(home, away, ratings, home_adv_coef, intercept, neutral=True)
            if probs is None:
                print(f"    ⚠  Missing ratings for {home} or {away} — skipped")
                continue

            if   hs > aws: outcome_idx, outcome_str = 0, "H"
            elif hs < aws: outcome_idx, outcome_str = 2, "A"
            else:          outcome_idx, outcome_str = 1, "D"

            records.append({
                "date":      day,
                "home":      home,
                "away":      away,
                "score":     f"{hs}-{aws}",
                "outcome":   outcome_str,
                "p_home":    probs[0],
                "p_draw":    probs[1],
                "p_away":    probs[2],
                "p_correct": probs[outcome_idx],
                "log_loss":  log_loss_single(probs, outcome_idx),
                "brier":     brier_score_single(probs, outcome_idx),
                "pair":      conf_pairing(home, away),
            })

    if not records:
        print("\nNo matches evaluated.")
        return

    n          = len(records)
    avg_ll     = sum(r["log_loss"] for r in records) / n
    avg_brier  = sum(r["brier"]    for r in records) / n
    baseline   = -math.log(1 / 3)

    print(f"\n{'=' * W}")
    print(f"  RESULTS  ({n} matches evaluated)")
    print(f"{'=' * W}")
    print(f"\n  Overall")
    print(f"    Avg log loss   : {avg_ll:.4f}  (random baseline: {baseline:.4f})")
    print(f"    Avg Brier      : {avg_brier:.4f}  (random baseline: {1/3 * 2:.4f})")
    print(f"    Improvement LL : {(baseline - avg_ll) / baseline * 100:.1f}% vs random")

    # ── Confederation pairing breakdown ──────────────────────────────────────
    pair_stats: dict[str, list] = defaultdict(list)
    for r in records:
        pair_stats[r["pair"]].append(r["log_loss"])

    print(f"\n  Log loss by confederation pairing:")
    print(f"    {'Pairing':<32}  {'n':>3}  {'avg LL':>7}  {'vs random':>9}")
    for pair, lls in sorted(pair_stats.items(), key=lambda x: sum(x[1]) / len(x[1])):
        if len(lls) < 1:
            continue
        avg = sum(lls) / len(lls)
        delta = baseline - avg
        print(f"    {pair:<32}  {len(lls):>3}  {avg:>7.4f}  {delta:>+8.4f}")

    # ── Top 5 misses ─────────────────────────────────────────────────────────
    by_ll = sorted(records, key=lambda r: -r["log_loss"])

    print(f"\n  Top 5 biggest misses (highest log loss):")
    hdr = f"    {'Match':<38} {'Scr':<5} {'H%':>5} {'D%':>5} {'A%':>5} {'p✓':>6}  {'LL':>7}"
    print(hdr)
    print(f"    {'─' * (W - 4)}")
    for r in by_ll[:5]:
        print(
            f"    {r['home'] + ' v ' + r['away']:<38} {r['score']:<5} "
            f"{r['p_home']*100:>4.0f}% {r['p_draw']*100:>4.0f}% {r['p_away']*100:>4.0f}% "
            f"{r['p_correct']*100:>5.1f}%  {r['log_loss']:>7.4f}"
        )

    # ── Top 5 best ───────────────────────────────────────────────────────────
    print(f"\n  Top 5 best predictions (lowest log loss):")
    print(hdr)
    print(f"    {'─' * (W - 4)}")
    for r in by_ll[-5:][::-1]:
        print(
            f"    {r['home'] + ' v ' + r['away']:<38} {r['score']:<5} "
            f"{r['p_home']*100:>4.0f}% {r['p_draw']*100:>4.0f}% {r['p_away']*100:>4.0f}% "
            f"{r['p_correct']*100:>5.1f}%  {r['log_loss']:>7.4f}"
        )

    # ── Full match table ─────────────────────────────────────────────────────
    print(f"\n  Full match log (sorted by log loss desc):")
    print(hdr)
    print(f"    {'─' * (W - 4)}")
    for r in by_ll:
        print(
            f"    {r['home'] + ' v ' + r['away']:<38} {r['score']:<5} "
            f"{r['p_home']*100:>4.0f}% {r['p_draw']*100:>4.0f}% {r['p_away']*100:>4.0f}% "
            f"{r['p_correct']*100:>5.1f}%  {r['log_loss']:>7.4f}"
        )

    print(f"\n{'=' * W}\n")


# ── Part 2: Decay Rate Sensitivity ───────────────────────────────────────────

def fit_glm_with_decay(df, decay_years):
    """
    Fit Poisson GLM on df using the given exponential decay half-life.
    Identical to fit_glm_in_memory's fitting logic but decay_years is explicit
    and no WC rows are injected — pure historical evaluation.
    Returns (ratings, home_adv_coef, intercept) or None on failure.
    """
    reference_date = df["date"].max()
    obs = []
    for row in df.itertuples(index=False):
        try:
            hs  = int(row.home_score)
            aws = int(row.away_score)
        except (ValueError, TypeError):
            continue
        years_ago = (reference_date - row.date).days / 365.25
        recency   = math.exp(-years_ago / decay_years)
        imp       = tournament_weight(str(row.tournament))
        w         = imp * recency
        neutral   = str(getattr(row, "neutral", "False")).strip().lower() == "true"
        obs.append({"goals": hs,  "attack": row.home_team, "defense": row.away_team,
                    "home_adv": 0.0 if neutral else 1.0, "weight": w})
        obs.append({"goals": aws, "attack": row.away_team, "defense": row.home_team,
                    "home_adv": 0.0, "weight": w})

    model_df = pd.DataFrame(obs)
    wvals = model_df["weight"].values.astype(float)
    bad   = ~np.isfinite(wvals) | (wvals <= 0)
    if bad.any():
        model_df = model_df[~bad].copy()
        wvals    = model_df["weight"].values.astype(float)
    model_df = model_df.copy()
    model_df["weight"] = wvals / wvals.mean()

    try:
        result = smf.glm(
            "goals ~ home_adv + C(attack) + C(defense)",
            data=model_df,
            family=sm.families.Poisson(),
            freq_weights=model_df["weight"],
        ).fit_regularized(alpha=1e-4, L1_wt=0, disp=False)
    except Exception as e:
        print(f"GLM fit error: {e}")
        return None

    params        = result.params
    intercept     = float(params["Intercept"])
    home_adv_coef = float(params.get("home_adv", 0.0))

    ratings = {}
    for team in set(model_df["attack"].unique()):
        ac = float(params.get(f"C(attack)[T.{team}]", 0.0))
        dc = float(params.get(f"C(defense)[T.{team}]", 0.0))
        ratings[team] = (math.exp(intercept + ac), math.exp(intercept + dc))

    return ratings, home_adv_coef, intercept


def decay_sensitivity() -> None:
    W = 72
    print("=" * W)
    print("  Part 2: Decay Rate Sensitivity  (historical data only, no WC2026)")
    print("=" * W)

    historical_df = load_historical_from_db()

    # Chronological 90/10 split — validation is the most recent 10%
    sorted_df = historical_df.sort_values("date").reset_index(drop=True)
    split_idx = int(len(sorted_df) * 0.9)
    train_df  = sorted_df.iloc[:split_idx].copy()
    val_df    = sorted_df.iloc[split_idx:].copy()

    print(f"  Train : {len(train_df):,} matches  "
          f"({train_df['date'].min()} → {train_df['date'].max()})")
    print(f"  Val   : {len(val_df):,} matches  "
          f"({val_df['date'].min()} → {val_df['date'].max()})")
    print()

    decay_rates = [3, 5, 7, 10]
    rows = []

    for decay in decay_rates:
        print(f"  decay={decay}y — fitting … ", end="", flush=True)
        fit = fit_glm_with_decay(train_df, decay)
        if fit is None:
            print("FAILED")
            continue
        ratings, home_adv_coef, intercept = fit
        print("done — evaluating … ", end="", flush=True)

        lls, briers, skipped = [], [], 0
        for row in val_df.itertuples(index=False):
            try:
                hs  = int(row.home_score)
                aws = int(row.away_score)
            except (ValueError, TypeError):
                skipped += 1
                continue

            neutral = str(getattr(row, "neutral", "False")).strip().lower() == "true"
            probs = predict(row.home_team, row.away_team,
                            ratings, home_adv_coef, intercept, neutral=neutral)
            if probs is None:
                skipped += 1
                continue

            if   hs > aws: outcome_idx = 0
            elif hs < aws: outcome_idx = 2
            else:          outcome_idx = 1

            lls.append(log_loss_single(probs, outcome_idx))
            briers.append(brier_score_single(probs, outcome_idx))

        n_eval = len(lls)
        avg_ll = sum(lls)    / n_eval if lls    else float("nan")
        avg_bs = sum(briers) / n_eval if briers else float("nan")
        print(f"{n_eval:,} evaluated  ({skipped} skipped)")
        rows.append({"decay": decay, "n": n_eval, "avg_ll": avg_ll, "avg_bs": avg_bs})

    if not rows:
        print("No results.")
        return

    baseline_ll = -math.log(1 / 3)
    baseline_bs = 2 / 3          # uniform 3-outcome Brier baseline

    best = min(rows, key=lambda r: r["avg_ll"])

    print()
    print(f"  {'Decay':>7}  {'n':>6}  {'Avg LL':>8}  {'Avg Brier':>10}  "
          f"{'vs random':>10}  {'':}")
    print(f"  {'─' * 62}")
    for r in rows:
        marker = " ← best" if r["decay"] == best["decay"] else ""
        delta  = (baseline_ll - r["avg_ll"]) / baseline_ll * 100
        print(f"  {r['decay']:>5}y   {r['n']:>6,}  {r['avg_ll']:>8.4f}  "
              f"{r['avg_bs']:>10.4f}  {delta:>9.1f}%{marker}")
    print(f"  {'random':>7}  {'—':>6}  {baseline_ll:>8.4f}  {baseline_bs:>10.4f}  "
          f"{'0.0%':>10}")

    print(f"\n  Best decay rate by log loss: /{best['decay']}y  "
          f"(avg LL {best['avg_ll']:.4f})")
    print(f"{'=' * W}\n")


# ── Part 3: Match Importance Weight Sensitivity ───────────────────────────────

_CONTINENTAL_KEYWORDS = (
    "uefa euro", "uefa european championship",
    "copa am", "copa áme",
    "africa cup of nations",
    "afc asian cup",
    "concacaf gold cup", "gold cup",
    "ofc nations cup",
    "confederations cup",
)


def _make_weight_fn(wc, continental, qualifier, friendly):
    """Return a tournament_weight-compatible callable with custom multipliers.
    Uses the same classification logic as spi_model.tournament_weight."""
    def _fn(tournament):
        t = tournament.lower()
        is_q = "qualif" in t or "qualifying" in t or "qualification" in t
        if "world cup" in t and not is_q:
            return wc
        if any(k in t for k in _CONTINENTAL_KEYWORDS) and not is_q:
            return continental
        if is_q:
            return qualifier
        return friendly
    return _fn


def fit_glm_with_scheme(df, decay_years, weight_fn):
    """
    Fit Poisson GLM on df using decay_years for recency and weight_fn for
    tournament importance. Identical structure to fit_glm_with_decay but
    accepts a custom weight callable instead of tournament_weight.
    Returns (ratings, home_adv_coef, intercept) or None on failure.
    """
    reference_date = df["date"].max()
    obs = []
    for row in df.itertuples(index=False):
        try:
            hs  = int(row.home_score)
            aws = int(row.away_score)
        except (ValueError, TypeError):
            continue
        years_ago = (reference_date - row.date).days / 365.25
        recency   = math.exp(-years_ago / decay_years)
        imp       = weight_fn(str(row.tournament))
        w         = imp * recency
        neutral   = str(getattr(row, "neutral", "False")).strip().lower() == "true"
        obs.append({"goals": hs,  "attack": row.home_team, "defense": row.away_team,
                    "home_adv": 0.0 if neutral else 1.0, "weight": w})
        obs.append({"goals": aws, "attack": row.away_team, "defense": row.home_team,
                    "home_adv": 0.0, "weight": w})

    model_df = pd.DataFrame(obs)
    wvals = model_df["weight"].values.astype(float)
    bad   = ~np.isfinite(wvals) | (wvals <= 0)
    if bad.any():
        model_df = model_df[~bad].copy()
        wvals    = model_df["weight"].values.astype(float)
    model_df = model_df.copy()
    model_df["weight"] = wvals / wvals.mean()

    try:
        result = smf.glm(
            "goals ~ home_adv + C(attack) + C(defense)",
            data=model_df,
            family=sm.families.Poisson(),
            freq_weights=model_df["weight"],
        ).fit_regularized(alpha=1e-4, L1_wt=0, disp=False)
    except Exception as e:
        print(f"GLM fit error: {e}")
        return None

    params        = result.params
    intercept     = float(params["Intercept"])
    home_adv_coef = float(params.get("home_adv", 0.0))

    ratings = {}
    for team in set(model_df["attack"].unique()):
        ac = float(params.get(f"C(attack)[T.{team}]", 0.0))
        dc = float(params.get(f"C(defense)[T.{team}]", 0.0))
        ratings[team] = (math.exp(intercept + ac), math.exp(intercept + dc))

    return ratings, home_adv_coef, intercept


def weight_sensitivity() -> None:
    W = 72
    DECAY = RECENCY_DECAY_YEARS   # hold decay constant at current default; vary weights only

    print("=" * W)
    print("  Part 3: Importance Weight Sensitivity  (historical only, decay=5y)")
    print("=" * W)

    historical_df = load_historical_from_db()

    # Same deterministic 90/10 chronological split as Part 2
    sorted_df = historical_df.sort_values("date").reset_index(drop=True)
    split_idx = int(len(sorted_df) * 0.9)
    train_df  = sorted_df.iloc[:split_idx].copy()
    val_df    = sorted_df.iloc[split_idx:].copy()

    print(f"  Train : {len(train_df):,} matches  "
          f"({train_df['date'].min()} → {train_df['date'].max()})")
    print(f"  Val   : {len(val_df):,} matches  "
          f"({val_df['date'].min()} → {val_df['date'].max()})")
    print()

    schemes = [
        ("Current",  _make_weight_fn(4.0, 3.0,  2.0, 1.0),  "WC=4 Cont=3 Qual=2 Fr=1"),
        ("Flatter",  _make_weight_fn(2.0, 1.75, 1.5, 1.0),  "WC=2 Cont=1.75 Qual=1.5 Fr=1"),
        ("Steeper",  _make_weight_fn(6.0, 4.0,  2.0, 0.5),  "WC=6 Cont=4 Qual=2 Fr=0.5"),
        ("Equal",    _make_weight_fn(1.0, 1.0,  1.0, 1.0),  "all weights=1"),
    ]

    rows = []
    for name, weight_fn, desc in schemes:
        print(f"  {name:<8} ({desc}) — fitting … ", end="", flush=True)
        fit = fit_glm_with_scheme(train_df, DECAY, weight_fn)
        if fit is None:
            print("FAILED")
            continue
        ratings, home_adv_coef, intercept = fit
        print("done — evaluating … ", end="", flush=True)

        lls, briers, skipped = [], [], 0
        for row in val_df.itertuples(index=False):
            try:
                hs  = int(row.home_score)
                aws = int(row.away_score)
            except (ValueError, TypeError):
                skipped += 1
                continue

            neutral = str(getattr(row, "neutral", "False")).strip().lower() == "true"
            probs = predict(row.home_team, row.away_team,
                            ratings, home_adv_coef, intercept, neutral=neutral)
            if probs is None:
                skipped += 1
                continue

            if   hs > aws: outcome_idx = 0
            elif hs < aws: outcome_idx = 2
            else:          outcome_idx = 1

            lls.append(log_loss_single(probs, outcome_idx))
            briers.append(brier_score_single(probs, outcome_idx))

        n_eval = len(lls)
        avg_ll = sum(lls)    / n_eval if lls    else float("nan")
        avg_bs = sum(briers) / n_eval if briers else float("nan")
        print(f"{n_eval:,} evaluated  ({skipped} skipped)")
        rows.append({"name": name, "desc": desc, "n": n_eval,
                     "avg_ll": avg_ll, "avg_bs": avg_bs})

    if not rows:
        print("No results.")
        return

    baseline_ll = -math.log(1 / 3)
    baseline_bs = 2 / 3
    best = min(rows, key=lambda r: r["avg_ll"])

    print()
    print(f"  {'Scheme':<10}  {'n':>6}  {'Avg LL':>8}  {'Avg Brier':>10}  "
          f"{'vs random':>10}")
    print(f"  {'─' * 58}")
    for r in rows:
        marker = " ← best" if r["name"] == best["name"] else ""
        delta  = (baseline_ll - r["avg_ll"]) / baseline_ll * 100
        print(f"  {r['name']:<10}  {r['n']:>6,}  {r['avg_ll']:>8.4f}  "
              f"{r['avg_bs']:>10.4f}  {delta:>9.1f}%{marker}")
    print(f"  {'random':<10}  {'—':>6}  {baseline_ll:>8.4f}  {baseline_bs:>10.4f}  "
          f"{'0.0%':>10}")

    print(f"\n  Best scheme by log loss: {best['name']}  ({best['desc']})")
    print(f"  Avg LL {best['avg_ll']:.4f}  vs Current {next(r['avg_ll'] for r in rows if r['name']=='Current'):.4f}")
    print(f"{'=' * W}\n")


# ── Part 4: Confederation Schedule Strength Bias ──────────────────────────────

def schedule_strength_bias() -> None:
    W    = 72
    DECAY     = RECENCY_DECAY_YEARS
    N_MATCHES = 15

    print("=" * W)
    print("  Part 4: Confederation Schedule Strength Bias")
    print("=" * W)

    historical_df = load_historical_from_db()
    reference_date = historical_df["date"].max()

    print(f"  Historical: {len(historical_df):,} matches  "
          f"({historical_df['date'].min()} → {reference_date})")
    print(f"  Fitting GLM (all data, decay={DECAY}y) … ", end="", flush=True)

    fit = fit_glm_with_decay(historical_df, DECAY)
    if fit is None:
        print("FAILED")
        return
    ratings, _, intercept = fit
    print("done")

    # Strength score: attack_rating + defense_strength (= 1/defense_rating),
    # normalized 0-100 relative to all teams present in the model.
    raw_strength  = {t: ar + 1.0 / dr for t, (ar, dr) in ratings.items()}
    max_str       = max(raw_strength.values())
    norm_str      = {t: s / max_str * 100.0 for t, s in raw_strength.items()}
    fallback_str  = sum(norm_str.values()) / len(norm_str)  # global model mean for unknown opponents

    # For each WC2026 team, recency-weighted avg opponent strength over last N_MATCHES.
    wc_teams     = sorted(CONFEDERATION.keys())
    team_sched: dict[str, float] = {}
    team_n:     dict[str, int]   = {}
    excluded:   list[str]        = []

    for team in wc_teams:
        mask = (historical_df["home_team"] == team) | (historical_df["away_team"] == team)
        recent = (
            historical_df[mask]
            .sort_values("date", ascending=False)
            .head(N_MATCHES)
        )
        if recent.empty:
            excluded.append(team)
            continue

        w_sum, w_tot = 0.0, 0.0
        for row in recent.itertuples(index=False):
            opp      = row.away_team if row.home_team == team else row.home_team
            opp_str  = norm_str.get(opp, fallback_str)
            years_ago = (reference_date - row.date).days / 365.25
            w        = math.exp(-years_ago / DECAY) * tournament_weight(str(row.tournament))
            w_sum   += w * opp_str
            w_tot   += w

        if w_tot > 0:
            team_sched[team] = w_sum / w_tot
            team_n[team]     = len(recent)
        else:
            excluded.append(team)

    if not team_sched:
        print("No schedule strength data computed.")
        return

    all_scores  = list(team_sched.values())
    global_mean = sum(all_scores) / len(all_scores)
    global_std  = (sum((s - global_mean) ** 2 for s in all_scores) / len(all_scores)) ** 0.5
    team_z      = {t: (s - global_mean) / global_std for t, s in team_sched.items()}

    # ── Full per-team table ───────────────────────────────────────────────────
    print(f"\n  Strength = recency-weighted avg opponent score (0–100) over last {N_MATCHES} matches")
    print(f"  Global mean: {global_mean:.1f}  std: {global_std:.1f}\n")
    print(f"  {'Team':<26} {'Conf':<10} {'n':>3} {'Sched':>6} {'z':>7}")
    print(f"  {'─' * 57}")
    for team in sorted(team_sched, key=lambda t: -team_sched[t]):
        conf = CONFEDERATION.get(team, "UNK")
        print(f"  {team:<26} {conf:<10} {team_n[team]:>3} "
              f"{team_sched[team]:>6.1f} {team_z[team]:>+7.2f}")

    # ── Teams > 1 std dev below average ──────────────────────────────────────
    flagged = sorted(
        [(t, team_sched[t], team_z[t]) for t in team_sched if team_z[t] < -1.0],
        key=lambda x: x[2],
    )
    print(f"\n  Teams > 1 std dev BELOW average ({len(flagged)} flagged):")
    if flagged:
        for t, s, z in flagged:
            print(f"    {t:<26} {CONFEDERATION.get(t, 'UNK'):<10} {s:>6.1f}  z={z:>+.2f}")
    else:
        print("    None")

    # ── Per-confederation averages ────────────────────────────────────────────
    conf_groups: dict[str, list] = defaultdict(list)
    for t in wc_teams:
        if t in team_sched:
            conf_groups[CONFEDERATION.get(t, "UNK")].append(team_sched[t])

    conf_avgs = {c: sum(v) / len(v) for c, v in conf_groups.items()}

    print(f"\n  Avg schedule strength by confederation:")
    print(f"  {'Conf':<12} {'n':>3} {'Avg':>6} {'vs global':>10} {'z (mean)':>9}")
    print(f"  {'─' * 46}")
    for conf in sorted(conf_avgs, key=lambda c: -conf_avgs[c]):
        scores   = conf_groups[conf]
        avg      = conf_avgs[conf]
        delta    = avg - global_mean
        # z of the confederation mean relative to global, scaled by SE of the sample mean
        z_mean   = delta / (global_std / len(scores) ** 0.5)
        print(f"  {conf:<12} {len(scores):>3} {avg:>6.1f} {delta:>+10.1f} {z_mean:>+9.2f}")

    # ── USA / CONCACAF spotlight ──────────────────────────────────────────────
    print(f"\n  USA / CONCACAF spotlight:")

    usa_score = team_sched.get("United States")
    usa_z     = team_z.get("United States")
    if usa_score is not None:
        label = "BELOW" if usa_z < 0 else "above"
        note  = ("notably weak (<−1σ)" if usa_z < -1.0
                 else "slightly weak" if usa_z < -0.25
                 else "near average" if abs(usa_z) <= 0.25
                 else "above average")
        print(f"    USA sched strength : {usa_score:.1f}  z={usa_z:+.2f}  "
              f"({label} global mean {global_mean:.1f} — {note})")

    concacaf_scores = conf_groups.get("CONCACAF", [])
    if len(concacaf_scores) >= 2:
        non_concacaf    = [s for c, sc in conf_groups.items()
                           if c != "CONCACAF" for s in sc]
        concacaf_mean   = sum(concacaf_scores) / len(concacaf_scores)
        concacaf_z      = (concacaf_mean - global_mean) / (global_std / len(concacaf_scores) ** 0.5)
        t_stat, p_val   = ttest_ind(concacaf_scores, non_concacaf, equal_var=False)
        sig_tag         = "SIGNIFICANT" if p_val < 0.05 else "not significant"
        verdict         = (
            "statistically distinct — CONCACAF teams face systematically weaker opponents"
            if p_val < 0.05 and concacaf_mean < global_mean
            else "within normal variance across confederations"
        )
        print(f"    CONCACAF avg       : {concacaf_mean:.1f}  z={concacaf_z:+.2f}")
        print(f"    Welch t-test (CONCACAF vs rest): t={t_stat:.2f}  p={p_val:.3f}  → {sig_tag} at α=0.05")
        print(f"    Verdict: {verdict}")

    if excluded:
        print(f"\n  Excluded (no historical matches): {', '.join(excluded)}")

    print(f"{'=' * W}\n")


# ── Part 5: Dixon-Coles Rho Validation ───────────────────────────────────────

def rho_validation() -> None:
    W          = 72
    DECAY      = RECENCY_DECAY_YEARS
    MAX_G      = 10
    RHO_VALUES = [round(-0.20 + 0.01 * i, 2) for i in range(21)]  # −0.20 → 0.00

    print("=" * W)
    print("  Part 5: Dixon-Coles Rho Validation")
    print("=" * W)

    historical_df = load_historical_from_db()
    print(f"  Historical: {len(historical_df):,} matches  "
          f"({historical_df['date'].min()} → {historical_df['date'].max()})")
    print(f"  Fitting GLM (all data, decay={DECAY}y) … ", end="", flush=True)

    fit = fit_glm_with_decay(historical_df, DECAY)
    if fit is None:
        print("FAILED")
        return
    ratings, home_adv_coef, intercept = fit
    baseline = math.exp(intercept)
    print("done")

    # ── Precompute per-match mu values and raw score matrices ─────────────────
    print(f"  Precomputing score matrices … ", end="", flush=True)
    mu_h_list, mu_a_list, outcome_list, hs_list, aws_list = [], [], [], [], []
    skipped = 0

    for row in historical_df.itertuples(index=False):
        try:
            hs = int(row.home_score)
            aws = int(row.away_score)
        except (ValueError, TypeError):
            skipped += 1
            continue
        if row.home_team not in ratings or row.away_team not in ratings:
            skipped += 1
            continue
        ar_h, dr_h = ratings[row.home_team]
        ar_a, dr_a = ratings[row.away_team]
        mu_h = ar_h * dr_a / baseline
        mu_a = ar_a * dr_h / baseline
        neutral = str(getattr(row, "neutral", "False")).strip().lower() == "true"
        if not neutral:
            mu_h *= math.exp(home_adv_coef)
        mu_h_list.append(mu_h)
        mu_a_list.append(mu_a)
        outcome_list.append(0 if hs > aws else (2 if hs < aws else 1))
        hs_list.append(hs)
        aws_list.append(aws)

    mu_h    = np.array(mu_h_list)
    mu_a    = np.array(mu_a_list)
    outcomes = np.array(outcome_list)   # 0=home win, 1=draw, 2=away win
    hs_arr  = np.array(hs_list)
    aws_arr = np.array(aws_list)
    n_eval  = len(mu_h)

    # Vectorised raw score matrices: raw[m, i, j] = P(home=i) * P(away=j)
    k      = np.arange(MAX_G + 1)
    ph     = poisson.pmf(k[None, :], mu_h[:, None])   # (n, 11)
    pa     = poisson.pmf(k[None, :], mu_a[:, None])   # (n, 11)
    raw    = ph[:, :, None] * pa[:, None, :]           # (n, 11, 11)

    # Extract the 4 DC-correctable cells and precompute stable (rho-independent) sums.
    raw_00 = raw[:, 0, 0].copy()
    raw_10 = raw[:, 1, 0].copy()
    raw_01 = raw[:, 0, 1].copy()
    raw_11 = raw[:, 1, 1].copy()

    dc_mask   = np.zeros((MAX_G + 1, MAX_G + 1), dtype=bool)
    dc_mask[0, 0] = dc_mask[1, 0] = dc_mask[0, 1] = dc_mask[1, 1] = True

    tril_mask = np.tril(np.ones((MAX_G + 1, MAX_G + 1)), -1).astype(bool)  # i > j → home win
    diag_mask = np.eye(MAX_G + 1, dtype=bool)                               # i == j → draw
    triu_mask = np.triu(np.ones((MAX_G + 1, MAX_G + 1)), 1).astype(bool)   # j > i → away win

    # Stable sums: cells not touched by DC correction (same across all rho)
    other_sum = raw[:, ~dc_mask].sum(axis=1)                            # all non-DC
    hw_other  = raw[:, tril_mask & ~dc_mask].sum(axis=1)               # home wins excl (1,0)
    dr_other  = raw[:, diag_mask & ~dc_mask].sum(axis=1)               # draws excl (0,0),(1,1)
    aw_other  = raw[:, triu_mask & ~dc_mask].sum(axis=1)               # away wins excl (0,1)

    xg_total  = mu_h + mu_a
    print(f"done  ({n_eval:,} evaluable, {skipped:,} skipped)")

    # ── Step 1: Observed low-score frequencies ────────────────────────────────
    bucket_defs = [
        (0.0, 2.0, "Low (<2.0) "),
        (2.0, 3.0, "Med (2–3)  "),
        (3.0, 99., "High (≥3.0)"),
    ]
    cells = [(0, 0, "0-0"), (1, 0, "1-0"), (0, 1, "0-1"), (1, 1, "1-1")]

    print(f"\n  Step 1 — Observed low-score frequencies  "
          f"(evaluable subset, n={n_eval:,})")
    print()
    print(f"  {'Score':<6} {'Overall':>9}  {'Low(<2)':>9}  {'Med(2-3)':>9}  {'High(≥3)':>9}")
    print(f"  {'─' * 52}")
    obs_freq: dict[tuple, float] = {}
    for i, j, label in cells:
        mask_ij = (hs_arr == i) & (aws_arr == j)
        freq    = mask_ij.sum() / n_eval
        obs_freq[(i, j)] = freq
        bfreqs = []
        for lo, hi, _ in bucket_defs:
            bm = (xg_total >= lo) & (xg_total < hi)
            bfreqs.append((mask_ij & bm).sum() / bm.sum() if bm.sum() > 0 else float("nan"))
        print(f"  {label:<6} {freq:>9.3%}  {bfreqs[0]:>9.3%}  {bfreqs[1]:>9.3%}  {bfreqs[2]:>9.3%}")
    print()
    for lo, hi, desc in bucket_defs:
        bm = (xg_total >= lo) & (xg_total < hi)
        n_b = int(bm.sum())
        print(f"    {desc}: n={n_b:,}  ({bm.mean()*100:.0f}% of matches,  "
              f"avg total xG = {xg_total[bm].mean():.2f})")

    # ── Step 2: Grid search rho ───────────────────────────────────────────────
    print(f"\n  Step 2 — Grid search rho {RHO_VALUES[0]:.2f} to {RHO_VALUES[-1]:.2f}  "
          f"(current = {DIXON_COLES_RHO})")
    print()
    print(f"  {'rho':>5}  {'Avg LL':>9}  {'ΔLL vs 0':>9}  {'SSD×10⁵':>9}  note")
    print(f"  {'─' * 62}")

    rho_results = []
    for rho in RHO_VALUES:
        # DC correction multiplicative factors for the 4 low cells.
        # Clip c10/c01 to 0 — they can go negative for high-mu matches with very negative rho.
        c00 = 1.0 - mu_h * mu_a * rho        # always ≥ 1 when rho < 0
        c10 = np.maximum(1.0 + mu_a * rho, 0.0)
        c01 = np.maximum(1.0 + mu_h * rho, 0.0)
        c11 = 1.0 - rho                        # scalar, always ≥ 1 when rho < 0

        corr_00 = raw_00 * c00
        corr_10 = raw_10 * c10
        corr_01 = raw_01 * c01
        corr_11 = raw_11 * c11

        Z      = corr_00 + corr_10 + corr_01 + corr_11 + other_sum
        p_home = (corr_10 + hw_other) / Z
        p_draw = (corr_00 + corr_11 + dr_other) / Z
        p_away = (corr_01 + aw_other) / Z

        p_correct = np.where(outcomes == 0, p_home,
                    np.where(outcomes == 1, p_draw, p_away))
        avg_ll = -np.log(np.maximum(p_correct, 1e-10)).mean()

        pred_00 = (corr_00 / Z).mean()
        pred_10 = (corr_10 / Z).mean()
        pred_01 = (corr_01 / Z).mean()
        pred_11 = (corr_11 / Z).mean()
        ssd = ((pred_00 - obs_freq[(0, 0)]) ** 2 +
               (pred_10 - obs_freq[(1, 0)]) ** 2 +
               (pred_01 - obs_freq[(0, 1)]) ** 2 +
               (pred_11 - obs_freq[(1, 1)]) ** 2)

        rho_results.append({"rho": rho, "avg_ll": avg_ll, "ssd": ssd,
                            "pred_00": pred_00, "pred_10": pred_10,
                            "pred_01": pred_01, "pred_11": pred_11})

    best_ll  = min(rho_results, key=lambda r: r["avg_ll"])
    best_ssd = min(rho_results, key=lambda r: r["ssd"])
    curr_row = next(r for r in rho_results if abs(r["rho"] - DIXON_COLES_RHO) < 0.005)
    ll_at_0  = next(r["avg_ll"] for r in rho_results if abs(r["rho"]) < 0.005)

    for r in rho_results:
        delta = r["avg_ll"] - ll_at_0
        tags  = []
        if abs(r["rho"] - best_ll["rho"]) < 0.005:   tags.append("← best LL")
        if abs(r["rho"] - best_ssd["rho"]) < 0.005:  tags.append("← best SSD")
        if abs(r["rho"] - DIXON_COLES_RHO) < 0.005:   tags.append("← current")
        note = "  " + ", ".join(tags) if tags else ""
        print(f"  {r['rho']:>5.2f}  {r['avg_ll']:>9.5f}  {delta:>+9.5f}  "
              f"{r['ssd'] * 1e5:>9.3f}{note}")

    # ── Step 3: Summary ───────────────────────────────────────────────────────
    print(f"\n  Step 3 — Summary")
    print(f"  {'─' * 62}")
    print(f"  Best rho by log loss       : {best_ll['rho']:+.2f}  "
          f"(avg LL {best_ll['avg_ll']:.5f})")
    print(f"  Best rho by low-score SSD  : {best_ssd['rho']:+.2f}  "
          f"(SSD {best_ssd['ssd']:.2e})")
    print(f"  Current rho (DIXON_COLES_RHO) : {DIXON_COLES_RHO:+.2f}  "
          f"(avg LL {curr_row['avg_ll']:.5f},  SSD {curr_row['ssd']:.2e})")
    print(f"  LL gap (current vs best)   : {curr_row['avg_ll'] - best_ll['avg_ll']:+.5f}")
    print(f"  SSD gap (current vs best)  : {curr_row['ssd'] - best_ssd['ssd']:+.2e}")

    # Low-score frequency comparison table for key rho values
    print(f"\n  Low-score predicted vs observed frequencies:")
    print(f"  {'':>10}  {'0-0':>8}  {'1-0':>8}  {'0-1':>8}  {'1-1':>8}")
    print(f"  {'observed':>10}  "
          f"{obs_freq[(0,0)]:>8.3%}  {obs_freq[(1,0)]:>8.3%}  "
          f"{obs_freq[(0,1)]:>8.3%}  {obs_freq[(1,1)]:>8.3%}")
    seen_rhos: set = set()
    for r in [best_ll, best_ssd, curr_row]:
        if r["rho"] in seen_rhos:
            continue
        seen_rhos.add(r["rho"])
        tags = []
        if abs(r["rho"] - best_ll["rho"]) < 0.005:  tags.append("bestLL")
        if abs(r["rho"] - best_ssd["rho"]) < 0.005: tags.append("bestSSD")
        if abs(r["rho"] - DIXON_COLES_RHO) < 0.005:   tags.append("curr")
        label = f"{r['rho']:+.2f} ({','.join(tags)})"
        print(f"  {label:>10}  "
              f"{r['pred_00']:>8.3%}  {r['pred_10']:>8.3%}  "
              f"{r['pred_01']:>8.3%}  {r['pred_11']:>8.3%}")

    if abs(best_ll["rho"] - best_ssd["rho"]) > 0.005:
        print(f"\n  Note: best-LL rho ({best_ll['rho']:+.2f}) ≠ best-SSD rho ({best_ssd['rho']:+.2f}).")
        print(f"  Log loss penalises every match's win/draw/loss calibration across all")
        print(f"  scorelines. SSD only measures fit to the 4 low-score cells. The SSD-")
        print(f"  optimal rho maximises low-score frequency match; the LL-optimal rho")
        print(f"  balances that against draw probability across higher-scoring outcomes.")
    else:
        print(f"\n  Best-LL and best-SSD rho agree: {best_ll['rho']:+.2f}")

    print(f"{'=' * W}\n")


if __name__ == "__main__":
    if "--decay" in sys.argv:
        decay_sensitivity()
    elif "--weights" in sys.argv:
        weight_sensitivity()
    elif "--schedule" in sys.argv:
        schedule_strength_bias()
    elif "--rho" in sys.argv:
        rho_validation()
    else:
        main()
