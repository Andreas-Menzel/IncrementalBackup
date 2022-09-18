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

import logHandler

from argparse import ArgumentParser, SUPPRESS
from datetime import datetime
from pathlib import Path
from shutil import rmtree
from socket import getfqdn
from subprocess import run
import time


_SCRIPT_VERSION = '1.0.0'

_DATETIME_STRING_NOW = datetime.today().strftime('%Y-%m-%d_%H:%M:%S')

# Data and backup directory
_PATH_SRC = None
_PATH_DST = None

# Files that must be present in _PATH_SRC / _PATH_DST
_CHECK_FILE_SRC = None
_CHECK_FILE_DST = None

_KEEP_N_BACKUPS = 0

_BACKUP_EXCLUDES = []

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
    global _PATH_SRC
    global _PATH_DST
    global _CHECK_FILE_SRC
    global _CHECK_FILE_DST
    global _KEEP_N_BACKUPS
    global _BACKUP_EXCLUDES

    def check_not_negative(value):
        ivalue = int(value)
        if ivalue < 0:
            raise argparse.ArgumentTypeError("%s is an invalid non-negative int value" % value)
        return ivalue

    parser = ArgumentParser(description='Create incremental backups.',
                            prog='IncrementalBackup',
                            add_help=False)
    required_args = parser.add_argument_group('required arguments')
    optional_args = parser.add_argument_group('optional arguments')

    required_args.add_argument('--src',
        help='Data directory.',
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
        help='Paths to exclude from the backup.')
    optional_args.add_argument('--dst_fqdn',
        default='True',
        help='Add fully qualified domain name to the backup path. Default is True.')

    args = parser.parse_args()

    _PATH_SRC = Path(args.src)
    _PATH_DST = Path(args.dst)
    
    if args.dst_fqdn.lower() == 'true':
        _PATH_DST = _PATH_DST.joinpath(getfqdn())

    _CHECK_FILE_SRC = _PATH_SRC.joinpath('.backup_src_check')
    _CHECK_FILE_DST = _PATH_DST.joinpath('.backup_dst_check')

    _KEEP_N_BACKUPS = args.keep
    _BACKUP_EXCLUDES = args.exclude


# check_requirements
#
# Checks whether a backup can be done.
#
# @return Bool
def check_requirements():
    global _LOGGER
    global _PATH_SRC
    global _PATH_DST
    global _CHECK_FILE_SRC
    global _CHECK_FILE_DST

    try:
        # Check if _PATH_SRC exists
        _LOGGER.info(f'Checking if data directory exists...')
        if not (_PATH_SRC.exists() and _PATH_SRC.is_dir()):
            _LOGGER.error(f'Directory does not exist: "{_PATH_SRC.absolute()}"')
            raise FileNotFoundError(f'_PATH_SRC ({_PATH_SRC.absolute()}) not found.')
        else:
            _LOGGER.info('OK.')

        # Check if _PATH_DST exists
        _LOGGER.info(f'Checking if backup directory exists...')
        if not (_PATH_DST.exists() and _PATH_DST.is_dir()):
            _LOGGER.error(f'Directory does not exist: "{_PATH_DST.absolute()}"')
            raise FileNotFoundError(f'_PATH_DST ({_PATH_DST.absolute()}) not found.')
        else:
            _LOGGER.info('OK.')

        # Check if _CHECK_FILE_SRC exists
        _LOGGER.info(f'Checking if source-check-file exists...')
        if not (_CHECK_FILE_SRC.exists() and _CHECK_FILE_SRC.is_file()):
            _LOGGER.error(f'File does not exist: "{_CHECK_FILE_SRC.absolute()}"')
            raise FileNotFoundError(f'_CHECK_FILE_SRC ({_CHECK_FILE_SRC.absolute()}) not found.')
        else:
            _LOGGER.info('OK.')

        # Check if _CHECK_FILE_DST exists
        _LOGGER.info(f'Checking if destination-check-file exists...')
        if not (_CHECK_FILE_DST.exists() and _CHECK_FILE_DST.is_file()):
            _LOGGER.error(f'File does not exist: "{_CHECK_FILE_DST.absolute()}"')
            raise FileNotFoundError(f'_CHECK_FILE_DST ({_CHECK_FILE_DST.absolute()}) not found.')
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
    global _PATH_DST
    global _KEEP_N_BACKUPS
    global _PATH_LOG_FILES
    global _LOGGER

    # Create log-files directory
    if not _PATH_LOG_FILES.exists():
        _LOGGER.info(f'Creating log-files directory: "{_PATH_LOG_FILES.absolute()}"')
        _PATH_LOG_FILES.mkdir(parents=True, exist_ok=True)

    backup_to_tmp = _PATH_DST.joinpath('tmp_partial_backup')

    # Get old backups
    paths_old_backups = [path for path in _PATH_DST.iterdir() if path.is_dir()]
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
            backup_to_recycle.rename(_PATH_DST.joinpath('tmp_partial_backup'))
        else:
            backup_to_tmp.mkdir(parents=True, exist_ok=True)


# do_backup
#
# Creates the backup.
#
# @return None
def do_backup():
    global _DATETIME_STRING_NOW
    global _PATH_SRC
    global _PATH_DST
    global _BACKUP_EXCLUDES
    global _PATH_LOG_FILES
    global _LOGGER

    backup_to_tmp = _PATH_DST.joinpath('tmp_partial_backup')

    # Get latest backup for --link-dest
    path_latest_backup = None
    _LOGGER.info('Looking for latest backup for --link-dest...')
    
    paths_old_backups = [path for path in _PATH_DST.iterdir() if path.is_dir()]
    paths_old_backups = [path for path in paths_old_backups if path.stem not in ['tmp_partial_backup']]
    paths_old_backups.sort()
    if not paths_old_backups == []:
        path_latest_backup = max(paths_old_backups)
        _LOGGER.info(f'Backup found: "{path_latest_backup.absolute()}"')
    else:
        _LOGGER.info('No backup found.')

    # Path of the new incremental backup
    path_backup = _PATH_DST.joinpath(_DATETIME_STRING_NOW)
    _LOGGER.info(f'Backup will be done to "{path_backup.absolute()}"')
    
    # Create link-dest string
    rsync_cmd_arg_linkDest = ' '
    if not path_latest_backup is None:
        rsync_cmd_arg_linkDest = f'--link-dest "../{path_latest_backup.stem}" '

    # Create exclude string
    rsync_cmd_arg_exclude = ' '
    if len(_BACKUP_EXCLUDES) > 0:
        tmp_string_list = ','.join('"' + item + '"' for item in _BACKUP_EXCLUDES)
        rsync_cmd_arg_exclude = f'--exclude={{{tmp_string_list}}} '
    
    # Create log-file string
    rsync_cmd_arg_log_file = f'--log-file "{_PATH_LOG_FILES.absolute()}/{_DATETIME_STRING_NOW}_rsync.log" '

    rsync_cmd = f'rsync -a --delete {rsync_cmd_arg_exclude}{rsync_cmd_arg_linkDest}"{_PATH_SRC.absolute()}/" "{backup_to_tmp}"'
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
