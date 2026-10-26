"""The NBA's official injury report (official.nba.com), published several times a day as a PDF.
It gives each player's status (Out, Doubtful, Questionable, Probable, Available), which is much
clearer than ESPN's "Day-To-Day". Needs the `pdftotext` program (poppler-utils)."""
import datetime as dt, re, subprocess, tempfile, unicodedata, urllib.request

STATUSES = ("Out", "Doubtful", "Questionable", "Probable", "Available")
W = r"[^,\s]+(?: [^,\s]+)*"  # words separated by single spaces
LINE = re.compile(r"^(?P<pre>.*?)\s{2,}(?P<name>" + W + r"(?:, (?:Jr\.|Sr\.|II|III|IV))?, " + W + r")\s{2,}(?P<status>"
                  + "|".join(STATUSES) + r")\b")


def norm(name):
    """'Udeh, Jr., Ernest' or 'Ernest Udeh Jr.' -> 'ernest udeh'"""
    if "," in name:
        parts = [p.strip() for p in name.split(",")]
        name = " ".join(parts[-1:] + parts[:-1])
    name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    name = re.sub(r"[^a-z ]", "", name)
    return " ".join(w for w in name.split() if w not in ("jr", "sr", "ii", "iii", "iv"))


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def latest_report(team_names, now=None):
    """{team full name: {normalized player name: (status, reason)}} from the newest report, or {} on any problem."""
    try:
        now = now or dt.datetime.now(dt.timezone.utc)
        y = now.year if now.month >= 8 else now.year - 1
        page = _get(f"https://official.nba.com/nba-injury-report-{y}-{str(y + 1)[-2:]}-season/").decode("utf8", "ignore")
        links = re.findall(r"https://ak-static\.cms\.nba\.com/referee/injury/Injury-Report_[^\"']+\.pdf", page)
        if not links:
            page = _get(f"https://official.nba.com/nba-injury-report-{y}-{y + 1}-season/").decode("utf8", "ignore")
            links = re.findall(r"https://ak-static\.cms\.nba\.com/referee/injury/Injury-Report_[^\"']+\.pdf", page)
        if not links:
            return {}
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            f.write(_get(links[-1])); f.flush()
            text = subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, text=True, timeout=60).stdout
        out, team = {}, None
        names = sorted(team_names, key=len, reverse=True)
        lines = text.splitlines()
        for i, line in enumerate(lines):
            m = LINE.match(line)
            if not m:
                continue
            for t in names:
                if t in m.group("pre"):
                    team = t
                    break
            reason = line[m.end():].strip()
            if not reason:  # long reasons wrap onto the lines just above and below
                near = [lines[j].strip() for j in (i - 1, i + 1) if 0 <= j < len(lines)
                        and lines[j].strip() and not LINE.match(lines[j]) and lines[j].startswith(" " * 40)]
                reason = " ".join(near)
            reason = re.sub(r"^Injury/Illness - ", "", reason).replace(" / ", " ").strip()
            if team:
                out.setdefault(team, {})[norm(m.group("name"))] = (m.group("status"), reason)
        return out
    except Exception as e:  # never block the update
        print("NBA injury report not used:", e)
        return {}
