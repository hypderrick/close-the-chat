#!/usr/bin/env python3
"""监测一个接入了「不怕关对话」的项目：每个对话读了哪些项目文件、花了多少 token。

数据来自 Claude Code 存在本机的对话记录（~/.claude/projects/），只在本机统计，
只输出数字和文件名，不输出对话内容。项目本身零改动。

用法：
  python3 工具/监测.py <项目路径> [--标签 v1.2] [--自 2026-11-24]

结果打印成表，同时追加一行快照到 监测/<项目名>.jsonl（开发目录里，不发布）。
"""
import argparse
import datetime as dt
import glob
import json
import os
import re
import sys
import unicodedata

开发目录 = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
记录根 = os.path.expanduser("~/.claude/projects")


def nfc(s):
    return unicodedata.normalize("NFC", s)


def 项目文件快照(项目):
    """每次开工都会读到的文件有多大，以及进度表的构成。"""
    快照 = {}
    for 相对 in ["AGENTS.md", "CLAUDE.md", "进度.md", "进度-已完成.md"]:
        p = os.path.join(项目, 相对)
        if os.path.exists(p):
            快照[相对] = len(open(p, encoding="utf-8").read())
    for p in sorted(glob.glob(os.path.join(项目, "沉淀", "*.md"))):
        快照["沉淀/" + os.path.basename(p)] = len(open(p, encoding="utf-8").read())
    进度 = os.path.join(项目, "进度.md")
    行 = {}
    if os.path.exists(进度):
        for l in open(进度, encoding="utf-8"):
            if l.startswith("|") and not l.startswith("|---") and "编号" not in l:
                for 状态 in ["已收到", "处理中", "待你验收", "需要你决定", "已完成"]:
                    if f"| {状态}" in l or f"|{状态}" in l:
                        行[状态] = 行.get(状态, 0) + 1
                        break
    return {"文件字数": 快照, "进度条目": 行}


def 对话记录(项目):
    结果 = []
    for f in glob.glob(os.path.join(记录根, "*", "*.jsonl")):
        with open(f, encoding="utf-8") as fh:
            for i, l in enumerate(fh):
                if i > 40:
                    break
                try:
                    o = json.loads(l)
                except ValueError:
                    continue
                if o.get("cwd"):
                    if nfc(o["cwd"]).rstrip("/") == 项目:
                        结果.append(f)
                    break
    return 结果


项目文件模式 = re.compile(r"(AGENTS\.md|CLAUDE\.md|进度(?:-已完成)?\.md|沉淀/[^\s'\"|;>*$]+?\.md|机制/[^\s'\"|;>*$]+?\.md|素材库\.md)")


def 分析(f, 项目):
    记录 = []
    for l in open(f, encoding="utf-8"):
        try:
            记录.append(json.loads(l))
        except ValueError:
            pass
    标题, 开始 = None, None
    已计 = set()
    调用 = []  # 每次 API 调用的输入总量
    输出 = 0
    轮 = 0
    读 = []  # (第几轮, 文件)
    自动加载 = []
    for o in 记录:
        t = o.get("type")
        if t == "custom-title":
            标题 = o.get("customTitle") or o.get("title") or 标题
        if o.get("timestamp") and not 开始:
            开始 = o["timestamp"]
        if t == "attachment" and (o.get("attachment") or {}).get("type") == "instructions":
            for x in o["attachment"].get("files", []):
                自动加载.append((os.path.relpath(nfc(x["path"]), 项目), len(x.get("content", ""))))
        if t == "user" and not o.get("isMeta") and not o.get("isSidechain"):
            c = o["message"]["content"]
            真提问 = isinstance(c, str) or any(
                isinstance(x, dict) and x.get("type") == "text" for x in c
            )
            if 真提问 and not any(isinstance(x, dict) and x.get("type") == "tool_result" for x in (c if isinstance(c, list) else [])):
                轮 += 1
        if t == "assistant":
            m = o["message"]
            u = m.get("usage") or {}
            if m.get("id") not in 已计 and u:
                已计.add(m.get("id"))
                调用.append(u.get("input_tokens", 0) + u.get("cache_creation_input_tokens", 0) + u.get("cache_read_input_tokens", 0))
                输出 += u.get("output_tokens", 0)
            for c in m.get("content", []):
                if not (isinstance(c, dict) and c.get("type") == "tool_use"):
                    continue
                inp = c.get("input", {})
                if c["name"] == "Read":
                    文本 = nfc(inp.get("file_path", ""))
                elif c["name"] == "Bash" and re.search(r"\b(cat|sed|head|tail|less|grep)\b", inp.get("command", "")):
                    文本 = nfc(inp.get("command", ""))
                else:
                    continue
                for 名 in set(项目文件模式.findall(文本)):
                    if 名.startswith("_"):
                        continue
                    读.append((max(轮, 1), 名))
    # 同一文件只记第一次读到的轮次
    首读 = {}
    for 第几轮, 名 in 读:
        首读.setdefault(名, 第几轮)
    return {
        "对话": os.path.basename(f)[:8],
        "开始": 开始,
        "标题": 标题,
        "轮数": 轮,
        "API调用": len(调用),
        "首次调用上下文": 调用[0] if 调用 else 0,
        "最大上下文": max(调用) if 调用 else 0,
        "累计输入": sum(调用),
        "累计输出": 输出,
        "自动加载": 自动加载,
        "第1轮读的文件": sorted(k for k, v in 首读.items() if v == 1),
        "之后按需读的文件": sorted(f"{k}@第{v}轮" for k, v in 首读.items() if v > 1),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("项目")
    ap.add_argument("--标签", default="")
    ap.add_argument("--自", default="", help="只统计这个日期（含）之后开始的对话，如 2026-11-24")
    a = ap.parse_args()
    项目 = nfc(os.path.abspath(os.path.expanduser(a.项目))).rstrip("/")
    快照 = 项目文件快照(项目)
    对话 = sorted((分析(f, 项目) for f in 对话记录(项目)), key=lambda x: x["开始"] or "")
    if a.自:
        对话 = [x for x in 对话 if (x["开始"] or "") >= a.自]

    print(f"项目：{项目}   标签：{a.标签 or '-'}")
    print("\n当前文件字数：")
    for k, v in 快照["文件字数"].items():
        print(f"  {k:24} {v:>7}")
    print(f"  进度条目：{快照['进度条目'] or '无'}")
    print("\n各对话（token 为模型处理的输入总量，含缓存）：")
    for x in 对话:
        print(f"- {x['开始'][:16] if x['开始'] else '?'}  {x['标题'] or x['对话']}")
        print(f"    轮数 {x['轮数']}  调用 {x['API调用']}  首次上下文 {x['首次调用上下文']:,}  最大上下文 {x['最大上下文']:,}  累计输入 {x['累计输入']:,}  输出 {x['累计输出']:,}")
        print(f"    自动加载：{', '.join(f'{p}({n})' for p, n in x['自动加载']) or '-'}")
        print(f"    第 1 轮读：{', '.join(x['第1轮读的文件']) or '-'}")
        print(f"    之后读：{', '.join(x['之后按需读的文件']) or '-'}")
    if 对话:
        n = len(对话)
        print(f"\n平均：首次上下文 {sum(x['首次调用上下文'] for x in 对话)//n:,}  每轮累计输入 {sum(x['累计输入'] for x in 对话)//max(1,sum(x['轮数'] for x in 对话)):,}")

    os.makedirs(os.path.join(开发目录, "监测"), exist_ok=True)
    出 = os.path.join(开发目录, "监测", os.path.basename(项目) + ".jsonl")
    with open(出, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({"记录时间": dt.datetime.now().isoformat(timespec="seconds"), "标签": a.标签, "快照": 快照, "对话": 对话}, ensure_ascii=False) + "\n")
    print(f"\n已追加到 {os.path.relpath(出, 开发目录)}")


if __name__ == "__main__":
    sys.exit(main())
