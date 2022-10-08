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
#
# Evtl. Probleme:
# - Log-Datei nicht im richtigen Ordner

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
# @param str    _source_id_none
#
# @return (<err_code>, <sources>, <destination>, <keep_n_backups>,
#          <backup_excludes>, <path_log_files>, <path_log_summary>)
#
# @note See comments at the top of this file for more information on the
#           structure of the variables.
#
# TODO: log error and return err_code (1x) instead of raise
def _process_argparse(_source_id_none = '#DEFAULT_SOURCE_ID#'):
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
        help='Format: <path>|<id>#<path>. Data directories (+ identifiers).',
        required=True)
    required_args.add_argument('--dst',
        help='Format: <path>. Backup directory.',
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
        default=0,
        type=check_not_negative,
        help='Number of backups to keep. 0 = no limit (default). NOTE: THIS WILL DELETE ALL BUT THE LAST <KEEP> BACKUPS!')
    optional_args.add_argument('--exclude',
        default=[],
        nargs='+',
        help='Format: <path>|<id>#<path>. Paths (+ source identifiers) to exclude from the backup.')
    optional_args.add_argument('--dst_fqdn',
        default='True',
        help='Format: "True"|"False". Add fully qualified domain name to the backup path. Default is True.')
    optional_args.add_argument('--path_log_files',
        default='log-files',
        help='Format: <path>. Path to the directory containing the log-files.')
    optional_args.add_argument('--log_summary',
        default=None,
        help='Format: <path>. Path to a file where the log-files will be listed.')

    args = parser.parse_args()

    if (args.dst_fqdn.lower() == 'true' or args.dst_fqdn == '1'):
        args.dst_fqdn = True
    else:
        args.dst_fqdn = False
    
    return process_arguments(_src=args.src, _dst=args.dst, _keep=args.keep,
                             _exclude=args.exclude, _dst_fqdn=args.dst_fqdn,
                             _path_log_files=args.path_log_files,
                             _path_log_summary=args.log_summary,
                             _source_id_none=_source_id_none)


# process_arguments
#
# Checks if the given arguments are valid and returns the processed variables.
#
# @param [str]          _src
# @param str            _dst
# @param int            _keep
# @param [str]          _exclude
# @param bool           _dst_fqdn
# @param str            _path_log_files
# @param str            _path_log_summary
# @param str            _source_id_none
#
# @return (<err_code>, <sources>, <destination>, <keep_n_backups>,
#          <backup_excludes>, <path_log_files>, <path_log_summary>)
#
# @note See comments at the top of this file for more information on the
#           structure of the variables.
#
# TODO: return err_code (2x) instead of raise
def process_arguments(_src, _dst, _keep, _exclude, _dst_fqdn, _path_log_files,
                      _path_log_summary, _source_id_none = '#DEFAULT_SOURCE_ID#'):
    def check_key_value_pair(argument):
        split = argument.split('#')
        if not (len(split) == 2 and len(split[0]) > 0 and len(split[1]) > 0):
            raise ArgumentTypeError(f'{argument} is an invalid key#value pair')
        return argument
    
    # Prepare <sources> variable
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
            tmp_id = _source_id_none
            tmp_path = Path(src)
        sources.append({ 'id': tmp_id, 'path': tmp_path,
                         'check_file': tmp_path.joinpath('.backup_src_check') })
    else:
        # multiple sources
        for i_src in _src:
            check_key_value_pair(i_src)
            tmp_id = i_src.split('#')[0]
            tmp_path = Path(i_src.split('#')[1])
            sources.append({ 'id': tmp_id, 'path': tmp_path,
                             'check_file': tmp_path.joinpath('.backup_src_check') })
    
    # Prepare <destination> variable
    tmp_dst_path = Path(_dst)
    if _dst_fqdn:
        tmp_dst_path = tmp_dst_path.joinpath(getfqdn())
    destination = { 'path': tmp_dst_path,
                    'check_file': tmp_dst_path.joinpath('.backup_dst_check') }
    
    # Prepare <keep_n_backups> variable
    keep_n_backups = _keep
    
    # Prepare <backup_excludes> variable
    backup_excludes = {}
    for i_source in sources:
        backup_excludes[i_source['id']] = []
    for i_exclude in _exclude:
        if '#' in i_exclude:
            check_key_value_pair(i_exclude)
            tmp_id = i_exclude.split('#')[0]
            tmp_path = i_exclude.split('#')[1]
            if not tmp_id in [i_source['id'] for i_source in sources]:
                raise ArgumentTypeError(f'Id "{tmp_id}" was not assigned to any source. Check --exclude.')
            backup_excludes[tmp_id].append(tmp_path)
        else:
            tmp_id = _source_id_none
            tmp_path = i_exclude
            if len(sources) > 1:
                raise ArgumentTypeError(f'Exclude-path cannot be associated with any source. Assigning an id to the exclude-path is required when using multiple sources.')
            if not sources[0]['id'] == _source_id_none:
                raise ArgumentTypeError(f'Please assign an ID to the exclude path.')
            backup_excludes[tmp_id].append(tmp_path)
    
    # Prepare <path_log_files> variable
    path_log_files = Path(_path_log_files)

    # Prepare <path_log_summary> variable
    path_log_summary = path_log_files.joinpath('latest_log_files.txt')
    if not _path_log_summary is None:
        path_log_summary = Path(_path_log_summary)
    
    return (0, sources, destination, keep_n_backups, backup_excludes,
            path_log_files, path_log_summary)


# _check_requirements
#
# Checks whether the following directories and files exist:
# - source directories, source-check files
# - destination directory, destination-check file
#
# @param dict   _sources
# @param dict   _destination
# @param        _logger
#
# @return <err_code>
#
# @note See comments at the top of this file for more information on the
#           structure of the variables.
#
# @note err_code  0: OK
# @note err_code 31: one or more source / data directories not found
# @note err_code 32: destination / backup directory not found
# @note err_code 33: one or more source-check-files not found
# @note err_code 34: destination-check-file not found
def _check_requirements(_sources, _destination, _logger):
    err_code = 0
    
    try:
        # Check if source / data directories exist
        for i_source in _sources:
            _logger.info(f'Checking if data directory for id "{i_source["id"]}" exists...')
            if not (i_source['path'].exists() and i_source['path'].is_dir()):
                _logger.error(f'Directory does not exist: "{i_source["path"].absolute()}"')
                err_code = 31
                raise FileNotFoundError()
            else:
                _logger.info('OK.')

        # Check if destination / backup directory exists
        _logger.info(f'Checking if backup directory exists...')
        if not (_destination['path'].exists() and _destination['path'].is_dir()):
            _logger.error(f'Directory does not exist: "{_destination["path"].absolute()}"')
            err_code = 32
            raise FileNotFoundError()
        else:
            _logger.info('OK.')

        # Check if source-check-files exist
        for i_source in _sources:
            _logger.info(f'Checking if source-check-file for id "{i_source["id"]}" exists...')
            if not (i_source['check_file'].exists() and i_source['check_file'].is_file()):
                _logger.error(f'File does not exist: "{i_source["check_file"].absolute()}"')
                err_code = 33
                raise FileNotFoundError()
            else:
                _logger.info('OK.')

        # Check if destination-check-file exists
        _logger.info(f'Checking if destination-check-file exists...')
        if not (_destination['check_file'].exists() and _destination['check_file'].is_file()):
            _logger.error(f'File does not exist: "{_destination["check_file"].absolute()}"')
            err_code = 34
            raise FileNotFoundError()
        else:
            _logger.info('OK.')
    
    except FileNotFoundError:
        _logger.error('WARNING: No backup will be done!')
    
    return err_code


# _prepare_backup
#
# Creates log-files directories, deletes old backups and prepares the
# tmp_partial_backup folder.
#
# @param dict   _destination
# @param int    _keep_n_backups
# @param Path   _path_log_files
# @param        _logger
#
# @return <err_code>
#
# @note err_code 0: OK
#
# (@note err_code: 4x)
def _prepare_backup(_destination, _keep_n_backups, _path_log_files,
                    _path_log_summary, _logger):
    # Create log-files directory
    if not _path_log_files.exists():
        _logger.info(f'Creating log-files directory: "{_path_log_files.absolute()}"')
        _path_log_files.mkdir(parents=True)
    
    # Create directory containing log-summary file
    if not _path_log_summary.parent.exists():
        _logger.info(f'Creating directory for log-summary file: "{_path_log_summary.absolute()}"')
        _path_log_summary.parent.mkdir(parents=True)

    backup_to_tmp = _destination['path'].joinpath('tmp_partial_backup')

    # Get old backups
    paths_old_backups = [i_path for i_path in _destination['path'].iterdir()
                         if i_path.is_dir()]
    paths_old_backups = [i_path for i_path in paths_old_backups
                         if i_path.stem not in ['tmp_partial_backup']]
    paths_old_backups.sort()

    # Remove old backups - keep <keep_n_backups> latest backups
    if _keep_n_backups > 0:
        if backup_to_tmp.exists():
            _logger.warning('Last backup was not finished. Continuing.')
            _keep_n_backups -= 1
        backups_to_remove = paths_old_backups[:-_keep_n_backups]
        paths_old_backups = paths_old_backups[len(backups_to_remove):]
        for i_backup in backups_to_remove:
            _logger.info(f'Deleting old backup: "{i_backup.absolute()}"')
            rmtree(i_backup)
            _logger.info(f'Done.')

    # Create tmp_partial_backup folder
    if not backup_to_tmp.exists():
        if _keep_n_backups > 0 and len(paths_old_backups) == _keep_n_backups:
            print('A')
            # recycle old backup
            backup_to_recycle = min(paths_old_backups)
            _logger.info(f'Recycling old backup: "{backup_to_recycle.absolute()}"')
            backup_to_recycle.rename(_destination['path'].joinpath('tmp_partial_backup'))
        else:
            backup_to_tmp.mkdir(parents=True)

    return 0


# _do_backup
#
# Executes rsync to create the backup.
#
# @param dict   _sources
# @param str    _source_id_none
# @param dict   _destination
# @param dict   _backup_excludes
# @param str    _datetime_string_now
# @param Path   _path_log_files
# @param        _logger
#
# @return <err_code>, <log_files>
#
# err_code (5x)
def _do_backup(_sources, _source_id_none, _destination, _backup_excludes,
               _datetime_string_now, _path_log_files, _logger):
    # Path of all log-files
    log_files = []

    backup_to_tmp = _destination['path'].joinpath('tmp_partial_backup')

    # Get path to latest backup for --link-dest (higher-layer)
    path_latest_backup = None
    _logger.info('Looking for latest backup for --link-dest...')
    
    paths_old_backups = [i_path for i_path in _destination['path'].iterdir()
                         if i_path.is_dir()]
    paths_old_backups = [i_path for i_path in paths_old_backups
                         if i_path.stem not in ['tmp_partial_backup']]
    paths_old_backups.sort()
    if not paths_old_backups == []:
        path_latest_backup = max(paths_old_backups)
        _logger.info(f'Potential backup found: "{path_latest_backup.absolute()}"')
    else:
        _logger.info('No backup found.')

    # Path of the new incremental backup (higher-layer)
    path_backup = _destination['path'].joinpath(_datetime_string_now)
    _logger.info(f'Backup will be created on "{path_backup.absolute()}"')
    
    for i_source in _sources:
        # Create link-dest string
        rsync_cmd_arg_linkDest = ' '
        if not path_latest_backup is None:
            tmp_link_dest_path = None
            tmp_link_dest_go_up = '../'
            if i_source['id'] == _source_id_none:
                tmp_link_dest_path = path_latest_backup
            else:
                tmp_link_dest_go_up = '../../'
                tmp_link_dest_path = path_latest_backup.joinpath(i_source['id'])
            rsync_cmd_arg_linkDest = f'--link-dest "{tmp_link_dest_go_up}'\
                                     f'{tmp_link_dest_path.relative_to(_destination["path"])}" '
            if not tmp_link_dest_path.exists():
                rsync_cmd_arg_linkDest = ' '
                _logger.warning(f'Cannot use "--link-dest {tmp_link_dest_go_up}'\
                                f'{tmp_link_dest_path.relative_to(_destination["path"])}".')
                _logger.warning(f'↳ Maybe the source id "{i_source["id"]}" changed?')

        # Create exclude string
        rsync_cmd_arg_exclude = ' '
        if len(_backup_excludes[i_source['id']]) > 0:
            tmp_string_list = ','.join('"' + i_item + '"' for i_item in _backup_excludes[source['id']])
            rsync_cmd_arg_exclude = f'--exclude={{{tmp_string_list}}} '
        
        # Create log-file string
        tmp_logfile_filename = ''
        if not i_source['id'] == _source_id_none:
            tmp_logfile_filename = f'{_datetime_string_now}_{i_source["id"]}_rsync.log'
        else:
            tmp_logfile_filename = f'{_datetime_string_now}_rsync.log'
        rsync_cmd_arg_log_file = f'--log-file "{_path_log_files.joinpath(tmp_logfile_filename).absolute()}" '
        log_files.append(_path_log_files.joinpath(tmp_logfile_filename))

        # Create dst-path string
        tmp_dst = backup_to_tmp
        if not i_source['id'] == _source_id_none:
            tmp_dst = tmp_dst.joinpath(i_source['id'])
        rsync_dst = tmp_dst.absolute()

        rsync_cmd = f'rsync -a --delete {rsync_cmd_arg_exclude}'\
                    f'{rsync_cmd_arg_linkDest}"'\
                    f'{i_source["path"].absolute()}/" "{rsync_dst}" '\
                    f'{rsync_cmd_arg_log_file}'

        _logger.info('Executing the following command:')
        _logger.info(f'{rsync_cmd}')

        run(rsync_cmd, shell=True)

    _logger.info(f'Renaming tmp_partial_backup folder to "{path_backup.stem}"...')
    backup_to_tmp.rename(path_backup)
    _logger.info('Ok.')

    return 0, log_files


# backup
#
# Start a backup.
#
# @param dict   arguments
# @param Path   path_log_files
# @param Path   path_log_summary
# @param        logger
#
# @return <err_code>
#
# @note err_code 0: OK
#
# @note err_code 1x: function _process_argparse()
#
# @note err_code 2x: function _process_arguments()
#
# @note err_code 3x: function _check_requirements()
# @note err_code 31: one or more data directories not found
# @note err_code 32: backup directory not found
# @note err_code 33: one or more source-check-files not found
# @note err_code 34: destination-check-file not found
#
# @note err_code 4x: function _prepare_backup()
#
# @note err_code 5x: function _do_backup()
def backup(arguments = None, logger = None):
    datetime_string_now = datetime.today().strftime('%Y-%m-%d_%H:%M:%S')
    
    log_files = []

    log_file_filename = None
    tmp_path_log_file = None
    if logger is None:
        # log file will be moved into log-files directory later
        log_file_filename = f'{datetime_string_now}_incremental_backup.log'
        tmp_path_log_file = Path(log_file_filename)
        logger = logHandler.get_logger(name=__name__,
                                        stream_logger={ 'log_level': logHandler.DEBUG, 'stream': None },
                                        file_logger={ 'log_level': logHandler.DEBUG,
                                                      'filename': tmp_path_log_file.absolute(),
                                                      'write_mode': 'a' },
                                        mode=None)

    logger.info(f'IncrementalBackup started at {datetime.today().strftime("%Y-%m-%d %H:%M:%S")}')
    
    return_code = 0
    try:
        # Process arguments
        err_code = None
        sources = None
        destination = None
        keep_n_backups = None
        backup_excludes = None
        path_log_files = None
        path_log_summary = None

        if arguments is None:
            err_code, sources, destination, keep_n_backups, backup_excludes, path_log_files, path_log_summary = _process_argparse('#NO_SOURCE_ID_SPECIFIED#')
        else:
            _src = arguments['src']
            _dst = arguments['dst']
            _keep = arguments['keep']
            _exclude = arguments['exclude']
            _dst_fqdn = arguments['dst_fqdn']
            _path_log_files = arguments['path_log_files']
            _path_log_summary = arguments['path_log_summary']
            err_code, sources, destination, keep_n_backups, backup_excludes, path_log_files, path_log_summary = _process_arguments(_src, _dst, _keep,
                                                                                                 _exclude, _dst_fqdn,
                                                                                                 _path_log_files, _path_log_summary,
                                                                                                 '#NO_SOURCE_ID_SPECIFIED#')

        path_log_file = path_log_files.joinpath(log_file_filename)
        log_files.append(path_log_file)

        if err_code != 0:
            return_code = err_code
            raise Exception()
        
        # Check requirements
        err_code = _check_requirements(sources, destination, logger)
        if err_code != 0:
            return_code = err_code
            raise Exception()
        
        # Prepare backup
        err_code = _prepare_backup(destination, keep_n_backups, path_log_files, path_log_summary, logger)
        if err_code != 0:
            return_code = err_code
            raise Exception()
        
        # Do backup
        err_code, tmp_log_files = _do_backup(sources, '#NO_SOURCE_ID_SPECIFIED#', destination, backup_excludes, datetime_string_now, path_log_files, logger)
        log_files = [ *log_files, *tmp_log_files ]
        if err_code != 0:
            return_code = err_code
            raise Exception()
    except Exception:
        logger.critical(f'An error occured. Terminating backup process at {datetime.today().strftime("%Y-%m-%d %H:%M:%S")}.')

    # List all log-files and write their paths to file
    logger.info('The following log-files were created:')
    for tmp_log_file in log_files:
        logger.info(f'↳ {tmp_log_file.absolute()}')
    
    with open(f'{path_log_summary}', 'w') as file:
        for tmp_log_file in log_files:
            file.write(f'{tmp_log_file.absolute()}\n')

    if not tmp_log_file is None:
        logger.info('This log-file will be moved to log-files directory after the next message.')
    
    logger.info(f'IncrementalBackup finished at {datetime.today().strftime("%Y-%m-%d %H:%M:%S")}')

    # Move log-file
    if not tmp_path_log_file is None:
        tmp_path_log_file.rename(path_log_files.joinpath(tmp_path_log_file.name))

    return return_code


if __name__ == '__main__':
    return_code = backup()
    exit(return_code)
