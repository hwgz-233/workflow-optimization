# -*- coding: utf-8 -*-
r"""
全仓找「某个值 / 某句话」的**全部命中**，并按**文件性质**分类 —— 只读，不改任何东西。

为什么需要它
------------
「改一处要搜全部副本」说起来简单，做起来难在**分类**：
搜出来的命中里，有的是"当前判定依据"（必须逐条关闭），
有的是"历史记录 / 日记 / 指南原文"（**本来就该保留**）。
一锅端地改会毁掉历史，一锅端地不管会留下两套答案。
**本脚本只做一件事：把命中按性质分好类，并标出哪些是"没标注过的现在时声明"。**

分类（**基于路径的启发式，必须人工确认**）
------------------------------------------
    [A] 权威/代码    `scripts\` 或 .py/.json/.yaml/.toml/.ini   ← 大概率是该保留的那一处
    [B] 活文档       🔴 其余 .md（README/规范/SKILL/进度…）   ← **这类才是要逐条关闭的**
    [C] 归档/历史    路径含 归档/旧版/backup/_v1/archive/存档/校验图…
    [D] 日记         路径含 memory/ 且文件名形如 YYYY-MM-DD.md ← 只追加，不改
    [E] 指南/报告    文件名含 改造指南/体检报告/执行反馈/评审/完成报告

**忽略「数字中间」的假命中**
------------------------------
找 `70 字` 会命中 `670 字`。故命中处**前一个字符与后一个字符都不能是数字**。
（这条是实战加的：第一次跑就报了 4 处这种假阳性。）

判定「已标注」
--------------
对 [B] 类命中，**两级**判定：

1. **就近**：命中行 ±2 行内出现 `作废 / 旧值 / 已废弃 / 历史 / 不再 / 校正前 / 改版前 / 旧表 / 已推翻`；
2. **同节**：从命中行往上到**最近的标题行**之间，出现 `⛔ / 已作废 / 不要再用 / 以代码为准`
   —— 覆盖"整节声明作废、旧表留在下面很远"的写法（那种标注离表能有 20 行）。

两级都不中 → 视为 **「未标注的现在时声明」**，这才是要处理的。

退出码
------
    0 = 没有"未标注的 [B] 类命中"
    1 = 存在"未标注的 [B] 类命中"（需要逐条确认或补标注）
    2 = 参数/路径错误

用法
----
    python find_copies.py --root "D:\projects\demo" --value "单页上限"
    python find_copies.py --root "D:\projects\demo" --value "800" --value "1200"
    python find_copies.py --root "D:\projects\demo" --value "上限" --only-b     # 只看活文档
    python find_copies.py --root "D:\projects\demo" --value "单页上限" --json out.json
"""
import os, io, re, sys, json, argparse

EXT_CODE = (".py", ".json", ".yaml", ".yml", ".toml", ".ini", ".cfg", ".bat", ".ps1", ".sh")
RE_ARCHIVE = re.compile(r"归档|旧版|历史|存档|backup|_v1|_v2|oldaudio|_old|archive|_bak", re.I)
# ⚠ `(?:^|[\\/])` 不能省：relpath 对**根目录的直接子目录**返回 `memory\x.md`（前面没有斜杠），
#   只写 `[\\/]memory[\\/]` 时，**memory 恰好是扫描根的直接子目录**这一种布局会永远命不中 ——
#   结果是日记被当成"未标注的活文档"（更深的 `docs/memory/` 反而正常）。
RE_DIARY = re.compile(r"(?:^|[\\/])memory[\\/]\d{4}-\d{2}-\d{2}\.md$", re.I)
RE_GUIDE = re.compile(r"改造指南|体检报告|执行反馈|评审|完成报告|评估报告")
# 「已标注」信号词
RE_ANNOTATED = re.compile(r"作废|旧值|已废弃|历史|不再|校正前|改版前|旧表|先前|旧记|已推翻|已撤销")
# 「强标记」：整节声明作废（旧表可能留在下面很远的地方）
RE_STRIKE = re.compile(r"⛔|已作废|已废弃|不要再用|不要再引用|不再引用|以代码为准")
SCAN_EXT = (".md", ".py")
MAX_BYTES = 6 * 1024 * 1024      # 跳过超大文件


def section_start(lines, i):
    """往上找最近的「标题行」（以 # 或 > 开头），作为本段的起点。"""
    for k in range(i - 1, -1, -1):
        s = lines[k].lstrip()
        if s.startswith("#"):
            return k + 1
    return 0


def is_annotated(lines, i):
    """「已标注」判定，两级：

    ① 命中行 ±2 行内有标注词（就近）；
    ② 同一**小节**（往上到最近的标题行之间）内有 `⛔ 已作废` 这类强标记 ——
       覆盖「整节声明作废、旧表留在下面」的写法（那种情况标注离表很远）。
    """
    near = "\n".join(lines[max(0, i - 2):i + 3])
    if RE_ANNOTATED.search(near):
        return True
    seg = "\n".join(lines[section_start(lines, i):i + 1])
    return bool(RE_STRIKE.search(seg))


def classify(rel):
    """按路径猜文件性质（启发式）"""
    low = rel.replace("\\", "/")
    if RE_DIARY.search(rel.replace("\\", "/")):
        return "D"
    if RE_ARCHIVE.search(low):
        return "C"
    if RE_GUIDE.search(os.path.basename(low)):
        return "E"
    if low.lower().endswith(EXT_CODE) or "/scripts/" in low:
        return "A"
    if low.lower().endswith(".md"):
        return "B"
    return "B"      # 兜底当作活文档（宁可多看一眼）


LABEL = {
    "A": "[A] 权威/代码    ",
    "B": "[B] 活文档  🔴    ",
    "C": "[C] 归档/历史     ",
    "D": "[D] 日记（不改）  ",
    "E": "[E] 指南/报告     ",
}


def scan(root, values, exts, skip_names):
    hits = {v: [] for v in values}
    for r, ds, fs in os.walk(root):
        ds[:] = [d for d in ds if d not in ("__pycache__", ".git", "node_modules")]
        for f in fs:
            if not f.lower().endswith(exts):
                continue
            if f in skip_names:
                continue
            p = os.path.join(r, f)
            try:
                if os.path.getsize(p) > MAX_BYTES:
                    continue
                txt = io.open(p, encoding="utf-8", errors="replace").read()
            except Exception:
                continue
            lines = txt.splitlines()
            rel = os.path.relpath(p, root)
            for v in values:
                for i, ln in enumerate(lines):
                    if v not in ln:
                        continue
                    # 跳过「数字中间」的假命中：找 "70 字" 会命中 "670 字" / "3,970 字"。
                    # 判据：命中处的前一个字符与后一个字符都不能是数字。
                    ok, idx = False, 0
                    while True:
                        j = ln.find(v, idx)
                        if j < 0:
                            break
                        pre = ln[j - 1] if j > 0 else ""
                        post = ln[j + len(v)] if j + len(v) < len(ln) else ""
                        if not pre.isdigit() and not post.isdigit():
                            ok = True
                            break
                        idx = j + 1
                    if not ok:
                        continue
                    ctx = "\n".join(lines[max(0, i - 2):i + 3])
                    hits[v].append({
                        "file": rel, "line": i + 1, "text": ln.strip()[:180],
                        "cls": classify(rel),
                        "annotated": is_annotated(lines, i),
                    })
    return hits


def safe_stdio():
    """中文 Windows 下管道默认 GBK，打印 ✅🔴🛑 会 UnicodeEncodeError 直接崩 ——
    而重定向正是挂 CI 的标准用法。修法：errors="replace"（**不换编码**：
    换了中文会乱码，替换只让个别符号变 ?）。"""
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass


def looks_like_abs_path(s):
    """这个值看起来像绝对路径吗？（用来提示 MSYS 改写的风险）"""
    return bool(s[:1] in ("/", "\\") or re.match(r"^[A-Za-z]:[\\/]", s))


def main():
    safe_stdio()
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", required=True, help="项目根目录")
    ap.add_argument("--value", action="append", required=True,
                    help="要找的值/句子，可重复")
    ap.add_argument("--ext", default="md,py", help="扫描的扩展名（默认 md,py）")
    ap.add_argument("--only-b", action="store_true", help="只列 [B] 活文档类命中")
    ap.add_argument("--json", help="把结果写一份 JSON")
    ap.add_argument("--skip", action="append", default=[],
                    help="跳过的文件名（可重复），如 find_copies.py")
    a = ap.parse_args()

    root = a.root
    if not os.path.isdir(root):
        print("找不到目录：%s" % root)
        sys.exit(2)
    exts = tuple("." + e.strip().lstrip(".") for e in a.ext.split(",") if e.strip())

    hits = scan(root, a.value, exts, set(a.skip))

    L = ["=" * 78,
         "全仓副本扫描（只读）",
         "根目录: %s" % root,
         "扩展名: %s" % ",".join(exts),
         "=" * 78]
    todo_total = 0
    suspect_zero = []       # 形如绝对路径、且 0 命中的值 —— 可能是被 shell 改写，不能当通过
    for v in a.value:
        hs = hits[v]
        L += ["", "-" * 78, "### 找：%r   共 %d 处命中" % (v, len(hs)), "-" * 78]
        if not hs:
            L.append("  （0 命中 —— 该值已完全不存在，或换一种写法再搜）")
            if looks_like_abs_path(v):
                suspect_zero.append(v)
                L.append("  ⚠ 该值形如绝对路径。在 Git Bash / MSYS 下，shell 会把「以斜杠开头」")
                L.append("    的参数值改写成安装目录（如 /archive/ → C:/.../PortableGit/archive/），")
                L.append("    于是永远匹配不上、**而且不报错**。先看一眼真值：")
                L.append('      python -c "import sys;[print(repr(a)) for a in sys.argv[1:]]" --value <你的值>')
                L.append("    规避：命令前加 MSYS_NO_PATHCONV=1，或改成不带前导斜杠的写法（archive/）。")
            continue
        by = {}
        for h in hs:
            by.setdefault(h["cls"], []).append(h)
        for cls in "ABCDE":
            if cls not in by:
                continue
            L.append("")
            L.append("  %s %d 处" % (LABEL[cls], len(by[cls])))
            for h in by[cls]:
                if a.only_b and cls != "B":
                    continue
                flag = ""
                if cls == "B":
                    flag = "  ✅已标注" if h["annotated"] else "  🔴未标注（现在时口吻）"
                    if not h["annotated"]:
                        todo_total += 1
                elif cls == "C":
                    flag = "  （归档，允许保留旧值）"
                elif cls == "D":
                    flag = "  （日记，只追加）"
                L.append("      %s:%d%s" % (h["file"], h["line"], flag))
                L.append("        | %s" % h["text"])

    L += ["", "=" * 78]
    if todo_total:
        L.append("🛑 有待处理项：**%d 处 [B] 活文档命中未被标注**。" % todo_total)
        L.append("   ⇒ 逐条确认：要么改掉，要么补一行「旧值/已作废」标注并指向权威。")
        L.append("   ⇒ ⚠ 归档/[C] 与日记/[D] 的命中**不要动**（那是历史记录）。")
    else:
        if suspect_zero:
            L.append("⚠ 有 %d 个值形如绝对路径且 0 命中（见上）—— **本次结论不可当「通过」用**。" % len(suspect_zero))
            L.append("   先确认这些值没有被 shell 改写成安装目录，再重跑一次。")
        else:
            L.append("✅ 没有「未标注的现在时声明」—— 剩余命中都在归档/日记/已标注的历史段落里。")
    L.append("⚠ 分类是**按路径猜的启发式**，[B] 类里也可能有正当的历史段落；**逐条人工确认**。")
    L.append("=" * 78)

    out = "\n".join(L)
    print(out)
    print("\n退出码 = %d" % (1 if todo_total else 0))

    if a.json:
        io.open(a.json, "w", encoding="utf-8").write(
            json.dumps(hits, ensure_ascii=False, indent=1))
        print("[JSON] %s" % a.json)

    sys.exit(1 if todo_total else 0)


if __name__ == "__main__":
    main()
