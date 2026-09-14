"""Import and inspect locally owned Arena content."""
import argparse
import json
from pathlib import Path
import struct

from arena.games.tomb_raider.codec import ProtocolError
from arena.games.tomb_raider.guides import encode_links
from arena.games.tomb_raider.replay import GHOST_HEADER, clip_inputs, read_clip, read_ghost, time_checksum
from arena.games.tomb_raider.store import Store


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data', type=Path, default=Path('data'))
    commands = parser.add_subparsers(dest='command', required=True)
    for name in ('import-clip', 'import-guide', 'import-course'):
        command = commands.add_parser(name)
        command.add_argument('file', type=Path)
        command.add_argument('--name', required=True)
        if name == 'import-guide':
            command.add_argument('--level', type=int, choices=range(16), required=True)
    command = commands.add_parser('export')
    command.add_argument('id', type=int)
    command.add_argument('file', type=Path)
    commands.add_parser('status')
    command = commands.add_parser('author-guide-links')
    command.add_argument('description', type=Path, help='JSON array of level, room, bounds and optional directory records')
    command.add_argument('output', type=Path)
    command = commands.add_parser('author-course')
    command.add_argument('clip', type=Path)
    command.add_argument('output', type=Path)
    command.add_argument('--race-id', type=int, required=True)
    command.add_argument('--level', type=int, choices=range(1,16), required=True)
    command.add_argument('--room', type=int, required=True)
    command.add_argument('--start', nargs=3, type=int, required=True, metavar=('X','Y','Z'))
    command.add_argument('--yaw', type=int, default=0)
    command.add_argument('--checkpoint', nargs=3, type=int, action='append', required=True)
    command.add_argument('--time-ms', type=int, required=True)
    command.add_argument('--limit-seconds', type=int, default=300)
    args = parser.parse_args()
    store = Store(args.data)
    try:
        if args.command == 'author-guide-links':
            args.output.write_bytes(encode_links(json.loads(args.description.read_text())))
            print('Native guide links written; install with arena.games.tomb_raider.setup --guide-links.')
        elif args.command == 'author-course':
            course = GHOST_HEADER.pack(args.race_id,args.level,args.room,len(args.checkpoint),
                args.yaw & 0xffffffff,0,args.limit_seconds*25,*args.start,0x1234)
            course += b''.join(struct.pack('<iii',*point) for point in args.checkpoint)
            data = course + struct.pack('<II',args.time_ms,time_checksum(args.time_ms)) + clip_inputs(args.clip.read_bytes())
            read_ghost(data)
            args.output.write_bytes(data)
            print('Course written; verify its generated time in the game before publishing.')
        elif args.command == 'import-course':
            print(store.import_course(args.name,args.file.read_bytes()))
        elif args.command in ('import-clip','import-guide'):
            data = args.file.read_bytes()
            read_clip(data)
            parent = 1402 + args.level if args.command == 'import-guide' else 1301
            print(store.add_content(parent,2222,args.name,data))
        elif args.command == 'export':
            data = store.content(args.id)
            if data is None:
                raise ValueError('Object has no downloadable content')
            args.file.write_bytes(data)
        else:
            result = {table:[dict(row) for row in store.db.execute(query)] for table,query in {
                'users':'SELECT id,name,created FROM users',
                'content':'SELECT id,parent,kind,name,length(content) AS bytes FROM objects',
                'courses':'SELECT id,name,level,reference_object FROM courses',
                'results':'SELECT * FROM race_results',
                'league':'SELECT month,user_id,SUM(points) AS points FROM league_events GROUP BY month,user_id',
            }.items()}
            result['trophies'] = [dict(row) for row in store.trophies()]
            print(json.dumps(result,indent=2))
    except (OSError,ValueError,ProtocolError,struct.error,KeyError,TypeError) as error:
        parser.exit(1,f'{error}\n')
    finally:
        store.close()


if __name__ == '__main__':
    main()
