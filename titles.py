"""제목 10개 → 점수 → 1개 확정.

원본 규칙은 저장소 루트 **제목규칙.md** 다. 이 파일은 그 구현체다.
규칙을 바꾸려면 제목규칙.md 를 먼저 고치고 여기를 맞춘다. 반대로 하면 둘이 갈라진다.

설계 원칙: 제목 선택은 LLM이 하지 않는다.
모델은 후보만 만들고, 고르는 건 아래 점수 함수다.

2026-08-16 전면 교체. 이전 표는 "다이어트 정보"에 가점을 줬다(앞20자 다이어트
신호어 +22). 사용자 판정으로 그 방향이 뒤집혔다 — 클릭을 만드는 건 다이어트가
아니라 **인물 가십**이고, 다이어트는 훅이 아니라 명분이다.
그래서 다이어트 단어가 앞쪽에 있으면 이제 **감점**이다.
"""

import re

import config as C

# ── 제목규칙 §1 폐기 조건 판정용 ────────────────────────────────────────
_AGE = re.compile(r"\d+\s*(?:세|대|년생)")
_JOB = re.compile(
    r"여배우|배우|여가수|가수|모델|아나운서|방송인|개그우먼|코미디언|트로트|"
    r"여신|스타|아이돌|디바|MC|셀럽|출신|여사장|사업가"
)
# §1-3 큰따옴표 발화 훅. 맨 앞에서 열려야 한다(§2 "훅은 반드시 맨 앞").
_HOOK = re.compile(r'^\s*["“]([^"“”]{2,30})["”]')
# §1-4 kg·cm·인치 중 하나
_SIZE = re.compile(r"\d+\s*(?:kg|KG|킬로|키로|cm|CM|센치|센티|인치)")
# §1-6 "N가지" / "Best N" / "TOP N"
_LISTICLE = re.compile(r"\d+\s*가지|\bbest\s*\d+|\btop\s*\d+|베스트\s*\d+|탑\s*\d+",
                       re.IGNORECASE)

# ── 제목규칙 §3 화력 증폭기 판정용 ──────────────────────────────────────
# §3-2 돈: 800억 / 12억 / 3천만원 / 억대
_MONEY = re.compile(r"\d+\s*(?:억|조|천만원|백만원|만원)|억대|조원")
# §3-4 상식 배반: "먹었는데 뺐다". 양보/역접 어미 + 먹는 행위
# ⚠️ 2026-08-19 확장. 좁아서 규칙서가 직접 예로 든 문형까지 놓치고 있었다.
#    실측으로 놓친 것: "굶으면 오히려 쪄요"(규칙서 본문 예시 문구) ·
#    "라면 끊은 적 없다는" · "운동은 한 번도 안 했다는".
#    사용자: "핵심은 어? 진짜? 설마? 하면서 들어오게 만드는 것."
#    상식 배반은 그 '설마?'를 만드는 축이라 넓게 잡아야 한다.
_DEFY = re.compile(
    r"(?:먹|밥|탄수화물|치킨|야식|빵|면|술|디저트|라면)[^ ]{0,6}"
    r"(?:는데도|은데도|인데도|었는데|았는데|고도|면서도)"
    r"|굶어도|안 굶고|약 안 먹고|운동 안 하고|끊지 않"
    # 역방향 결과 — "굶으면 오히려 쪄요"
    r"|오히려\s*\S{0,6}(?:쪄|찐|찝|늘|불어|더 )"
    # 한 번도 안 했다 — "운동은 한 번도 안 했다는"
    r"|한 번도\s*(?:안|못)|평생\s*(?:안|한 번도)|단 한 번도"
    # 끊은 적이 없다 — "라면 끊은 적 없다는"
    r"|(?:끊|참|줄인|거른|건너뛴)[^ ]{0,4}적\s*(?:이\s*)?없"
    r"|끊은 적 없|참은 적 없|안 하고도|없이도|그대로 먹|그대로 마시"
)
# §3-5 억울·자기부정 발화
# ⚠️ 2026-08-19 확장. 규칙서가 "억울·불만이 성공담보다 세다"라고 못 박아 뒀는데
#    감지기는 "억울" 이라는 낱말 몇 개만 봤다. 실측으로 놓친 것:
#    "저는 원래 물만 먹어도 쪄요" · "살 빼도 아무도 몰라주더라" ·
#    "거울 보기 싫었다던" · "평생 뚱뚱했다고 놀림받았다는".
_SELF_NEG = re.compile(
    r"억울|밖에 안|망언|뭐한거지|나 살쪘|걱정했|짜증|서럽|후회|자괴|한심|창피"
    # 체질 호소 — "물만 먹어도 쪄요"
    r"|물만 먹어도|숨만 쉬어도|원래 잘 안|원래 안 빠|타고나길"
    # 몰라준다 — "아무도 몰라주더라"
    r"|아무도\s*(?:몰라|모르|안 알아|못 알아)|티도 안|표도 안"
    # 자기혐오 — "거울 보기 싫었다"
    r"|보기 싫|보기가 싫|쳐다보기도|숨고 싶|가리고 다|자신 없|자신감 없"
    # 상처 — "놀림받았다"
    r"|놀림|놀렸|비웃|무시당|눈치 보|주눅|상처받|소리 들"
    r"|포기했|포기하려|그만두려"
)
# §4 나이 불신형 훅: "이게 46세?" / "진짜 46세 맞아?"
# ⚠️ 2026-08-19 확장. "82년생이라는 게 믿기냐" · "주민등록증 보여달라던" 을
#    놓쳤다. 둘 다 "어? 진짜?" 를 만드는 전형적인 나이 불신형이다.
_AGE_DISBELIEF = re.compile(
    r"(?:이게|진짜|실화|실제로).{0,10}\d+\s*(?:세|대|년생)"
    r"|\d+\s*(?:세|대|년생).{0,10}(?:맞아|맞나|맞냐|실화|라고\?|믿기|믿어지|믿을 수)"
    # 신분증 확인 — 나이 불신의 관용 표현
    r"|주민등록증|민증|신분증.{0,6}(?:보여|확인|까)"
    # 나이를 되묻는 형태
    r"|나이[^ ]{0,4}(?:속|의심|안 믿|못 믿)|몇 살[^ ]{0,4}(?:이야|인지|냐)"
)
# 정보 단어가 **사건 서술** 안에 들어간 경우. 남이 물어봤다·궁금해했다는
# 사건이지 우리가 정보를 주겠다는 예고가 아니다 (2026-08-19).
_INFO_AS_EVENT = re.compile(
    r"(?:비결|비법|방법|노하우)\s*(?:을|를|이|가)?\s*"
    r"(?:물어|캐물|여쭤|궁금|알고 싶|알려달|묻|캐)"
)
# §4 정보형 훅: 가십이 아니라 정보다
_INFO_HOOK = re.compile(
    r"비법|비결|방법|팁|노하우|정리|총정리|알아보|추천|효능|효과적|하는 법|"
    r"주의사항|체크리스트|가이드"
)
# §3 감량폭+기간 동시: "40일, 28kg" / "3개월에 16kg" / "두 달 만에 9kg"
_PERIOD = re.compile(r"\d+\s*(?:일|주|개월|달|년)|두\s*달|석\s*달|한\s*달")
_DROP_AMOUNT = re.compile(r"\d+\s*(?:kg|KG|킬로|키로)")
_HEIGHT = re.compile(r"(\d{2,3})\s*(?:cm|CM|센치|센티)")
_KG = re.compile(r"(\d{2,3})\s*(?:kg|KG|킬로|키로)")


# 경력·기간을 숫자로 밝힌 표현도 수식어로 인정한다 ("19년 차 배우", "데뷔 27년").
# 목록에만 의존하면 멀쩡한 제목이 '맨몸' 취급을 받는다.
_TENURE = re.compile(r"\d+\s*년\s*(?:차|째|만에)|데뷔\s*\d+|\d+\s*기|\d+\s*년\s*활동")


# 이름 뒤에 붙는 한 글자 조사. 이 집합 안이면 이름 경계로 본다.
_JOSA = set("이가은는을를과와도만의에로께랑씨님")


def _name_hit(text: str, name: str) -> bool:
    """실명이 **독립된 이름으로** 들어 있는가 (2026-08-19, 패션비버에서 이식).

    단순 부분문자열 검사는 두 방향으로 틀린다.
      · 앞 경계 없음: "서현" 이 "서현진" 에 걸린다. 실제 풀에 그런 쌍이 셋 있다
        (서현/서현진 · 윤아/송윤아 · 윤아/오윤아).
        주인공이 "서현" 인 글에서 제3자로 "서현진" 을 쓰면 §1-7 이 주인공
        실명 노출로 오판해 **멀쩡한 제목이 즉시 탈락**한다.
      · 뒤 경계를 한글로 막으면: "김태희도" 처럼 조사가 붙은 실제 표기를
        전부 놓친다 (패션비버에서 상위 20편 중 12편을 놓쳤다).
    그래서 앞은 한글이면 막고, 뒤는 조사만 허용한다.
    """
    if not name or len(name) < 2:
        return False
    for i in range(len(text) - len(name) + 1):
        if text[i:i + len(name)] != name:
            continue
        before = text[i - 1] if i > 0 else ""
        after = text[i + len(name)] if i + len(name) < len(text) else ""
        if "가" <= before <= "힣":
            continue
        if "가" <= after <= "힣" and after not in _JOSA:
            continue
        return True
    return False


def _third_party_pool(subject=None):
    """제목에 남아 있어도 되는(=오히려 +30인) 실명들.

    주인공은 §1-7 로 이미 폐기되므로, 제목에 살아남은 실명은 정의상 제3자다.
    주인공만 빼고 전부 제3자로 본다.
    """
    pool = set(C.CELEB_POOL) | set(C.MALE_CELEB_NAMES) | set(C.THIRD_PARTY_EXTRA)
    if subject:
        pool.discard(subject.strip())
    return pool


def hook_units(title: str, subject=None):
    """제목에 든 **서로 다른 훅 축** 목록 (2026-08-19 사용자 지시로 신설).

    사용자: "하나가 엄청 구체적이면서 강력한 거면 몰라도, 그냥 적당히 강한
    거면 2개를 넣는 게 더 세게 꽂힌다. 0.5초 안에 클릭할지 말지 결정하게
    만들어야 한다. 홈판에서 클릭이 안 나오면 글이 아무리 좋아도 의미 없다."

    ⚠️ 나이·kg·큰따옴표 훅은 §1 이 이미 **필수**로 강제한다. 그래서 축으로
       세지 않는다 — 모든 제목이 갖고 있으니 세봐야 변별이 안 된다.
       여기서 세는 건 그 위에 얹은 **선택 축**이다. 축이 하나뿐이면
       "필수 요소 + 적당히 강한 것 하나" 이고, 그게 사용자가 말한 약한 제목이다.

    패션비버 실측(월간 상위 20편): 축 1개 평균 14,690회 / 2개 20,499 /
    3개 32,286 / 4개 14,180. 건강비버는 자체 순위 데이터가 아직 없어 같은
    방향으로만 적용한다 — 순위표가 생기면 여기서 다시 재야 한다.
    """
    got = []
    if any(_name_hit(title, n) for n in _third_party_pool(subject)):
        got.append("실명")
    if _MONEY.search(title):
        got.append("돈")
    if any(x in title for x in C.TABOO_WORDS):
        got.append("금기")
    # 아래 축 구분은 제목규칙 §4 점수표의 항목과 1:1 로 맞췄다.
    # 나이 불신형과 상식 배반은 표에서도 **다른 줄**이라 따로 센다.
    if _AGE_DISBELIEF.search(title):
        got.append("나이불신")
    if _DEFY.search(title):
        got.append("상식배반")
    if _SELF_NEG.search(title):
        got.append("자기부정")
    if (_PERIOD.search(title) and _DROP_AMOUNT.search(title)) or (
            _HEIGHT.search(title) and _KG.search(title)):
        got.append("수치")
    return got


def disqualify_reason(title: str, subject=None):
    """즉시 탈락 사유(제목규칙 §1). 없으면 None.

    subject 는 그 글의 주인공 이름이다. §1-7 은 **주인공 실명만** 폐기한다.
    예전에는 여자 연예인 179명 풀 전체를 죽였는데, 그러면 §3-1 의 최강 카드
    (김태희 같은 제3자 실명, 실증 5,425회)가 같이 죽는다.
    """
    t = title.strip()

    # 기존 안전장치는 유지한다. 제목규칙 §6-3 이 "나머지는 허용"이라고 했지만
    # 아래 셋은 수위 문제가 아니라 사고 방지라 성격이 다르다.
    for w in C.EXTREME_WORDS:                       # 거식·프로아나 = 섭식장애 미화
        if w in t:
            return f"극단 마름 표현: {w}"
    for w in C.BANNED_HOOKS:                        # 약물·시술
        if w in t:
            return f"금지선: {w}"
    for w in getattr(C, "CLICHE_OPENERS", ()):      # 프롬프트 예시 복붙
        if w in t:
            return f"상투 문구 복붙: {w}"

    # ── 제목규칙 §1 ──
    if subject and _name_hit(t, subject.strip()):
        return f"§1-7 주인공 실명 노출: {subject.strip()}"
    if not (_AGE.search(t) or _JOB.search(t)):
        return "§1-1 인물이 없다"
    if not _AGE.search(t):
        return "§1-2 나이 숫자가 없다"
    if not _HOOK.match(t):
        return "§1-3 맨 앞에 큰따옴표 발화 훅이 없다"
    if not _SIZE.search(t):
        return "§1-4 kg·cm·인치가 하나도 없다"
    for w in C.MEDICAL_WORDS:
        if w in t:
            return f"§1-5 질병·영양제·의사 소재: {w}"
    if _LISTICLE.search(t):
        return "§1-6 N가지 / Best N / TOP N"
    return None


def quote_warning(title: str, factsheet=None):
    """제목규칙 §6-1 — 큰따옴표 발화가 팩트시트에 근거가 있는가.

    **경고만 낸다. 폐기하지 않는다.** 제목의 훅은 원문을 줄인 의역이라 글자가
    일치하지 않는 게 정상이고, 형태 D/E(사실형 훅 "이게 46세 몸매?")는 애초에
    인물 발언이 아니라서 문자열 대조로 죽이면 전부 오탐이 된다.
    그래서 추적이 안 되는 발화형 훅에만 표시를 달아 사람이 보게 한다.
    """
    m = _HOOK.match(title.strip())
    if not m or not factsheet:
        return None
    hook = m.group(1)
    # 사실형 훅(나이 불신·상식 파괴 단정)은 인물 발언이 아니므로 대조 대상이 아니다
    if _AGE_DISBELIEF.search(hook):
        return None
    quotes = factsheet.get("quotes") or []
    if not quotes:
        return "§6-1 팩트시트에 발언이 하나도 없는데 발화형 훅을 썼다 — 근거 확인 필요"
    # 2자 이상 토막이 하나라도 겹치면 의역으로 본다
    frags = {hook[i:i + 2] for i in range(len(hook) - 1) if not hook[i:i + 2].isspace()}
    for q in quotes:
        if any(f in q for f in frags):
            return None
    return "§6-1 훅이 팩트시트 발언과 겹치는 부분이 없다 — 지어낸 말인지 확인 필요"


def score(title: str, subject=None, factsheet=None):
    """(점수, 사유 목록) 반환. 사유는 titles.json에 그대로 남긴다."""
    title = (title or "").strip()
    reasons = []

    dq = disqualify_reason(title, subject)
    if dq:
        return C.DISQUALIFIED, [f"{dq} → 즉시 탈락"]

    head = title[: C.HEAD_LEN]
    w = C.WEIGHTS
    total = 0

    # ── §3-1 제3자 유명인 실명 (+30) — 최강 카드 ──
    hit = [n for n in _third_party_pool(subject) if _name_hit(title, n)]
    if hit:
        total += w["third_party_celeb"]
        reasons.append(f"제3자 유명인 실명({hit[0]}) +{w['third_party_celeb']}")

    # ── §3-3 금기 소재 (+25) ──
    tb = [x for x in C.TABOO_WORDS if x in title]
    if tb:
        total += w["taboo"]
        reasons.append(f"금기 소재({tb[0]}) +{w['taboo']}")

    # ── §3-2 돈 숫자 (+20) ──
    if _MONEY.search(title):
        total += w["money"]
        reasons.append(f"돈 숫자 +{w['money']}")

    # ── §3-5 자기부정·억울 (+15) ──
    if _SELF_NEG.search(title):
        total += w["self_negative"]
        reasons.append(f"자기부정·억울 훅 +{w['self_negative']}")

    # ── §4 나이 불신형 훅 (+15) ──
    if _AGE_DISBELIEF.search(title):
        total += w["age_disbelief"]
        reasons.append(f"나이 불신형 훅 +{w['age_disbelief']}")

    # ── §4 감량폭+기간 동시 (+15) ──
    if _PERIOD.search(title) and _DROP_AMOUNT.search(title):
        total += w["drop_with_period"]
        reasons.append(f"감량폭+기간 동시 +{w['drop_with_period']}")

    # ── §3-4 상식 배반 (+15) ──
    if _DEFY.search(title):
        total += w["defy_sense"]
        reasons.append(f"상식 배반(먹었는데 뺐다) +{w['defy_sense']}")

    # ── §2 S2 수식어 특정성 (+10) ──
    if any(e in title for e in C.SPECIFIC_EPITHETS):
        total += w["specific_epithet"]
        reasons.append(f"수식어 특정성 +{w['specific_epithet']}")

    # ── §4 키+몸무게 동시 (+10) ──
    if _HEIGHT.search(title) and _KG.search(title):
        total += w["height_weight"]
        reasons.append(f"키+몸무게 동시 +{w['height_weight']}")

    # ── §5 앞 20자 안에서 훅이 온전히 닫힘 (+10) ──
    m = _HOOK.match(title)
    if m and m.end() <= C.HEAD_LEN:
        total += w["hook_in_head"]
        reasons.append(f"앞{C.HEAD_LEN}자 안에 훅 완결 +{w['hook_in_head']}")

    # ── §4 감점: 다이어트 단어가 앞쪽 ──
    # 훅이 있어야 할 자리를 명분(다이어트)이 먹었다는 뜻이다.
    # 훅 인용구 안의 다이어트 단어는 세지 않는다 — 그건 훅이지 명분이 아니다.
    after_hook = title[m.end():] if m else title
    early = after_hook[: max(0, C.HEAD_LEN - (m.end() if m else 0))]
    if any(s in early for s in C.DIET_SIGNAL_WORDS if s not in ("kg", "킬로", "키로")):
        total += w["diet_word_early"]
        reasons.append(f"다이어트 단어가 앞쪽 {w['diet_word_early']}")

    # ── §4 감점: 직업어에 수식어가 없다 ──
    # 2026-08-18 사용자 확정(두 블로그 동일 규칙):
    #   "앞에 충분히 궁금해 할 만한 포인트가 들어가면서 수식어가 붙으면 사용 가능."
    # 전에는 "여배우" 라는 글자만 검사해서 `40대 여가수`·`톱스타 걸그룹`·`모델` 은
    # 그냥 통과했다. 금지가 아니라 **맨몸으로 쓰지 말라**는 규칙이므로
    # 직업어 전체를 같은 기준으로 본다.
    if (_JOB.search(title)
            and not any(e in title for e in C.SPECIFIC_EPITHETS)
            and not _TENURE.search(title)):
        total += w["bare_actress"]
        reasons.append(f"직업어에 수식어가 없다(특정성 0) {w['bare_actress']}")

    # ── §4 감점: 훅이 정보형 ──
    # 규칙서: "훅이 정보형(팁·비법·방법)이면 -25. 그건 가십이 아니라 정보다."
    # ⚠️ 2026-08-19: **남이 비결을 물어봤다는 건 사건이지 정보 제공이 아니다.**
    #    실측 — "이효리도 비결 캐물었다는" 이 -25 를 맞았다. 이건 제3자 실명
    #    사건형(최강 카드)인데 정보형으로 오판한 것이다.
    if _INFO_HOOK.search(title) and not _INFO_AS_EVENT.search(title):
        total += w["info_hook"]
        reasons.append(f"훅이 정보형(팁·비법·방법) {w['info_hook']}")

    # ── §5 길이 30~40자 ──
    over = len(title) - C.TITLE_LEN_MAX
    if over > 0:
        total -= over
        reasons.append(f"{C.TITLE_LEN_MAX}자 초과 {over}자 -{over}")
    short = C.TITLE_LEN_MIN - len(title)
    if short > 0:
        total -= short
        reasons.append(f"{C.TITLE_LEN_MIN}자 미달 {short}자 -{short}")

    # ── 훅 축 다양성 (2026-08-19 사용자 지시) ──────────────────────────
    # "적당히 강한 거면 2개를 넣어야 세게 꽂힌다. 0.5초 안에 결정된다."
    #
    # ⚠️ **점수는 건드리지 않는다.** 제목규칙 §4 의 점수표는 사용자가 정한
    #    것이고, 같은 절이 배점 조정 조건까지 못 박아 뒀다:
    #        "점수 60~70인데 조회수가 상위권이면 → 해당 요소 배점을 올린다"
    #    즉 배점은 **조회수를 보고** 바꾸는 것이다. 건강비버는 아직 그
    #    순위 데이터가 없다. 패션비버 수치(축 1개 14,690회 / 2개 20,499 /
    #    3개 32,286)를 다른 블로그에 그대로 옮겨 배점을 흔들면 근거 없는
    #    조작이 된다. 그래서 여기서는 **표시와 동점 처리에만** 쓴다.
    units = hook_units(title, subject)
    if len(units) >= 2:
        reasons.append(f"훅 축 {len(units)}개({'+'.join(units)})")
    else:
        reasons.append(
            f"⚠ 훅 축 {len(units)}개({'+'.join(units) or '없음'}) — 나이·kg·인용은 "
            "어차피 필수다. 그 위에 실명·돈·금기·반전·감정 중 둘은 얹어야 "
            "0.5초 안에 눌린다")

    wr = quote_warning(title, factsheet)
    if wr:
        reasons.append(f"⚠ {wr}")

    return total, reasons


def pick(candidates, subject=None, factsheet=None):
    """후보 리스트 → [{title, score, reasons}] 내림차순. 1등이 확정 제목.

    동점이면 제목규칙 §4 에 따라 제3자 실명 보유 쪽을 위로 올린다.
    실명까지 같으면 **훅 축이 많은 쪽**을 올린다 (2026-08-19 사용자 지시).
    점수표를 건드리지 않고 사용자의 새 원칙을 반영할 수 있는 자리다.
    """
    scored = []
    for t in candidates:
        t = (t or "").strip()
        if not t:
            continue
        s, r = score(t, subject, factsheet)
        units = hook_units(t, subject)
        scored.append({
            "title": t, "score": s, "reasons": r,
            # 실명 판정도 경계 검사를 쓴다 — "서현" 이 "서현진" 에 걸리던 버그
            "third_party": "실명" in units,
            "hook_units": units,
        })
    scored.sort(key=lambda x: (-x["score"], not x["third_party"],
                               -len(x["hook_units"])))
    return scored


def below_floor(ranked):
    """제목규칙 §4 — 최고점이 60점 미만이면 전부 폐기하고 다시 뽑아야 한다."""
    if not ranked:
        return True
    return ranked[0]["score"] < C.MIN_SCORE


def material_report(factsheet, subject=None):
    """이 팩트시트로 60점을 만들 재료가 있는가.

    점수표 산술상 제3자 실명(+30)·금기 소재(+25)·돈 숫자(+20) 중 최소 하나가
    없으면 60점을 넘기기가 사실상 불가능하다(나머지를 6개 쌓으면 40자를 넘어
    초과 감점으로 되돌아온다). 재료가 없는 인물은 **후보를 몇 번 다시 뽑아도
    안 된다** — 인물을 바꾸는 게 맞다.

    제목을 뽑기 전에 이걸 봐야 슬롯 하나를 통째로 날리지 않는다.
    반환: (가진 카드 목록, 없는 카드 목록)
    """
    if not factsheet:
        return [], ["팩트시트 없음"]
    blob = " ".join(
        str(v) for k, v in factsheet.items()
        if k not in ("celeb",) and isinstance(v, (str, int, float, list))
        for v in ([v] if not isinstance(v, list) else v)
    )
    have, missing = [], []
    tp = [n for n in _third_party_pool(subject) if len(n) >= 2 and n in blob]
    (have if tp else missing).append(
        f"제3자 실명(+30){': ' + tp[0] if tp else ''}")
    tb = [x for x in C.TABOO_WORDS if x in blob]
    (have if tb else missing).append(
        f"금기 소재(+25){': ' + tb[0] if tb else ''}")
    mn = _MONEY.search(blob)
    (have if mn else missing).append(
        f"돈 숫자(+20){': ' + mn.group() if mn else ''}")
    return have, missing


# ── 자체 테스트 ─────────────────────────────────────────────────────────
# 제목규칙.md 의 실증 예시를 그대로 쓴다. 조회수가 붙은 것은 실제 성과다.
KNOWN = [
    # §1 폐기 — 실패 실증
    ("마그네슘과 함께 먹으면 좋은 음식 Best 5", C.DISQUALIFIED),        # 인물X·마그네슘·Best N
    ("이거 모르면 나도 모르게 식중독", C.DISQUALIFIED),                  # 인물X·식중독
    ("의사가 경고한 당뇨 유발 음식", C.DISQUALIFIED),                    # 의사·당뇨
    ("두 달 만에 9kg 감량 성공 톱스타 이승연 다이어트", C.DISQUALIFIED),  # 주인공 실명(§1-7)
    # 훅은 있는데 나이가 없다 → §1-2
    ('"우리가 헤어졌다.." 톱스타의 45kg', C.DISQUALIFIED),
    # 통과형 — 제3자 실명(+30) 또는 금기(+25)를 물고 있으면 여유 있게 넘는다
    ('"성시경과 결혼할 줄 알았지만".. 11살 연상과 결혼 후 46세 원조 요정 43kg', 68),
    # ⚠️ 아래 둘은 제목규칙 §2 형태 E·§3-4·§3-5 를 제대로 갖췄는데도 **60 미만**이다.
    #    버그가 아니라 §4 점수표의 산술이 그렇다. 제3자 실명(+30)·금기(+25)·돈(+20)
    #    셋 중 하나가 없으면 나머지 항목을 6개는 쌓아야 60이 된다.
    #    즉 이 표는 "세 카드 중 최소 하나는 반드시 물어라"는 뜻이다.
    #    §4 지시대로 이런 후보만 나오면 폐기하고 다시 뽑는다(main.py 재생성 루프).
    ('"이게 46세 몸매?" 밥 두 공기씩 먹었는데도 49kg 유지하는 원조 얼짱', 48),
    ('"2kg밖에 안 빠져 억울하다는" 53세 미스코리아 출신, 165cm 43kg', 42),
    # 항목을 5개까지 쌓아도 길이가 늘어 -10 을 맞아 결국 50 이다.
    # §4 표(최대 90) + §5 길이 상한(40자, 초과 1자당 -1)이 서로 당긴다:
    #   세 카드 없이 60을 넘기려면 항목 6개가 필요한데 그러면 45~50자가 되고,
    #   그 초과분이 다시 점수를 깎아 60 아래로 되돌아온다.
    # 결론: **이 표는 사실상 "제3자 실명·금기 소재·돈 숫자 중 최소 하나는
    #        반드시 물어라"는 규칙이다.** 셋 다 없으면 재생성이 정상 동작이다.
    ('"2kg밖에 안 빠져 억울하다는" 53세 미스코리아 출신, 40일 만에 165cm 43kg', 50),
]

if __name__ == "__main__":
    import sys

    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    SUBJECT = "이승연"
    ok = True
    for title, expected in KNOWN:
        got, reasons = score(title, SUBJECT)
        if expected is None:                     # 통과형: 60점 이상이어야 한다
            good = got >= C.MIN_SCORE
            mark = "OK " if good else "FAIL"
            exp_s = f">={C.MIN_SCORE}"
        else:
            good = got == expected
            mark = "OK " if good else "FAIL"
            exp_s = str(expected)
        if not good:
            ok = False
        print(f"{mark} 기대 {exp_s:>6} / 실제 {got:>5}  {title}")
        for r in reasons:
            print(f"        - {r}")
    print()
    print("전부 일치" if ok else "불일치 있음 — 제목규칙.md 와 대조할 것")
    sys.exit(0 if ok else 1)
