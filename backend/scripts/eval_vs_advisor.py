"""Evaluate a generated literature map against the advisor's gold map (A9).

All scoring is programmatic; the model that generated the map never judges it.
Only standard library plus optional httpx (when --base/--review is used).
"""
import argparse
import csv
import io
import json
import random
import re
from pathlib import Path

DEFAULT_SEED = 20261008


def normalize_doi(value) -> str:
    text = str(value or '').strip().lower()
    if text.startswith('https://doi.org/'):
        text = text[len('https://doi.org/'):]
    return text


def normalize_title(value) -> str:
    return re.sub(r'[^0-9a-z\u4e00-\u9fff]+', '', str(value or '').lower())


def align(gold_papers, map_papers):
    """Match by DOI first, then by normalized title; each paper pairs at most once."""
    by_doi = {normalize_doi(p.get('doi')): p for p in map_papers if normalize_doi(p.get('doi'))}
    by_title = {normalize_title(p.get('title')): p for p in map_papers if normalize_title(p.get('title'))}
    used, aligned, unaligned_gold = set(), [], []
    for gold in gold_papers:
        match, how = by_doi.get(normalize_doi(gold.get('doi'))), 'doi'
        if match is None or match.get('paper_id') in used:
            match, how = by_title.get(normalize_title(gold.get('title'))), 'title'
        if match is None or match.get('paper_id') in used:
            unaligned_gold.append(gold.get('key'))
            continue
        used.add(match['paper_id'])
        aligned.append({'gold_key': gold.get('key'), 'paper_id': match['paper_id'], 'by': how,
                        'gold': gold, 'paper': match})
    unaligned_map = [p.get('paper_id') for p in map_papers if p.get('paper_id') not in used]
    return {'aligned': aligned, 'unaligned_gold': unaligned_gold, 'unaligned_map': unaligned_map}


def suggest_theme_map(gold, map_data, aligned):
    """For each advisor theme, our themes where its representative DOIs landed."""
    doi_to_paper = {normalize_doi(a['gold'].get('doi')): a['paper'] for a in aligned
                    if a['gold'].get('doi')}
    suggestions = {}
    for theme in gold.get('themes') or []:
        counts = {}
        for doi in theme.get('representative_dois') or []:
            paper = doi_to_paper.get(normalize_doi(doi))
            if not paper:
                continue
            for tid in paper.get('themes') or []:
                counts[tid] = counts.get(tid, 0) + 1
        ranked = sorted((tid for tid, n in counts.items() if n > 0),
                        key=lambda tid: (-counts[tid], tid))[:2]
        suggestions[theme.get('name')] = ranked
    return suggestions


def theme_coverage(gold, map_data, aligned, theme_map):
    """Covered advisor themes and representative-paper recall per theme."""
    doi_to_paper = {normalize_doi(a['gold'].get('doi')): a['paper'] for a in aligned
                    if a['gold'].get('doi')}
    rows, recalled_total, representatives_total = [], 0, 0
    for theme in gold.get('themes') or []:
        mapped = [tid for tid in (theme_map.get(theme.get('name')) or []) if tid]
        dois = theme.get('representative_dois') or []
        hits = 0
        for doi in dois:
            paper = doi_to_paper.get(normalize_doi(doi))
            if paper and set(paper.get('themes') or []) & set(mapped):
                hits += 1
        recalled_total += hits
        representatives_total += len(dois)
        rows.append({'theme': theme.get('name'), 'mapped': mapped, 'representatives': len(dois),
                     'recalled': hits,
                     'recall': round(hits / len(dois), 4) if dois else None})
    covered = sum(1 for row in rows if row['mapped'])
    return {'covered': covered, 'total_gold_themes': len(rows), 'rows': rows,
            'representatives_total': representatives_total, 'recalled_total': recalled_total,
            'overall_recall': round(recalled_total / representatives_total, 4)
            if representatives_total else None}


def _card_fields(card):
    if not isinstance(card, dict):
        return []
    fields = [card.get(name) for name in ('problem', 'mechanism', 'data_setting', 'boundary')]
    fields += card.get('contributions') or []
    return [field for field in fields if isinstance(field, dict)]


def card_stats(cards):
    """Field-status counts overall and per evidence level, plus problem papers."""
    by_evidence, status_total, problem_papers = {}, {}, []
    for entry in cards or []:
        card = entry.get('card') or {}
        level = card.get('evidence_level') or 'unknown'
        bucket = by_evidence.setdefault(level, {'fields': 0, 'statuses': {}})
        statuses = set()
        for field in _card_fields(card):
            status = field.get('status') or 'unknown'
            bucket['fields'] += 1
            bucket['statuses'][status] = bucket['statuses'].get(status, 0) + 1
            status_total[status] = status_total.get(status, 0) + 1
            if status in ('number_mismatch', 'quote_not_found'):
                statuses.add(status)
        for status in sorted(statuses):
            problem_papers.append({'paper_id': entry.get('paper_id'), 'status': status})
    fields_total = sum(status_total.values())
    ratios = {status: round(count / fields_total, 4) for status, count in status_total.items()} \
        if fields_total else {}
    return {'by_evidence': by_evidence, 'status_total': status_total, 'status_ratios': ratios,
            'fields_total': fields_total, 'problem_papers': problem_papers}


SAMPLE_HEADERS = ['导师编号', '题名', '导师主要贡献', '导师证据边界', '我们的主要贡献',
                  '我们的判断边界', '各字段核对状态', '判定', '备注']


def _status_text(card):
    pairs = [('问题', card.get('problem')), ('机制', card.get('mechanism')),
             ('数据条件', card.get('data_setting')), ('判断边界', card.get('boundary'))]
    return ';'.join(f'{label}={field.get("status", "")}' for label, field in pairs if field)


def sample_sheet(gold, cards, aligned, n=30, seed=DEFAULT_SEED):
    """Random sample of aligned papers as (csv with BOM, markdown). No model calls."""
    rng = random.Random(seed)
    picks = rng.sample(list(aligned), min(n, len(aligned))) if aligned else []
    cards_by_pid = {c.get('paper_id'): c for c in cards or []}
    rows = []
    for item in picks:
        gold_paper = item['gold']
        card = (cards_by_pid.get(item['paper_id']) or {}).get('card') or {}
        rows.append([
            gold_paper.get('key'), gold_paper.get('title'),
            gold_paper.get('contribution') or '', gold_paper.get('boundary') or '',
            '\n'.join(field.get('value', '') for field in card.get('contributions') or []),
            (card.get('boundary') or {}).get('value', ''),
            _status_text(card), '', '',
        ])
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(SAMPLE_HEADERS)
    writer.writerows(rows)
    csv_text = '\ufeff' + buf.getvalue()
    md = [f'# 抽查工作表（{len(rows)} 篇，种子 {seed}）', '',
          '判定列由研究者或另一个模型填写：正确 / 部分正确 / 错误。脚本不调用模型。', '']
    for row in rows:
        md += [f"## [{row[0]}] {row[1]}", f"- 导师主要贡献：{row[2] or '—'}",
               f"- 导师证据边界：{row[3] or '—'}",
               f"- 我们的主要贡献：{row[4] or '—'}",
               f"- 我们的判断边界：{row[5] or '—'}",
               f"- 核对状态：{row[6] or '—'}", f"- 判定：{row[7] or '（留空）'}", '']
    return csv_text, '\n'.join(md)


def accuracy_from_csv(csv_text):
    """Contribution accuracy from filled 判定 column; None when nothing filled."""
    rows = list(csv.reader(io.StringIO(str(csv_text).lstrip('\ufeff'))))
    if not rows:
        return {'filled': 0, 'correct': 0, 'accuracy': None}
    header = {name: index for index, name in enumerate(rows[0])}
    if '判定' not in header:
        return {'filled': 0, 'correct': 0, 'accuracy': None}
    column = header['判定']
    filled = [row[column].strip() for row in rows[1:] if len(row) > column and row[column].strip()]
    if not filled:
        return {'filled': 0, 'correct': 0, 'accuracy': None}
    correct = sum(1 for judgment in filled if judgment == '正确')
    return {'filled': len(filled), 'correct': correct, 'accuracy': round(correct / len(filled), 4)}


def verified_rate_from_csv(csv_text):
    """Approximate verified share among papers judged 正确 (spec'd approximation)."""
    rows = list(csv.reader(io.StringIO(str(csv_text).lstrip('\ufeff'))))
    if not rows:
        return {'verified_fields': 0, 'fields': 0, 'rate': None}
    header = {name: index for index, name in enumerate(rows[0])}
    if '判定' not in header or '各字段核对状态' not in header:
        return {'verified_fields': 0, 'fields': 0, 'rate': None}
    judged, status_col = header['判定'], header['各字段核对状态']
    verified, total = 0, 0
    for row in rows[1:]:
        if len(row) <= max(judged, status_col) or row[judged].strip() != '正确':
            continue
        for chunk in row[status_col].split(';'):
            if '=' in chunk:
                total += 1
                if chunk.split('=', 1)[1] == 'quote_verified':
                    verified += 1
    return {'verified_fields': verified, 'fields': total,
            'rate': round(verified / total, 4) if total else None}


def usage_summary(usage):
    if not isinstance(usage, dict):
        return None
    by_kind = usage.get('by_kind') or {}
    by_model = usage.get('by_model') or {}
    total = usage.get('total')
    if not isinstance(total, int):
        total = sum(by_kind.values())
    return {'total': total, 'by_kind': by_kind, 'by_model': by_model}


def build_report(alignment, coverage, stats, theme_map_confirmed, accuracy, verified,
                 usage, sample_count):
    lines = ['# 文献地图对标报告（A 阶段）', '']
    lines += [f'- 对齐：导师论文与地图论文对齐 {len(alignment["aligned"])} 篇'
              f'（DOI {sum(1 for a in alignment["aligned"] if a["by"] == "doi")} 篇、题名 '
              f'{sum(1 for a in alignment["aligned"] if a["by"] == "title")} 篇）；'
              f'导师侧未对齐 {len(alignment["unaligned_gold"])} 篇、地图侧未对齐 '
              f'{len(alignment["unaligned_map"])} 篇。']
    lines += ['', '## 主题覆盖', '',
              f'- 映射{"已经" if theme_map_confirmed else "未经"}人工确认'
              f'{"" if theme_map_confirmed else "（使用建议映射）"}。']
    lines += [f'- 导师主题有对应：{coverage["covered"]}/{coverage["total_gold_themes"]}（退出条件：≥7/8）。',
              f'- 代表论文总体召回：{coverage["recalled_total"]}/{coverage["representatives_total"]}'
              f'（{coverage["overall_recall"]}）。', '', '| 导师主题 | 映射主题 | 代表论文召回 |', '|---|---|---|']
    for row in coverage['rows']:
        mapped = '、'.join(row['mapped']) or '—'
        recall = f'{row["recalled"]}/{row["representatives"]}'
        lines.append(f'| {row["theme"]} | {mapped} | {recall} |')
    lines += ['', '## 卡片核对统计', '',
              f'- 字段总数 {stats["fields_total"]}；'
              + '；'.join(f'{status} {count}（{ratio}）' for status, (count, ratio)
                          in sorted((s, (c, stats["status_ratios"].get(s, 0)))
                                    for s, c in stats['status_total'].items())) or '- 无字段。',
              '']
    lines += ['按证据级别：']
    for level, bucket in sorted(stats['by_evidence'].items()):
        detail = '；'.join(f'{status} {count}' for status, count in sorted(bucket['statuses'].items()))
        lines.append(f'- {level}：{bucket["fields"]} 字段（{detail}）')
    if stats['problem_papers']:
        listing = '、'.join(f'[P{item["paper_id"]}]（{item["status"]}）'
                            for item in stats['problem_papers'])
        lines += ['', f'- 需核对的论文：{listing}']
    lines += ['', '## 抽查工作表', '',
              f'- 抽样 {sample_count} 篇（sample.csv / sample.md，判定列待填写）。',
              '- 贡献正确率：' + (f'{accuracy["correct"]}/{accuracy["filled"]}（{accuracy["accuracy"]}）'
                                  if accuracy['accuracy'] is not None else '待填写'),
              '- quote_verified 近似正确率（判定为“正确”的论文中 verified 字段占比，属近似）：'
              + (f'{verified["verified_fields"]}/{verified["fields"]}（{verified["rate"]}）'
                 if verified['rate'] is not None else '待填写'), '',
              '## A 阶段退出条件对照', '',
              f'- 导师 8 个主题中至少 7 个有对应：{"满足" if coverage["covered"] >= 7 else "未满足"}'
              f'（当前 {coverage["covered"]}/{coverage["total_gold_themes"]}）。',
              '- 抽查贡献正确率 ≥ 90%：'
              + (f'{"满足" if accuracy["accuracy"] is not None and accuracy["accuracy"] >= 0.9 else "未满足"}'
                 f'（当前 {accuracy["accuracy"]}）' if accuracy['accuracy'] is not None else '待填写'),
              '- quote_verified 字段正确率 ≥ 95%（近似）：'
              + (f'{"满足" if verified["rate"] is not None and verified["rate"] >= 0.95 else "未满足"}'
                 f'（当前 {verified["rate"]}）' if verified['rate'] is not None else '待填写'),
              '- 研究者主观判断项：待研究者确认。']
    summary = usage_summary(usage)
    if summary is not None:
        lines += ['', '## 成本（--usage）', '', f'- 总 token：{summary["total"]}']
        for kind, tokens in sorted(summary['by_kind'].items(), key=lambda kv: -kv[1]):
            lines.append(f'- 用途 {kind}：{tokens} token')
        for model, tokens in sorted(summary['by_model'].items(), key=lambda kv: -kv[1]):
            lines.append(f'- 模型 {model}：{tokens} token')
    lines.append('')
    return '\n'.join(lines)


def _fetch_live(base, review, out_dir):
    import httpx

    with httpx.Client(base_url=base, timeout=30) as client:
        map_data = client.get(f'/reviews/{review}/map').raise_for_status().json()
        cards = client.get(f'/reviews/{review}/cards').raise_for_status().json()
    (out_dir / 'map.json').write_text(json.dumps(map_data, ensure_ascii=False, indent=2),
                                      encoding='utf-8')
    (out_dir / 'cards.json').write_text(json.dumps(cards, ensure_ascii=False, indent=2),
                                        encoding='utf-8')
    return map_data, cards


def main(argv=None):
    parser = argparse.ArgumentParser(description='对标导师文献地图的评测脚本（A9）')
    parser.add_argument('--gold', required=True, help='advisor_gold.json（只读）')
    parser.add_argument('--map', help='GET /reviews/{id}/map 的返回 JSON 文件')
    parser.add_argument('--cards', help='GET /reviews/{id}/cards 的返回 JSON 文件')
    parser.add_argument('--base', help='运行中应用的 API 基地址，如 http://127.0.0.1:4391/api')
    parser.add_argument('--review', help='综述 id（与 --base 一起使用）')
    parser.add_argument('--out', required=True, help='输出目录')
    parser.add_argument('--theme-map', help='人工确认后的主题映射 theme_map.json')
    parser.add_argument('--usage', help='GET /usage 的返回 JSON 文件')
    parser.add_argument('--seed', type=int, default=DEFAULT_SEED)
    parser.add_argument('--sample', type=int, default=30)
    args = parser.parse_args(argv)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    gold = json.loads(Path(args.gold).read_text(encoding='utf-8'))
    if args.base and args.review:
        map_data, cards = _fetch_live(args.base, args.review, out_dir)
    else:
        map_data = json.loads(Path(args.map).read_text(encoding='utf-8'))
        cards = json.loads(Path(args.cards).read_text(encoding='utf-8'))

    alignment = align(gold.get('papers') or [], map_data.get('papers') or [])
    suggested = suggest_theme_map(gold, map_data, alignment['aligned'])
    (out_dir / 'theme_map.suggested.json').write_text(
        json.dumps(suggested, ensure_ascii=False, indent=2), encoding='utf-8')

    theme_map_confirmed = bool(args.theme_map)
    theme_map = json.loads(Path(args.theme_map).read_text(encoding='utf-8')) if args.theme_map \
        else suggested
    coverage = theme_coverage(gold, map_data, alignment['aligned'], theme_map)
    stats = card_stats(cards)

    sample_path = out_dir / 'sample.csv'
    if not sample_path.exists():  # 保留研究者已填写的判定
        csv_text, md_text = sample_sheet(gold, cards, alignment['aligned'],
                                         n=args.sample, seed=args.seed)
        sample_path.write_text(csv_text, encoding='utf-8', newline='')
        (out_dir / 'sample.md').write_text(md_text, encoding='utf-8')
    accuracy = accuracy_from_csv(sample_path.read_text(encoding='utf-8'))
    verified = verified_rate_from_csv(sample_path.read_text(encoding='utf-8'))
    usage = json.loads(Path(args.usage).read_text(encoding='utf-8')) if args.usage else None

    report = build_report(alignment, coverage, stats, theme_map_confirmed, accuracy, verified,
                          usage, sample_count=min(args.sample, len(alignment['aligned'])))
    (out_dir / 'report.md').write_text(report, encoding='utf-8')
    print(f'评测完成：{out_dir / "report.md"}')


if __name__ == '__main__':
    main()
