#!/usr/bin/env python3
"""Read the latest odds snapshot from odds.db and write index.html."""

import sqlite3
import os
from html import escape as esc

DB_PATH = "odds.db"
OUT_PATH = "index.html"

# ---------------------------------------------------------------------------
# Schedule — 72 group-stage games
# ---------------------------------------------------------------------------
SCHEDULE = [
    {"date": "Thu, Jun 11", "grp": "A", "home": "Mexico",            "away": "South Africa",    "time": "3:00 PM ET",   "venue": "Estadio Azteca, Mexico City"},
    {"date": "Thu, Jun 11", "grp": "A", "home": "South Korea",       "away": "Czechia",          "time": "10:00 PM ET",  "venue": "Estadio Akron, Guadalajara"},
    {"date": "Fri, Jun 12", "grp": "B", "home": "Canada",            "away": "Bosnia-Herzegovina","time": "3:00 PM ET",  "venue": "BMO Field, Toronto"},
    {"date": "Fri, Jun 12", "grp": "D", "home": "United States",     "away": "Paraguay",         "time": "9:00 PM ET",   "venue": "SoFi Stadium, Inglewood"},
    {"date": "Sat, Jun 13", "grp": "B", "home": "Qatar",             "away": "Switzerland",      "time": "3:00 PM ET",   "venue": "Levi's Stadium, Santa Clara"},
    {"date": "Sat, Jun 13", "grp": "C", "home": "Brazil",            "away": "Morocco",          "time": "6:00 PM ET",   "venue": "MetLife Stadium, East Rutherford"},
    {"date": "Sat, Jun 13", "grp": "C", "home": "Haiti",             "away": "Scotland",         "time": "9:00 PM ET",   "venue": "Gillette Stadium, Foxboro"},
    {"date": "Sat, Jun 13", "grp": "D", "home": "Australia",         "away": "Turkiye",          "time": "12:00 AM ET",  "venue": "BC Place, Vancouver"},
    {"date": "Sun, Jun 14", "grp": "E", "home": "Germany",           "away": "Curacao",          "time": "1:00 PM ET",   "venue": "NRG Stadium, Houston"},
    {"date": "Sun, Jun 14", "grp": "F", "home": "Netherlands",       "away": "Japan",            "time": "4:00 PM ET",   "venue": "AT&T Stadium, Arlington"},
    {"date": "Sun, Jun 14", "grp": "E", "home": "Ivory Coast",       "away": "Ecuador",          "time": "7:00 PM ET",   "venue": "Lincoln Financial Field, Philadelphia"},
    {"date": "Sun, Jun 14", "grp": "F", "home": "Sweden",            "away": "Tunisia",          "time": "10:00 PM ET",  "venue": "Estadio BBVA, Monterrey"},
    {"date": "Mon, Jun 15", "grp": "H", "home": "Spain",             "away": "Cape Verde",       "time": "12:00 PM ET",  "venue": "Mercedes-Benz Stadium, Atlanta"},
    {"date": "Mon, Jun 15", "grp": "G", "home": "Belgium",           "away": "Egypt",            "time": "3:00 PM ET",   "venue": "Lumen Field, Seattle"},
    {"date": "Mon, Jun 15", "grp": "H", "home": "Saudi Arabia",      "away": "Uruguay",          "time": "6:00 PM ET",   "venue": "Hard Rock Stadium, Miami"},
    {"date": "Mon, Jun 15", "grp": "G", "home": "Iran",              "away": "New Zealand",      "time": "9:00 PM ET",   "venue": "SoFi Stadium, Inglewood"},
    {"date": "Tue, Jun 16", "grp": "I", "home": "France",            "away": "Senegal",          "time": "3:00 PM ET",   "venue": "MetLife Stadium, East Rutherford"},
    {"date": "Tue, Jun 16", "grp": "I", "home": "Iraq",              "away": "Norway",           "time": "6:00 PM ET",   "venue": "Gillette Stadium, Foxborough"},
    {"date": "Tue, Jun 16", "grp": "J", "home": "Argentina",         "away": "Algeria",          "time": "9:00 PM ET",   "venue": "Arrowhead Stadium, Kansas City"},
    {"date": "Tue, Jun 16", "grp": "J", "home": "Austria",           "away": "Jordan",           "time": "12:00 AM ET",  "venue": "Levi's Stadium, Santa Clara"},
    {"date": "Wed, Jun 17", "grp": "K", "home": "Portugal",          "away": "DR Congo",         "time": "1:00 PM ET",   "venue": "NRG Stadium, Houston"},
    {"date": "Wed, Jun 17", "grp": "L", "home": "England",           "away": "Croatia",          "time": "4:00 PM ET",   "venue": "AT&T Stadium, Arlington"},
    {"date": "Wed, Jun 17", "grp": "L", "home": "Ghana",             "away": "Panama",           "time": "7:00 PM ET",   "venue": "BMO Field, Toronto"},
    {"date": "Wed, Jun 17", "grp": "K", "home": "Uzbekistan",        "away": "Colombia",         "time": "10:00 PM ET",  "venue": "Estadio Azteca, Mexico City"},
    {"date": "Thu, Jun 18", "grp": "A", "home": "Czechia",           "away": "South Africa",     "time": "12:00 PM ET",  "venue": "Mercedes-Benz Stadium, Atlanta"},
    {"date": "Thu, Jun 18", "grp": "B", "home": "Switzerland",       "away": "Bosnia-Herzegovina","time": "3:00 PM ET",  "venue": "SoFi Stadium, Inglewood"},
    {"date": "Thu, Jun 18", "grp": "B", "home": "Canada",            "away": "Qatar",            "time": "6:00 PM ET",   "venue": "BC Place, Vancouver"},
    {"date": "Thu, Jun 18", "grp": "A", "home": "Mexico",            "away": "South Korea",      "time": "9:00 PM ET",   "venue": "Estadio Akron, Guadalajara"},
    {"date": "Fri, Jun 19", "grp": "D", "home": "United States",     "away": "Australia",        "time": "3:00 PM ET",   "venue": "Lumen Field, Seattle"},
    {"date": "Fri, Jun 19", "grp": "C", "home": "Scotland",          "away": "Morocco",          "time": "6:00 PM ET",   "venue": "Gillette Stadium, Foxboro"},
    {"date": "Fri, Jun 19", "grp": "C", "home": "Brazil",            "away": "Haiti",            "time": "8:30 PM ET",   "venue": "Lincoln Financial Field, Philadelphia"},
    {"date": "Fri, Jun 19", "grp": "D", "home": "Turkiye",           "away": "Paraguay",         "time": "11:00 PM ET",  "venue": "Levi's Stadium, Santa Clara"},
    {"date": "Sat, Jun 20", "grp": "F", "home": "Netherlands",       "away": "Sweden",           "time": "1:00 PM ET",   "venue": "NRG Stadium, Houston"},
    {"date": "Sat, Jun 20", "grp": "E", "home": "Germany",           "away": "Ivory Coast",      "time": "4:00 PM ET",   "venue": "BMO Field, Toronto"},
    {"date": "Sat, Jun 20", "grp": "E", "home": "Ecuador",           "away": "Curacao",          "time": "8:00 PM ET",   "venue": "Arrowhead Stadium, Kansas City"},
    {"date": "Sat, Jun 20", "grp": "F", "home": "Tunisia",           "away": "Japan",            "time": "12:00 AM ET",  "venue": "Estadio BBVA, Monterrey"},
    {"date": "Sun, Jun 21", "grp": "H", "home": "Spain",             "away": "Saudi Arabia",     "time": "12:00 PM ET",  "venue": "Mercedes-Benz Stadium, Atlanta"},
    {"date": "Sun, Jun 21", "grp": "G", "home": "Belgium",           "away": "Iran",             "time": "3:00 PM ET",   "venue": "SoFi Stadium, Inglewood"},
    {"date": "Sun, Jun 21", "grp": "H", "home": "Uruguay",           "away": "Cape Verde",       "time": "6:00 PM ET",   "venue": "Hard Rock Stadium, Miami"},
    {"date": "Sun, Jun 21", "grp": "G", "home": "New Zealand",       "away": "Egypt",            "time": "9:00 PM ET",   "venue": "BC Place, Vancouver"},
    {"date": "Mon, Jun 22", "grp": "J", "home": "Argentina",         "away": "Austria",          "time": "1:00 PM ET",   "venue": "AT&T Stadium, Arlington"},
    {"date": "Mon, Jun 22", "grp": "I", "home": "France",            "away": "Iraq",             "time": "5:00 PM ET",   "venue": "Lincoln Financial Field, Philadelphia"},
    {"date": "Mon, Jun 22", "grp": "I", "home": "Norway",            "away": "Senegal",          "time": "8:00 PM ET",   "venue": "MetLife Stadium, East Rutherford"},
    {"date": "Mon, Jun 22", "grp": "J", "home": "Jordan",            "away": "Algeria",          "time": "11:00 PM ET",  "venue": "Levi's Stadium, Santa Clara"},
    {"date": "Tue, Jun 23", "grp": "K", "home": "Portugal",          "away": "Uzbekistan",       "time": "1:00 PM ET",   "venue": "NRG Stadium, Houston"},
    {"date": "Tue, Jun 23", "grp": "L", "home": "England",           "away": "Ghana",            "time": "4:00 PM ET",   "venue": "Gillette Stadium, Foxborough"},
    {"date": "Tue, Jun 23", "grp": "L", "home": "Panama",            "away": "Croatia",          "time": "7:00 PM ET",   "venue": "BMO Field, Toronto"},
    {"date": "Tue, Jun 23", "grp": "K", "home": "Colombia",          "away": "DR Congo",         "time": "10:00 PM ET",  "venue": "Estadio Akron, Guadalajara"},
    {"date": "Wed, Jun 24", "grp": "B", "home": "Switzerland",       "away": "Canada",           "time": "3:00 PM ET",   "venue": "BC Place, Vancouver"},
    {"date": "Wed, Jun 24", "grp": "B", "home": "Bosnia-Herzegovina","away": "Qatar",            "time": "3:00 PM ET",   "venue": "Lumen Field, Seattle"},
    {"date": "Wed, Jun 24", "grp": "C", "home": "Scotland",          "away": "Brazil",           "time": "6:00 PM ET",   "venue": "Hard Rock Stadium, Miami"},
    {"date": "Wed, Jun 24", "grp": "C", "home": "Morocco",           "away": "Haiti",            "time": "6:00 PM ET",   "venue": "Mercedes-Benz Stadium, Atlanta"},
    {"date": "Wed, Jun 24", "grp": "A", "home": "Czechia",           "away": "Mexico",           "time": "9:00 PM ET",   "venue": "Estadio Azteca, Mexico City"},
    {"date": "Wed, Jun 24", "grp": "A", "home": "South Africa",      "away": "South Korea",      "time": "9:00 PM ET",   "venue": "Estadio BBVA, Monterrey"},
    {"date": "Thu, Jun 25", "grp": "E", "home": "Curacao",           "away": "Ivory Coast",      "time": "4:00 PM ET",   "venue": "Lincoln Financial Field, Philadelphia"},
    {"date": "Thu, Jun 25", "grp": "E", "home": "Ecuador",           "away": "Germany",          "time": "4:00 PM ET",   "venue": "MetLife Stadium, East Rutherford"},
    {"date": "Thu, Jun 25", "grp": "F", "home": "Japan",             "away": "Sweden",           "time": "7:00 PM ET",   "venue": "AT&T Stadium, Arlington"},
    {"date": "Thu, Jun 25", "grp": "F", "home": "Tunisia",           "away": "Netherlands",      "time": "7:00 PM ET",   "venue": "Arrowhead Stadium, Kansas City"},
    {"date": "Thu, Jun 25", "grp": "D", "home": "Turkiye",           "away": "United States",    "time": "10:00 PM ET",  "venue": "SoFi Stadium, Inglewood"},
    {"date": "Thu, Jun 25", "grp": "D", "home": "Paraguay",          "away": "Australia",        "time": "10:00 PM ET",  "venue": "Levi's Stadium, Santa Clara"},
    {"date": "Fri, Jun 26", "grp": "I", "home": "Norway",            "away": "France",           "time": "3:00 PM ET",   "venue": "Gillette Stadium, Foxborough"},
    {"date": "Fri, Jun 26", "grp": "I", "home": "Senegal",           "away": "Iraq",             "time": "3:00 PM ET",   "venue": "BMO Field, Toronto"},
    {"date": "Fri, Jun 26", "grp": "H", "home": "Cape Verde",        "away": "Saudi Arabia",     "time": "8:00 PM ET",   "venue": "NRG Stadium, Houston"},
    {"date": "Fri, Jun 26", "grp": "H", "home": "Uruguay",           "away": "Spain",            "time": "8:00 PM ET",   "venue": "Estadio Akron, Guadalajara"},
    {"date": "Fri, Jun 26", "grp": "G", "home": "Egypt",             "away": "Iran",             "time": "11:00 PM ET",  "venue": "Lumen Field, Seattle"},
    {"date": "Fri, Jun 26", "grp": "G", "home": "New Zealand",       "away": "Belgium",          "time": "11:00 PM ET",  "venue": "BC Place, Vancouver"},
    {"date": "Sat, Jun 27", "grp": "L", "home": "Panama",            "away": "England",          "time": "5:00 PM ET",   "venue": "MetLife Stadium, East Rutherford"},
    {"date": "Sat, Jun 27", "grp": "L", "home": "Croatia",           "away": "Ghana",            "time": "5:00 PM ET",   "venue": "Lincoln Financial Field, Philadelphia"},
    {"date": "Sat, Jun 27", "grp": "K", "home": "Colombia",          "away": "Portugal",         "time": "7:30 PM ET",   "venue": "Hard Rock Stadium, Miami"},
    {"date": "Sat, Jun 27", "grp": "K", "home": "DR Congo",          "away": "Uzbekistan",       "time": "7:30 PM ET",   "venue": "Mercedes-Benz Stadium, Atlanta"},
    {"date": "Sat, Jun 27", "grp": "J", "home": "Jordan",            "away": "Argentina",        "time": "10:00 PM ET",  "venue": "AT&T Stadium, Arlington"},
    {"date": "Sat, Jun 27", "grp": "J", "home": "Algeria",           "away": "Austria",          "time": "10:00 PM ET",  "venue": "Arrowhead Stadium, Kansas City"},
]

FLAGS = {
    "Mexico":             "🇲🇽",
    "South Africa":       "🇿🇦",
    "South Korea":        "🇰🇷",
    "Czechia":            "🇨🇿",
    "Canada":             "🇨🇦",
    "Bosnia-Herzegovina": "🇧🇦",
    "Qatar":              "🇶🇦",
    "Switzerland":        "🇨🇭",
    "Brazil":             "🇧🇷",
    "Morocco":            "🇲🇦",
    "Haiti":              "🇭🇹",
    "Scotland":           "🏴󠁧󠁢󠁳󠁣󠁴󠁿",
    "United States":      "🇺🇸",
    "Paraguay":           "🇵🇾",
    "Australia":          "🇦🇺",
    "Turkiye":            "🇹🇷",
    "Germany":            "🇩🇪",
    "Curacao":            "🇨🇼",
    "Ivory Coast":        "🇨🇮",
    "Ecuador":            "🇪🇨",
    "Netherlands":        "🇳🇱",
    "Japan":              "🇯🇵",
    "Sweden":             "🇸🇪",
    "Tunisia":            "🇹🇳",
    "Belgium":            "🇧🇪",
    "Egypt":              "🇪🇬",
    "Iran":               "🇮🇷",
    "New Zealand":        "🇳🇿",
    "Spain":              "🇪🇸",
    "Cape Verde":         "🇨🇻",
    "Saudi Arabia":       "🇸🇦",
    "Uruguay":            "🇺🇾",
    "France":             "🇫🇷",
    "Senegal":            "🇸🇳",
    "Iraq":               "🇮🇶",
    "Norway":             "🇳🇴",
    "Argentina":          "🇦🇷",
    "Algeria":            "🇩🇿",
    "Austria":            "🇦🇹",
    "Jordan":             "🇯🇴",
    "Portugal":           "🇵🇹",
    "DR Congo":           "🇨🇩",
    "Uzbekistan":         "🇺🇿",
    "Colombia":           "🇨🇴",
    "England":            "🏴󠁧󠁢󠁥󠁮󠁧󠁿",
    "Croatia":            "🇭🇷",
    "Ghana":              "🇬🇭",
    "Panama":             "🇵🇦",
}

# ---------------------------------------------------------------------------
# CSS (not an f-string — curly braces are literal)
# ---------------------------------------------------------------------------
CSS = """
:root {
  --bg:           #080c18;
  --surface:      #111827;
  --surface2:     #1a2236;
  --border:       #1f2d47;
  --text:         #e2e8f0;
  --muted:        #7a8ba0;
  --green:        #10b981;
  --green-dim:    rgba(16,185,129,.12);
  --green-border: rgba(16,185,129,.35);
  --amber:        #f59e0b;
  --amber-dim:    rgba(245,158,11,.10);
  --amber-border: rgba(245,158,11,.32);
  --red:          #ef4444;
  --red-dim:      rgba(239,68,68,.08);
  --red-border:   rgba(239,68,68,.25);
  --gray:         #4b5563;
  --gray-dim:     rgba(75,85,99,.10);
  --gray-border:  rgba(75,85,99,.30);
  --accent:       #3b82f6;
}
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
body {
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
               "Helvetica Neue", Arial, sans-serif;
  font-size: 14px;
  line-height: 1.5;
  min-height: 100vh;
}

/* ── Header ── */
header {
  background: linear-gradient(160deg, #0c1528 0%, #162040 100%);
  border-bottom: 1px solid var(--border);
  padding: 28px 32px 22px;
  text-align: center;
}
header h1 {
  font-size: clamp(1.4rem, 3vw, 2rem);
  font-weight: 800;
  letter-spacing: -.5px;
  color: #fff;
}
header h1 span { color: var(--accent); }
.subtitle { color: var(--muted); font-size: 13px; margin-top: 4px; }

/* ── Summary strip ── */
.summary-strip {
  background: var(--surface);
  border-bottom: 1px solid var(--border);
  display: flex;
  justify-content: center;
  flex-wrap: wrap;
}
.summary-item {
  padding: 14px 28px;
  text-align: center;
  border-right: 1px solid var(--border);
  min-width: 160px;
}
.summary-item:last-child { border-right: none; }
.s-label {
  display: block;
  color: var(--muted);
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 1.2px;
  margin-bottom: 3px;
}
.s-value {
  display: block;
  font-size: 1.35rem;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
}
.s-value.warn { color: var(--amber); }

/* ── Main two-column layout ── */
.main-layout {
  display: flex;
  max-width: 1440px;
  margin: 0 auto;
  padding: 24px 16px 48px;
  gap: 20px;
  align-items: flex-start;
}
.schedule-col { flex: 1; min-width: 0; }
.leaderboard-col {
  width: 290px;
  flex-shrink: 0;
  position: sticky;
  top: 16px;
}

/* ── Section headers ── */
.section-label {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 1.4px;
  color: var(--muted);
  margin-bottom: 14px;
}

/* ── Date groups ── */
.date-group { margin-bottom: 28px; }
.date-header {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 15px;
  font-weight: 600;
  color: var(--accent);
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border);
  margin-bottom: 12px;
}
.date-header .game-count {
  font-size: 11px;
  font-weight: 500;
  color: var(--muted);
}
.games-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(270px, 1fr));
  gap: 10px;
}

/* ── Game cards ── */
.game-card {
  background: var(--surface);
  border-radius: 8px;
  padding: 13px 14px 11px;
  border: 1px solid var(--border);
  border-left: 3px solid var(--gray);
  transition: transform .12s ease, box-shadow .12s ease;
}
.game-card:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 16px rgba(0,0,0,.35);
}
.game-card.green { border-left-color: var(--green); background: var(--green-dim); border-color: var(--green-border); }
.game-card.amber { border-left-color: var(--amber); background: var(--amber-dim); border-color: var(--amber-border); }
.game-card.red   { border-left-color: var(--red);   background: var(--red-dim);   border-color: var(--red-border);   }
.game-card.gray  { border-left-color: var(--gray);  background: var(--gray-dim);  border-color: var(--gray-border);  }

.card-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 9px;
}
.grp-badge {
  background: var(--accent);
  color: #fff;
  font-size: 10px;
  font-weight: 700;
  padding: 2px 7px;
  border-radius: 4px;
  letter-spacing: .4px;
}
.card-time { color: var(--muted); font-size: 11px; }

.matchup { margin-bottom: 9px; }
.team-row {
  display: flex;
  align-items: center;
  gap: 7px;
  padding: 3px 0;
}
.team-flag { font-size: 17px; line-height: 1; flex-shrink: 0; }
.team-name { flex: 1; font-weight: 500; font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.team-prob { font-variant-numeric: tabular-nums; font-size: 12px; font-weight: 600; color: var(--muted); white-space: nowrap; }
.vs-line { font-size: 10px; color: var(--muted); padding: 1px 0 1px 24px; }

.prob-track { background: var(--border); border-radius: 3px; height: 4px; margin: 8px 0 7px; overflow: hidden; }
.prob-fill { height: 100%; border-radius: 3px; }
.prob-fill.green { background: var(--green); }
.prob-fill.amber { background: var(--amber); }
.prob-fill.red   { background: var(--red);   }
.prob-fill.gray  { background: var(--gray);  }

.card-bottom {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 8px;
}
.combined-lbl {
  font-size: 11px;
  font-weight: 700;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
}
.game-card.green .combined-lbl { color: var(--green); }
.game-card.amber .combined-lbl { color: var(--amber); }
.game-card.red   .combined-lbl { color: var(--red);   }
.game-card.gray  .combined-lbl { color: var(--muted); }
.venue-lbl { font-size: 10px; color: var(--muted); text-align: right; line-height: 1.35; }

/* ── Leaderboard ── */
.lb-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 12px;
  margin-bottom: 10px;
  font-size: 11px;
  color: var(--muted);
  align-items: center;
}
.dot { display: inline-block; width: 7px; height: 7px; border-radius: 50%; margin-right: 3px; }
.dot.green { background: var(--green); }
.dot.amber { background: var(--amber); }
.dot.red   { background: var(--red);   }

.leaderboard {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
  max-height: calc(100vh - 120px);
  overflow-y: auto;
  scrollbar-width: thin;
  scrollbar-color: var(--border) transparent;
}
.lb-row {
  display: grid;
  grid-template-columns: 28px 20px 1fr auto;
  align-items: center;
  gap: 6px;
  padding: 7px 11px;
  border-bottom: 1px solid var(--border);
}
.lb-row:last-child { border-bottom: none; }
.lb-rank { color: var(--muted); font-size: 10px; text-align: right; }
.lb-flag { font-size: 13px; text-align: center; }
.lb-name-wrap { min-width: 0; }
.lb-name {
  font-size: 12px;
  font-weight: 500;
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  margin-bottom: 3px;
}
.lb-bar-track { background: var(--border); border-radius: 2px; height: 3px; overflow: hidden; }
.lb-bar-fill  { height: 100%; border-radius: 2px; }
.lb-bar-fill.green { background: var(--green); }
.lb-bar-fill.amber { background: var(--amber); }
.lb-bar-fill.red   { background: var(--red);   }
.lb-bar-fill.gray  { background: var(--gray);  }
.lb-pct {
  font-variant-numeric: tabular-nums;
  font-size: 11px;
  font-weight: 600;
  color: var(--muted);
  white-space: nowrap;
  text-align: right;
}

/* ── Footer ── */
footer {
  text-align: center;
  padding: 20px;
  color: var(--muted);
  font-size: 11px;
  border-top: 1px solid var(--border);
}
footer a { color: var(--accent); text-decoration: none; }

/* ── Responsive ── */
@media (max-width: 960px) {
  .main-layout { flex-direction: column; }
  .leaderboard-col { width: 100%; position: static; }
  .leaderboard { max-height: 420px; }
}
@media (max-width: 560px) {
  .summary-strip { flex-direction: column; }
  .summary-item { border-right: none; border-bottom: 1px solid var(--border); }
  .games-grid { grid-template-columns: 1fr; }
  header { padding: 18px 16px; }
}
"""

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_odds(db_path: str):
    """Return ({team: implied_prob}, fetched_at) from the most recent snapshot."""
    if not os.path.exists(db_path):
        return {}, None
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT MAX(fetched_at) FROM odds_snapshots").fetchone()
        if not row or not row[0]:
            return {}, None
        fetched_at = row[0]
        rows = conn.execute(
            "SELECT team, implied_prob FROM odds_snapshots WHERE fetched_at = ?",
            (fetched_at,),
        ).fetchall()
        return {r[0]: r[1] for r in rows}, fetched_at
    finally:
        conn.close()


def fmt_pct(p, d: int = 2) -> str:
    return "—" if p is None else f"{p * 100:.{d}f}%"


def color_cls(combined) -> str:
    if combined is None:
        return "gray"
    if combined >= 0.125:
        return "green"
    if combined >= 0.0417:
        return "amber"
    return "red"


def lb_color(prob) -> str:
    """Individual-team tier for leaderboard bars."""
    if prob is None:
        return "gray"
    if prob >= 0.05:     # top contenders (~top 8)
        return "green"
    if prob >= 0.0208:   # above 1/48 baseline
        return "amber"
    return "red"


def flag(team: str) -> str:
    return FLAGS.get(team, "🏳️")


# ---------------------------------------------------------------------------
# HTML builder
# ---------------------------------------------------------------------------

def build_html(odds: dict, fetched_at) -> str:
    # ---- compute per-game data ----
    game_rows = []
    for g in SCHEDULE:
        hp = odds.get(g["home"])
        ap = odds.get(g["away"])
        combined = (hp + ap) if (hp is not None and ap is not None) else None
        game_rows.append({**g, "hp": hp, "ap": ap, "combined": combined})

    valid_combined = [r["combined"] for r in game_rows if r["combined"] is not None]
    max_combined = max(valid_combined, default=0.5)

    # ---- summary strip ----
    total_prob = sum(odds.values()) if odds else 0.0
    overround = total_prob - 1.0

    if fetched_at:
        try:
            from datetime import datetime, timezone
            dt = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
            updated_str = dt.strftime("%b %d, %Y %H:%M UTC")
        except Exception:
            updated_str = fetched_at
    else:
        updated_str = "No data yet"

    # ---- group games by date (insertion order) ----
    date_games: dict[str, list] = {}
    for r in game_rows:
        date_games.setdefault(r["date"], []).append(r)

    # ---- schedule HTML ----
    sched_parts = []
    for date, games in date_games.items():
        n = len(games)
        sched_parts.append(
            f'<div class="date-group">'
            f'<div class="date-header">'
            f'{esc(date)}'
            f'<span class="game-count">({n} game{"s" if n != 1 else ""})</span>'
            f'</div>'
            f'<div class="games-grid">'
        )
        for r in games:
            cls = color_cls(r["combined"])
            bar_w = int((r["combined"] / max_combined) * 100) if r["combined"] else 0
            sched_parts.append(
                f'<div class="game-card {cls}">'
                f'<div class="card-top">'
                f'<span class="grp-badge">GRP {esc(r["grp"])}</span>'
                f'<span class="card-time">{esc(r["time"])}</span>'
                f'</div>'
                f'<div class="matchup">'
                f'<div class="team-row">'
                f'<span class="team-flag">{flag(r["home"])}</span>'
                f'<span class="team-name">{esc(r["home"])}</span>'
                f'<span class="team-prob">{fmt_pct(r["hp"])}</span>'
                f'</div>'
                f'<div class="vs-line">vs</div>'
                f'<div class="team-row">'
                f'<span class="team-flag">{flag(r["away"])}</span>'
                f'<span class="team-name">{esc(r["away"])}</span>'
                f'<span class="team-prob">{fmt_pct(r["ap"])}</span>'
                f'</div>'
                f'</div>'
                f'<div class="prob-track">'
                f'<div class="prob-fill {cls}" style="width:{bar_w}%"></div>'
                f'</div>'
                f'<div class="card-bottom">'
                f'<span class="combined-lbl">Combined: {fmt_pct(r["combined"])}</span>'
                f'<span class="venue-lbl">{esc(r["venue"])}</span>'
                f'</div>'
                f'</div>'
            )
        sched_parts.append('</div></div>')

    # ---- leaderboard HTML ----
    all_teams = sorted({g["home"] for g in SCHEDULE} | {g["away"] for g in SCHEDULE})
    ranked = sorted([(t, odds.get(t)) for t in all_teams], key=lambda x: -(x[1] or 0))
    max_prob = ranked[0][1] if ranked and ranked[0][1] else 1.0

    lb_parts = []
    for i, (team, prob) in enumerate(ranked, 1):
        bar_w = int((prob / max_prob) * 100) if prob else 0
        lc = lb_color(prob)
        lb_parts.append(
            f'<div class="lb-row">'
            f'<span class="lb-rank">#{i}</span>'
            f'<span class="lb-flag">{flag(team)}</span>'
            f'<div class="lb-name-wrap">'
            f'<span class="lb-name">{esc(team)}</span>'
            f'<div class="lb-bar-track">'
            f'<div class="lb-bar-fill {lc}" style="width:{bar_w}%"></div>'
            f'</div>'
            f'</div>'
            f'<span class="lb-pct">{fmt_pct(prob)}</span>'
            f'</div>'
        )

    # ---- assemble ----
    warn_cls = ' class="s-value warn"' if overround > 0 else ' class="s-value"'
    overround_str = ("+" if overround >= 0 else "") + fmt_pct(overround, 1) if odds else "—"

    parts = [
        "<!DOCTYPE html>",
        '<html lang="en">',
        "<head>",
        '<meta charset="UTF-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
        "<title>2026 FIFA World Cup &mdash; Championship Odds Dashboard</title>",
        f"<style>{CSS}</style>",
        "</head>",
        "<body>",
        "<header>",
        "<h1>&#9917; 2026 FIFA World Cup <span>&mdash; Championship Odds</span></h1>",
        '<p class="subtitle">Group Stage Dashboard &bull; Updated daily via GitHub Actions</p>',
        "</header>",
        '<div class="summary-strip">',
        '<div class="summary-item">',
        '<span class="s-label">Teams Tracked</span>',
        f'<span class="s-value">{len(odds)}&thinsp;/&thinsp;48</span>',
        "</div>",
        '<div class="summary-item">',
        '<span class="s-label">Total Implied</span>',
        f'<span class="s-value">{fmt_pct(total_prob, 1) if odds else "—"}</span>',
        "</div>",
        '<div class="summary-item">',
        '<span class="s-label">Overround</span>',
        f'<span{warn_cls}>{overround_str}</span>',
        "</div>",
        '<div class="summary-item">',
        '<span class="s-label">Last Updated</span>',
        f'<span class="s-value" style="font-size:1rem">{esc(updated_str)}</span>',
        "</div>",
        "</div>",  # summary-strip
        '<div class="main-layout">',
        '<div class="schedule-col">',
        '<div class="section-label">Group Stage Schedule &mdash; 72 Games</div>',
        "".join(sched_parts),
        "</div>",  # schedule-col
        '<div class="leaderboard-col">',
        '<div class="section-label">Championship Odds</div>',
        '<div class="lb-legend">',
        '<span><span class="dot green"></span>&ge;12.5% combined</span>',
        '<span><span class="dot amber"></span>4.17&ndash;12.5%</span>',
        '<span><span class="dot red"></span>&lt;4.17%</span>',
        "</div>",
        '<div class="leaderboard">',
        "".join(lb_parts),
        "</div>",  # leaderboard
        "</div>",  # leaderboard-col
        "</div>",  # main-layout
        "<footer>",
        "<p>Odds sourced from "
        '<a href="https://the-odds-api.com" target="_blank" rel="noopener">The Odds API</a>'
        " &bull; Best available US line per team &bull; Baseline: 1/48 = 2.08% per team</p>",
        "</footer>",
        "</body>",
        "</html>",
    ]

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    odds, fetched_at = get_odds(DB_PATH)
    if not odds:
        print("WARNING: No odds data found in DB — generating skeleton dashboard.")

    html = build_html(odds, fetched_at)
    with open(OUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)

    size_kb = os.path.getsize(OUT_PATH) / 1024
    print(f"Wrote {OUT_PATH} ({size_kb:.1f} KB, {len(odds)} teams with odds)")


if __name__ == "__main__":
    main()
