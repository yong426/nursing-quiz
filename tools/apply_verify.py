# -*- coding: utf-8 -*-
"""교차 검수 보고서를 incoming 문항 파일에 일괄 적용한다.

검수 에이전트는 원본을 건드리지 않고 보고서(JSON 배열)만 쓴다. 이 스크립트가 그 보고서를
읽어 한곳에서 반영하므로, 여러 검수자가 동시에 같은 파일을 고쳐 충돌하는 일이 없다.

사용법:
    python tools/apply_verify.py <보고서디렉터리> [--dry]

보고서 항목 형식:
    {"file":"nq3_1_....json", "i":3, "verdict":"fail"|"uncertain",
     "reason":"...",
     "patch":{"q":..,"c":[5개],"ans":N,"exp":..},      # 바뀌는 필드만
     "drop":true, "replace":{...완전한 문항...}}        # 살릴 수 없을 때

  - verdict가 "uncertain"이고 patch/drop이 없으면 **건드리지 않고** 보류 목록에만 남긴다.
  - patch와 drop이 함께 오면 drop이 우선한다.
  - 같은 (file, i)에 여러 보고서가 겹치면 나중 보고서가 이긴다(파일명 사전순).
"""
import os, sys, glob, json, io, shutil, collections

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
INCOMING = os.path.join(ROOT, "tools", "incoming")
FIELDS = ("t", "q", "c", "ans", "exp")


def load(p):
    return json.load(io.open(p, encoding="utf-8"))


def save(p, obj):
    io.open(p, "w", encoding="utf-8", newline="\n").write(
        json.dumps(obj, ensure_ascii=False, indent=1))


def valid_item(it):
    """적용 후 문항이 스키마를 지키는지 (여기서 막아야 병합 단계까지 안 흘러간다)"""
    if not isinstance(it, dict):
        return "객체가 아님"
    for k in FIELDS:
        if k not in it:
            return f"'{k}' 키 없음"
    if not isinstance(it["c"], list) or len(it["c"]) != 5:
        return f"보기가 5개가 아님 ({len(it['c']) if isinstance(it['c'], list) else '?'})"
    if not isinstance(it["ans"], int) or not 1 <= it["ans"] <= 5:
        return f"ans가 1~5 정수가 아님: {it['ans']!r}"
    if len({str(c).strip() for c in it["c"]}) != 5:
        return "보기 중복"
    if not str(it["q"]).strip() or not str(it["exp"]).strip():
        return "발문 또는 해설이 빈 문자열"
    return None


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    dry = "--dry" in sys.argv
    if not args:
        print(__doc__)
        return 1
    reports = sorted(glob.glob(os.path.join(args[0], "*.json")))
    if not reports:
        print("보고서를 찾지 못했다:", args[0])
        return 1

    # (file, i) -> 항목. 나중 보고서가 이긴다.
    plan, seen_reports = {}, []
    for rp in reports:
        try:
            items = load(rp)
        except Exception as e:
            print(f"✗ 보고서 파싱 실패 {os.path.basename(rp)}: {e}")
            return 1
        if not isinstance(items, list):
            print(f"✗ 보고서 최상위가 배열이 아님: {os.path.basename(rp)}")
            return 1
        seen_reports.append((os.path.basename(rp), len(items)))
        for x in items:
            if not isinstance(x, dict) or "file" not in x or "i" not in x:
                print(f"✗ {os.path.basename(rp)}: file/i 없는 항목")
                return 1
            plan[(x["file"], int(x["i"]))] = dict(x, _src=os.path.basename(rp))

    print(f"보고서 {len(reports)}개 / 지적 {len(plan)}건")
    for n, c in seen_reports:
        print(f"  {n:22s} {c:3d}건")

    applied = collections.Counter()
    changes, held, errors = [], [], []
    by_file = collections.defaultdict(list)
    for (fn, i), x in plan.items():
        by_file[fn].append((i, x))

    for fn in sorted(by_file):
        path = os.path.join(INCOMING, fn)
        if not os.path.exists(path):
            errors.append(f"{fn}: incoming에 파일이 없음")
            continue
        items = load(path)
        dirty = False
        for i, x in sorted(by_file[fn]):
            if not 0 <= i < len(items):
                errors.append(f"{fn} #{i}: 인덱스 범위 밖 (총 {len(items)}문항)")
                continue
            if x.get("drop"):
                rep = x.get("replace")
                if not rep:
                    errors.append(f"{fn} #{i}: drop인데 replace 대체 문항이 없음")
                    continue
                bad = valid_item(rep)
                if bad:
                    errors.append(f"{fn} #{i}: 대체 문항 스키마 위반 — {bad}")
                    continue
                if rep.get("t") != items[i].get("t"):
                    errors.append(f"{fn} #{i}: 대체 문항 주제가 다름 "
                                  f"({items[i].get('t')} → {rep.get('t')})")
                    continue
                items[i] = {k: rep[k] for k in FIELDS}
                applied["교체"] += 1
                changes.append(f"교체  {fn} #{i}  [{x['_src']}] {x.get('reason','')[:70]}")
                dirty = True
                continue
            patch = x.get("patch")
            if not patch:
                held.append(f"보류  {fn} #{i}  ({x.get('verdict')}) [{x['_src']}] "
                            f"{x.get('reason','')[:70]}")
                continue
            unknown = [k for k in patch if k not in FIELDS]
            if unknown:
                errors.append(f"{fn} #{i}: 패치에 알 수 없는 필드 {unknown}")
                continue
            cand = dict(items[i])
            cand.update({k: patch[k] for k in patch})
            bad = valid_item(cand)
            if bad:
                errors.append(f"{fn} #{i}: 패치 적용 후 스키마 위반 — {bad}")
                continue
            items[i] = {k: cand[k] for k in FIELDS}
            applied["패치"] += 1
            changes.append(f"패치  {fn} #{i}  {sorted(patch.keys())}  [{x['_src']}] "
                           f"{x.get('reason','')[:60]}")
            dirty = True
        if dirty and not dry:
            bak = path + ".bak"
            if not os.path.exists(bak):
                shutil.copy2(path, bak)
            save(path, items)

    print()
    for c in sorted(changes):
        print(" ", c)
    for h in sorted(held):
        print(" ", h)
    print()
    if errors:
        print(f"오류 {len(errors)}건 — 해당 항목은 적용하지 않았다:")
        for e in errors:
            print("  ✗", e)
        print()
    print(f"적용: 패치 {applied['패치']}건 / 교체 {applied['교체']}건 · "
          f"보류 {len(held)}건 · 오류 {len(errors)}건" + ("  (dry-run, 파일 미수정)" if dry else ""))
    if not dry and (applied["패치"] or applied["교체"]):
        print("원본은 *.json.bak 로 보존했다. 다음: python tools/validate.py \"tools/incoming/*.json\"")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
