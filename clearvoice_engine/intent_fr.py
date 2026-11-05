"""French reframing rules.

The English reframer works by English syntax: find a verb from a small list, lift
the time expression ("Tuesday"), rebuild a courteous frame ("Could you … please?").
Applied to French that machinery finds nothing — no verb, no time word, no frame —
so it falls back to the transcript with a capital letter and a full stop. That is
exactly the defect a French speaker reports: *"in english it puts the words in
order, in french it's literally the exact thing I said."*

So French gets its own tables and its own small pipeline, sharing only the entry
point and the Proposal type:

    (tokens) → strip the request frame → find the verb (infinitive) → lift the
    time expression → rebuild "Pourriez-vous {verbe} {objet} {quand}, s'il vous
    plaît ?"

Nothing here calls a model: a sentence is rebuilt by rules, so the same input
always produces the same sentence and a test can hold it.
"""

from __future__ import annotations

import re
import unicodedata

# --- lexicon ---------------------------------------------------------------

FR_FILLERS = {
    "euh", "heu", "heum", "hmm", "hum", "bah", "ben", "bon", "bh",
    "enfin", "bref", "genre", "voila", "quoi", "disons", "donc",
}

# Words that carry no meaning once the sentence is rebuilt.
FR_FRAME_WORDS = {
    "je", "j", "ai", "as", "avons", "voudrais", "voudrai", "veux", "veut",
    "voulons", "aimerais", "aimerai", "souhaite", "souhaiterais", "besoin",
    "faut", "faudrait", "dois", "doit", "devons", "il", "elle", "on", "y",
    "vous", "tu", "me", "m", "nous", "te", "t", "peux", "peut", "pouvez",
    "pourrais", "pourriez", "pouvons", "est", "ce", "qu", "que", "s", "se",
    "svp", "plait", "plait-il", "merci", "juste", "sans", "doute", "peu",
    "vraiment", "super", "alors", "stp", "srp",
}
# "a" (avoir) is deliberately absent: "à" normalises to "a", and dropping the
# preposition turned "à propos des ordonnances" into "propos des ordonnances".

FR_VERB_FORMS = {
    # infinitive forms and the common spoken ones
    "déplacer": "déplacer", "deplacer": "déplacer",
    "déplace": "déplacer", "deplace": "déplacer",
    "déplacerai": "déplacer", "déplacerais": "déplacer",
    "reporter": "reporter", "reporte": "reporter",
    "changer": "changer", "change": "changer",
    "modifier": "modifier", "modifie": "modifier",
    "avancer": "avancer", "avance": "avancer",
    "décaler": "décaler", "decale": "décaler", "décale": "décaler",
    "rappeler": "rappeler", "rappelle": "rappeler", "rappelez": "rappeler",
    "appeler": "appeler", "appelle": "appeler", "appelez": "appeler",
    "téléphoner": "téléphoner", "téléphone": "téléphoner",
    "envoyer": "envoyer", "envoie": "envoyer", "envoyez": "envoyer",
    "annuler": "annuler", "annule": "annuler", "annulez": "annuler",
    "confirmer": "confirmer", "confirme": "confirmer", "confirmez": "confirmer",
    "commander": "commander", "commande": "commander",
    "réserver": "réserver", "réserve": "réserver", "reserve": "réserver",
    "récupérer": "récupérer", "récupère": "récupérer",
    "payer": "payer", "paie": "payer", "paye": "payer",
    "prévenir": "prévenir", "préviens": "prévenir",
    "demander": "demander", "demande": "demander",
    "prendre": "prendre", "prends": "prendre",
    "passer": "passer", "passe": "passer",
    "renvoyer": "renvoyer", "renvoie": "renvoyer",
    "imprimer": "imprimer", "imprime": "imprimer",
    "préparer": "préparer", "prépare": "préparer",
    "vérifier": "vérifier", "vérifie": "vérifier",
    "répéter": "répéter", "répète": "répéter",
    "expliquer": "expliquer", "explique": "expliquer",
    "dire": "dire", "dis": "dire", "dites": "dire",
    "attendre": "attendre", "attends": "attendre",
    "chercher": "chercher", "cherche": "chercher",
    "trouver": "trouver", "trouve": "trouver",
    "ouvrir": "ouvrir", "ouvre": "ouvrir",
    "fermer": "fermer", "ferme": "fermer",
    "venir": "venir", "viens": "venir", "venez": "venir",
    "partir": "partir", "pars": "partir",
    "retrouver": "retrouver", "retrouve": "retrouver",
}

FR_DAYS = {"lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"}
FR_MONTHS = {
    "janvier", "février", "fevrier", "mars", "avril", "mai", "juin", "juillet",
    "août", "aout", "septembre", "octobre", "novembre", "décembre", "decembre",
}
FR_RELATIVE = {
    "aujourd'hui", "aujourdhui", "demain", "après-demain", "hier", "matin",
    "matinée", "midi", "après-midi", "apres-midi", "soir", "soirée", "nuit",
    "semaine", "mois", "quatre", "année", "heure", "heures",
}
FR_TIME_WORDS = FR_DAYS | FR_MONTHS | FR_RELATIVE

FR_TIME_LINKS = {"de", "du", "d", "à", "a", "au", "aux", "le", "la", "l",
                 "ce", "cette", "pour", "vers", "dans", "et", "prochain",
                 "prochaine", "matin", "après-midi", "soir"}

FR_DETERMINERS = {
    "mon", "ma", "mes", "ton", "ta", "tes", "son", "sa", "ses",
    "notre", "nos", "votre", "vos", "leur", "leurs",
    "le", "la", "les", "l", "un", "une", "des", "du", "de", "ce", "cette", "ces",
}

FR_QUESTION_STARTS = {
    "est-ce", "est", "qui", "que", "quoi", "quand", "où", "ou", "comment",
    "pourquoi", "combien", "quel", "quelle", "quels", "quelles",
    "pouvez", "pourriez", "peux", "pourrais", "as", "avez", "es", "êtes",
    "c'est", "y", "a",
}

FR_AFFIRMATIONS = {"oui", "ouais", "exact", "exactement", "d'accord", "accord",
                   "ok", "okay", "volontiers", "sûr", "sure", "bien", "parfait"}
FR_NEGATIONS = {"non", "pas", "jamais", "aucun", "aucune", "rien", "personne",
                "annule", "annulez", "arrête", "arrete", "stop"}
FR_GREETINGS = {"bonjour", "salut", "bonsoir", "coucou", "revoir", "merci",
                "bienvenue"}

FR_CONSEQUENTIAL = {
    "annule", "annuler", "annulez", "paye", "payer", "virement", "argent",
    "compte", "orde", "ordonnance", "dossier", "médicament", "medicament",
    "docteur", "médecin", "medecin", "hôpital", "hopital", "urgence",
}

# --- helpers ---------------------------------------------------------------


def _strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _norm(token: str) -> str:
    return _strip_accents(token.lower().strip())


def _frame_prefix(token: str) -> str:
    """'j'ai' → 'j': elided pronouns carry the frame, not the content."""
    head = _norm(token).split("'", 1)[0]
    return head if head and head != _norm(token) else ""


def _is_frame_word(token: str) -> bool:
    norm = _norm(token)
    if norm in FR_FRAME_WORDS:
        return True
    prefix = _frame_prefix(token)
    return bool(prefix) and prefix in FR_FRAME_WORDS


_PUNCT = re.compile(r"[^\w'\-\s]", re.UNICODE)


def clean(transcript: str) -> str:
    text = _PUNCT.sub(" ", transcript or "")
    return re.sub(r"\s+", " ", text).strip()


def tokens_of(transcript: str) -> list[str]:
    """Words, case preserved (proper nouns keep their capital), fillers dropped."""
    raw = [t for t in clean(transcript).split(" ") if t]
    kept = []
    for index, token in enumerate(raw):
        if _norm(token) in FR_FILLERS:
            continue
        # A capital that only exists because the sentence started there is not a
        # proper noun: "Rendez-vous" at the head of a transcript becomes lowercase.
        if index == 0 and len(raw) > 1 and token[:1].isupper():
            token = token[:1].lower() + token[1:]
        kept.append(token)
    return kept


def capitalise(text: str) -> str:
    return text[:1].upper() + text[1:] if text else text


def _article(word: str) -> str:
    """A determiner for a bare noun, by the cheapest rules that do not embarrass."""
    low = _norm(word)
    if not low:
        return ""
    first = low[0]
    if first in "aeiouh":
        return "l'" if not low.startswith("h") else "l'"
    if low.endswith(("tion", "sion", "ance", "ence", "ette", "ure", "ité",
                     "ite", "ie", "ade", "euse", "elle")):
        return "la"
    if low.endswith("e"):
        return "la"
    return "le"


def _with_article(obj: str) -> str:
    if not obj:
        return obj
    first = obj.split(" ", 1)[0]
    if _norm(first) in FR_DETERMINERS:
        return obj
    article = _article(obj)
    if article.endswith("'"):
        return f"{article}{obj}"
    return f"{article} {obj}"


# --- recognition -----------------------------------------------------------


def classify(tokens: list[str]) -> str:
    if not tokens:
        return "unclear"
    norms = [_norm(t) for t in tokens]
    first = norms[0]

    if any(n in FR_GREETINGS for n in norms) and len(norms) <= 4:
        return "greeting"
    if first in FR_QUESTION_STARTS and len(norms) > 1:
        return "question"
    if any(t in FR_VERB_FORMS for t in norms):
        return "request"
    if any(n in FR_AFFIRMATIONS for n in norms) and len(norms) <= 3:
        return "affirmation"
    if any(n in FR_NEGATIONS for n in norms) and len(norms) <= 3:
        return "negation"
    return "statement"


def _verb_index(norms: list[str]) -> int:
    for index, token in enumerate(norms):
        if token in FR_VERB_FORMS:
            return index
    return -1


def _time_span(tokens: list[str]) -> tuple[int, int] | None:
    """Span of the time expression: ("de mardi à jeudi", "pour demain", "mardi")."""
    norms = [_norm(t) for t in tokens]
    anchor = next((i for i, n in enumerate(norms) if n in {_norm(w) for w in FR_TIME_WORDS}), None)
    if anchor is None:
        return None
    start = anchor
    while start > 0 and _norm(tokens[start - 1]) in {_norm(w) for w in FR_TIME_LINKS}:
        start -= 1
    end = anchor
    while end + 1 < len(tokens) and _norm(tokens[end + 1]) in {_norm(w) for w in FR_TIME_LINKS | FR_TIME_WORDS}:
        end += 1
    return start, end


def _parts(tokens: list[str]):
    """(verb, object phrase, time phrase) — the three pieces of a French request."""
    norms = [_norm(t) for t in tokens]
    span = _time_span(tokens)

    time_tokens: list[str] = []
    body = list(tokens)
    body_norms = list(norms)
    if span:
        start, end = span
        time_tokens = tokens[start:end + 1]
        body = tokens[:start] + tokens[end + 1:]
        body_norms = norms[:start] + norms[end + 1:]

    index = _verb_index(body_norms)
    verb = ""
    if index >= 0:
        verb = FR_VERB_FORMS.get(body_norms[index], body_norms[index])
        raw_object = body[index + 1:]
        before = body[:index]
    else:
        raw_object = body
        before = []

    # The object stops only at a preposition that introduces a time ("de mardi");
    # "à propos des ordonnances" or "chez le dentiste" is part of what is wanted.
    cleaned_object: list[str] = []
    time_norms = {_norm(word) for word in FR_TIME_WORDS}
    for offset, token in enumerate(raw_object):
        if _is_frame_word(token):
            continue
        norm = _norm(token)
        if norm in {"de", "du", "d", "à", "a", "au", "aux", "pour", "vers"}:
            following = _norm(raw_object[offset + 1]) if offset + 1 < len(raw_object) else ""
            if following in time_norms:
                break
        cleaned_object.append(token)
    if not cleaned_object and before:
        # Fragmented speech often puts the object first: "mon rendez-vous, déplacer".
        cleaned_object = [t for t in before if not _is_frame_word(t)]

    obj = _with_article(" ".join(cleaned_object).strip())
    when = " ".join(time_tokens).strip()
    return verb, obj, when


def _time_clause(when: str) -> str:
    if not when:
        return ""
    first = _norm(when.split(" ", 1)[0])
    if first in {"de", "du", "d", "à", "a", "au", "aux", "le", "la", "l", "ce",
                 "cette", "pour", "vers", "dans"}:
        return when
    return f"pour {when}"


def courteous(tokens: list[str]) -> tuple[str, bool, bool]:
    """Pourriez-vous … s'il vous plaît ? — returns (message, has_verb_object, has_time)."""
    verb, obj, when = _parts(tokens)
    clause = _time_clause(when)

    if verb and obj:
        message = f"Pourriez-vous {verb} {obj}"
        return f"{message} {clause}, s'il vous plaît ?" if clause else f"{message}, s'il vous plaît ?", True, bool(when)
    if verb:
        message = f"Pourriez-vous {verb}"
        return (f"{message} {clause}, s'il vous plaît ?" if clause else f"{message}, s'il vous plaît ?"), False, bool(when)
    if obj:
        return f"Je voudrais {obj}, s'il vous plaît.", False, bool(when)
    return "Pourriez-vous m'aider, s'il vous plaît ?", False, bool(when)


def literal(tokens: list[str]) -> str:
    verb, obj, when = _parts(tokens)
    clause = _time_clause(when)
    core = " ".join(part for part in (verb, obj, clause) if part)
    if not core:
        core = " ".join(tokens)
    return capitalise(core.rstrip(".")) + "."


def verbatim(text: str, intent: str) -> str:
    tidied = capitalise(" ".join(clean(text).split()))
    if intent == "question":
        return tidied.rstrip("?.") + " ?"
    return tidied.rstrip(".") + "."


def candidates(intent: str, primary: str, tokens: list[str]) -> list[str]:
    plain = capitalise(" ".join(tokens)) + "."
    options = [primary]
    if intent == "request":
        options.append(literal(tokens))
        options.append(f"Je voudrais {plain[0].lower()}{plain[1:]}")
    elif intent == "question":
        options.append(primary.rstrip("? ") + " ?")
    else:
        options.append(plain)
    unique: list[str] = []
    for option in options:
        if option not in unique and option:
            unique.append(option)
    return unique[:3]


def guess_language(text: str) -> str:
    """French or English, from the words a speaker actually uses."""
    lowered = (text or "").lower()
    if re.search(r"[àâçéèêëîïôùûœ]", lowered):
        return "fr"
    words = re.findall(r"[a-z']+", lowered)
    if not words:
        return "en"
    fr_marks = {"le", "la", "les", "des", "du", "un", "une", "je", "j'ai", "vous",
                "nous", "est", "pas", "pour", "avec", "mon", "ma", "mes", "c'est",
                "s'il", "au", "aux", "ce", "cette", "et", "de", "que", "qui",
                "il", "elle", "on", "dans", "sur", "sont", "être", "avoir"}
    en_marks = {"the", "a", "an", "i", "you", "we", "is", "are", "not", "to",
                "with", "my", "your", "could", "can", "please", "and", "of",
                "need", "want", "it", "that", "this", "yes", "no", "help",
                "stop", "thanks", "hello", "medicine", "appointment"}
    fr = sum(1 for word in words if word in fr_marks)
    en = sum(1 for word in words if word in en_marks)
    # English is the default pack: on a tie, or with no evidence either way, do
    # not silently start rebuilding a sentence with French rules.
    return "fr" if fr > en else "en"
