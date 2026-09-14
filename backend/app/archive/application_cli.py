"""JSON-report interface used by the source and windowed executable restore script."""
import argparse
import json
from pathlib import Path


def main(argv=None):
    parser = argparse.ArgumentParser(description='PaperMind application archive maintenance')
    parser.add_argument('action', choices=['verify', 'restore'])
    parser.add_argument('backup')
    parser.add_argument('--report', required=True)
    parser.add_argument('--data-dir')
    parser.add_argument('--db-path')
    parser.add_argument('--master-key-path')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    try:
        if args.action == 'verify':
            from app.archive.application import verify
            result = verify(Path(args.backup))
            result.pop('manifest', None)
        else:
            if not args.data_dir:
                raise ValueError('整体恢复必须明确指定目标数据目录')
            from app.archive.application_restore import restore
            result = restore(args.backup, args.data_dir, db_path=args.db_path,
                             master_key_path=args.master_key_path, apply=args.apply)
    except Exception as exc:
        result = {'ok': False, 'errors': [str(exc)]}
    Path(args.report).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0 if result['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
