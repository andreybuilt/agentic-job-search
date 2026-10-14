#!/usr/bin/env python3
"""
ats_common.py -- shared ATS screening logic (title include/exclude regex,
location screen) used by sweep.py and filter_discover.py.

The original version of filter_discover.py took a shortcut: it `exec`'d a
slice of sweep.py's source up to a marker to reuse its screen functions.
That is replaced here with a clean, importable module -- same mechanism
(title screen + location screen, config-driven, with the same generic
fallback defaults), no source-slicing.
"""
import re

UA = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/152.0.0.0 Safari/537.36"
}

# EXAMPLE defaults, used only when a sourcing.* key is empty: titles for field and solutions
# roles, and a fictional home metro. Set your own in config.yaml.
DEFAULT_TITLE_IN = (
    r"customer success|success manager|technical success|client success|customer engineer|"
    r"account manager, technical|solutions? (engineer|architect|consultant)|sales engineer|"
    r"field (engineer|cto)|forward[- ]deployed|technical account manag|\bTAM\b|"
    r"pre-?sales|domain consultant|systems engineer|partner (solutions|technical|sales engineer)|"
    r"solutions? lead|deployment (strategist|manager|engineer)|value engineer|technical advisor|"
    r"implementation (architect|consultant)"
)
DEFAULT_TITLE_OUT = (
    r"intern\b|new grad|account executive|business development rep|\bSDR\b|\bBDR\b|recruit|"
    r"marketing|software engineer\b(?!.*customer)|backend|data scientist|\bVP\b|vice president|"
    r"chief|director"
)
DEFAULT_TARGET_METRO = r"example city|example suburb a|example suburb b|example state\b"
DEFAULT_TARGET_STATE_ABBR = "XX"

NONUS = (
    r"canada|toronto|vancouver|london|uk\b|united kingdom|emea|europe|germany|france|india|"
    r"bangalore|australia|sydney|singapore|japan|tokyo|brazil|mexico|israel|tel aviv|ireland|"
    r"dublin|netherlands|amsterdam|spain|poland|apac|latam|korea|uae|dubai|abu dhabi|berlin|"
    r"munich|romania|bucharest|paris|s[aã]o paulo|istanbul|vienna|apj|madrid|barcelona|"
    r"lisbon|warsaw|prague|zurich|stockholm|copenhagen|oslo|helsinki|milan|tel-aviv|hyderabad|"
    r"pune|chennai|manila|jakarta|seoul|taipei|hong kong|shanghai|beijing|melbourne|auckland|"
    r"montreal|ottawa|calgary|saudi|riyadh|jeddah|qatar|doha|kuwait|bahrain|egypt|cairo|"
    r"south africa|johannesburg|nigeria|lagos|kenya|nairobi"
)
DC = r"washington,? ?d\.? ?c\.?|district of columbia|\bDC\b"
STATE_REMOTE = r"(?i:remote)\s*[-–—,:(]\s*(?!US\b|USA\b|U\.S)[A-Z]{2}\b|\b(?!US\b)[A-Z][A-Za-z]+-Remote\b"


def build_title_regexes(cfg_get):
    """cfg_get(dotted_key, default) -> (title_in_compiled, title_out_compiled)."""
    title_in = re.compile(cfg_get("sourcing.title_include_regex", None) or DEFAULT_TITLE_IN, re.I)
    title_out = re.compile(cfg_get("sourcing.title_exclude_regex", None) or DEFAULT_TITLE_OUT, re.I)
    return title_in, title_out


def make_loc_ok(target_metro_regex=DEFAULT_TARGET_METRO, target_state_abbr=DEFAULT_TARGET_STATE_ABBR):
    def loc_ok(locs, remote):
        L = " | ".join(l for l in locs if l)
        Lmetro = re.sub(DC, " ", L, flags=re.I)
        if re.search(target_metro_regex, Lmetro, re.I):
            return "HOME-METRO"
        state_pat = rf"\b{re.escape(target_state_abbr)}\b"
        if re.search(STATE_REMOTE, L) and not re.search(state_pat, L, re.I):
            return "REMOTE-STATE?"
        usremote = re.search(r"remote", L, re.I) or remote
        if (
            usremote
            and re.search(r"\bUS\b|U\.S\.|united states|USA|americas|north america|anywhere|remote$|^remote", L, re.I)
            and not (re.search(NONUS, L, re.I) and not re.search(r"\bUS\b|united states|USA", L, re.I))
        ):
            return "REMOTE-US"
        if remote and not re.search(NONUS, L, re.I):
            return "REMOTE?"
        return None

    return loc_ok


def strip_html(h):
    import html as _html

    return re.sub(
        r"\s+\n", "\n",
        re.sub(
            r"[ \t]+", " ",
            re.sub(r"<[^>]+>", " ", _html.unescape(re.sub(r"<(br|/p|/li|/h\d)[^>]*>", "\n", _html.unescape(h or "")))),
        ),
    ).strip()


if __name__ == "__main__":
    # A library, not a command: print the module help and exit 0.
    print(__doc__)
