# -*- coding: utf-8 -*-
"""제목·팩트시트에 실제로 나온 음식을 뽑아내고, 그 음식의 사진 검색어를 준다.

왜 필요한가 (2026-08-08 사고):
    제목이 "호박식혜 해프닝의 반전"인데 아보카도 사진이 나갔다.
    "바나나와 필라테스뿐인데..."라는 제목에도 바나나가 아니라 샐러드가 붙었다.
    기존 images.choose_buckets는 미리 정의된 9개 버킷에 문자열이 걸릴 때만
    반영하고, 안 걸리면 날짜로 돌린 기본 버킷을 넣었다. 그래서 글에 나온
    음식과 사진이 아무 상관이 없었다. 10편 중 1편만 우연히 맞았다.

설계:
    - 어휘 사전을 둔다. 임의 토큰화는 "감량", "관리" 같은 걸 음식으로 잡는다.
    - 긴 이름을 먼저 맞춘다 (호박식혜 → 식혜, 오이김밥 → 김밥 순서로 밀리지 않게).
    - 검색어는 영문이다. 스톡 3사·Commons 인덱스가 영문 기반이라 한글 쿼리는
      적중률이 급락한다 (car-blog 실측 교훈, build_photo_library.py 주석 참조).
    - 한식은 로마자 표기 + 설명어를 같이 준다. Commons가 그렇게 색인한다.
"""

# 음식 이름 -> 사진 검색어(영문).
# 키 순서는 상관없다. 매칭할 때 길이순으로 정렬해서 쓴다.
FOOD_QUERIES = {
    # ── 한식·한국 음식 ────────────────────────────────────────────────
    "호박식혜": "sikhye korean sweet rice drink",
    "식혜": "sikhye korean rice punch",
    "오이김밥": "gimbap korean rice roll cucumber",
    "김밥": "gimbap korean rice roll",
    "떡볶이": "tteokbokki korean rice cake",
    "비빔국수": "bibim guksu korean spicy noodles",
    "비빔밥": "bibimbap korean rice bowl",
    "주먹밥": "korean rice ball onigiri",
    "미역국": "miyeokguk seaweed soup",
    "삼계탕": "samgyetang ginseng chicken soup",
    "된장찌개": "doenjang jjigae soybean paste stew",
    "청국장": "cheonggukjang fermented soybean stew",
    "김치": "kimchi korean fermented cabbage",
    "쌈채소": "korean lettuce wrap vegetables",
    "참치쌈장": "canned tuna korean dipping sauce",
    "닭발": "korean spicy chicken feet dish",
    "잡곡밥": "multigrain rice bowl",
    "현미": "brown rice bowl",
    "생식": "raw grain powder health food",

    # ── 단백질 ───────────────────────────────────────────────────────
    "닭가슴살": "grilled chicken breast meal",
    "소고기": "lean beef steak plate",
    "삶은 달걀": "hard boiled egg halved yolk",
    "달걀": "hard boiled egg halved yolk",
    "계란": "hard boiled egg halved yolk",
    "구운란": "roasted eggs snack",
    "두부": "tofu block fresh",
    "두유": "soy milk glass",
    "연어": "salmon fillet healthy",
    "오징어": "squid seafood dish",
    "갑오징어": "cuttlefish seafood fresh",
    "꽃게": "blue crab fresh seafood",
    "새우": "shrimp healthy plate",
    "참치": "canned tuna healthy",
    "낫토": "natto fermented soybeans",
    "단백질쉐이크": "protein shake glass",
    "프로틴": "protein shake glass",

    # ── 채소·과일 ────────────────────────────────────────────────────
    "브로콜리니": "broccolini fresh green",
    "브로콜리": "broccoli fresh green",
    "콜리플라워": "cauliflower rice bowl",
    "단호박": "kabocha squash steamed",
    "호박": "pumpkin squash fresh",
    "고구마": "sweet potato steamed",
    "감자": "boiled potatoes plate",
    "토마토": "fresh tomatoes",
    "오이": "fresh cucumber slices",
    "당근": "fresh carrots",
    "양배추": "fresh cabbage",
    "바나나": "fresh bananas",
    "사과": "fresh apples",
    "블루베리": "fresh blueberries bowl",
    "딸기": "fresh strawberries",
    "수박": "watermelon slices",
    "레몬": "yellow lemon closeup",
    "아보카도": "avocado halved fresh",
    "옥수수": "corn cobs fresh",

    # ── 유제품·간식·기타 ─────────────────────────────────────────────
    "그릭요거트": "greek yogurt bowl berries",
    "요거트": "yogurt bowl fresh",
    "우유": "glass of milk",
    "치즈": "cheese board fresh",
    "부라타": "burrata cheese salad",
    "아몬드우유": "almond milk glass",
    "견과류": "mixed nuts bowl",
    "땅콩버터": "peanut butter jar toast",
    "올리브오일": "olive oil bottle pour",
    "사과식초": "apple cider vinegar bottle",
    "오트밀": "oatmeal bowl breakfast",
    "곤약": "konjac jelly noodles",
    "샐러드": "fresh salad bowl vegetables",
    "포케": "poke bowl healthy",
    "도시락": "meal prep lunch box",
    "샌드위치": "healthy sandwich plate",
    "김밥말이": "korean rice roll",
    "라면": "instant ramen noodles bowl",
    "도넛": "donuts plate",
    "피자": "pizza slice",
    "주스": "fresh juice glass",
    "디저트": "healthy dessert plate",
    "국물": "clear soup bowl",
    "밀프렙": "meal prep containers",
}

# 한식·한국 특유의 음식은 Wikimedia Commons 를 먼저 본다.
# 스톡 3사(Pexels·Unsplash·Pixabay)에는 식혜·떡볶이 같은 게 아예 없어서
# "korean rice drink" 로 검색하면 엉뚱한 걸 준다 — 실제로 호박식혜 자리에
# 고구마밥이 잡혔다(2026-08-08). Commons 는 로마자 표기로 정확히 색인돼 있고,
# 검색어는 짧을수록 정확하다: "Sikhye" > "sikhye korean rice punch".
COMMONS_QUERIES = {
    "호박식혜": "Sikhye",
    "식혜": "Sikhye",
    "오이김밥": "Gimbap",
    "김밥": "Gimbap",
    "김밥말이": "Gimbap",
    "떡볶이": "Tteokbokki",
    "비빔국수": "Bibim guksu",
    "비빔밥": "Bibimbap",
    "주먹밥": "Jumeokbap",
    "미역국": "Miyeokguk",
    "삼계탕": "Samgyetang",
    "된장찌개": "Doenjang jjigae",
    "청국장": "Cheonggukjang",
    "김치": "Kimchi",
    "쌈채소": "Ssam korean",
    "참치쌈장": "Ssamjang",
    "닭발": "Dakbal",
    "잡곡밥": "Japgokbap",
    "생식": "Misugaru",
    "곤약": "Konjac food",
    "단호박": "Kabocha",
    "두유": "Soy milk",
    "낫토": "Natto",
    "구운란": "Roasted egg korean",
}


def sources_for(food):
    """(소스이름, 검색어) 순서 목록. 한식이면 Commons 를 먼저 본다."""
    order = []
    cq = COMMONS_QUERIES.get(food)
    if cq:
        order.append(("wiki", cq))
    sq = FOOD_QUERIES.get(food)
    if sq:
        order.append(("stock", sq))
        order.append(("openverse", sq))
    if cq and not sq:
        order.append(("openverse", cq))
    return order


# 이미 라이브러리에 버킷이 있는 음식은 그 버킷을 그대로 쓴다.
# (config.FOOD_BUCKETS_ONLY 와 같은 이름들)
EXISTING_BUCKETS = {
    "닭가슴살", "샐러드", "고구마", "단백질쉐이크", "그릭요거트",
    "아보카도", "두부", "오트밀", "도시락", "식단레시피",
}

# 매칭 우선순위: 긴 이름 먼저 (호박식혜가 호박·식혜보다 먼저 걸리게)
_TERMS = sorted(FOOD_QUERIES, key=len, reverse=True)


def query_for(food: str) -> str:
    """음식 이름 → 사진 검색어. 사전에 없으면 None."""
    return FOOD_QUERIES.get(food)


def _scan(text: str, found: list):
    """text 안에 등장하는 음식을 등장 순서대로 found에 넣는다(중복 제외)."""
    if not text:
        return
    hits = []
    for term in _TERMS:
        pos = text.find(term)
        if pos >= 0:
            # 이미 더 긴 이름으로 잡힌 구간이면 건너뛴다 (호박식혜 잡고 호박 또 잡지 않게)
            if any(pos >= s and pos + len(term) <= e for s, e in hits):
                continue
            hits.append((pos, pos + len(term)))
            found.append((pos, term))


def extract_foods(title: str, fs: dict, limit: int = 6):
    """제목과 팩트시트에서 실제로 언급된 음식을 우선순위 순으로 뽑는다.

    순서가 곧 사진 순서다:
      1) 제목에 나온 음식이 제일 앞 — 1번 사진은 홈판 썸네일이라 제목과 맞아야 한다.
      2) 그다음 팩트시트 foods 에 적힌 순서
      3) 그다음 habits·life_events 같은 서술문에 섞여 나온 것

    반환: ["호박식혜", "고구마", ...] (중복 없음)
    """
    ordered = []

    # 1) 제목 — 위치순
    t_hits = []
    _scan(title or "", t_hits)
    for _, term in sorted(t_hits):
        if term not in ordered:
            ordered.append(term)

    # 2) 팩트시트 foods — 배열 순서를 존중한다.
    #    "떡볶이 (떡 대신 다른 식재료로...)" 처럼 설명이 붙어 있어도 잡히게 통째로 스캔.
    for item in (fs.get("foods") or []):
        hits = []
        _scan(str(item), hits)
        for _, term in sorted(hits):
            if term not in ordered:
                ordered.append(term)

    # 3) 습관·인생사건 서술문에 섞여 나온 음식
    tail = " ".join(str(x) for x in
                    (fs.get("habits") or []) + (fs.get("life_events") or []))
    h_hits = []
    _scan(tail, h_hits)
    for _, term in sorted(h_hits):
        if term not in ordered:
            ordered.append(term)

    return ordered[:limit]


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    cases = [
        ('"임신설까지 돌았던" 40kg대 여가수, 호박식혜 해프닝의 반전', {}),
        ("바나나와 필라테스뿐인데 56세에 신체나이 30대라는 여가수",
         {"foods": ["저탄고지 식단", "바나나", "밀가루를 뺀 비빔국수 샐러드"]}),
        ("4kg 빠졌는데 근육량은 늘었다는 개그우먼의 식단 딱 한 가지",
         {"foods": ["꽃게", "갑오징어"]}),
        ('"비연예인과 재혼한" 46세 여배우가 20년째 지킨 몸무게',
         {"foods": ["오이김밥", "참치쌈장"]}),
        ("168cm 52kg인데 \"살 잘 찌는 체질\"이라는 40대 배우의 루틴",
         {"foods": ["떡볶이 (떡 대신 다른 식재료로 대체해 먹는다고 언급)"]}),
    ]
    for title, fs in cases:
        foods = extract_foods(title, fs)
        print(f"{title[:34]:36} -> {foods}")
        for f in foods:
            print(f"      {f}: {query_for(f)}")
