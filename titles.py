"""제목 10개 → 점수 → 1개 확정.

설계 원칙: 제목 선택은 LLM이 하지 않는다.
모델은 후보만 만들고, 고르는 건 아래 점수 함수다.
홈판은 앞 20자만 노출되므로 총점의 절반 이상이 앞 20자에서 나온다.

튜닝은 프롬프트가 아니라 config.WEIGHTS 숫자로 한다.
"""

import re

import config as C

_NUM = re.compile(r"\d+")
_AGE = re.compile(r"\d+\s*(?:세|대)")
_JOB = re.compile(
    r"여배우|배우|가수|모델|아나운서|방송인|개그우먼|코미디언|트로트|"
    r"여신|스타|아이돌|디바|MC|셀럽"
)
# 유지 기간형: 37년째 / 20년간 / 15년 동안
_DURATION = re.compile(r"\d+\s*년\s*(?:째|간|동안|넘게|째로)")
_WEIGHT_TOKEN = re.compile(r"\d+\s*(?:kg|KG|킬로|키로)|\d+\s*사이즈|몸무게|체중")
# 감량 낙차형: 58kg에서 44kg으로 / 58 → 44 / 70kg대에서
_DROP = re.compile(
    r"\d+\s*(?:kg|KG|킬로|키로)?\s*(?:대)?\s*(?:에서|부터|→|->)\s*\d+"
)
_QUOTE = re.compile(r'["“”‘’\']')
_HEIGHT = re.compile(r"(\d{2,3})\s*(?:cm|CM|센치|센티)")
_KG = re.compile(r"(\d{2,3})\s*(?:kg|KG|킬로|키로)")
_QUESTION_END = re.compile(r"(?:\?|까|까요|나요|을까|ㄹ까|일까|는지)\s*$")
_OPEN_END = re.compile(r"(?:\.\.\.|…)\s*$")


def _head(title: str) -> str:
    return title[: C.HEAD_LEN]


def _fully_inside(pattern: re.Pattern, head: str, title: str) -> bool:
    """패턴이 앞 20자 안에서 '온전히' 끝나는지. 잘린 매치는 인정하지 않는다."""
    for m in pattern.finditer(title):
        if m.end() <= len(head):
            return True
    return False


def _bmi(title: str):
    """제목에 키와 몸무게가 함께 병기됐을 때만 BMI를 계산한다."""
    h = _HEIGHT.search(title)
    w = _KG.search(title)
    if not (h and w):
        return None
    cm = int(h.group(1))
    kg = int(w.group(1))
    if cm < 120 or cm > 210 or kg < 25 or kg > 200:
        return None
    return kg / ((cm / 100) ** 2)


def disqualify_reason(title: str):
    """즉시 탈락 사유. 없으면 None."""
    for w in C.EXTREME_WORDS:
        if w in title:
            return f"극단 마름 표현: {w}"
    for w in C.BANNED_HOOKS:
        if w in title:
            return f"금지선: {w}"
    for name in C.CELEB_POOL:
        if name in title:
            return f"여자 실명 노출: {name}"
    return None


def score(title: str):
    """(점수, 사유 목록) 반환. 사유는 titles.json에 그대로 남긴다."""
    title = title.strip()
    reasons = []

    dq = disqualify_reason(title)
    if dq:
        return C.DISQUALIFIED, [f"{dq} → 즉시 탈락"]

    head = _head(title)
    w = C.WEIGHTS
    total = 0

    if _NUM.search(head):
        total += w["head_number"]
        reasons.append(f"앞20자 숫자 +{w['head_number']}")

    if any(s in head for s in C.DIET_SIGNAL_WORDS):
        total += w["head_diet_signal"]
        reasons.append(f"앞20자 다이어트 신호어 +{w['head_diet_signal']}")

    if _fully_inside(_AGE, head, title) or _fully_inside(_JOB, head, title):
        total += w["head_person"]
        reasons.append(f"앞20자 인물 특정 +{w['head_person']}")

    if _DURATION.search(title) and _WEIGHT_TOKEN.search(title):
        total += w["duration_form"]
        reasons.append(f"유지 기간형 +{w['duration_form']}")

    if _DROP.search(title):
        total += w["drop_form"]
        reasons.append(f"감량 낙차형 +{w['drop_form']}")

    if _QUOTE.search(title):
        total += w["quote"]
        reasons.append(f"본인 발언 인용 +{w['quote']}")

    if any(e in title for e in C.LIFE_EVENTS):
        total += w["life_event"]
        reasons.append(f"인생 사건 +{w['life_event']}")

    if any(n in title for n in C.MALE_CELEB_NAMES):
        total += w["male_celeb"]
        reasons.append(f"관계 남자 연예인 +{w['male_celeb']}")

    if _OPEN_END.search(title):
        pass  # 말줄임 종결은 단정형도 질문형도 아니다
    elif _QUESTION_END.search(title):
        total += w["question_end"]
        reasons.append(f"질문형 종결 {w['question_end']}")
    else:
        total += w["assertive_end"]
        reasons.append(f"단정형 종결 +{w['assertive_end']}")

    n = min(len(_NUM.findall(title)), C.MAX_COUNTED_NUMBERS)
    if n:
        total += n * w["per_number"]
        reasons.append(f"숫자 {n}개 +{n * w['per_number']}")

    over = len(title) - C.TITLE_LEN_SOFT_MAX
    if over > 0:
        total -= over
        reasons.append(f"{C.TITLE_LEN_SOFT_MAX}자 초과 {over}자 -{over}")

    bmi = _bmi(title)
    if bmi is not None and bmi < C.BMI_FLOOR:
        total += w["underweight"]
        reasons.append(f"저체중 스펙 BMI {bmi:.1f} {w['underweight']}")

    return total, reasons


def pick(candidates):
    """후보 리스트 → [{title, score, reasons}] 내림차순. 1등이 확정 제목."""
    scored = []
    for t in candidates:
        t = (t or "").strip()
        if not t:
            continue
        s, r = score(t)
        scored.append({"title": t, "score": s, "reasons": r})
    scored.sort(key=lambda x: -x["score"])
    return scored


# ── 자체 테스트 ─────────────────────────────────────────────────────────
# 인수인계 문서에 적힌 실측 점수를 그대로 재현하는지 확인한다.
KNOWN = [
    ("37년째 53kg 유지한다는 58세 여배우의 아침 식탁", 110),
    ("58kg에서 44kg으로, 이혼 후 달라진 44세 여배우 근황", 104),
    ('"165cm 43kg" 유지한다는 62세 여배우의 아침 식탁', 30),
    ("뼈말라 몸매로 화제된 40대 여배우 다이어트", C.DISQUALIFIED),
]

if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    ok = True
    for title, expected in KNOWN:
        got, reasons = score(title)
        mark = "OK " if got == expected else "FAIL"
        if got != expected:
            ok = False
        print(f"{mark} 기대 {expected:>5} / 실제 {got:>5}  {title}")
        for r in reasons:
            print(f"        - {r}")
    print()
    print("전부 일치" if ok else "불일치 있음 — 가중치 확인 필요")
    sys.exit(0 if ok else 1)
