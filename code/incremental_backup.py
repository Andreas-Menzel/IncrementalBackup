#!/usr/bin/env python3

#-------------------------------------------------------------------------------
# IncrementalBackup
#
# Creates incremental backups.
#
# https://github.com/Andreas-Menzel/IncrementalBackup
#-------------------------------------------------------------------------------
# @author: Andreas Menzel
# @license: MIT License
# @copyright: Copyright (c) 2022 Andreas Menzel
#-------------------------------------------------------------------------------
# TODO
# - Exception Handling rsync
# - Implement own logHandler
#   -> pass log-filename
#   -> overwrite / append
# - def send log files on error
# - gleichzeitige ausführung verhindern(?)

import logHandler

from argparse import ArgumentParser, ArgumentTypeError, SUPPRESS
from datetime import datetime
from pathlib import Path
from shutil import rmtree
from socket import getfqdn
from subprocess import run
import time


_SCRIPT_VERSION = '1.0.0'

_DATETIME_STRING_NOW = datetime.today().strftime('%Y-%m-%d_%H:%M:%S')

# Paths to the source directories and source-check-files
# [
#     {
#         'id'         : <source_identifier>, # string
#         'path'       : <path_to_source>,    # Path
#         'check_file' : <check_file>         # Path
#     }, ...
# ]
_SOURCES = None

# Default source id when using only once source and not assigning an id
_SOURCE_ID_NONE = '#NO_SOURCE_ID_SPECIFIED#'

# Path to the backup directory and destination-check-file
# {
#     'path'      : <path_to_destination>, # Path
#     'check_file': <check_file>           # Path
# }
_DESTINATION = None

# Files that must be present in _PATH_SRC / _PATH_DST
_CHECK_FILE_SRC = None
_CHECK_FILE_DST = None

_KEEP_N_BACKUPS = 0

# Files and directories to exclude
# {
#     <id_1>: [ <path_1>, ... ], ...
# }
_BACKUP_EXCLUDES = {}

# Setup logger
_PATH_LOG_FILES = Path('log-files')
_LOGGER = logHandler.getSimpleLogger(__name__,
                                    streamLogLevel=logHandler.DEBUG,
                                    fileLogLevel=logHandler.DEBUG)


# process_argparse
#
# Uses argparse to process the arguments given to the script.
#
# @return None
def process_argparse():
    global _SCRIPT_VERSION
    global _SOURCES
    global _SOURCE_ID_NONE
    global _DESTINATION
    global _KEEP_N_BACKUPS
    global _BACKUP_EXCLUDES

    def check_not_negative(argument):
        ivalue = int(argument)
        if ivalue < 0:
            raise ArgumentTypeError(f'{argument} is an invalid non-negative int value.')
        return ivalue
    
    def check_key_value_pair(argument):
        split = argument.split('#')
        if not (len(split) == 2 and len(split[0]) > 0 and len(split[1]) > 0):
            raise ArgumentTypeError(f'{argument} is an invalid key#value pair')
        return argument

    parser = ArgumentParser(description='Create incremental backups.',
                            prog='IncrementalBackup',
                            add_help=False)
    required_args = parser.add_argument_group('required arguments')
    optional_args = parser.add_argument_group('optional arguments')

    required_args.add_argument('--src',
        nargs='+',
        metavar='PATH|ID#PATH',
        help='Data directories + identifiers.',
        required=True)
    required_args.add_argument('--dst',
        help='Backup directory.',
        required=True)

    optional_args.add_argument('-h',
        '--help',
        action='help',
        default=SUPPRESS,
        help='show this help message and exit')
    optional_args.add_argument('--version',
        action='version',
        version=f'%(prog)s {_SCRIPT_VERSION}')
    optional_args.add_argument('--keep',
        default=0,
        type=check_not_negative,
        help='Number of backups to keep. 0 = no limit. Default is 0.')
    optional_args.add_argument('--exclude',
        default=[],
        nargs='+',
        metavar='PATH|ID#PATH',
        help='Paths to exclude from the backup.')
    optional_args.add_argument('--dst_fqdn',
        default='True',
        help='Add fully qualified domain name to the backup path. Default is True.')

    args = parser.parse_args()

    _SOURCES = []
    if len(args.src) == 1:
        # only one source
        tmp_id = None
        tmp_path = None

        src = args.src[0]
        if '#' in src:
            check_key_value_pair(src)
            tmp_id = src.split('#')[0]
            tmp_path = Path(src.split('#')[1])
        else:
            tmp_id = _SOURCE_ID_NONE
            tmp_path = Path(src)
        _SOURCES.append({ 'id': tmp_id, 'path': tmp_path, 'check_file': tmp_path.joinpath('.backup_src_check') })
    else:
        # multiple sources
        for src in args.src:
            check_key_value_pair(src)
            tmp_id = src.split('#')[0]
            tmp_path = Path(src.split('#')[1])
            _SOURCES.append({ 'id': tmp_id, 'path': tmp_path, 'check_file': tmp_path.joinpath('.backup_src_check') })

    tmp_dst_path = Path(args.dst)
    if args.dst_fqdn.lower() == 'true':
        tmp_dst_path = tmp_dst_path.joinpath(getfqdn())
    _DESTINATION = { 'path': tmp_dst_path, 'check_file': tmp_dst_path.joinpath('.backup_dst_check') }

    _KEEP_N_BACKUPS = args.keep

    for source in _SOURCES:
        _BACKUP_EXCLUDES[source['id']] = []
    for exclude in args.exclude:
        if '#' in exclude:
            check_key_value_pair(exclude)
            tmp_id = exclude.split('#')[0]
            tmp_path = exclude.split('#')[1]
            if not tmp_id in [source['id'] for source in _SOURCES]:
                raise ArgumentTypeError(f'Id "{tmp_id}" was not assigned to any source. Check --exclude.')
            _BACKUP_EXCLUDES[tmp_id].append(tmp_path)
        else:
            tmp_id = _SOURCE_ID_NONE
            tmp_path = exclude
            if len(_SOURCES) > 1:
                raise ArgumentTypeError(f'Exclude-path cannot be associated with any source. Assigning an id to the exclude-path is required when using multiple sources.')
            if not _SOURCES[0]['id'] == _SOURCE_ID_NONE:
                raise ArgumentTypeError(f'Please assign an ID to the exclude path.')
            _BACKUP_EXCLUDES[tmp_id].append(tmp_path)


# check_requirements
#
# Checks whether a backup can be done.
#
# @return Bool
def check_requirements():
    global _LOGGER
    global _SOURCES
    global _DESTINATION

    try:
        # Check if data directories exist
        for source in _SOURCES:
            _LOGGER.info(f'Checking if data directory for id "{source["id"]}" exists...')
            if not (source['path'].exists() and source['path'].is_dir()):
                _LOGGER.error(f'Directory does not exist: "{source["path"].absolute()}"')
                raise FileNotFoundError(f'Data directory for id "{source["id"]}" not found: "{source["path"].absolute()}"')
            else:
                _LOGGER.info('OK.')

        # Check if backup directory exists
        _LOGGER.info(f'Checking if backup directory exists...')
        if not (_DESTINATION['path'].exists() and _DESTINATION['path'].is_dir()):
            _LOGGER.error(f'Directory does not exist: "{_DESTINATION["path"].absolute()}"')
            raise FileNotFoundError(f'Backup directory not found: "{_DESTINATION["path"].absolute()}"')
        else:
            _LOGGER.info('OK.')

        # Check if source-check-files exist
        for source in _SOURCES:
            _LOGGER.info(f'Checking if source-check-file for id "{source["id"]}" exists...')
            if not (source['check_file'].exists() and source['check_file'].is_file()):
                _LOGGER.error(f'File does not exist: "{source["check_file"].absolute()}"')
                raise FileNotFoundError(f'Source-check-file for id "{source["id"]}" not found: "{source["check_file"].absolute()}"')
            else:
                _LOGGER.info('OK.')

        # Check if destination-check-file exists
        _LOGGER.info(f'Checking if destination-check-file exists...')
        if not (_DESTINATION['check_file'].exists() and _DESTINATION['check_file'].is_file()):
            _LOGGER.error(f'File does not exist: "{_DESTINATION["check_file"].absolute()}"')
            raise FileNotFoundError(f'Destination-check-file not found: "{_DESTINATION["check_file"].absolute()}"')
        else:
            _LOGGER.info('OK.')
    except FileNotFoundError:
        _LOGGER.error('WARNING: No backup will be done!')
        return False
    
    return True


# prepare_backup
#
# Deletes old backups and prepares the tmp_partial_backup folder.
#
# @return None
def prepare_backup():
    global _DESTINATION
    global _KEEP_N_BACKUPS
    global _PATH_LOG_FILES
    global _LOGGER

    # Create log-files directory
    if not _PATH_LOG_FILES.exists():
        _LOGGER.info(f'Creating log-files directory: "{_PATH_LOG_FILES.absolute()}"')
        _PATH_LOG_FILES.mkdir(parents=True, exist_ok=True)

    backup_to_tmp = _DESTINATION['path'].joinpath('tmp_partial_backup')

    # Get old backups
    paths_old_backups = [path for path in _DESTINATION['path'].iterdir() if path.is_dir()]
    paths_old_backups = [path for path in paths_old_backups if path.stem not in ['tmp_partial_backup']]
    paths_old_backups.sort()

    # Remove old backups - keep _KEEP_N_BACKUPS latest backups
    if _KEEP_N_BACKUPS > 0:
        if backup_to_tmp.exists():
            _LOGGER.warning('Last backup was not finished. Continuing.')
            _KEEP_N_BACKUPS -= 1
        backups_to_remove = paths_old_backups[:-_KEEP_N_BACKUPS]
        paths_old_backups = paths_old_backups[len(backups_to_remove):]
        for backup in backups_to_remove:
            _LOGGER.info(f'Deleting old backup: "{backup.absolute()}"')
            rmtree(backup)
            _LOGGER.info(f'Done.')

    # Create tmp_partial_backup folder
    if not backup_to_tmp.exists():
        if _KEEP_N_BACKUPS > 0 and len(paths_old_backups) == _KEEP_N_BACKUPS:
            backup_to_recycle = min(paths_old_backups)
            _LOGGER.info(f'Recycling old backup: "{backup_to_recycle.absolute()}"')
            backup_to_recycle.rename(_DESTINATION['path'].joinpath('tmp_partial_backup'))
        else:
            backup_to_tmp.mkdir(parents=True, exist_ok=True)


# do_backup
#
# Creates the backup.
#
# @return None
def do_backup():
    global _DATETIME_STRING_NOW
    global _SOURCES
    global _SOURCE_ID_NONE
    global _DESTINATION
    global _BACKUP_EXCLUDES
    global _PATH_LOG_FILES
    global _LOGGER

    backup_to_tmp = _DESTINATION['path'].joinpath('tmp_partial_backup')

    # Get path to latest backup for --link-dest (higher-layer)
    path_latest_backup = None
    _LOGGER.info('Looking for latest backup for --link-dest...')
    
    paths_old_backups = [path for path in _DESTINATION['path'].iterdir() if path.is_dir()]
    paths_old_backups = [path for path in paths_old_backups if path.stem not in ['tmp_partial_backup']]
    paths_old_backups.sort()
    if not paths_old_backups == []:
        path_latest_backup = max(paths_old_backups)
        _LOGGER.info(f'Backup found: "{path_latest_backup.absolute()}"')
    else:
        _LOGGER.info('No backup found.')

    # Path of the new incremental backup (higher-layer)
    path_backup = _DESTINATION['path'].joinpath(_DATETIME_STRING_NOW)
    _LOGGER.info(f'Backup will be created on "{path_backup.absolute()}"')
    
    for source in _SOURCES:
        # Create link-dest string
        rsync_cmd_arg_linkDest = ' '
        if not path_latest_backup is None:
            if source['id'] == _SOURCE_ID_NONE:
                rsync_cmd_arg_linkDest = f'--link-dest "../{path_latest_backup.stem}" '
            else:
                rsync_cmd_arg_linkDest = f'--link-dest "../../{path_latest_backup.stem}/{source["id"]}" '

        # Create exclude string
        rsync_cmd_arg_exclude = ' '
        if len(_BACKUP_EXCLUDES[source['id']]) > 0:
            tmp_string_list = ','.join('"' + item + '"' for item in _BACKUP_EXCLUDES[source['id']])
            rsync_cmd_arg_exclude = f'--exclude={{{tmp_string_list}}} '
        
        # Create log-file string
        rsync_cmd_arg_log_file = f'--log-file "{_PATH_LOG_FILES.absolute()}/{_DATETIME_STRING_NOW}_{source["id"]}_rsync.log" '

        # Create dst-path string
        tmp_dst = backup_to_tmp
        if not source['id'] == _SOURCE_ID_NONE:
            tmp_dst = tmp_dst.joinpath(source['id'])
        rsync_dst = tmp_dst.absolute()

        rsync_cmd = f'rsync -a --delete {rsync_cmd_arg_exclude}{rsync_cmd_arg_linkDest}"{source["path"].absolute()}/" "{rsync_dst}"'
        rsync_cmd += f' {rsync_cmd_arg_log_file}'

        _LOGGER.info('Executing the following command:')
        _LOGGER.info(f'{rsync_cmd}')

        run(rsync_cmd, shell=True)

    _LOGGER.info(f'Renaming tmp_partial_backup folder to "{path_backup.stem}".')
    backup_to_tmp.rename(path_backup)


def main():
    global _LOGGER

    _LOGGER.info(f'IncrementalBackup started at {datetime.today().strftime("%Y-%m-%d %H:%M:%S")}')
    process_argparse()
    if check_requirements():
        prepare_backup()
        do_backup()
    _LOGGER.info(f'IncrementalBackup finished at {datetime.today().strftime("%Y-%m-%d %H:%M:%S")}')


if __name__ == '__main__':
    main()
