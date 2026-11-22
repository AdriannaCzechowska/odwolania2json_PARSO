"""Normalizacja wartosci wg typow pol z YAML + weryfikacja w tekscie zrodlowym."""
import re
import unicodedata

MONTHS = {
    "stycznia": 1, "lutego": 2, "marca": 3, "kwietnia": 4, "maja": 5, "czerwca": 6,
    "lipca": 7, "sierpnia": 8, "września": 9, "wrzesnia": 9, "października": 10,
    "pazdziernika": 10, "listopada": 11, "grudnia": 12,
    "styczeń": 1, "luty": 2, "marzec": 3, "kwiecień": 4, "maj": 5, "czerwiec": 6,
    "lipiec": 7, "sierpień": 8, "wrzesień": 9, "październik": 10, "listopad": 11, "grudzień": 12,
}
_MONTH_RE = "|".join(sorted(MONTHS, key=len, reverse=True))
TITLES = re.compile(r"^(?:adw\.|adwokat|r\.\s*pr\.|radca\s+prawny|radczyni\s+prawna|mec\.|mecenas|apl\.\s*(?:adw|radc)\.?|dr|prof\.|pan|pani)\s+", re.I)


def digits(v) -> str:
    return re.sub(r"\D", "", str(v))


def parse_date(v):
    if v is None:
        return None
    s = str(v).strip().lower()
    m = re.search(r"(20\d\d)[-./](\d{1,2})[-./](\d{1,2})", s)
    if m:
        y, mo, d = int(m[1]), int(m[2]), int(m[3])
    else:
        m = re.search(r"(\d{1,2})[-./ ](\d{1,2})[-./ ](20\d\d)", s)
        if m:
            d, mo, y = int(m[1]), int(m[2]), int(m[3])
        else:
            m = re.search(rf"(\d{{1,2}})\s*({_MONTH_RE})\s*(20\d\d)", s)
            if not m:
                return None
            d, mo, y = int(m[1]), MONTHS[m[2]], int(m[3])
    if not (1 <= mo <= 12 and 1 <= d <= 31):
        return None
    return f"{y:04d}-{mo:02d}-{d:02d}"


def parse_amount(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).replace("\xa0", " ")
    m = re.search(r"\d[\d \.]*(?:,\d{1,2})?|\d+(?:\.\d{1,2})?", s)
    if not m:
        return None
    num = m.group(0).strip()
    if "," in num:
        num = num.replace(" ", "").replace(".", "").replace(",", ".")
    else:
        parts = num.replace(" ", "").split(".")
        num = "".join(parts[:-1]) + "." + parts[-1] if len(parts) > 1 and len(parts[-1]) <= 2 else "".join(parts)
    try:
        return float(num)
    except ValueError:
        return None


def clean_text(v):
    if v is None:
        return None
    s = re.sub(r"\s+", " ", str(v)).strip()
    return s or None


def person(v):
    s = clean_text(v)
    if not s:
        return None
    while True:
        new = TITLES.sub("", s)
        if new == s:
            break
        s = new
    return s.strip(" ,;") or None


_ADDR = re.compile(r"\s+z\s+siedzibą\b.*$|,\s*(?:ul\.|al\.|pl\.|os\.|ulica|adres)(?=\s|$).*$|,\s*\d{2}-\d{3}\b.*$", re.I)


def org_name(v):
    """Nazwa podmiotu bez doklejonego adresu i siedziby."""
    s = clean_text(v)
    if not s:
        return None
    s = _ADDR.sub("", s).strip(" ,;")
    return s or None


def first_person(v):
    """Pierwsza osoba z listy 'A, B' / 'A i B'."""
    s = person(v)
    if not s:
        return None
    s = re.split(r",|;|\s+i\s+|\s+oraz\s+", s)[0]
    return person(s)


def ted(v):
    if not v:
        return None
    s = str(v)
    m = re.search(r"(20\d\d)\s*/\s*S\s*\d{1,3}\s*-\s*(\d{6})", s)
    if m:
        return f"{m[2]}-{m[1]}"
    m = re.search(r"(\d{6})\s*-\s*(20\d\d)", s)
    return f"{m[1]}-{m[2]}" if m else None


def bzp(v):
    if not v:
        return None
    m = re.search(r"(20\d\d)\s*/\s*BZP\s*(\d{6,8})(?:\s*/\s*(\d{1,2}))?", str(v), re.I)
    if not m:
        return None
    return f"{m[1]}/BZP{m[2]}" + (f"/{m[3]}" if m[3] else "")


def fixed_digits(n):
    def f(v):
        d = digits(v) if v is not None else ""
        if not d:
            return None
        if len(d) < n and n == 10:          # KRS bywa pisany bez zer wiodacych
            d = d.zfill(10)
        return d if len(d) == n else None
    return f


def regon(v):
    d = digits(v) if v is not None else ""
    return d if len(d) in (9, 14) else None


FOREIGN_IBAN = re.compile(r"(?<![A-Z])(?!PL)([A-Z]{2}\d{2}[A-Z0-9]{11,30})")


def iban(v):
    """Polski rachunek: 26 cyfr (prefiks PL dokleja pipeline, jesli jest w dokumencie).
    Zagraniczny IBAN (inny kod kraju): bez spacji, w formie z dokumentu (decyzja UZP)."""
    if v is None:
        return None
    m = FOREIGN_IBAN.search(re.sub(r"[\s\-]", "", str(v)).upper())
    if m:
        return m.group(1)
    d = digits(v)
    return d[-26:] if len(d) >= 26 else None


def int01(v):
    if v in (0, 1):
        return int(v)
    if isinstance(v, str) and v.strip() in ("0", "1"):
        return int(v)
    if isinstance(v, bool):
        return int(v)
    return None


def to_int(v):
    try:
        return int(v) if v is not None and str(v).strip() != "" else None
    except (TypeError, ValueError):
        return None


def email(v):
    m = re.search(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", str(v or ""))
    return m.group(0).lower() if m else None


def quoted_text(v):
    s = clean_text(v)
    if not s:
        return None
    s = s.rstrip(". ") if s.rstrip(". ").endswith(("”", '"', "“")) else s   # „tytul”. -> tytul
    return s.strip("„”\"'“ ") or None


NORMALIZERS = {
    "date": parse_date, "amount": parse_amount, "text": clean_text, "person": person,
    "ted": ted, "bzp": bzp, "krs": fixed_digits(10), "nip": fixed_digits(10), "regon": regon,
    "pesel": fixed_digits(11), "iban": iban, "int01": int01, "int": to_int, "email": email,
    "quoted_text": quoted_text, "place": clean_text, "org_name": org_name, "first_person": first_person, "ref": clean_text, "multiline": clean_text,
}

# typy, ktorych wartosc musi wystapic w tekscie zrodlowym (ochrona przed halucynacja)
GROUNDED = {"krs", "nip", "regon", "pesel", "iban", "email"}


def digit_runs(text: str):
    """Ciagi cyfr z tekstu (spacje i myslniki wewnatrz numeru dozwolone) + pozycja."""
    return [(re.sub(r"\D", "", m.group()), m.start())
            for m in re.finditer(r"\d(?:[\d]|[ \-](?=\d)){5,}", text)]


def grounded(kind: str, value, runs, source_lower: str) -> bool:
    """Wartosc musi wystapic w dokumencie jako caly numer (nie sklejka cyfr)."""
    if value is None:
        return True
    if kind == "email":
        return value.lower() in source_lower
    if kind == "iban" and FOREIGN_IBAN.fullmatch(str(value)):
        return str(value).lower() in re.sub(r"[\s\-]", "", source_lower)
    d = digits(value)
    if kind == "iban" and len(d) >= 26:
        return d in "".join(r for r, _ in runs) or d in re.sub(r"\D", "", source_lower)  # numer zlamany na 2 linie
    for run, pos in runs:
        if kind == "iban" and run.endswith(d):
            return True
        if run == d:
            return True
        if kind == "krs" and run.zfill(10) == d and "krs" in source_lower[max(0, pos - 25):pos]:
            return True      # KRS zapisany bez zer wiodacych, ale z etykieta "KRS"
    return False


# --- polskie znaki w nazwach miejscowosci -------------------------------------------
PL_PLACES = """Łódź Kraków Wrocław Poznań Gdańsk Szczecin Białystok Toruń Częstochowa Radom Sosnowiec Kielce
Gliwice Zabrze Bielsko-Biała Rzeszów Ruda_Śląska Rybnik Tychy Dąbrowa_Górnicza Płock Elbląg Gorzów_Wielkopolski
Wałbrzych Włocławek Tarnów Chorzów Grudziądz Słupsk Jastrzębie-Zdrój Nowy_Sącz Jelenia_Góra Mysłowice Piła
Ostrów_Wielkopolski Siemianowice_Śląskie Gniezno Głogów Świdnica Suwałki Tomaszów_Mazowiecki Zamość
Kędzierzyn-Koźle Przemyśl Piotrków_Trybunalski Łomża Żory Pruszków Bełchatów Świętochłowice Będzin Ełk
Biała_Podlaska Racibórz Ostrołęka Świnoujście Piekary_Śląskie Żyrardów Puławy Wołomin Kołobrzeg Świdnik
Oświęcim Śrem Września Łuków Łowicz Łańcut Żagań Żary Świebodzin Środa_Śląska Sławno Wągrowiec Chełm Chełmno
Inowrocław Kraśnik Łęczna Kłodzko Zielona_Góra Sandomierz Bolesławiec Ząbki Łomianki Józefów Żywiec Cieszyn
Gorlice Wieliczka Skawina Mińsk_Mazowiecki Sochaczew Płońsk Ciechanów Mława Sieradz Zduńska_Wola Pabianice
Łęczyca Brzeziny Opoczno Końskie Ostrowiec_Świętokrzyski Skarżysko-Kamienna Busko-Zdrój Jędrzejów Kłobuck
Lubliniec Tarnowskie_Góry Mikołów Knurów Czechowice-Dziedzice Wadowice Myślenice Zakopane Nowy_Targ Kłodzko
Dzierżoniów Bielawa Świebodzice Oława Oleśnica Głuchołazy Kędzierzyn Prudnik Brzeg Namysłów Kluczbork Ostrzeszów
Kępno Krotoszyn Jarocin Środa_Wielkopolska Gostyń Leszno Kościan Śmigiel Międzychód Szamotuły Oborniki Chodzież
Złotów Wałcz Człuchów Bytów Kościerzyna Kartuzy Wejherowo Puck Starogard_Gdański Kwidzyn Malbork Sztum Iława
Ostróda Działdowo Nidzica Szczytno Mrągowo Giżycko Węgorzewo Gołdap Olecko Ełk Łódź_Kaliska Zgierz Głowno
Bydgoszcz_Fordon Świecie Chojnice Tuchola Sępólno_Krajeńskie Nakło_nad_Notecią Żnin Mogilno Strzelno Brodnica
Golub-Dobrzyń Rypin Lipno Aleksandrów_Kujawski Ciechocinek Radziejów Koło Turek Konin Słupca Gniezno Wronki""".split()
PL_PLACES = sorted({x.replace("_", " ") for x in PL_PLACES})


def fold(s: str) -> str:
    """Bez polskich znakow i wielkosci liter: 'Łódź' -> 'lodz'."""
    s = s.replace("ł", "l").replace("Ł", "L")
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


_PL_CHARS = set("ąćęłńóśźżĄĆĘŁŃÓŚŹŻ")


def fix_place(value, doc_text: str):
    """Przywraca polskie znaki w nazwie miejscowosci: najpierw wg pisowni w tym samym dokumencie,
    potem wg listy miast. Zmienia tylko, gdy litery po usunieciu znakow sa identyczne."""
    if not value:
        return value
    key = fold(value)
    words = len(value.split())
    pat = r"[A-ZĄĆĘŁŃÓŚŹŻ][\wąćęłńóśźżĄĆĘŁŃÓŚŹŻ\-]*" + r"(?:\s+[A-ZĄĆĘŁŃÓŚŹŻ][\wąćęłńóśźżĄĆĘŁŃÓŚŹŻ\-]*)" * (words - 1)
    counts = {}
    for m in re.finditer(pat, doc_text):
        cand = m.group(0)
        if fold(cand) == key and any(c in _PL_CHARS for c in cand):
            counts[cand] = counts.get(cand, 0) + 1
    if counts:
        return max(counts, key=counts.get)
    for place in PL_PLACES:
        if fold(place) == key:
            return place
    return value


# --- dociaganie nazw do brzmienia z dokumentu (UZP: nazwa firmy "jak w dokumencie") ---
_FORMS = [
    ["spółka z ograniczoną odpowiedzialnością", "sp. z o.o.", "sp. z o. o.", "sp.z o.o.", "spółka z o.o."],
    ["spółka akcyjna", "s.a."],
    ["spółka komandytowo-akcyjna", "s.k.a.", "sp. k.a."],
    ["spółka komandytowa", "sp. k.", "sp.k."],
    ["spółka jawna", "sp. j.", "sp.j."],
    ["spółka partnerska", "sp. p.", "sp.p."],
]
_FORM_RE = re.compile(r"^[\s,]*(" + "|".join(
    re.escape(f).replace(r"\ ", r"\s*") for g in _FORMS for f in sorted(g, key=len, reverse=True)) + r")", re.I)
_TAIL_RE = re.compile(r"[\s,]*(" + "|".join(
    re.escape(f).replace(r"\ ", r"\s*") for g in _FORMS for f in sorted(g, key=len, reverse=True)) + r")\s*$", re.I)


def _collapse(s):
    return " ".join(str(s).split())


def snap_org(value, text):
    """Nazwa podmiotu w brzmieniu z dokumentu. Zmienia tylko forme prawna, gdy model ja skrocil
    albo rozwinal ("Sp. z o.o." <-> "spółka z ograniczoną odpowiedzialnością"); rdzen nazwy musi
    wystepowac w tekscie. Gdy dokument zawiera kilka wariantow, wybiera najpelniejszy (tak jak wzorce UZP)."""
    if not value or not text:
        return value
    t = _collapse(text)
    tl, v = t.lower(), _collapse(value)
    m = _TAIL_RE.search(v)
    if not m:
        return value                      # bez formy prawnej nic nie zmieniamy
    core = v[:m.start()].strip(" ,")
    if len(core) < 4:
        return value
    found, start = [], 0
    while True:
        i = tl.find(core.lower(), start)
        if i < 0:
            break
        f = _FORM_RE.match(t[i + len(core):i + len(core) + 60])
        if f:
            found.append(t[i:i + len(core) + f.end()].strip(" ,"))
        start = i + 1
    if not found:
        return value
    return max(found, key=len)


def snap_person(value, text):
    """Imie i nazwisko w kolejnosci z dokumentu ("Kaczmarek Weronika" -> "Weronika Kaczmarek"),
    tylko gdy odwrocona kolejnosc wystepuje w tekscie doslownie."""
    if not value or not text:
        return value
    tl, v = _collapse(text).lower(), _collapse(value)
    parts = v.split(" ")
    if v.lower() in tl or len(parts) not in (2, 3):
        return value
    rev = " ".join(parts[-1:] + parts[:-1])
    return rev if rev.lower() in tl else value
