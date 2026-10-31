#!/usr/bin/env python3
"""List/select one IG thread without extracting unrelated conversations."""
import argparse
import datetime as dt
import json
import os
from pathlib import Path, PurePosixPath
import stat
import zipfile

LIMIT = 2 * 1024 ** 3


def safe(name):
    p = PurePosixPath(name)
    if not name or '\\' in name or p.is_absolute() or '..' in p.parts or ':' in p.parts[0]:
        raise ValueError('不安全的 ZIP 路徑')
    return p


def inventory(z):
    found = {}
    for info in z.infolist():
        safe(info.filename)
        if stat.S_ISLNK(info.external_attr >> 16):
            raise ValueError('ZIP 含符號連結，已停止')
        if info.filename in found:
            raise ValueError('ZIP 含重複路徑，已停止')
        found[info.filename] = info
    return found


def read_json(z, info):
    if info.file_size > 64 * 1024 ** 2:
        raise ValueError('單個 JSON 超過 64 MiB；請先檢查或分段')
    return json.loads(z.read(info).decode('utf-8-sig'))


def signature(path):
    s = Path(path).stat()
    return {'size': s.st_size, 'mtime_ns': s.st_mtime_ns}


def display(value):
    if not isinstance(value, str):
        return value
    try:
        repaired = value.encode('latin1').decode('utf-8')
        return repaired
    except (UnicodeError, ValueError):
        return value


def list_threads(path, out, max_bytes):
    threads, skipped = {}, []
    used = 0
    with zipfile.ZipFile(path) as z:
        entries = inventory(z)
        for name, info in sorted(entries.items()):
            p = PurePosixPath(name)
            if not (p.name.startswith('message') and p.suffix.lower() == '.json'):
                continue
            used += info.file_size
            if used > max_bytes:
                raise ValueError('候選 JSON 總大小超過資源上限')
            data = read_json(z, info)
            if not isinstance(data, dict) or not isinstance(data.get('messages'), list):
                skipped.append(name)
                continue
            key = str(p.parent)
            t = threads.setdefault(key, {'folder': key, 'title': '', 'participants': [], 'files': [], 'export_records': 0, 'timestamp_min': None, 'timestamp_max': None})
            t['files'].append(name)
            t['title'] = display(data.get('title', t['title']))
            for participant in data.get('participants', []):
                if isinstance(participant, dict) and participant.get('name'):
                    person = display(participant['name'])
                    if person not in t['participants']:
                        t['participants'].append(person)
            t['export_records'] += len(data['messages'])
            for msg in data['messages']:
                timestamp = msg.get('timestamp_ms') if isinstance(msg, dict) else None
                if isinstance(timestamp, (int, float)) and not isinstance(timestamp, bool):
                    t['timestamp_min'] = timestamp if t['timestamp_min'] is None else min(timestamp, t['timestamp_min'])
                    t['timestamp_max'] = timestamp if t['timestamp_max'] is None else max(timestamp, t['timestamp_max'])
    result = []
    zone = dt.timezone(dt.timedelta(hours=8))
    for i, t in enumerate(threads.values(), 1):
        t['id'] = f'T{i:03d}'
        for edge in ('min', 'max'):
            raw = t[f'timestamp_{edge}']
            try:
                t[f'date_{edge}'] = dt.datetime.fromtimestamp(raw / 1000, zone).isoformat() if raw is not None else None
            except (ValueError, OverflowError, OSError):
                t[f'date_{edge}'] = None
        result.append(t)
    payload = {'source_signature': signature(path), 'threads': result, 'skipped_json': skipped}
    write_new(out, payload)
    print(json.dumps({'threads': len(result), 'index': str(out), 'skipped_json': len(skipped)}, ensure_ascii=False))


def uris(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key == 'uri' and isinstance(item, str):
                yield item
            else:
                yield from uris(item)
    elif isinstance(value, list):
        for item in value:
            yield from uris(item)


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)


def select(path, index, thread_id, out, max_bytes):
    idx = json.loads(Path(index).read_text(encoding='utf-8'))
    if idx['source_signature'] != signature(path):
        raise ValueError('來源 ZIP 已變更，請重新列出清單')
    matches = [t for t in idx['threads'] if t['id'] == thread_id]
    if len(matches) != 1:
        raise ValueError('找不到指定聊天室')
    thread = matches[0]
    target = Path(out)
    if target.exists():
        raise ValueError('輸出目錄已存在，請選新目錄')
    with zipfile.ZipFile(path) as z:
        entries = inventory(z)
        selected = set(thread['files'])
        missing, external, ambiguous = [], [], []
        for name in thread['files']:
            if name not in entries:
                raise ValueError('清單來源不存在')
            for uri in uris(read_json(z, entries[name])):
                if uri.startswith(('https://', 'http://')):
                    external.append(uri)
                    continue
                safe(uri)
                possible = [n for n in entries if n == uri or n.endswith('/' + uri)]
                if len(possible) == 1:
                    selected.add(possible[0])
                elif not possible:
                    missing.append(uri)
                else:
                    ambiguous.append(uri)
        total = sum(entries[n].file_size for n in selected)
        if total > max_bytes:
            raise ValueError('選定資料超過資源上限；需分包或明確調整 --max-bytes')
        if any(entries[n].is_dir() for n in selected):
            raise ValueError('附件指向目錄，需人工檢查')
        target.mkdir(parents=True)
        manifest = {'thread': thread, 'source_signature': signature(path), 'included_files': sorted(selected), 'uncompressed_bytes': total, 'missing_attachments': sorted(set(missing)), 'external_uris_not_fetched': sorted(set(external)), 'ambiguous_attachments': sorted(set(ambiguous)), 'note': '此工具僅整理檔案，不代表訊息或附件已完成分析。'}
        try:
            with zipfile.ZipFile(target / 'selected.zip', 'x', compression=zipfile.ZIP_DEFLATED) as dest:
                for name in sorted(selected):
                    # Streaming limits peak memory; paths are never extracted to disk.
                    with z.open(entries[name]) as src, dest.open(name, 'w', force_zip64=True) as dst:
                        while True:
                            chunk = src.read(1024 * 1024)
                            if not chunk:
                                break
                            dst.write(chunk)
            write_new(target / 'bundle-manifest.json', manifest)
        except Exception:
            # Only remove this invocation's incomplete outputs.
            for name in ('selected.zip', 'bundle-manifest.json'):
                (target / name).unlink(missing_ok=True)
            target.rmdir()
            raise
    print(json.dumps({'bundle': str(target / 'selected.zip'), 'manifest': str(target / 'bundle-manifest.json'), 'missing': len(manifest['missing_attachments']), 'ambiguous': len(manifest['ambiguous_attachments'])}, ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for command in ('list', 'select'):
        p = sub.add_parser(command)
        p.add_argument('zip')
        p.add_argument('--out', required=True)
        p.add_argument('--max-bytes', type=int, default=LIMIT)
        if command == 'select':
            p.add_argument('--index', required=True)
            p.add_argument('--id', required=True)
    args = parser.parse_args()
    try:
        if args.max_bytes <= 0:
            raise ValueError('--max-bytes 必須大於零')
        if args.command == 'list':
            list_threads(args.zip, args.out, args.max_bytes)
        else:
            select(args.zip, args.index, args.id, args.out, args.max_bytes)
    except (ValueError, KeyError, OSError, zipfile.BadZipFile, UnicodeError) as e:
        parser.exit(1, f'停止：{e}\n')


if __name__ == '__main__':
    main()
