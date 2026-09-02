#!/usr/bin/env python3
"""校验所有 locale 翻译中的 <PLACEHOLDER> 与 valhalla.pot 模板一致。

narrative_dictionary 不校验占位符——翻译里丢失/多出 <XXX> 不会报错，
只会输出错乱文本（如"<KILOMETERS>"被吃掉或残留英文占位符）。
本脚本在构建前把这类问题拦下来。

用法（依赖 polib）：
    python3 locales/check_placeholders.py [locales/xx.po ...]
不带参数时校验 locales/ 下全部 .po。
"""
import re
import sys
from pathlib import Path

import polib

LOCALES_DIR = Path(__file__).resolve().parent
POT = LOCALES_DIR / "valhalla.pot"

PLACEHOLDER_RE = re.compile(r"<[A-Z][A-Z_]*>")


def placeholders(s: str) -> list[str]:
    return sorted(PLACEHOLDER_RE.findall(s))


def main() -> None:
    pot = polib.pofile(str(POT))
    pot_map = {e.msgctxt: e.msgid for e in pot}

    targets = [Path(a) for a in sys.argv[1:]] or sorted(LOCALES_DIR.glob("*.po"))
    failures = 0
    checked = 0
    for po_path in targets:
        po = polib.pofile(str(po_path))
        for entry in po:
            # 未翻译或 fuzzy 的条目构建时会回退英文，不校验
            if not entry.msgstr or entry.fuzzy:
                continue
            reference = pot_map.get(entry.msgctxt)
            if reference is None:
                print(f"{po_path.name}: pot 中不存在的条目 {entry.msgctxt}")
                failures += 1
                continue
            checked += 1
            expected = placeholders(reference)
            actual = placeholders(entry.msgstr)
            if expected != actual:
                print(
                    f"{po_path.name} [{entry.msgctxt}]: 占位符不一致\n"
                    f"  msgid  {expected}\n"
                    f"  msgstr {actual}"
                )
                failures += 1

    status = "OK" if failures == 0 else f"{failures} 处失败"
    print(f"已检查 {checked} 条已译条目，{status}")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
