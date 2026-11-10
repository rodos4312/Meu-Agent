"""Portable, bounded project snapshots. No databases, credentials or host runtimes."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re

CHUNK = 192 * 1024
MAX_FILE = 32 * 1024 * 1024
MAX_TOTAL = 128 * 1024 * 1024
MAX_FILES = 4000
EXCLUDED = {'.git', '.svn', '.hg', '.venv', 'venv', 'node_modules', '__pycache__',
            '.dart_tool', '.gradle', 'build', '.cache', '.codex', '.hermes', '.meu',
            'auth.json', 'key.properties', 'local.properties'}


def portable(path):
    if not isinstance(path, str) or not path or len(path) > 512 or '\\' in path:
        raise ValueError('invalid_project_path')
    parts = path.split('/')
    if any(not part or part in {'.', '..'} or len(part) > 180 or
           re.search(r'[<>:"|?*\x00-\x1f]', part) or part.endswith((' ', '.')) or
           part.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL',
                *('COM' + str(i) for i in range(1, 10)), *('LPT' + str(i) for i in range(1, 10))}
           for part in parts):
        raise ValueError('invalid_project_path')
    if any(part.lower() in EXCLUDED or part.lower().startswith('.env') or
           part.lower().endswith(('.pem', '.key', '.keystore', '.jks', '.p12', '.pfx')) for part in parts):
        raise ValueError('private_or_generated_file')
    return PurePosixPath(path)


def regular(path):
    info = path.lstat()
    if path.is_symlink() or getattr(info, 'st_file_attributes', 0) & 0x400:
        raise ValueError('project_link_refused')
    return info


def checked_root(root):
    root = Path(root).absolute()
    for item in (root, *root.parents):
        regular(item)
    if not root.is_dir() or root == Path(root.anchor):
        raise ValueError('invalid_project_directory')
    return root


def manifest(root, *, copy_to=None):
    root = checked_root(root)
    entries, names, total = [], set(), 0
    for directory, folders, files in os.walk(root, followlinks=False):
        for name in list(folders):
            relative = (Path(directory) / name).relative_to(root).as_posix()
            try:
                portable(relative)
            except ValueError as error:
                if str(error) == 'private_or_generated_file':
                    folders.remove(name)
                    continue
                raise
            regular(Path(directory) / name)
            if relative.casefold() in names or len(entries) >= MAX_FILES:
                raise ValueError('project_case_collision_or_limit')
            names.add(relative.casefold())
            entries.append({'path': relative, 'size': 0, 'sha256': hashlib.sha256(b'').hexdigest(),
                            'executable': False, 'directory': True})
            if copy_to is not None:
                (Path(copy_to) / relative).mkdir(parents=True, exist_ok=True)
        for name in sorted(files):
            source = Path(directory) / name
            relative = source.relative_to(root).as_posix()
            try:
                portable(relative)
            except ValueError as error:
                if str(error) == 'private_or_generated_file':
                    continue
                raise
            before = regular(source)
            if not source.is_file() or before.st_nlink > 1:
                raise ValueError('project_link_refused')
            total += before.st_size
            if before.st_size > MAX_FILE or total > MAX_TOTAL or len(entries) >= MAX_FILES:
                raise ValueError('project_too_large')
            if relative.casefold() in names:
                raise ValueError('project_case_collision')
            names.add(relative.casefold())
            digest = hashlib.sha256()
            target = None
            if copy_to is not None:
                destination = Path(copy_to) / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                target = destination.open('xb')
            try:
                with source.open('rb') as stream:
                    opened = os.fstat(stream.fileno())
                    if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                        raise ValueError('project_changed')
                    size = 0
                    while chunk := stream.read(CHUNK):
                        size += len(chunk)
                        if size > MAX_FILE:
                            raise ValueError('project_changed')
                        digest.update(chunk)
                        if target:
                            target.write(chunk)
            finally:
                if target:
                    target.close()
            after = regular(source)
            if (size, after.st_size, after.st_mtime_ns, after.st_ino) != (
                    before.st_size, before.st_size, before.st_mtime_ns, before.st_ino):
                raise ValueError('project_changed')
            entries.append({'path': relative, 'size': size, 'sha256': digest.hexdigest(),
                            'executable': bool(before.st_mode & 0o111), 'directory': False})
    entries.sort(key=lambda item: item['path'])
    return entries


def validate(entries):
    if not isinstance(entries, list) or len(entries) > MAX_FILES:
        raise ValueError('invalid_project_manifest')
    names, total = {}, 0
    for item in entries:
        if not isinstance(item, dict) or set(item) != {'path', 'size', 'sha256', 'executable', 'directory'}:
            raise ValueError('invalid_project_manifest')
        portable(item['path'])
        name = item['path'].casefold()
        if type(item['directory']) is not bool:
            raise ValueError('invalid_project_manifest')
        if name in names or any((name.startswith(old + '/') and not directory) or
                               (old.startswith(name + '/') and not item['directory']) for old, directory in names.items()):
            raise ValueError('project_case_collision')
        names[name] = item['directory']
        if type(item['size']) is not int or not 0 <= item['size'] <= MAX_FILE:
            raise ValueError('project_too_large')
        if type(item['executable']) is not bool or not isinstance(item['sha256'], str) or not re.fullmatch(r'[0-9a-f]{64}', item['sha256']):
            raise ValueError('invalid_project_manifest')
        if item['directory'] and (item['size'] != 0 or item['executable'] or item['sha256'] != hashlib.sha256(b'').hexdigest()):
            raise ValueError('invalid_project_manifest')
        total += item['size']
    if total > MAX_TOTAL:
        raise ValueError('project_too_large')
    return entries


def fingerprint(entries):
    return hashlib.sha256(json.dumps(entries, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
