#!/usr/bin/env python3
"""清洗 Markdown 文本用于 TTS 语音合成。删除 Markdown 语法和特殊符号，保留汉字、中文标点、数字。"""

import argparse
import re
import sys

KEEP_PATTERN = re.compile(r'[^\u4e00-\u9fff，。！？、：；""''…—\n0-9a-zA-Z]')

CONSECUTIVE_NEWLINES = re.compile(r'\n{2,}')


def clean(text: str) -> str:
    text = KEEP_PATTERN.sub('', text)
    text = CONSECUTIVE_NEWLINES.sub('\n', text)
    return text.strip()


def main():
    parser = argparse.ArgumentParser(description='清洗 Markdown 文本用于 TTS')
    parser.add_argument('input', nargs='?', help='输入文件（默认读 stdin）')
    parser.add_argument('-o', '--output', help='输出文件（默认写 stdout）')
    args = parser.parse_args()

    if args.input:
        with open(args.input, encoding='utf-8') as f:
            text = f.read()
    else:
        text = sys.stdin.read()

    result = clean(text)

    if args.output:
        with open(args.output, 'w', encoding='utf-8') as f:
            f.write(result)
    else:
        print(result)


if __name__ == '__main__':
    main()
