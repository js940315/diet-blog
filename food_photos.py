# -*- coding: utf-8 -*-
"""글에 나온 음식의 사진 버킷이 없으면 그 자리에서 만들어 온다.

build_photo_library.py 는 '미리 정해둔 카테고리'를 미리 채우는 도구다.
그런데 글에 나오는 음식은 미리 정할 수 없다 — 호박식혜, 참치쌈장, 갑오징어처럼
그날 기사에만 나오는 게 대부분이다. 그래서 finish 시점에 필요한 음식이
라이브러리에 없으면 여기서 즉석 소싱한다.

소스 순서: stock(키 필요) → wikimedia commons(키 불필요) → openverse(키 불필요)
클라우드 루틴에는 스톡 API 키가 없으므로 Commons 가 실질 주력이다.
한식은 Commons 쪽 커버리지가 오히려 스톡 3사보다 낫다(식혜·떡볶이·김밥 등).
"""

import os

import food_match
import photo_library as PL
from image_sourcing import (prepare_photo, stock_photo_candidates,
                            wikimedia_photo_candidates, photo_candidates)

DIR = PL.PHOTO_DIR
INDEX = PL.INDEX_PATH

MIN_WIDTH = 1200      # build_photo_library 기본(1600)보다 낮다 — 한식은 고해상도가 드물다
TARGET = 2            # 음식 하나당 이만큼만 받는다. 즉석 소싱이라 오래 끌면 안 된다


def _load_index():
    return PL._load_json_safe(INDEX, {})


def _save_index(idx):
    PL._save_json(INDEX, idx)


def _has_key(name):
    return bool(os.environ.get(name))


def _stock_ready():
    return any(_has_key(k) for k in
               ("PEXELS_API_KEY", "UNSPLASH_ACCESS_KEY", "PIXABAY_API_KEY"))


def _plan(food):
    """이 음식을 어느 소스에서 어떤 검색어로 찾을지. 한식은 Commons 가 먼저다."""
    plan = [(s, q) for s, q in food_match.sources_for(food)
            if s != "stock" or _stock_ready()]
    return plan


def ensure_bucket(food, target=TARGET, quiet=False):
    """음식 이름의 사진 버킷을 보장한다. 이미 있으면 소싱하지 않는다.

    반환: 그 버킷에서 쓸 수 있는 사진 장수 (0이면 소싱 실패)
    """
    have = len(PL.category_pool(food))
    if have:
        return have

    plan = _plan(food)
    if not plan:
        if not quiet:
            print(f"  [사진] '{food}' 검색어가 사전에 없습니다 — food_match.py 에 추가 필요")
        return 0

    idx = _load_index()
    got = 0
    used_queries = []
    for sname, query in plan:
        if got >= target:
            break
        prefix = f"{food}_{sname[0]}"
        try:
            if sname == "stock":
                rep = stock_photo_candidates(query, DIR, keep=target,
                                             min_side=MIN_WIDTH, prefix=prefix)
            elif sname == "wiki":
                rep = wikimedia_photo_candidates(query, DIR, limit=target,
                                                 min_width=MIN_WIDTH, prefix=prefix)
            else:
                rep = photo_candidates(query, DIR, limit=target,
                                       min_width=MIN_WIDTH, prefix=prefix)
        except Exception as e:
            if not quiet:
                print(f"  [사진] {food}/{sname} 소싱 실패: {str(e)[:50]}")
            continue

        for r in rep:
            if "path" not in r:
                continue
            fn = os.path.basename(r["path"])
            try:
                prepare_photo(r["path"], r["path"], size=1400)
            except Exception:
                pass
            idx[fn] = {
                "카테고리": food,
                "license": r.get("license", ""),
                "credit": r.get("credit", ""),
                "attribution_required": bool(r.get("attrib_required")),
                "원본해상도": f"{r.get('src_w','?')}x{r.get('src_h','?')}",
                "처리": "정사각 1400px",
                "검색어": query,
                "검수": "미확인 — 즉석 소싱",
            }
            got += 1
            if f"{sname}:{query}" not in used_queries:
                used_queries.append(f"{sname}:{query}")
            if got >= target:
                break

    tried = ", ".join(f"{s}:{q}" for s, q in plan)
    if got:
        _save_index(idx)
        if not quiet:
            print(f"  [사진] '{food}' 버킷 신규 소싱 {got}장 ({'; '.join(used_queries)})")
    elif not quiet:
        print(f"  [사진] '{food}' 사진을 못 구했습니다 (시도: {tried})")
    return got


if __name__ == "__main__":
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    for food in sys.argv[1:]:
        n = ensure_bucket(food)
        print(f"{food}: {n}장")
