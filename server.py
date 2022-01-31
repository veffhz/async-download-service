import asyncio
import logging
import argparse
from pathlib import Path

import aiofiles
from aiohttp import web

FILENAME = 'photos.zip'
DEFAULT_PHOTO_PATH = 'test_photos'
ZIP_COMMAND_TEMPLATE = 'zip -r -q -'
KILL_COMMAND_TEMPLATE = 'pkill -9 -P'


async def get_photo_dir(photo_path) -> Path:
    """
    получает полный путь до папки с фото
    :param photo_path:
    :return: absolute path
    """

    # если передан полный путь
    path = Path(photo_path)
    if path.is_dir():
        return path

    # путь по умолчанию
    return Path(__file__)\
        .parent\
        .joinpath(DEFAULT_PHOTO_PATH)\
        .absolute()


async def kill(pid):
    """
    убивает процесс bash и процесс zip по pid
    :param pid:
    """

    bash_command = f'{KILL_COMMAND_TEMPLATE} {pid}'

    await asyncio.create_subprocess_shell(
        bash_command, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )


async def on_shutdown(_app):
    logging.debug('Shutting down!')

    # stopped all tasks
    for task in asyncio.all_tasks():
        task.cancel()


async def archivate(request):
    archive_hash = request.match_info.get('archive_hash')
    photo_dir = await get_photo_dir(request.app['photo_path'])

    if not photo_dir.joinpath(archive_hash).exists():
        raise web.HTTPNotFound(text='Архив не существует или был удален')

    bash_command = f'{ZIP_COMMAND_TEMPLATE} {archive_hash}'

    proc = await asyncio.create_subprocess_shell(
        bash_command, cwd=photo_dir,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE
    )

    if proc.returncode:
        stderr = await proc.stderr.read()
        logging.error(stderr)
        raise web.HTTPInternalServerError(text='Ошибка. Попробуйте позже!')

    response = web.StreamResponse()
    response.content_type = 'application/zip'
    response.headers['Content-Disposition'] = f'attachment; filename="{FILENAME}"'

    await response.prepare(request)

    try:
        while not proc.stdout.at_eof():
            data = await proc.stdout.read(request.app['chunk_size'])
            content = bytearray(data)

            logging.debug('Sending archive chunk ...')

            await response.write(content)
            await asyncio.sleep(request.app['delay'])

        await response.write_eof()

        return response

    except asyncio.CancelledError:
        logging.warning('Download was interrupted!')

        # отпускаем перехваченный CancelledError
        raise

    finally:
        if proc.returncode is None:
            await kill(proc.pid)
            logging.warning('Stopped send!')


async def handle_index_page(request):
    async with aiofiles.open('index.html', mode='r') as index_file:
        index_contents = await index_file.read()
    return web.Response(text=index_contents, content_type='text/html')


def parse_args() -> argparse.Namespace:
    """Parse script arguments."""
    parser = argparse.ArgumentParser()
    parser.add_argument('-v', '--verbose', help='increase output verbosity',
                        action='store_true')

    parser.add_argument('-d', '--delay', help='Delay for response service',
                        type=int, default=1)

    parser.add_argument('--photo_path', help='Source folder for images',
                        type=str, default=DEFAULT_PHOTO_PATH)

    return parser.parse_args()


if __name__ == '__main__':
    args = parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)

    app = web.Application()

    app['delay'] = args.delay
    app['photo_path'] = args.photo_path
    app['chunk_size'] = 1024 * 1024

    app.on_shutdown.append(on_shutdown)
    app.add_routes([
        web.get('/', handle_index_page),
        web.get('/archive/{archive_hash}/', archivate),
    ])
    web.run_app(app)
