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
#
# - def send log files on error
# - --restore

import logHandler

from argparse import ArgumentParser, ArgumentTypeError, SUPPRESS, RawDescriptionHelpFormatter
from datetime import datetime
from pathlib import Path
from shutil import rmtree
from socket import getfqdn
from subprocess import run
import time

_SCRIPT_VERSION = '1.0.0'

# Structure of some important variables:
#
# variable: sources
# Paths to the source directories and source-check-files
# [
#     {
#         'id'         : <source_identifier>, # string
#         'path'       : <path_to_source>,    # Path
#         'check_file' : <check_file>         # Path
#     }, ...
# ]
#
# variable: source_id_none
# Default source id when using only once source and not assigning an id
#
# variable: destination
# Path to the backup directory and destination-check-file
# {
#     'path'      : <path_to_destination>, # Path
#     'check_file': <check_file>           # Path
# }
#
# variable: backup_excludes
# Files and directories to exclude
# {
#     <id_1>: [ <path_1>, ... ], ...
# }


# _process_argparse
#
# Uses argparse to process the arguments given to the script.
#
# @param str    source_id_none
#
# @return <err_code>, <sources>, <destination>, <keep_n_backups>, <backup_excludes>
#
# TODO: log error and return err_code instead of raise
def _process_argparse(source_id_none = '#DEFAULT_SOURCE_ID#'):
    global _SCRIPT_VERSION

    def check_not_negative(argument):
        ivalue = int(argument)
        if ivalue < 0:
            raise ArgumentTypeError(f'{argument} is an invalid non-negative int value.')
        return ivalue
    
    parser_description = '''
%(prog)s is a wrapper for rsync and provides an easy interface for a safe and efficient backup process.

The script will perform the following checks before executing rsync:
- Do the source- and destination- directories exist?
- Do the source- and destination- check-files exist? (to ensure that the provided paths are correct)

%(prog)s will execute rsync with the --link-dest argument to create hard-links for files that did not change.
When using the --keep option, %(prog)s will also recycle old backups to reduce the runtime.

Have a look at the README.md file and the Github repository for more information.
https://github.com/Andreas-Menzel/IncrementalBackup
    '''
    
    parser_epilog = '''
Examples:

    Basic backup:
        python3 %(prog)s --scr /data --dst /backup
    
    ... with excludes:
        python3 %(prog)s --src /data --dst /backup --exclude /data/exclude_me/ /data/me_too.md

    Backup multiple sources:
        python3 %(prog)s --scr DATA#/data WWW#/var/www --dst /backup

    ... with excludes:
        python3 %(prog)s --src DATA#/data WWW#/var/www --dst /backup --exclude DATA#/data/exclude_me/ WWW#/var/www/me_too.md        
    '''
    parser = ArgumentParser(description=parser_description,
                            prog='IncrementalBackup.py',
                            add_help=False,
                            epilog=parser_epilog,
                            formatter_class=RawDescriptionHelpFormatter)
    required_args = parser.add_argument_group('required arguments')
    optional_args = parser.add_argument_group('optional arguments')

    required_args.add_argument('--src',
        nargs='+',
        metavar='<path>|<id>#<path>',
        help='Data directories (+ identifiers).',
        required=True)
    required_args.add_argument('--dst',
        metavar='<path>',
        help='Backup directory.',
        required=True)

    optional_args.add_argument('-h',
        '--help',
        action='help',
        default=SUPPRESS,
        help='Show this help message and exit')
    optional_args.add_argument('--version',
        action='version',
        version=f'%(prog)s {_SCRIPT_VERSION}',
        help='Show the program\'s version number and exit')
    optional_args.add_argument('--keep',
        metavar='<pos_num>',
        default=0,
        type=check_not_negative,
        help='Number of backups to keep. 0 = no limit (default). NOTE: THIS WILL DELETE ALL BUT THE LAST <pos_num> BACKUPS!')
    optional_args.add_argument('--exclude',
        metavar='<path>|<id>#<path>',
        default=[],
        nargs='+',
        help='Paths (+ source identifiers) to exclude from the backup.')
    optional_args.add_argument('--dst_fqdn',
        metavar='True|False',
        default='True',
        help='Add fully qualified domain name to the backup path. Default is True.')

    args = parser.parse_args()

    if args.dst_fqdn.lower() == 'true':
        args.dst_fqdn = True
    else:
        args.dst_fqdn = False
    
    return process_arguments(args.src, args.dst, args.keep, args.exclude, args.dst_fqdn, source_id_none)


# process_arguments
#
# Checks if the given arguments are valid and returns the processed variables.
#
# @param str | [str]    _src
# @param str            _dst
# @param int            _keep
# @param [str]          _exclude
# @param bool           _dst_fqdn
# @param str            source_id_none
#
# @return <err_code>, <sources>, <destination>, <keep_n_backups>, <backup_excludes>
#
# @note See comments at the top of this file for more information on the
#           structure of the variables.
#
# TODO: return err_code instead of raise
def process_arguments(_src, _dst, _keep, _exclude, _dst_fqdn, source_id_none = '#DEFAULT_SOURCE_ID#'):
    def check_key_value_pair(argument):
        split = argument.split('#')
        if not (len(split) == 2 and len(split[0]) > 0 and len(split[1]) > 0):
            raise ArgumentTypeError(f'{argument} is an invalid key#value pair')
        return argument
    
    # sources
    sources = []
    if len(_src) == 1:
        # only one source
        tmp_id = None
        tmp_path = None

        src = _src[0]
        if '#' in src:
            check_key_value_pair(src)
            tmp_id = src.split('#')[0]
            tmp_path = Path(src.split('#')[1])
        else:
            tmp_id = source_id_none
            tmp_path = Path(src)
        sources.append({ 'id': tmp_id, 'path': tmp_path, 'check_file': tmp_path.joinpath('.backup_src_check') })
    else:
        # multiple sources
        for src in _src:
            check_key_value_pair(src)
            tmp_id = src.split('#')[0]
            tmp_path = Path(src.split('#')[1])
            sources.append({ 'id': tmp_id, 'path': tmp_path, 'check_file': tmp_path.joinpath('.backup_src_check') })
    
    # destination
    tmp_dst_path = Path(_dst)
    if _dst_fqdn:
        tmp_dst_path = tmp_dst_path.joinpath(getfqdn())
    destination = { 'path': tmp_dst_path, 'check_file': tmp_dst_path.joinpath('.backup_dst_check') }
    
    # keep_n_backups
    keep_n_backups = _keep
    
    # backup_excludes
    backup_excludes = {}
    for source in sources:
        backup_excludes[source['id']] = []
    for exclude in _exclude:
        if '#' in exclude:
            check_key_value_pair(exclude)
            tmp_id = exclude.split('#')[0]
            tmp_path = exclude.split('#')[1]
            if not tmp_id in [source['id'] for source in sources]:
                raise ArgumentTypeError(f'Id "{tmp_id}" was not assigned to any source. Check --exclude.')
            backup_excludes[tmp_id].append(tmp_path)
        else:
            tmp_id = source_id_none
            tmp_path = exclude
            if len(sources) > 1:
                raise ArgumentTypeError(f'Exclude-path cannot be associated with any source. Assigning an id to the exclude-path is required when using multiple sources.')
            if not sources[0]['id'] == source_id_none:
                raise ArgumentTypeError(f'Please assign an ID to the exclude path.')
            backup_excludes[tmp_id].append(tmp_path)
    
    return (0, sources, destination, keep_n_backups, backup_excludes)


# _check_requirements
#
# Checks whether data- & backup directories and check-files exist.
#
# @param dict   sources
# @param dict   destination
# @param        logger
#
# @return <err_code>
#
# @note err_code 0: OK
# @note err_code 1: one or more data directories not found
# @note err_code 2: backup directory not found
# @note err_code 3: one or more source-check-files not found
# @note err_code 4: destination-check-file not found
def _check_requirements(sources, destination, logger):
    err_code = 0
    
    try:
        # Check if data directories exist
        for source in sources:
            logger.info(f'Checking if data directory for id "{source["id"]}" exists...')
            if not (source['path'].exists() and source['path'].is_dir()):
                logger.error(f'Directory does not exist: "{source["path"].absolute()}"')
                err_code = 1
                raise FileNotFoundError()
            else:
                logger.info('OK.')

        # Check if backup directory exists
        logger.info(f'Checking if backup directory exists...')
        if not (destination['path'].exists() and destination['path'].is_dir()):
            logger.error(f'Directory does not exist: "{destination["path"].absolute()}"')
            err_code = 2
            raise FileNotFoundError()
        else:
            logger.info('OK.')

        # Check if source-check-files exist
        for source in sources:
            logger.info(f'Checking if source-check-file for id "{source["id"]}" exists...')
            if not (source['check_file'].exists() and source['check_file'].is_file()):
                logger.error(f'File does not exist: "{source["check_file"].absolute()}"')
                err_code = 3
                raise FileNotFoundError()
            else:
                logger.info('OK.')

        # Check if destination-check-file exists
        logger.info(f'Checking if destination-check-file exists...')
        if not (destination['check_file'].exists() and destination['check_file'].is_file()):
            logger.error(f'File does not exist: "{destination["check_file"].absolute()}"')
            err_code = 4
            raise FileNotFoundError()
        else:
            logger.info('OK.')
    
    except FileNotFoundError:
        logger.error('WARNING: No backup will be done!')
    
    return err_code


# _prepare_backup
#
# Deletes old backups and prepares the tmp_partial_backup folder.
#
# @param dict   destination
# @param int    keep_n_backups
# @param Path   path_log_files
# @param        logger
#
# @return <err_code>
#
# @note err_code 0: OK
def _prepare_backup(destination, keep_n_backups, path_log_files, logger):
    # Create log-files directory
    if not path_log_files.exists():
        logger.info(f'Creating log-files directory: "{path_log_files.absolute()}"')
        path_log_files.mkdir(parents=True)

    backup_to_tmp = destination['path'].joinpath('tmp_partial_backup')

    # Get old backups
    paths_old_backups = [path for path in destination['path'].iterdir() if path.is_dir()]
    paths_old_backups = [path for path in paths_old_backups if path.stem not in ['tmp_partial_backup']]
    paths_old_backups.sort()

    # Remove old backups - keep keep_n_backups latest backups
    if keep_n_backups > 0:
        if backup_to_tmp.exists():
            logger.warning('Last backup was not finished. Continuing.')
            keep_n_backups -= 1
        backups_to_remove = paths_old_backups[:-keep_n_backups]
        paths_old_backups = paths_old_backups[len(backups_to_remove):]
        for backup in backups_to_remove:
            logger.info(f'Deleting old backup: "{backup.absolute()}"')
            rmtree(backup)
            logger.info(f'Done.')

    # Create tmp_partial_backup folder
    if not backup_to_tmp.exists():
        if keep_n_backups > 0 and len(paths_old_backups) == keep_n_backups:
            backup_to_recycle = min(paths_old_backups)
            logger.info(f'Recycling old backup: "{backup_to_recycle.absolute()}"')
            backup_to_recycle.rename(destination['path'].joinpath('tmp_partial_backup'))
        else:
            backup_to_tmp.mkdir(parents=True)

    return 0


# _do_backup
#
# Creates the backup.
#
# @param dict   sources
# @param str    source_id_none
# @param dict   destination
# @param dict   backup_excludes
# @param str    datetime_string_now
# @param Path   path_log_files
# @param        logger
#
# @return <err_code>
def _do_backup(sources, source_id_none, destination, backup_excludes,
              datetime_string_now, path_log_files, logger):
    backup_to_tmp = destination['path'].joinpath('tmp_partial_backup')

    # Get path to latest backup for --link-dest (higher-layer)
    path_latest_backup = None
    logger.info('Looking for latest backup for --link-dest...')
    
    paths_old_backups = [path for path in destination['path'].iterdir() if path.is_dir()]
    paths_old_backups = [path for path in paths_old_backups if path.stem not in ['tmp_partial_backup']]
    paths_old_backups.sort()
    if not paths_old_backups == []:
        path_latest_backup = max(paths_old_backups)
        logger.info(f'Potential backup found: "{path_latest_backup.absolute()}"')
    else:
        logger.info('No backup found.')

    # Path of the new incremental backup (higher-layer)
    path_backup = destination['path'].joinpath(datetime_string_now)
    logger.info(f'Backup will be created on "{path_backup.absolute()}"')
    
    for source in sources:
        # Create link-dest string
        rsync_cmd_arg_linkDest = ' '
        if not path_latest_backup is None:
            tmp_link_dest_path = None
            tmp_link_dest_go_up = '../'
            if source['id'] == source_id_none:
                tmp_link_dest_path = path_latest_backup
            else:
                tmp_link_dest_go_up = '../../'
                tmp_link_dest_path = path_latest_backup.joinpath(source['id'])
            rsync_cmd_arg_linkDest = f'--link-dest "{tmp_link_dest_go_up}{tmp_link_dest_path.relative_to(destination["path"])}" '
            if not tmp_link_dest_path.exists():
                rsync_cmd_arg_linkDest = ' '
                logger.warning(f'Cannot use "--link-dest {tmp_link_dest_go_up}{tmp_link_dest_path.relative_to(destination["path"])}".')
                logger.warning(f'↳ Maybe the source id "{source["id"]}" changed?')

        # Create exclude string
        rsync_cmd_arg_exclude = ' '
        if len(backup_excludes[source['id']]) > 0:
            tmp_string_list = ','.join('"' + item + '"' for item in backup_excludes[source['id']])
            rsync_cmd_arg_exclude = f'--exclude={{{tmp_string_list}}} '
        
        # Create log-file string
        tmp_logfile_filename = ''
        if not source['id'] == source_id_none:
            tmp_logfile_filename = f'{datetime_string_now}_{source["id"]}_rsync.log'
        else:
            tmp_logfile_filename = f'{datetime_string_now}_rsync.log'
        rsync_cmd_arg_log_file = f'--log-file "{path_log_files.joinpath(tmp_logfile_filename).absolute()}" '

        # Create dst-path string
        tmp_dst = backup_to_tmp
        if not source['id'] == source_id_none:
            tmp_dst = tmp_dst.joinpath(source['id'])
        rsync_dst = tmp_dst.absolute()

        rsync_cmd = f'rsync -a --delete {rsync_cmd_arg_exclude}{rsync_cmd_arg_linkDest}"{source["path"].absolute()}/" "{rsync_dst}"'
        rsync_cmd += f' {rsync_cmd_arg_log_file}'

        logger.info('Executing the following command:')
        logger.info(f'{rsync_cmd}')

        run(rsync_cmd, shell=True)

    logger.info(f'Renaming tmp_partial_backup folder to "{path_backup.stem}".')
    backup_to_tmp.rename(path_backup)

    return 0


# backup
#
# Start a backup.
#
# @param dict   arguments
# @param Path   path_log_files
# @param        logger
#
# @return <err_code>
#
# @note err_code 0: OK
# @note err_code 1: An error occured
def backup(arguments = None, path_log_files = None, logger = None):
    datetime_string_now = datetime.today().strftime('%Y-%m-%d_%H:%M:%S')

    if path_log_files is None:
        path_log_files = Path('log-files')
    if not path_log_files.exists():
        path_log_files.mkdir(parents=True)

    if logger is None:
        logger = logHandler.get_logger(name=__name__,
                                        stream_logger={ 'log_level': logHandler.DEBUG, 'stream': None },
                                        file_logger={ 'log_level': logHandler.DEBUG,
                                                      'filename': path_log_files.joinpath(f'{datetime_string_now}_incremental_backup.log').absolute(),
                                                      'write_mode': 'a' },
                                        mode=None)

    logger.info(f'IncrementalBackup started at {datetime.today().strftime("%Y-%m-%d %H:%M:%S")}')
    
    try:
        # Process arguments
        err_code = None
        sources = None
        destination = None
        keep_n_backups = None
        backup_excludes = None

        if arguments is None:
            err_code, sources, destination, keep_n_backups, backup_excludes = _process_argparse('#NO_SOURCE_ID_SPECIFIED#')
        else:
            _src = arguments['src']
            _dst = arguments['dst']
            _keep = arguments['keep']
            _exclude = arguments['exclude']
            _dst_fqdn = arguments['dst_fqdn']
            err_code, sources, destination, keep_n_backups, backup_excludes = _process_arguments(_src, _dst, _keep,
                                                                                                 _exclude, _dst_fqdn,
                                                                                                 '#NO_SOURCE_ID_SPECIFIED#')
        if err_code != 0:
            raise Exception()
        
        # Check requirements
        err_code = _check_requirements(sources, destination, logger)
        if err_code != 0:
            raise Exception()
        
        # Prepare backup
        err_code = _prepare_backup(destination, keep_n_backups, path_log_files, logger)
        if err_code != 0:
            raise Exception()
        
        # Do backup
        err_code = _do_backup(sources, '#NO_SOURCE_ID_SPECIFIED#', destination, backup_excludes, datetime_string_now, path_log_files, logger)
        if err_code != 0:
            raise Exception()
    except Exception:
        logger.error(f'An error occured. Terminating backup process at {datetime.today().strftime("%Y-%m-%d %H:%M:%S")}.')
        return 1

    logger.info(f'IncrementalBackup finished at {datetime.today().strftime("%Y-%m-%d %H:%M:%S")}')


if __name__ == '__main__':
    backup()
