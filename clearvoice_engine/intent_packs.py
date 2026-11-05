"""A data-driven reframer: the grammar lives in a table, the pipeline is shared.

English and French each cost ~380 lines because every language re-implemented the
same steps: strip the request frame, find the verb, lift the time expression,
rebuild in the polite frame. Only four things are actually per-language:

    verbs        the forms people say, mapped to one canonical verb
    time words   weekdays, months, relatives ("demain", "diesen Freitag")
    frame words  the pronouns and auxiliaries that carry "I would like…"
    frame        how a polite request is built, and where the verb goes

So: one engine, one table per language. A new language is a table — 60–90 lines,
reviewable by a native speaker without touching the pipeline — instead of another
copy of the algorithm.

Only languages whose grammar I can actually check get a table here. The rest keep
`intent_langs.polish()` and say so in the pane: a wrong sentence in a language
nobody verified is worse than an honest tidy-up.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from functools import lru_cache

from .intent_langs import polish, politeness_for


@dataclass(frozen=True)
class Pack:
    """Everything that differs between two languages, and nothing else."""

    code: str
    verbs: dict[str, str]           # form as spoken → canonical infinitive
    days: frozenset[str]
    months: frozenset[str]
    relatives: frozenset[str]
    frame_words: frozenset[str]     # "je", "voudrais", "ich", "möchte"…
    request_markers: frozenset[str] # multiword tells, matched on the joined text
    determiners: frozenset[str]
    links: frozenset[str]           # prepositions that glue a time expression
    courteous: str                  # "{verb} {object} {time}" → the sentence
    noun_class: dict[str, str] = field(default_factory=dict)  # article by suffix
    stop_words: frozenset[str] = frozenset()
    capitalises_nouns: bool = False

    def all_time_words(self) -> frozenset[str]:
        return self.days | self.months | self.relatives


# ---------------------------------------------------------------------------
# German
# ---------------------------------------------------------------------------

DE = Pack(
    code="de",
    verbs={
        "verschieben": "verschieben", "verschiebe": "verschieben", "verschiebt": "verschieben",
        "verlegen": "verlegen", "verlege": "verlegen",
        "ändern": "ändern", "ändere": "ändern", "ändert": "ändern",
        "absagen": "absagen", "sage": "absagen", "sagt": "absagen",
        "anrufen": "anrufen", "rufe": "anrufen", "ruft": "anrufen",
        "schicken": "schicken", "schicke": "schicken", "sendet": "schicken",
        "senden": "senden", "sende": "senden",
        "bestätigen": "bestätigen", "bestätige": "bestätigen",
        "bezahlen": "bezahlen", "bezahle": "bezahlen", "zahle": "bezahlen",
        "buchen": "buchen", "buche": "buchen",
        "abholen": "abholen", "hole": "abholen",
        "bringen": "bringen", "bringe": "bringen",
        "erklären": "erklären", "erkläre": "erklären",
        "fragen": "fragen", "frage": "fragen",
        "wiederholen": "wiederholen", "wiederhole": "wiederholen",
        "drucken": "drucken", "drucke": "drucken",
        "holen": "holen",
        "kaufen": "kaufen", "kaufe": "kaufen",
        "warten": "warten", "warte": "warten",
        "kommen": "kommen", "komme": "kommen",
        "aufschieben": "aufschieben",
    },
    days=frozenset({"montag", "dienstag", "mittwoch", "donnerstag", "freitag", "samstag", "sonnabend", "sonntag"}),
    months=frozenset({"januar", "februar", "märz", "maerz", "april", "mai", "juni", "juli", "august", "september", "oktober", "november", "dezember"}),
    relatives=frozenset({"heute", "morgen", "übermorgen", "gestern", "vormittag", "mittag", "nachmittag", "abend", "nacht", "woche", "monat", "uhr", "nächste", "naechste", "diese", "diesen"}),
    frame_words=frozenset({"ich", "wir", "du", "sie", "muss", "müssen", "muessen", "möchte", "moechte", "moechten", "möchten", "will", "wollen", "brauche", "brauchen", "kann", "können", "koennen", "könnten", "koennten", "kannst", "bitte", "mal", "doch", "einfach", "gerade", "sollte", "sollten", "habe", "haben", "es", "ist", "wäre", "waere", "würde", "wuerde", "würden", "wuerden", "mir", "mich", "um", "zu"}),
    request_markers=frozenset({"können sie", "koennen sie", "könnten sie", "koennten sie", "ich möchte", "ich moechte", "ich brauche", "ich muss"}),
    determiners=frozenset({"meinen", "meine", "mein", "den", "die", "das", "dem", "der", "einen", "eine", "einem", "einer", "ein", "unseren", "unsere", "unser", "ihren", "ihre"}),
    links=frozenset({"am", "an", "auf", "bis", "von", "vom", "zum", "zur", "im", "in", "diese", "diesen", "nächsten", "naechsten", "um", "ab"}),
    courteous="Könnten Sie {object}{time} bitte {verb}?",
    stop_words=frozenset({"der", "die", "das", "ein", "eine", "und", "zu", "am", "im", "in", "es"}),
    capitalises_nouns=True,
)

# ---------------------------------------------------------------------------
# Spanish
# ---------------------------------------------------------------------------

ES = Pack(
    code="es",
    verbs={
        "cambiar": "cambiar", "cambia": "cambiar", "cambio": "cambiar", "cambie": "cambiar",
        "mover": "mover", "mueve": "mover", "mueva": "mover",
        "cancelar": "cancelar", "cancela": "cancelar", "cancele": "cancelar",
        "llamar": "llamar", "llama": "llamar", "llame": "llamar",
        "enviar": "enviar", "envía": "enviar", "envia": "enviar", "envíe": "enviar",
        "mandar": "mandar", "manda": "mandar",
        "confirmar": "confirmar", "confirma": "confirmar",
        "pagar": "pagar", "paga": "pagar", "pague": "pagar",
        "reservar": "reservar", "reserva": "reservar",
        "recoger": "recoger", "recoge": "recoger",
        "traer": "traer", "trae": "traer",
        "explicar": "explicar", "explica": "explicar",
        "preguntar": "preguntar", "pregunta": "preguntar",
        "repetir": "repetir", "repite": "repetir",
        "imprimir": "imprimir", "imprime": "imprimir",
        "esperar": "esperar", "espera": "esperar",
        "venir": "venir", "viene": "venir",
        
        "apuntar": "apuntar", "apunta": "apuntar",
        "adelantar": "adelantar", "adelanta": "adelantar",
    },
    days=frozenset({"lunes", "martes", "miércoles", "miercoles", "jueves", "viernes", "sábado", "sabado", "domingo"}),
    months=frozenset({"enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"}),
    relatives=frozenset({"hoy", "mañana", "manana", "ayer", "tarde", "noche", "mediodía", "mediodia", "semana", "mes", "hora", "próximo", "proximo", "próxima", "proxima", "este", "esta"}),
    frame_words=frozenset({"yo", "quiero", "quisiera", "necesito", "tengo", "tengo que", "debo", "puedes", "puede", "podría", "podria", "podrías", "podrias", "por", "favor", "me", "que", "debo", "hay", "es", "está", "para"}),
    request_markers=frozenset({"puede", "puedes", "podría", "podria", "quiero", "quisiera", "necesito", "me gustaría", "me gustaria"}),
    determiners=frozenset({"mi", "mis", "el", "la", "los", "las", "un", "una", "unos", "unas", "su", "sus", "nuestro", "nuestra", "este", "esta"}),
    links=frozenset({"el", "la", "los", "las", "de", "del", "al", "a", "para", "hasta", "desde", "por", "en", "este", "esta", "próximo", "proximo", "próxima", "proxima"}),
    courteous="¿Podría {verb} {object}{time}, por favor?",
    stop_words=frozenset({"el", "la", "los", "las", "un", "una", "de", "y", "que", "es"}),
)

# ---------------------------------------------------------------------------
# Italian
# ---------------------------------------------------------------------------

IT = Pack(
    code="it",
    verbs={
        "spostare": "spostare", "sposta": "spostare", "sposti": "spostare",
        "cambiare": "cambiare", "cambia": "cambiare", "cambi": "cambiare",
        "annullare": "annullare", "annulla": "annullare",
        "chiamare": "chiamare", "chiama": "chiamare", "chiami": "chiamare",
        "telefonare": "telefonare", "telefona": "telefonare",
        "inviare": "inviare", "invia": "inviare", "mandare": "mandare", "manda": "mandare",
        "confermare": "confermare", "conferma": "confermare",
        "pagare": "pagare", "paga": "pagare", "paghi": "pagare",
        "prenotare": "prenotare", "prenota": "prenotare",
        "ritirare": "ritirare", "ritira": "ritirare",
        "portare": "portare", "porta": "portare",
        "spiegare": "spiegare", "spiega": "spiegare",
        "chiedere": "chiedere", "chiede": "chiedere",
        "ripetere": "ripetere", "ripete": "ripetere",
        "stampare": "stampare", "stampa": "stampare",
        "aspettare": "aspettare", "aspetta": "aspettare",
        "venire": "venire", "viene": "venire",
        "anticipare": "anticipare", "anticipa": "anticipare",
        "posticipare": "posticipare", "posticipa": "posticipare",
    },
    days=frozenset({"lunedì", "lunedi", "martedì", "martedi", "mercoledì", "mercoledi", "giovedì", "giovedi", "venerdì", "venerdi", "sabato", "domenica"}),
    months=frozenset({"gennaio", "febbraio", "marzo", "aprile", "maggio", "giugno", "luglio", "agosto", "settembre", "ottobre", "novembre", "dicembre"}),
    relatives=frozenset({"oggi", "domani", "dopodomani", "ieri", "mattina", "pomeriggio", "sera", "notte", "mezzogiorno", "settimana", "mese", "ora", "prossimo", "prossima", "questo", "questa"}),
    frame_words=frozenset({"io", "vorrei", "voglio", "ho", "bisogno", "devo", "dobbiamo", "puoi", "può", "puo", "potrebbe", "potrei", "mi", "per", "favore", "che", "di", "è", "e", "sono", "c'è"}),
    request_markers=frozenset({"puoi", "può", "puo", "potrebbe", "vorrei", "ho bisogno", "devo"}),
    determiners=frozenset({"il", "lo", "la", "i", "gli", "le", "un", "uno", "una", "mio", "mia", "miei", "mie", "suo", "sua", "questo", "questa"}),
    links=frozenset({"il", "lo", "la", "i", "gli", "le", "di", "del", "della", "a", "al", "alla", "per", "fino", "da", "in", "questo", "questa", "prossimo", "prossima"}),
    courteous="Potrebbe {verb} {object}{time}, per favore?",
    stop_words=frozenset({"il", "lo", "la", "i", "gli", "le", "un", "una", "di", "e", "che", "è"}),
)

# ---------------------------------------------------------------------------
# Portuguese
# ---------------------------------------------------------------------------

PT = Pack(
    code="pt",
    verbs={
        "mudar": "mudar", "muda": "mudar", "mude": "mudar",
        "alterar": "alterar", "altera": "alterar",
        "cancelar": "cancelar", "cancela": "cancelar", "cancele": "cancelar",
        "ligar": "ligar", "liga": "ligar", "ligue": "ligar",
        "telefonar": "telefonar", "telefona": "telefonar",
        "enviar": "enviar", "envia": "enviar", "envie": "enviar",
        "mandar": "mandar", "manda": "mandar",
        "confirmar": "confirmar", "confirma": "confirmar",
        "pagar": "pagar", "paga": "pagar", "pague": "pagar",
        "marcar": "marcar", "marca": "marcar", "marque": "marcar",
        "buscar": "buscar", "busca": "buscar", "recolher": "recolher",
        "trazer": "trazer", "traz": "trazer",
        "explicar": "explicar", "explica": "explicar",
        "perguntar": "perguntar", "pergunta": "perguntar",
        "repetir": "repetir", "repete": "repetir",
        "imprimir": "imprimir", "imprime": "imprimir",
        "esperar": "esperar", "espera": "esperar",
        "vir": "vir", "vem": "vir",
        "adiar": "adiar", "adia": "adiar",
        "antecipar": "antecipar", "antecipa": "antecipar",
    },
    days=frozenset({"segunda", "terça", "terca", "quarta", "quinta", "sexta", "sábado", "sabado", "domingo"}),
    months=frozenset({"janeiro", "fevereiro", "março", "marco", "abril", "maio", "junho", "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"}),
    relatives=frozenset({"hoje", "amanhã", "amanha", "ontem", "manhã", "manha", "tarde", "noite", "meio-dia", "semana", "mês", "mes", "hora", "próximo", "proximo", "próxima", "proxima", "este", "esta"}),
    frame_words=frozenset({"eu", "quero", "gostaria", "preciso", "tenho", "devo", "pode", "podes", "poderia", "por", "favor", "me", "que", "de", "é", "e", "estou", "para"}),
    request_markers=frozenset({"pode", "podes", "poderia", "quero", "gostaria", "preciso", "tenho que"}),
    determiners=frozenset({"o", "a", "os", "as", "um", "uma", "meu", "minha", "meus", "minhas", "seu", "sua", "este", "esta"}),
    links=frozenset({"o", "a", "os", "as", "de", "do", "da", "para", "até", "ate", "desde", "por", "em", "no", "na", "este", "esta", "próximo", "proximo", "próxima", "proxima"}),
    courteous="Poderia {verb} {object}{time}, por favor?",
    stop_words=frozenset({"o", "a", "os", "as", "um", "uma", "de", "e", "que", "é"}),
)

# ---------------------------------------------------------------------------
# Dutch
# ---------------------------------------------------------------------------

NL = Pack(
    code="nl",
    verbs={
        "verplaatsen": "verplaatsen", "verplaats": "verplaatsen", "verzetten": "verzetten",
        "wijzigen": "wijzigen", "wijzig": "wijzigen", "veranderen": "veranderen", "verander": "veranderen",
        "annuleren": "annuleren", "annuleer": "annuleren",
        "bellen": "bellen", "bel": "bellen",
        "sturen": "sturen", "stuur": "sturen",
        "opsturen": "opsturen", "opstuur": "opsturen",
        "bevestigen": "bevestigen", "bevestig": "bevestigen",
        "betalen": "betalen", "betaal": "betalen",
        "boeken": "boeken", "boek": "boeken",
        "ophalen": "ophalen", "haal": "ophalen",
        "brengen": "brengen", "breng": "brengen",
        "uitleggen": "uitleggen", "leg": "uitleggen",
        "vragen": "vragen", "vraag": "vragen",
        "herhalen": "herhalen", "herhaal": "herhalen",
        "printen": "printen", "print": "printen",
        "wachten": "wachten", "wacht": "wachten",
        "komen": "komen", "kom": "komen",
        "vervroegen": "vervroegen", "uitstellen": "uitstellen",
    },
    days=frozenset({"maandag", "dinsdag", "woensdag", "donderdag", "vrijdag", "zaterdag", "zondag"}),
    months=frozenset({"januari", "februari", "maart", "april", "mei", "juni", "juli", "augustus", "september", "oktober", "november", "december"}),
    relatives=frozenset({"vandaag", "morgen", "overmorgen", "gisteren", "ochtend", "middag", "avond", "nacht", "week", "maand", "uur", "volgende", "deze", "dit"}),
    frame_words=frozenset({"ik", "wil", "graag", "moet", "moeten", "kan", "kunnen", "zou", "zouden", "heb", "hebben", "nodig", "mag", "me", "even", "alsjeblieft", "alstublieft", "om", "te", "dat", "er"}),
    request_markers=frozenset({"kan ik", "kun je", "kunt u", "zou u", "ik wil", "ik moet", "ik heb"}),
    determiners=frozenset({"de", "het", "een", "mijn", "jouw", "zijn", "haar", "ons", "onze", "deze", "dit", "die"}),
    links=frozenset({"op", "om", "tot", "van", "naar", "vanaf", "voor", "in", "deze", "dit", "volgende"}),
    courteous="Kunt u {object}{time} {verb}, alstublieft?",
    stop_words=frozenset({"de", "het", "een", "en", "van", "dat", "is"}),
)

PACKS: dict[str, Pack] = {pack.code: pack for pack in (DE, ES, IT, PT, NL)}


# Fillers people actually say in the languages that have a pack.
FILLERS = frozenset({
    "euh", "heu", "hmm", "hum", "um", "uh", "er", "äh", "aeh", "also", "halt",
    "eh", "bueno", "pues", "o sea", "boh", "insomma", "dus", "nou", "even",
})


@lru_cache(maxsize=1)
def _fillers_norm() -> frozenset[str]:
    """Normalised on first use: "äh" and "ah" must compare equal."""
    return frozenset(_norm(word) for word in FILLERS)


def tokens_of(text: str, lower_first: bool = True) -> list[str]:
    """Words with case preserved (proper nouns keep it), fillers removed."""
    import unicodedata as _u

    def tidy(char: str) -> bool:
        if char in "'-":
            return True
        category = _u.category(char)
        return char.isspace() or category[0] in ("L", "N", "M")

    kept = "".join(char if tidy(char) else " " for char in str(text or ""))
    raw = [word for word in " ".join(kept.split()).split(" ") if word]
    out: list[str] = []
    for index, word in enumerate(raw):
        if _norm(word) in _fillers_norm():
            continue
        if lower_first and index == 0 and len(raw) > 1 and word[:1].isupper():
            word = word[:1].lower() + word[1:]
        out.append(word)
    return out


def has_pack(language: str) -> bool:
    return (language or "").strip().lower()[:2] in PACKS


# ---------------------------------------------------------------------------
# The shared pipeline
# ---------------------------------------------------------------------------

_APOSTROPHE = ("'", "’")


def _norm(token: str) -> str:
    import unicodedata

    decomposed = unicodedata.normalize("NFKD", token.lower().strip())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


@lru_cache(maxsize=None)
def _frame_set(code: str) -> frozenset[str]:
    """Normalised once: "können" must match "konnen", umlaut or not."""
    return frozenset(_norm(word) for word in PACKS[code].frame_words)


def _is_frame(token: str, pack: Pack) -> bool:
    norm = _norm(token)
    words = _frame_set(pack.code)
    if norm in words:
        return True
    head = norm.split("'")[0]
    return bool(head) and head != norm and head in words


def _time_span(tokens: list[str], pack: Pack) -> tuple[int, int] | None:
    time_words = {_norm(w) for w in pack.all_time_words()}
    links = {_norm(w) for w in pack.links}
    anchor = next((i for i, t in enumerate(tokens) if _norm(t) in time_words), None)
    if anchor is None:
        return None
    start = anchor
    while start > 0 and _norm(tokens[start - 1]) in links:
        start -= 1
    end = anchor
    while end + 1 < len(tokens):
        following = _norm(tokens[end + 1])
        after = _norm(tokens[end + 2]) if end + 2 < len(tokens) else ""
        if following in time_words:
            end += 1
        elif following in links and after in time_words:
            end += 2
        else:
            # "morgen an die Apotheke": a link only joins the span when a time
            # word follows it, otherwise the pharmacy is part of the request.
            break
    return start, end


def parts(tokens: list[str], pack: Pack) -> tuple[str, str, str]:
    """(verb, object, time phrase). Verb is a canonical infinitive."""
    normalized = [_norm(t) for t in tokens]
    span = _time_span(tokens, pack)

    time_tokens: list[str] = []
    body = list(tokens)
    body_norms = list(normalized)
    if span:
        start, end = span
        time_tokens = tokens[start:end + 1]
        body = tokens[:start] + tokens[end + 1:]
        body_norms = normalized[:start] + normalized[end + 1:]

    index = next((i for i, t in enumerate(body_norms) if t in pack.verbs), -1)
    verb = ""
    before: list[str] = []
    if index >= 0:
        verb = pack.verbs[body_norms[index]]
        raw_object = body[index + 1:]
        before = body[:index]
    else:
        raw_object = body

    time_words = {_norm(w) for w in pack.all_time_words()}
    object_tokens: list[str] = []
    for offset, token in enumerate(raw_object):
        if _is_frame(token, pack):
            continue
        following = _norm(raw_object[offset + 1]) if offset + 1 < len(raw_object) else ""
        if _norm(token) in pack.links and following in time_words:
            break
        object_tokens.append(token)
    if not object_tokens and before:
        object_tokens = [t for t in before if not _is_frame(t, pack)]

    return verb, " ".join(object_tokens).strip(), " ".join(time_tokens).strip()


def build(tokens: list[str], pack: Pack, style: str, text: str) -> tuple[str, bool, bool]:
    """(message, has_verb_and_object, has_time) — no model, same input twice."""
    verb, obj, when = parts(tokens, pack)
    has_time = bool(when)

    if style == "verbatim":
        sentence = " ".join(tokens)
        return sentence[:1].upper() + sentence[1:] + ".", bool(verb), has_time

    if verb:
        clause = pack.courteous.format(
            verb=verb,
            object=obj,
            time=f" {when}" if when else "",
        )
        return clause[:1].upper() + clause[1:], bool(obj), has_time

    # No verb found: say it politely instead of guessing at a structure. This
    # also keeps "danke" from becoming "danke, bitte".
    return polish(text, pack.code), False, has_time


def reframe_with_pack(text: str, cleaned: str, tokens: list[str], pack: Pack, style: str):
    message, has_vo, has_time = build(tokens, pack, style, cleaned)
    content = len([t for t in tokens if _norm(t) not in pack.stop_words])
    confidence = 0.55 + (0.15 if has_vo else 0) + (0.10 if has_time else 0)
    if content >= 3:
        confidence += 0.05
    if content <= 1:
        confidence -= 0.20
    confidence = round(max(0.05, min(0.95, confidence)), 2)
    return message, confidence, has_vo
