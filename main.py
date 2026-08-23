"""매일 최대 10편. 크롤링 → 팩트시트 → 제목 확정 → 본문 → output/날짜/슬롯/

산출물 폴더는 아침에 열었을 때 복붙할 것만 보이게 둔다.
  output/날짜/1/0번 본문.txt   ← 슬롯마다 본문 1 + 사진
  output/날짜/1/1번 사진.jpg …
  output/날짜/2/ … output/날짜/10/
  state/work/날짜/슬롯/         ← 팩트시트·제목점수·소스 등 중간 산출물

하루 발행량은 상한이다. 소스가 되는 인물이 부족하면 적게 나오는 게 정상 —
억지로 채우면 유사문서 위험만 커진다.

A) API 경로 — ANTHROPIC_API_KEY 가 있을 때 (슬롯 1만, 백업용)
     python main.py --dry-run / python main.py --celeb 김희선

B) 에이전트 경로 — 키가 없을 때. 클로드 코드가 글만 쓴다.
     python main.py --stage crawl            10개 슬롯 수집 + 지시서
     python main.py --stage title            전 슬롯 제목 확정 (또는 --slot N)
     python main.py --stage finish           전 슬롯 검증·마감 (또는 --slot N)

어느 쪽이든 수집·제목 점수·형식 검증은 파이썬이 한다. LLM은 글만 쓴다.
"""

import argparse
import json
import os
import shutil
import sys
import traceback

import brief
import config as C
import crawler
import store
import titles as T
import validator


def _utf8_stdout():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


def outdir(date_str, slot):
    """복붙할 것만 놓는 폴더. 슬롯당 본문 1개 + 사진 몇 장.

    폴더 생성은 본문이 완성되는 finish 시점에만 한다. crawl 때 미리 만들면
    아침에 빈 폴더가 보여서 "왜 비어 있냐"는 혼란이 생긴다(2026-08-05 실제 발생).
    폴더가 있다 = 발행 가능하다. 이 등식을 지킨다.

    날짜 폴더는 MMDD 로 쓴다 (2026-08-06 사용자 확정: 전 블로그 output/MMDD/번호 통일).
    """
    return os.path.join(C.OUTPUT_DIR, date_str.replace("-", "")[4:], str(slot))


def wpath(d, name):
    """중간 산출물 경로. output 폴더에는 본문과 사진만 남긴다."""
    return os.path.join(brief.workdir(d), name)


def _dump(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        if isinstance(obj, str):
            f.write(obj)
        else:
            json.dump(obj, f, ensure_ascii=False, indent=2)


def _load(path, what):
    if not os.path.exists(path):
        raise SystemExit(f"{what}가 없습니다: {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _load_text(path, what):
    if not os.path.exists(path):
        raise SystemExit(f"{what}가 없습니다: {path}")
    with open(path, encoding="utf-8") as f:
        return f.read()


def _slots(args):
    return [args.slot] if args.slot else list(range(1, C.DAILY_SLOTS + 1))


def _date_key(date_str):
    """폴더 키는 MMDD (2026-08-06 사용자 확정, 전 블로그 공통)."""
    return date_str.replace("-", "")[4:]


def _slot_meta(date_str, slot):
    # ⚠️ output 이 MMDD 로 바뀔 때 여기만 옛 경로(YYYY-MM-DD)로 남아서
    # 같은 날 인물 중복 방지가 통째로 무력화됐다 (9개 슬롯 전부 같은 인물).
    # 작업 폴더 키는 반드시 outdir 와 같은 MMDD 를 쓴다.
    p = os.path.join(C.WORK_DIR, _date_key(date_str), str(slot), "meta.json")
    if not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def _todays_celebs(date_str):
    """오늘 다른 슬롯이 이미 잡아둔 인물들. 같은 날 중복 방지."""
    used = set()
    for s in range(1, C.DAILY_SLOTS + 1):
        m = _slot_meta(date_str, s)
        if m and m.get("celeb"):
            used.add(m["celeb"])
    return used


def already_done(d, force):
    """완성된 글이 이미 있으면 건드리지 않는다.

    사람이 미리 만들어둔 원고를 새벽 루틴이 말없이 덮어쓰는 사고 방지.
    """
    post = os.path.join(d, C.POST_FILENAME)
    if force or not os.path.exists(post):
        return False
    print(f"■ 이미 완성된 글이 있습니다 → {post} (건너뜀. 재생성은 --force)")
    return True


def write_backup_titles(d, ranked):
    """예비제목.txt — 확정 제목과 나머지 후보를 output 폴더에 같이 둔다.

    패션비버와 같은 규격 (2026-08-07 사용자 확정). 확정 제목이 마음에 안 들면
    발행자가 예비 중 하나로 갈아끼우고 제목만 바꿔 발행할 수 있다.
    ⚠️ 예비로 바꿀 때는 제목의 숫자·인용구가 도입부와 어긋날 수 있다는 것만 유의.
    """
    # 첫 줄에 출처(블로그·날짜·슬롯)를 박는다.
    # 2026-08-16: 예비제목.txt 는 홈판 안에 100개 넘게 **전부 같은 이름**이고
    # 메모장은 탭에 파일명만 보여준다. 발행이 끝난 슬롯 폴더는 지워지는데
    # 메모장은 세션 복원으로 그 탭을 계속 들고 있어서, 이미 사라진 어제 파일이
    # 오늘 것처럼 떠 있는 일이 생긴다. 첫 줄만 보면 바로 걸린다.
    # 0번 본문.txt 에는 절대 넣지 않는다 — 그건 통째로 복사해 발행하는 파일이라
    # 한 줄만 들어가도 그 줄이 블로그에 그대로 실린다.
    p = os.path.abspath(d).replace("\\", "/").split("/")
    origin = f"건강비버 {p[-2]}-{p[-1]}" if len(p) >= 2 else "건강비버"
    lines = [f"[{origin} · 확정]", "", ranked[0]["title"], "", "─── 예비 ───", ""]
    for r in ranked[1:]:
        if r["score"] <= 0:
            continue                     # 탈락(실명 노출 등)은 예비로도 안 준다
        lines.append(r["title"])
        lines.append("")
    with open(os.path.join(d, "예비제목.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines).rstrip() + "\n")


def _finalize(d, body, richness, meta, chosen, polish_ok):
    """검증 → 0번 본문.txt → 사진 → report.json. 두 경로가 공유한다."""
    cta = meta.get("cta")
    celeb = meta.get("celeb")
    problems = validator.validate(body, richness, cta, celeb, chosen["title"],
                                  meta.get("factsheet"))
    polished = False
    if problems and polish_ok:
        body = validator.polish(body)
        polished = True
        problems = validator.validate(body, richness, cta, celeb, chosen["title"],
                                  meta.get("factsheet"))

    body = validator.ensure_notices(body)

    post = chosen["title"] + "\n" + C.BLANK_LINE + "\n" + body
    os.makedirs(d, exist_ok=True)   # 본문이 완성되는 이 순간에만 output 폴더가 생긴다
    _dump(os.path.join(d, C.POST_FILENAME), post)

    made = []
    # 2026-08-16 사용자 지시: "건강비버 앞으로 이미지 준비하지마. 쓸 수 있는 사진이 아예 없네."
    # 음식 사진 라이브러리가 고갈돼 매일 같은 사진이 돌아가고 있었다.
    # 되살리려면 config.IMAGES_ENABLED 를 True 로 바꾸면 된다 — 코드는 그대로 둔다.
    if C.IMAGES_ENABLED and not meta.get("no_images"):
        try:
            import images
            fs = _load(wpath(d, "factsheet.json"), "팩트시트")
            made = images.render(chosen["title"], fs,
                                 meta["date"].replace("-", "")[4:], d)
        except Exception as e:
            print(f"   [경고] 사진 준비 실패 — 본문은 정상입니다: {str(e)[:80]}")

    # 이미지메모.txt — 사진은 준비하지 않지만 어디서 구할지는 알려준다.
    # 2026-08-18 사용자 지시로 패션비버와 통일. 인스타 explore 링크는 죽어서 안 쓴다.
    _name = (meta.get("celeb") or "").strip()
    if _name:
        memo = [f"■ {_name} — 이미지 어디서 구하나", "",
                "이미지 검색 (로그인 없이 바로 열립니다):",
                f"  네이버  {C.IMAGE_SEARCH_PRIMARY.format(name=_name)}",
                f"  다음    {C.IMAGE_SEARCH_BACKUP.format(name=_name)}", "",
                "※ 못 찾으면 사진 없이 발행해도 되는 글입니다."]
        with open(os.path.join(d, "이미지메모.txt"), "w",
                  encoding="utf-8", newline="\n") as f:
            f.write("\n".join(memo) + "\n")

    cl = len(validator.content_lines(validator.split_sections(body)[0]))
    return post, problems, polished, made, cl


# ── B) 에이전트 경로 ────────────────────────────────────────────────────

def _crawl_one_slot(date_str, slot, args):
    """슬롯 하나에 인물을 배정하고 소스를 모은다.

    소스가 10건 미만인 인물은 글이 얇아지므로 쿨다운 처리하고 다음 인물로
    넘어간다. 억지로 얇은 인물을 붙잡는 것보다 풀을 순환시키는 게 낫다.
    """
    d = outdir(date_str, slot)
    if already_done(d, args.force):
        return "skip"

    # --redraw: 에이전트가 소재 부족·논란·동명이인으로 슬롯을 포기했을 때
    # 그 인물을 쿨다운으로 보내고 같은 슬롯에 새 인물을 다시 배정한다.
    # 이게 없으면 포기한 슬롯은 그날 영영 빈칸으로 남는다 (0812·0813 실측:
    # 10칸 중 5~6칸이 이 이유로 비었다). 사용자 결정(2026-08-13): 빈칸을 두지
    # 않고 대체 인물로 채운다.
    if getattr(args, "redraw", False):
        m = _slot_meta(date_str, slot)
        if m and m.get("celeb"):
            store.mark_celeb(m["celeb"])
            print(f"■ 슬롯 {slot}: {m['celeb']} 쿨다운 처리 → 새 인물로 재배정")
        shutil.rmtree(os.path.join(C.WORK_DIR, _date_key(date_str), str(slot)),
                      ignore_errors=True)
    elif _slot_meta(date_str, slot) and not args.force:
        print(f"■ 슬롯 {slot}: 이미 수집돼 있음 (건너뜀)")
        return "skip"

    tried = set(_todays_celebs(date_str))
    celeb, items = None, []
    for _ in range(6):
        if args.celeb and args.celeb not in tried:
            cand = args.celeb
        else:
            cand = next((n for n in store.available_celebs() if n not in tried), None)
        if not cand:
            break
        tried.add(cand)
        got = crawler.collect(cand, sort=args.sort, mode=args.source)
        if len(got) >= 10:
            celeb, items = cand, got
            break
        # 2026-08-23: 여기서 기본 15일을 걸어 풀을 태우고 있었다.
        # 기사가 없는 건 그날 사정이다 — 며칠 뒤엔 새 기사가 나온다.
        print(f"   [건너뜀] {cand}: 소스 {len(got)}건 — 부족. {C.SKIP_COOLDOWN_DAYS}일만 쉰다.")
        store.mark_celeb(cand, cooldown_days=C.SKIP_COOLDOWN_DAYS)

    if not celeb:
        print(f"■ 슬롯 {slot}: 채울 인물이 없습니다. 오늘은 여기까지가 상한입니다.")
        return "empty"

    richness = crawler.assess_richness(items)
    cta = store.next_cta(offset=slot - 1)
    heart = C.HEART_CTA_POOL[(int(date_str.replace("-", "")) + slot)
                             % len(C.HEART_CTA_POOL)]
    print(f"■ 슬롯 {slot}: {celeb} — {len(items)}건 / richness={richness}")

    _dump(wpath(d, "sources.json"), items)
    _dump(wpath(d, "meta.json"), {
        "date": date_str, "slot": slot, "celeb": celeb, "richness": richness,
        "sources": len(items), "cta": cta, "heart": heart,
        "no_images": args.no_images,
    })
    brief.factsheet_brief(d, celeb, richness, crawler.summarize(items), len(items))
    return "ok"


def stage_crawl(args):
    store.init()
    date_str = args.date or store.today_str()

    made = 0
    for s in _slots(args):
        r = _crawl_one_slot(date_str, s, args)
        if r == "ok":
            made += 1
        elif r == "empty":
            # 예전엔 여기서 break 했다. 그러면 인물 하나가 안 잡히는 순간
            # 뒤 슬롯이 전부 통째로 날아간다. 후보가 진짜 0명이면
            # _crawl_one_slot 이 즉시 반환하므로 계속 돌아도 비용이 없다.
            print(f"   슬롯 {s} 는 비워두고 다음 슬롯으로 넘어갑니다.")
            continue
        if args.celeb:      # 인물 지정은 슬롯 하나만 채운다
            break

    print(f"■ 수집 완료: 새 슬롯 {made}개 준비 (지시서: state/work/{_date_key(date_str)}/슬롯/)")
    print("   에이전트: 슬롯마다 factsheet.json + title_candidates.json 작성")
    print("   그 다음: python main.py --stage title")


def _title_one_slot(date_str, slot):
    d = outdir(date_str, slot)
    meta = _slot_meta(date_str, slot)
    if not meta:
        return None
    fs_p = wpath(d, "factsheet.json")
    cand_p = wpath(d, "title_candidates.json")
    if not (os.path.exists(fs_p) and os.path.exists(cand_p)):
        print(f"■ 슬롯 {slot}: 팩트시트/제목후보 없음 — 건너뜀")
        return None

    fs = _load(fs_p, "팩트시트")
    cand = _load(cand_p, "title_candidates.json")
    candidates = cand.get("titles") if isinstance(cand, dict) else cand
    # 제목규칙 §1-7 은 **주인공 실명만** 폐기한다. 제3자 실명은 오히려 +30 이므로
    # 주인공이 누구인지 넘겨야 한다. 팩트시트도 넘겨 §6-1(실제 발언인가)을 대조한다.
    subject = fs.get("celeb") or meta.get("celeb")
    ranked = T.pick(candidates or [], subject, fs)
    _dump(wpath(d, "titles.json"), ranked)

    if not ranked or ranked[0]["score"] <= 0:
        print(f"■ 슬롯 {slot}: 쓸 만한 제목이 없음 — 후보를 다시 써야 함")
        return None

    # 제목규칙 §4: 60점 미만이면 전부 폐기하고 다시 뽑는다.
    # 여기서는 후보를 다시 만들 수 없으므로(모델 호출은 앞 단계다) 멈추고 알린다.
    # 조용히 통과시키면 규칙을 글로만 적어둔 것과 같아진다.
    if T.below_floor(ranked):
        print(f"■ 슬롯 {slot}: 최고점 {ranked[0]['score']}점 < {C.MIN_SCORE}점 — "
              f"제목규칙 §4 에 따라 전부 폐기.")
        print(f"   1등: {ranked[0]['title']}")
        for r in ranked[0]["reasons"]:
            print(f"     - {r}")
        # 후보를 다시 뽑아야 하는지, 인물을 바꿔야 하는지 여기서 갈린다.
        # 재료가 없는 인물은 몇 번을 다시 뽑아도 60을 못 넘는다.
        have, missing = T.material_report(fs, subject)
        print(f"   팩트시트 재료 — 있음: {', '.join(have) if have else '없음'}")
        print(f"                  없음: {', '.join(missing) if missing else '없음'}")
        if have:
            print("   → 재료는 있다. 그 카드를 제목 앞쪽에 물려서 후보 10개를 다시 써라.")
        else:
            print("   → 세 카드가 하나도 없다. 후보를 다시 써도 60점은 안 나온다.")
            print("      이 인물은 건너뛰고 다른 인물로 슬롯을 채워라.")
        return None

    chosen = ranked[0]
    second = ranked[1]["score"] if len(ranked) > 1 else 0
    print(f"■ 슬롯 {slot} 확정: {chosen['title']}  ({chosen['score']}점, 2등과 {chosen['score']-second}점차)")
    for r in chosen["reasons"]:
        if r.startswith("⚠"):
            print(f"   {r}")

    heart = meta.get("heart") or C.HEART_CTA_POOL[0]
    brief.body_brief(d, chosen["title"], brief.factsheet_text(fs),
                     meta["richness"], meta["cta"],
                     bool(fs.get("has_exercise_detail")),
                     meta["celeb"], heart)
    return chosen


def stage_title(args):
    store.init()
    date_str = args.date or store.today_str()
    done = sum(1 for s in _slots(args) if _title_one_slot(date_str, s))
    print(f"■ 제목 확정 {done}개 슬롯. 에이전트: 슬롯마다 draft.txt 작성")
    print("   그 다음: python main.py --stage finish")


def _finish_one_slot(date_str, slot, args):
    d = outdir(date_str, slot)
    meta = _slot_meta(date_str, slot)
    if not meta:
        return None
    body_p = wpath(d, "body.txt")
    titles_p = wpath(d, "titles.json")
    if not (os.path.exists(body_p) and os.path.exists(titles_p)):
        print(f"■ 슬롯 {slot}: body.txt 없음 — 건너뜀")
        return None

    ranked = _load(titles_p, "titles.json")
    body = _load_text(body_p, "body.txt")
    chosen = ranked[0]
    if args.no_images:
        meta["no_images"] = True
    # 동명이인 교차검증에 쓴다. 없으면 그 검사만 건너뛴다.
    fs_p = wpath(d, "factsheet.json")
    if os.path.exists(fs_p):
        meta["factsheet"] = _load(fs_p, "factsheet.json")

    post, problems, polished, made, cl = _finalize(
        d, body, meta["richness"], meta, chosen, polish_ok=args.polish)

    _dump(wpath(d, "report.json"), {
        "date": meta["date"], "slot": slot, "celeb": meta["celeb"],
        "richness": meta["richness"], "sources": meta["sources"],
        "title": chosen, "cta": meta["cta"], "content_lines": cl,
        "polished": polished, "route": "agent",
        "final_problems": problems, "images": made,
    })

    if problems:
        brief.repair_note(d, problems)
        print(f"■ 슬롯 {slot}: 위반 {len(problems)}건 — draft.txt 고쳐서 다시")
        for p in problems[:8]:
            print(f"      · {p}")
        return False

    stale = wpath(d, "위반목록.md")
    if os.path.exists(stale):
        os.remove(stale)

    write_backup_titles(d, ranked)

    items = []
    if os.path.exists(wpath(d, "sources.json")):
        items = _load(wpath(d, "sources.json"), "sources.json")
    store.mark_celeb(meta["celeb"])
    store.mark_articles(items)
    store.record_post(meta["date"], meta["celeb"], chosen["title"], meta["cta"])

    print(f"■ 슬롯 {slot} 완료: {meta['celeb']} / 줄 {cl} / 사진 {len(made)}장"
          + (" (polish)" if polished else ""))
    return True


def stage_finish(args):
    store.init()
    date_str = args.date or store.today_str()
    ok, fail = 0, 0
    for s in _slots(args):
        r = _finish_one_slot(date_str, s, args)
        if r is True:
            ok += 1
        elif r is False:
            fail += 1
    print(f"■ 마감: 통과 {ok}개 / 위반 남음 {fail}개")
    if fail:
        sys.exit(4)


# ── A) API 경로 (슬롯 1 전용 백업) ──────────────────────────────────────

def run_api(args):
    import writer

    store.init()
    date_str = args.date or store.today_str()
    slot = args.slot or 1
    d = outdir(date_str, slot)
    if already_done(d, args.force):
        return

    tried = set(_todays_celebs(date_str))
    if args.celeb:
        celeb = args.celeb
    else:
        celeb = next((n for n in store.available_celebs() if n not in tried), None)
        if not celeb:
            raise SystemExit("사용 가능한 인물이 없습니다.")
    print(f"■ 인물: {celeb}   (날짜 {date_str} / 슬롯 {slot})")

    print("■ 수집 중...")
    items = crawler.collect(celeb, sort=args.sort, mode=args.source)
    if not items:
        raise SystemExit("소스를 하나도 못 모았습니다. 인물을 바꾸거나 --sort date로 시도하세요.")
    richness = crawler.assess_richness(items)
    print(f"   {len(items)}건 수집 / richness={richness}")

    print("■ 팩트시트 추출...")
    fs = writer.build_factsheet(celeb, crawler.summarize(items))
    fs_text = writer.factsheet_text(fs)
    _dump(wpath(d, "factsheet.json"), fs)

    # 제목규칙 §4: 60점 미만이면 전부 폐기하고 후보를 **다시 뽑는다**.
    # 이 경로는 모델을 직접 부를 수 있으므로 재생성이 가능하다.
    ranked, pool = [], []
    for attempt in range(1, C.TITLE_RETRY_MAX + 1):
        print(f"■ 제목 후보 생성... (시도 {attempt}/{C.TITLE_RETRY_MAX})")
        pool += writer.generate_titles(fs_text) or []
        ranked = T.pick(pool, celeb, fs)
        for r in ranked[:10]:
            print(f"   {r['score']:>5}  {r['title']}")
        if not T.below_floor(ranked):
            break
        top = ranked[0]["score"] if ranked else "-"
        print(f"   최고점 {top} < {C.MIN_SCORE} — 제목규칙 §4 에 따라 다시 뽑는다")
    _dump(wpath(d, "titles.json"), ranked)
    if not ranked or ranked[0]["score"] <= 0:
        raise SystemExit("쓸 만한 제목이 없습니다.")
    if T.below_floor(ranked):
        raise SystemExit(
            f"{C.TITLE_RETRY_MAX}번 다시 뽑아도 {C.MIN_SCORE}점을 못 넘었습니다.\n"
            "  거의 항상 원인은 하나입니다 — 제3자 실명·금기 소재·돈 숫자가 셋 다 없습니다.\n"
            "  팩트시트에 그 재료가 없으면 인물을 바꾸는 게 빠릅니다.")
    chosen = ranked[0]
    for r in chosen["reasons"]:
        if r.startswith("⚠"):
            print(f"   {r}")
    print(f"■ 확정: {chosen['title']}  ({chosen['score']}점)")

    if args.dry_run:
        print("\n(--dry-run 이므로 본문은 만들지 않습니다)")
        return

    cta = store.next_cta(offset=slot - 1)
    heart = C.HEART_CTA_POOL[(int(date_str.replace("-", "")) + slot)
                             % len(C.HEART_CTA_POOL)]
    body, history, polished = writer.generate_body(
        chosen["title"], fs_text, richness, cta,
        bool(fs.get("has_exercise_detail")), celeb, heart,
    )

    meta = {"date": date_str, "slot": slot, "celeb": celeb, "cta": cta,
            "no_images": args.no_images, "factsheet": fs}
    post, problems, extra_polish, made, cl = _finalize(
        d, body, richness, meta, chosen, polish_ok=False)

    _dump(wpath(d, "report.json"), {
        "date": date_str, "slot": slot, "celeb": celeb, "richness": richness,
        "sources": len(items), "title": chosen, "cta": cta,
        "content_lines": cl, "polished": polished or extra_polish,
        "repair_history": history, "final_problems": problems, "images": made,
    })

    write_backup_titles(d, ranked)
    store.mark_celeb(celeb)
    store.mark_articles(items)
    store.record_post(date_str, celeb, chosen["title"], cta)
    print(f"■ 완료 → {os.path.join(d, C.POST_FILENAME)} / 위반 {len(problems)}건")


def main():
    _utf8_stdout()
    ap = argparse.ArgumentParser(description="네이버 다이어트 블로그 자동 생성 (하루 최대 10편)")
    ap.add_argument("--stage", choices=("crawl", "title", "finish"),
                    help="에이전트 경로. 생략하면 API 경로(키 필요)")
    ap.add_argument("--slot", type=int, choices=range(1, 11), metavar="1~10",
                    help="특정 슬롯만. 생략하면 전 슬롯 순회")
    ap.add_argument("--dry-run", action="store_true", help="제목까지만 생성 (API 경로)")
    ap.add_argument("--celeb", help="인물 지정 (슬롯 하나만 채움)")
    ap.add_argument("--redraw", action="store_true",
                    help="포기한 슬롯을 새 인물로 재배정 "
                         "(--stage crawl --slot N --redraw). 기존 인물은 쿨다운 처리")
    ap.add_argument("--sort", choices=("sim", "date"), default=C.DEFAULT_SORT)
    ap.add_argument("--source", choices=("auto", "naver", "google"), default=C.SOURCE_MODE)
    ap.add_argument("--no-images", action="store_true", help="본문만 생성 (사진 생략)")
    ap.add_argument("--polish", action="store_true",
                    help="finish에서 형식 위반을 기계적으로 강제 복구 (최후 수단)")
    ap.add_argument("--date", help="작업 날짜 (YYYY-MM-DD). 기본은 오늘")
    ap.add_argument("--force", action="store_true",
                    help="완성된 본문이 있어도 새로 만든다")
    args = ap.parse_args()

    # --redraw 는 슬롯 하나를 지목해서 쓴다. 슬롯을 안 주면 오늘 수집분을
    # 전부 날려버리므로 막는다.
    if args.redraw and not args.slot:
        print("[중단] --redraw 는 --slot N 과 같이 써야 합니다. "
              "예: python main.py --stage crawl --slot 4 --redraw")
        sys.exit(2)

    try:
        if args.stage == "crawl":
            stage_crawl(args)
        elif args.stage == "title":
            stage_title(args)
        elif args.stage == "finish":
            stage_finish(args)
        else:
            run_api(args)
    except crawler.NaverKeyMissing as e:
        print(f"[중단] {e}")
        sys.exit(2)
    except SystemExit:
        raise
    except Exception as e:
        if type(e).__name__ == "RefusalError":
            print(f"[중단] {e}\n소재를 바꾸거나 다른 인물로 시도하세요.")
            sys.exit(3)
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
