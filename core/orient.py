"""Wykrywanie orientacji skanu z obrazu, bez OCR i bez modelu.

1. Prog tuszu liczony z jasnosci skanu (jasnoszary tekst tez jest tekstem).
2. Prostowanie: szukamy kata (do 4 stopni), przy ktorym profil wierszy jest najostrzejszy.
   Ten sam test dla strony obroconej o 90 stopni mowi, czy linie tekstu biegna poziomo czy pionowo.
3. Kierunek: tekst jest wyrownany do lewej (albo wyjustowany, a wtedy ostatnie linie akapitow
   koncza sie wczesniej), wiec poczatki linii tworza rowna krawedz, a konce sa poszarpane.
   Na stronie do gory nogami jest odwrotnie.
Wynik "pewny" tylko przy wyraznych sygnalach; w pozostalych przypadkach pipeline czyta strone
w dwoch orientacjach i wybiera odczyt z wieksza liczba konkretow (specificity).
Sprawdzone na prawdziwych skanach UZP (dane/skany) we wszystkich 4 obrotach.
"""
import numpy as np
from PIL import Image


def _prep(gray):
    h, w = gray.shape
    im = Image.fromarray(np.ascontiguousarray(gray[int(h * .03):int(h * .97), int(w * .03):int(w * .97)]))
    if im.width > 600:
        im = im.resize((im.width // 2, im.height // 2), Image.BILINEAR)
    return im


def _thr(im):
    a = np.asarray(im)
    return (np.percentile(a, 50) + np.percentile(a, 0.5)) / 2


def _deskew(im):
    """(ostrosc profilu wierszy, tusz po wyprostowaniu)."""
    t, best = _thr(im), (-1.0, None)
    for a in np.arange(-4, 4.01, 0.5):
        ink = np.asarray(im.rotate(a, resample=Image.BILINEAR, fillcolor=255)) < t
        p = ink.sum(axis=1).astype(float)
        s = float(p.var() / (p.mean() ** 2 + 1e-6))
        if s > best[0]:
            best = (s, ink)
    return best


def _rows(ink):
    prof = ink.sum(axis=1)
    on = prof > max(2, 0.06 * ink.shape[1] * ink.mean())
    rows, start = [], None
    for i, v in enumerate(list(on) + [False]):
        if v and start is None:
            start = i
        elif not v and start is not None:
            if i - start >= 3:
                rows.append((start, i))
            start = None
    return rows


def _edge(ink):
    """>0: lewa krawedz linii rowniejsza niz prawa (normalna orientacja)."""
    st, en = [], []
    for a, b in _rows(ink):
        cols = np.where(ink[a:b].sum(axis=0) > 0)[0]
        if len(cols) > 15:
            st.append(cols[0])
            en.append(cols[-1])
    if len(st) < 6:
        return 0.0
    st, en = np.array(st, float), np.array(en, float)
    tol = ink.shape[1] * 0.012
    return float(np.mean(np.abs(st - np.median(st)) < tol) - np.mean(np.abs(en - np.median(en)) < tol))


def detect_rotation(gray: np.ndarray):
    """(kat, pewny, kandydaci): kat 0/90/180/270 (obrot obrazu przeciwnie do ruchu wskazowek zegara).
    Strona wyraznie prosta -> jeden odczyt (na prawdziwych skanach UZP zawsze trafne).
    Pozostale -> dwa odczyty; wybor w pipeline (mniej powtorzen, remis = strona prosta)."""
    im = _prep(gray)
    if (np.asarray(im) < _thr(im)).mean() < 0.003:
        return 0, True, (0,)                      # pusta strona
    sh, ink_h = _deskew(im)
    sv, ink_v = _deskew(im.rotate(90, expand=True))
    if sh / (sv + 1e-9) >= 0.8:                   # linie poziome (albo niejasne)
        e = _edge(ink_h)
        if e > 0.1:                               # wyraznie prosta: na skanach UZP nigdy sie nie myli
            return 0, True, (0,)
        first = 180 if e < -0.1 else 0            # niejasne albo "odwrocona" (myli tez adresat z prawej)
        return first, False, (first, 180 - first)
    first = 270 if _edge(ink_v) < 0 else 90       # obraz obrocony o 90 CCW: krawedz >0 -> 90
    return first, False, (first, 360 - first)


def repetition(text: str) -> float:
    """Odsetek powtorzonych 4-gramow slow. Model czytajacy odwrocona strone zmysla tekst,
    ktory krazy wokol tych samych fraz (zmierzone na skanach UZP)."""
    import re
    w = re.findall(r"\w+", text.lower())
    g = [tuple(w[i:i + 4]) for i in range(len(w) - 3)]
    return 1 - len(set(g)) / len(g) if g else 1.0


SPECIFIC = [r"\b\d{1,2}[.\-/]\d{1,2}[.\-/]20\d\d\b", r"\b20\d\d-\d{2}-\d{2}\b", r"\b\d{2}-\d{3}\b",
            r"\b\d{10}\b", r"\b\d{3}-\d{3}-\d{2}-\d{2}\b", r"[\w.+-]+@[\w-]+\.\w+", r"\bul\.",
            r"(?i)\b(?:NIP|KRS|REGON|PESEL|rachun\w*|Zamawiaj\w*|Odwołuj\w*|pełnomocni\w*|przelew\w*)\b"]


def specificity(text: str) -> int:
    """Ile konkretnych danych (daty, numery, kody, adresy, slowa z dziedziny) jest w odczycie.
    Odczyt odwroconej strony bywa plynny, ale ubogi w takie konkrety."""
    import re
    return sum(len(re.findall(p, text)) for p in SPECIFIC)
