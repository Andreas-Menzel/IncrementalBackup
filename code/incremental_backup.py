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
# - upload to Github
# - Exception Handling rsync

import logHandler

import argparse
from datetime import datetime
from pathlib import Path
from shutil import rmtree
from socket import getfqdn
from subprocess import run
import time


script_version = '1.0.0'

# Setup argument parser
def check_not_negative(value):
    ivalue = int(value)
    if ivalue < 0:
        raise argparse.ArgumentTypeError("%s is an invalid non-negative int value" % value)
    return ivalue

parser = argparse.ArgumentParser(description='Create incremental backups.', prog='IncrementalBackup')
parser.add_argument('--version', action='version', version='%(prog)s ' + script_version)
parser.add_argument('--keep',
    default=0,
    type=check_not_negative,
    help='Number of backups to keep. 0 = no limit')
args = parser.parse_args()

# Data directory
path_src = Path('tmp/data')
# Backup directory
path_dst = Path('tmp/backup').joinpath(getfqdn())

# Files that must be present in path_src / path_dst
check_file_src = path_src.joinpath('.backup_src_check')
check_file_dst = path_dst.joinpath('.backup_dst_check')

backup_excludes = [f'{path_src.absolute()}/.Trash-1000', f'{path_src.absolute()}/lost+found']

datetime_string_now = datetime.today().strftime('%Y-%m-%d_%H:%M:%S')

# Setup logger
path_log_files = Path('log-files')
logger = logHandler.getSimpleLogger(__name__,
                                    streamLogLevel=logHandler.DEBUG,
                                    fileLogLevel=logHandler.DEBUG)


# check_requirements
#
# Checks whether a backup can be done.
#
# @return Bool
def check_requirements():
    global logger
    global path_src
    global path_dst
    global check_file_src
    global check_file_dst

    try:
        # Check if path_src exists
        logger.info(f'Checking if path_src exists...')
        if not (path_src.exists() and path_src.is_dir()):
            logger.error(f'Directory does not exist: "{path_src.absolute()}"')
            raise FileNotFoundError(f'path_src ({path_src.absolute()}) not found.')
        else:
            logger.info('OK.')

        # Check if path_dst exists
        logger.info(f'Checking if path_dst exists...')
        if not (path_dst.exists() and path_dst.is_dir()):
            logger.error(f'Directory does not exist: "{path_dst.absolute()}"')
            raise FileNotFoundError(f'path_dst ({path_dst.absolute()}) not found.')
        else:
            logger.info('OK.')

        # Check if check_file_src exists
        logger.info(f'Checking if check_file_src exists...')
        if not (check_file_src.exists() and check_file_src.is_file()):
            logger.error(f'File does not exist: "{check_file_src.absolute()}"')
            raise FileNotFoundError(f'check_file_src ({check_file_src.absolute()}) not found.')
        else:
            logger.info('OK.')

        # Check if check_file_dst exists
        logger.info(f'Checking if check_file_dst exists...')
        if not (check_file_dst.exists() and check_file_dst.is_file()):
            logger.error(f'File does not exist: "{check_file_dst.absolute()}"')
            raise FileNotFoundError(f'check_file_dst ({check_file_dst.absolute()}) not found.')
        else:
            logger.info('OK.')
    except FileNotFoundError:
        logger.error('WARNING: No backup will be done!')
        return False
    
    return True


# prepare_backup
#
# Deletes old backups and prepares the tmp_partial_backup folder.
#
# @return None
def prepare_backup():
    global logger
    global args
    global path_dst
    global path_log_files

    # Create log-files directory
    if not path_log_files.exists():
        logger.info(f'Creating log-files directory: "{path_log_files.absolute()}"')
        path_log_files.mkdir(parents=True, exist_ok=True)

    backup_to_tmp = path_dst.joinpath('tmp_partial_backup')

    # Get old backups
    paths_old_backups = [path for path in path_dst.iterdir() if path.is_dir()]
    paths_old_backups = [path for path in paths_old_backups if path.stem not in ['tmp_partial_backup']]
    paths_old_backups.sort()

    # Remove old backups - keep args.keep latest backups
    if args.keep > 0:
        keep_n_backups = args.keep
        if backup_to_tmp.exists():
            logger.warn('Last backup was not finished. Continuing.')
            keep_n_backups -= 1
        backups_to_remove = paths_old_backups[:-keep_n_backups]
        paths_old_backups = paths_old_backups[len(backups_to_remove):]
        for backup in backups_to_remove:
            logger.info(f'Deleting old backup: "{backup.absolute()}"')
            rmtree(backup)
            logger.info(f'Done.')

    # Create tmp_partial_backup folder
    if not backup_to_tmp.exists():
        if len(paths_old_backups) == args.keep:
            backup_to_recycle = min(paths_old_backups)
            logger.info(f'Recycling old backup: "{backup_to_recycle.absolute()}"')
            backup_to_recycle.rename(path_dst.joinpath('tmp_partial_backup'))
        else:
            backup_to_tmp.mkdir(parents=True, exist_ok=True)


# do_backup
#
# Creates the backup.
#
# @return None
def do_backup():
    global logger
    global path_src
    global path_dst
    global backup_excludes
    global datetime_string_now
    global path_log_files

    backup_to_tmp = path_dst.joinpath('tmp_partial_backup')

    # Get latest backup for --link-dest
    path_latest_backup = None
    logger.info('Looking for latest backup for --link-dest...')
    
    paths_old_backups = [path for path in path_dst.iterdir() if path.is_dir()]
    paths_old_backups = [path for path in paths_old_backups if path.stem not in ['tmp_partial_backup']]
    paths_old_backups.sort()
    if not paths_old_backups == []:
        path_latest_backup = max(paths_old_backups)
        logger.info(f'Backup found: "{path_latest_backup.absolute()}"')
    else:
        logger.info('No backup found.')

    # Path of the new incremental backup
    path_backup = path_dst.joinpath(datetime_string_now)
    logger.info(f'Backup will be done to "{path_backup.absolute()}"')
    
    # Create link-dest string
    rsync_cmd_arg_linkDest = ' '
    if not path_latest_backup is None:
        rsync_cmd_arg_linkDest = f'--link-dest "../{path_latest_backup.stem}" '

    # Create exclude string
    rsync_cmd_arg_exclude = ' '
    if len(backup_excludes) > 0:
        tmp_string_list = ','.join('"' + item + '"' for item in backup_excludes)
        rsync_cmd_arg_exclude = f'--exclude={{{tmp_string_list}}} '
    
    # Create log-file string
    rsync_cmd_arg_log_file = f'--log-file "{path_log_files.absolute()}/{datetime_string_now}_rsync.log" '

    rsync_cmd = f'rsync -a --delete {rsync_cmd_arg_exclude}{rsync_cmd_arg_linkDest}"{path_src.absolute()}/" "{backup_to_tmp}"'
    rsync_cmd += f' {rsync_cmd_arg_log_file}'

    logger.info('Executing the following command:')
    logger.info(f'{rsync_cmd}')

    run(rsync_cmd, shell=True)

    logger.info(f'Renaming tmp_partial_backup folder to "{path_backup.stem}".')
    backup_to_tmp.rename(path_backup)


def main():
    global logger

    logger.info(f'IncrementalBackup started at {datetime.today().strftime("%Y-%m-%d %H:%M:%S")}')
    if check_requirements():
        prepare_backup()
        do_backup()
    logger.info(f'IncrementalBackup finished at {datetime.today().strftime("%Y-%m-%d %H:%M:%S")}')


if __name__ == '__main__':
    main()