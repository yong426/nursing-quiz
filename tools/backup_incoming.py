# -*- coding: utf-8 -*-
"""tools/incoming 의 생성 문항을 리포 밖으로 백업한다.

incoming 폴더는 .gitignore 대상이라 로컬에만 존재한다. 생성에 쓴 할당량과 시간을
잃지 않도록, 배치가 쌓일 때마다 이 스크립트를 실행해 두면 된다.

    python tools/backup_incoming.py

기본 백업 위치: 리포 옆의 `nursing-quiz-incoming-backup/`
"""
import os, sys, glob, json, shutil

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SRC = os.path.join(ROOT, "tools", "incoming")
DST = os.environ.get("NQ_BACKUP_DIR") or os.path.join(os.path.dirname(ROOT),
                                                     "nursing-quiz-incoming-backup")


def count(files):
    total = 0
    for f in files:
        try:
            total += len(json.load(open(f, encoding="utf-8")))
        except Exception:
            pass
    return total


def main():
    os.makedirs(DST, exist_ok=True)
    src_files = sorted(glob.glob(os.path.join(SRC, "*.json")))
    if not src_files:
        print("백업할 파일이 없다:", SRC); return 1
    copied = 0
    for f in src_files:
        target = os.path.join(DST, os.path.basename(f))
        # 내용이 같으면 건너뛴다
        if os.path.exists(target) and os.path.getsize(target) == os.path.getsize(f):
            if open(target, "rb").read() == open(f, "rb").read():
                continue
        shutil.copy2(f, target)
        copied += 1
    dst_files = sorted(glob.glob(os.path.join(DST, "*.json")))
    n_src, n_dst = count(src_files), count(dst_files)
    print(f"원본 {len(src_files)}개 파일 / {n_src}문항")
    print(f"백업 {len(dst_files)}개 파일 / {n_dst}문항  (새로 복사 {copied}개)")
    print(f"위치: {DST}")
    # 백업에만 있고 원본에 없는 파일 안내 (병합 후 원본을 지운 경우)
    only = set(map(os.path.basename, dst_files)) - set(map(os.path.basename, src_files))
    if only:
        print(f"백업에만 남아 있는 파일 {len(only)}개 (이미 병합했다면 정상):", ", ".join(sorted(only)[:5]))
    return 0 if n_dst >= n_src else 1


if __name__ == "__main__":
    sys.exit(main())
